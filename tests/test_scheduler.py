"""Tests for app/scheduler.py: the research's worked numbers (Q12, Q13, Q14). No network."""
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models import PortalState  # noqa: E402
from app.scheduler import (  # noqa: E402
    AttachPhase, AttachProgress, DocumentNeed, KnownTender, ListRow, Publish, ReadPlan,
    SchedulerSettings, attach_decision, document_order, estimate_document_seconds,
    may_check_on_refresh, next_failed_check, next_outage_retry, next_read,
    parse_retry_after, plan_incremental_read, read_interval, read_plan,
)

UTC = timezone.utc
CET = timezone(timedelta(hours=1))
T0 = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
S = SchedulerSettings()


def minutes(m: float) -> timedelta:
    return timedelta(minutes=m)


# == Settings ==

def test_defaults_are_the_research_values():
    assert S.read_interval_seconds == 120 and S.read_interval_max_seconds == 1800
    assert S.attach_time_limit_seconds == 1200 and S.documents_before_serving_seconds == 600
    assert S.rotation_budget_share == 0.2 and S.rotation_urgent_seconds == 48 * 3600
    assert S.outage_retry_steps_seconds == (60, 120, 240, 480, 900, 1800)
    assert S.failed_check_steps_seconds == (300, 900, 3600)
    assert S.failed_check_every_seconds == S.blocked_check_every_seconds == 6 * 3600
    assert S.check_jitter_share == 0.2 and S.refresh_check_min_seconds == 60


def test_settings_from_env():
    s = SchedulerSettings.from_env({
        "READ_INTERVAL_SECONDS": "300", "ATTACH_TIME_LIMIT_SECONDS": "1800",
        "FIRST_PAGE_MIN_LIST_PAGES": "20", "OUTAGE_RETRY_STEPS_SECONDS": "30, 60",
        "UNRELATED": "x", "ROTATION_BUDGET_SHARE": "",
    })
    assert s.read_interval_seconds == 300 and s.attach_time_limit_seconds == 1800
    assert s.first_page_min_list_pages == 20 and isinstance(s.first_page_min_list_pages, int)
    assert s.outage_retry_steps_seconds == (30, 60)
    assert s.rotation_budget_share == 0.2
    assert SchedulerSettings.from_env({}) == S


def test_settings_refuse_floor_above_cap():
    with pytest.raises(ValueError):
        SchedulerSettings(read_interval_seconds=3600)


# == Read interval (Q13) ==

@pytest.mark.parametrize("list_seconds, interval_seconds", [
    (0, 120), (1, 120), (5, 120), (12, 120),   # floor: 2 minutes
    (13, 130),
    (50, 500),                                  # 50 pages: "8 min"
    (100, 1000),                                # 100 pages: "17 min"
    (180, 1800), (250, 1800),                   # cap: 30 minutes
])
def test_read_interval_q13_table(list_seconds, interval_seconds):
    assert read_interval(list_seconds) == timedelta(seconds=interval_seconds)


def test_list_share_of_budget_q13_table():
    # pages / interval at 1 request per second, as Q13's table prints them (250 pages: 13.9%, "14%").
    for pages, share in [(1, 0.8), (5, 4.2), (12, 10.0), (50, 10.0), (100, 10.0), (250, 13.9)]:
        assert round(pages / read_interval(pages).total_seconds() * 100, 1) == share


def test_first_page_alone_only_for_long_newest_first_lists():
    assert read_plan(12, 12, True).first_page_every is None
    assert read_plan(13, 13, False).first_page_every is None
    plan = read_plan(50, 50, True)
    assert plan == ReadPlan(interval=timedelta(seconds=500), first_page_every=minutes(2))


def test_next_read_from_the_start_of_the_last_read():
    short = read_plan(5, 5, True)
    assert next_read(short, T0).at == T0 + minutes(2)
    assert not next_read(short, T0).first_page_only

    plan = read_plan(50, 50, True)  # full every 500 s, first page every 120 s
    nxt = next_read(plan, T0)
    assert nxt.at == T0 + minutes(2) and nxt.first_page_only
    nxt = next_read(plan, T0, T0 + minutes(6))
    assert nxt.at == T0 + minutes(8) and nxt.first_page_only
    nxt = next_read(plan, T0, T0 + minutes(8))  # 10 min > 500 s: the full read comes first
    assert nxt.at == T0 + timedelta(seconds=500) and not nxt.first_page_only


def test_naive_datetimes_are_refused():
    with pytest.raises(ValueError):
        next_read(read_plan(5, 5, False), datetime(2026, 11, 20, 14, 0))


# == Outage retries (Q14, Q10) ==

def test_outage_ladder_is_the_first_hour():
    at, tries = T0, []
    for done in range(10):
        nxt = next_outage_retry(at, done)
        if nxt is None:
            break
        tries.append(nxt)
        at = nxt
    assert [(t - T0) / minutes(1) for t in tries] == [1, 3, 7, 15, 30, 60]
    assert next_outage_retry(T0, 6) is None


def test_outage_retry_obeys_retry_after_up_to_an_hour():
    assert next_outage_retry(T0, 0, retry_after=minutes(10)) == T0 + minutes(10)
    assert next_outage_retry(T0, 0, retry_after=timedelta(hours=3)) == T0 + timedelta(hours=1)
    assert next_outage_retry(T0, 0, retry_after=timedelta(seconds=10)) == T0 + minutes(1)


def test_parse_retry_after():
    assert parse_retry_after("120", T0) == timedelta(seconds=120)
    assert parse_retry_after("Fri, 20 Nov 2026 14:05:00 GMT", T0) == minutes(5)
    assert parse_retry_after("Fri, 20 Nov 2026 13:00:00 GMT", T0) == timedelta(0)
    assert parse_retry_after("soon", T0) is None
    assert parse_retry_after(None, T0) is None


# == Failed-portal checks (Q14) ==

def _ladder(rng_value: float, n: int, blocked: bool = False) -> list[float]:
    return [(next_failed_check(T0, k, blocked=blocked, rng=lambda: rng_value) - T0) / minutes(1)
            for k in range(n)]


def test_failed_checks_unshifted():
    assert _ladder(0.5, 6) == [5, 15, 60, 420, 780, 1140]
    assert _ladder(0.5, 3, blocked=True) == [360, 720, 1080]


def test_failed_checks_shift_bounds_exact():
    # Each check moves by at most 20% of its gap from the nominal check before it.
    assert _ladder(0.0, 5) == [4, 13, 51, 348, 708]
    assert _ladder(1.0, 5) == [6, 17, 69, 492, 852]
    assert _ladder(0.0, 2, blocked=True) == [288, 648]
    assert _ladder(1.0, 2, blocked=True) == [432, 792]


def test_failed_checks_random_stay_in_bounds_and_order():
    rng = random.Random(7)
    lows, highs = _ladder(0.0, 6), _ladder(1.0, 6)
    for _ in range(200):
        times = _ladder(rng.random(), 6)
        assert all(lo <= t <= hi for lo, t, hi in zip(lows, times, highs))
    assert all(h < lo for h, lo in zip(highs, lows[1:]))  # shifts never reorder checks


def test_failed_check_obeys_retry_after():
    due = next_failed_check(T0, 0, rng=lambda: 0.5, last_check_at=T0, retry_after=minutes(30))
    assert due == T0 + minutes(30)
    due = next_failed_check(T0, 0, rng=lambda: 0.5, retry_after=timedelta(hours=5))
    assert due == T0 + timedelta(hours=1)


def test_refresh_check_at_most_once_a_minute():
    assert may_check_on_refresh(None, T0)
    assert not may_check_on_refresh(T0, T0 + timedelta(seconds=59))
    assert may_check_on_refresh(T0, T0 + timedelta(seconds=60))


# == Document order and estimate (Q12) ==

def test_document_order_soonest_deadline_then_smallest_then_no_deadline():
    d = datetime(2026, 12, 1, 12, 0, tzinfo=CET)
    needs = [
        DocumentNeed("none-small", None, files=1),
        DocumentNeed("late", d + timedelta(days=5), files=1),
        DocumentNeed("soon-big", d, files=20),
        DocumentNeed("soon-zip", d.astimezone(UTC), zip=True, size_bytes=50_000_000),
        DocumentNeed("soon-small", d, files=1, size_bytes=1_000),
        DocumentNeed("soonest", d - timedelta(hours=1), files=30),
        DocumentNeed("none-big", None, files=9),
    ]
    order = [n.tender_id for n in document_order(needs)]
    assert order == ["soonest", "soon-small", "soon-zip", "soon-big", "late", "none-small", "none-big"]


def test_document_estimate_counts_requests():
    needs = [DocumentNeed("a", None, files=3), DocumentNeed("b", None, zip=True, reach_requests=1),
             DocumentNeed("c", None)]  # unknown count: 9 assumed
    assert estimate_document_seconds(needs) == 3 + 2 + 9
    assert estimate_document_seconds(needs, requests_per_second=0.5) == 28
    # Q12: 1,000 tenders x 9 files = 9,000 requests = 2.5 h after the records gate.
    assert estimate_document_seconds([DocumentNeed(str(i), None, files=9) for i in range(1000)]) == 9000


# == Attach: every row of the phase table (Q12, DESIGN.md) ==

def _attach(**kw) -> object:
    base = dict(started_at=T0, now=T0 + minutes(5), tenders_total=1000, records_done=0)
    base.update(kw)
    return attach_decision(AttachProgress(**base))


def test_row_list_phase():
    d = _attach(tenders_total=None, list_pages_read=3, now=T0 + minutes(1))
    assert (d.phase, d.state, d.publish) == (AttachPhase.reading, PortalState.integrating, Publish.none)
    assert d.reason == "Reading the tender list: 3 pages so far."


def test_row_record_phase():
    d = _attach(records_done=419, now=T0 + minutes(7))
    assert (d.state, d.publish) == (PortalState.integrating, Publish.none)
    assert d.reason == "Reading tender 420 of 1,000."


def test_row_time_limit_before_gate():
    d = _attach(records_done=400, now=T0 + minutes(20))
    assert (d.phase, d.state, d.publish) == (AttachPhase.time_limit, PortalState.serving, Publish.validated)
    # 600 records left at one detail request per second: 10 minutes.
    assert d.reason == "Delivering 400 of about 1,000 open tenders so far. The rest follow by 14:30 UTC."
    # Still delivering what is validated once published, even with the limit raised later.
    d = _attach(records_done=450, now=T0 + minutes(21), already_serving=True)
    assert d.state is PortalState.serving and d.publish is Publish.validated


def test_time_limit_with_list_unfinished_or_nothing_validated():
    d = _attach(tenders_total=None, records_done=250, now=T0 + minutes(20))
    assert d.state is PortalState.serving and d.publish is Publish.validated
    assert d.reason == "Delivering 250 open tenders so far. The tender list is still being read."
    d = _attach(records_done=0, now=T0 + minutes(25))
    assert (d.state, d.publish) == (PortalState.integrating, Publish.none)


def test_row_gate_documents_short():
    d = _attach(tenders_total=38, records_done=38, documents_done=12,
                documents_remaining_seconds=500, now=T0 + minutes(3))
    assert (d.phase, d.state, d.publish) == (AttachPhase.documents_short, PortalState.integrating, Publish.none)
    assert d.reason == "All 38 tenders read. Fetching documents: 12 of 38."


def test_row_gate_documents_long():
    d = _attach(records_done=1000, documents_done=140,
                documents_remaining_seconds=2 * 3600, now=T0 + minutes(40))
    assert (d.phase, d.state, d.publish) == (AttachPhase.documents_following, PortalState.serving, Publish.all)
    assert d.reason == ("All 1,000 open tenders are delivered. Documents are in for 140 of them, "
                        "soonest deadlines first; the rest follow by 16:40 UTC.")


def test_documents_short_becomes_serving_at_the_limit_or_once_published():
    kw = dict(tenders_total=38, records_done=38, documents_done=30, documents_remaining_seconds=60)
    assert _attach(now=T0 + minutes(20), **kw).state is PortalState.serving
    assert _attach(now=T0 + minutes(9), already_serving=True, **kw).publish is Publish.all
    # Exactly 10 minutes of documents is still "10 minutes or less".
    kw["documents_remaining_seconds"] = 600
    assert _attach(now=T0 + minutes(9), **kw).state is PortalState.integrating


def test_row_everything_in():
    d = _attach(records_done=1000, documents_done=1000, started_at=T0 + minutes(2), now=T0 + minutes(70))
    assert (d.phase, d.state, d.publish) == (AttachPhase.complete, PortalState.serving, Publish.all)
    assert d.reason == "Read at 14:02 UTC found 1,000 open tenders. Every check passed."


def test_empty_portal_and_one_tender():
    d = _attach(tenders_total=0, records_done=0)
    assert d.state is PortalState.serving and d.reason.endswith("found no open tenders. Every check passed.")
    d = _attach(tenders_total=1, records_done=1, documents_remaining_seconds=4000, now=T0 + minutes(1))
    assert d.reason.startswith("All 1 open tender is delivered.")


def test_reason_time_on_another_day_names_the_day():
    late = datetime(2026, 11, 20, 23, 50, tzinfo=UTC)
    d = attach_decision(AttachProgress(started_at=late - minutes(30), now=late, tenders_total=5000,
                                       records_done=5000, documents_remaining_seconds=5 * 3600))
    assert d.reason.endswith("the rest follow by 21 Nov 04:50 UTC.")


# == Incremental reads (Q12) ==

def _known(n: int, read_at: datetime | None = None, deadline: datetime | None = None) -> list[KnownTender]:
    return [KnownTender(f"T{i:04d}", f"h{i}", deadline, read_at, True) for i in range(n)]


def _rows(known: list[KnownTender]) -> list[ListRow]:
    return [ListRow(k.tender_id, k.row_hash, k.deadline) for k in known]


def _simulate(n: int, list_seconds: float, reads: int) -> tuple[int, dict[str, int]]:
    """Run `reads` reads; return the budget and, per tender, how many times it was rotated."""
    interval = read_interval(list_seconds)
    known = {k.tender_id: k for k in _known(n, read_at=T0 - timedelta(days=1))}
    counts = {tid: 0 for tid in known}
    now, budget = T0, 0
    for _ in range(reads):
        plan = plan_incremental_read(known.values(), _rows(list(known.values())), now, interval)
        budget = plan.rotation_budget
        for tid in plan.rotation:
            counts[tid] += 1
            k = known[tid]
            known[tid] = KnownTender(tid, k.row_hash, k.deadline, now, True)
        now += interval
    return budget, counts


def test_rotation_24_tenders_every_page_every_read():
    budget, counts = _simulate(24, 5, reads=3)
    assert budget == 24
    assert set(counts.values()) == {3}


def test_rotation_100_tenders_every_page_within_5_reads():
    # Q12: 24 detail pages per 2-minute read, so 100 tenders take 5 whole reads (10 minutes).
    budget, counts = _simulate(100, 5, reads=5)
    assert budget == 24 and min(counts.values()) >= 1


def test_rotation_1000_tenders_budget_binds():
    # 50 list pages: read every 500 s; a fifth of it is 100 detail pages per read;
    # every one of 1,000 detail pages is re-read within 10 reads = 5,000 s = 83 minutes.
    budget, counts = _simulate(1000, 50, reads=10)
    assert budget == 100
    assert set(counts.values()) == {1}
    budget, counts = _simulate(1000, 50, reads=9)
    assert sum(1 for c in counts.values() if c == 0) == 100


def test_rotation_budget_follows_the_request_rate():
    plan = plan_incremental_read(_known(100), _rows(_known(100)), T0, minutes(2), requests_per_second=0.5)
    assert plan.rotation_budget == 12 and len(plan.rotation) == 12


def test_rotation_closing_within_48_hours_first():
    recent = T0 - minutes(1)
    known = _known(30, read_at=T0 - timedelta(days=1))
    known[29] = KnownTender("T0029", "h29", T0 + timedelta(hours=47), recent, True)   # urgent
    known[28] = KnownTender("T0028", "h28", T0 + timedelta(hours=49), recent, True)   # not urgent
    known[27] = KnownTender("T0027", "h27", T0 - timedelta(hours=1), recent, True)    # already past
    plan = plan_incremental_read(known, _rows(known), T0, minutes(2))
    assert plan.rotation[0] == "T0029"
    assert "T0028" not in plan.rotation and "T0027" not in plan.rotation
    assert len(plan.rotation) == 24


def test_incremental_new_changed_unlisted_and_pending_documents():
    d = datetime(2026, 12, 1, 12, 0, tzinfo=CET)
    known = [
        KnownTender("same", "h1", d, T0 - minutes(10), True),
        KnownTender("changed", "h2", d + timedelta(days=3), T0 - minutes(10), True),
        KnownTender("gone", "h3", d, T0 - minutes(10), True),
        KnownTender("docs-missing", "h4", d, T0 - minutes(10), False),
    ]
    rows = [
        ListRow("same", "h1", d), ListRow("changed", "h2-new", d + timedelta(days=3)),
        ListRow("docs-missing", "h4", d), ListRow("new-late", "x", d + timedelta(days=9)),
        ListRow("new-soon", "y", d - timedelta(days=1)), ListRow("new-undated", "z", None),
    ]
    plan = plan_incremental_read(known, rows, T0, minutes(2))
    assert plan.fetch == ("new-soon", "changed", "new-late", "new-undated")
    assert plan.unlisted == ("gone",)
    assert plan.documents_pending == ("docs-missing",)
    assert set(plan.rotation) == {"same", "docs-missing"}
