"""The state machine (app/state.py): one test per row of Q10's verdict table, the rules around
repairs, Q14's rules for failed portals, and the cases the question was asked for."""
import re
import sys
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.checks import (  # noqa: E402
    Answer, CheckSettings, DetailLook, ErrorKind, DownloadFacts, ListFacts, LookOutcome, block_check, canary,
    confirm, confirm_missing, duplicate_ids, file_outcome, files_failed, html_paths, known_ids_missing,
    known_tenders_reproduce, list_outcome, paging_complete, printed_total, robots_check, shape, stale,
    structure, transport_check,
)
from app.models import CheckResult, PortalState, Severity, TenderRecord  # noqa: E402
from app.state import Cause, Decision, ReadFacts, Verdict, decide  # noqa: E402

UTC = timezone.utc
RUN = "run-1"
GOOD = datetime(2026, 11, 20, 14, 2, tzinfo=UTC)   # the last read that passed
NOW = datetime(2026, 11, 20, 14, 7, tzinfo=UTC)    # this read

serving, healing, failed, integrating = (PortalState.serving, PortalState.healing, PortalState.failed,
                                         PortalState.integrating)

_RULE_ID = re.compile(r"\b(T[1-4]|O[12]|C[1-7]|D1|F1)\b")


def facts(**changes) -> ReadFacts:
    values = dict(now=NOW, state_before=serving, last_good_at=GOOD, last_good_tenders=23)
    values.update(changes)
    return ReadFacts(**values)


def plain(decision: Decision) -> str:
    """The reason must read as plain words for an operator: sentences, no rule ids, no field or check names."""
    reason = decision.reason
    assert reason.endswith(".") and reason[0].isupper()
    assert not _RULE_ID.search(reason), reason
    assert "_" not in reason and "None" not in reason, reason
    return reason


def tender(n: int, **changes) -> TenderRecord:
    values = dict(portal_id="p1", tender_id=f"T-{n:04d}", url=f"https://portal.example/t/{n}",
                  title=f"Road works {n}", buyer_name="Stadt X", publication_date=date(2026, 11, 10),
                  submission_deadline=datetime(2026, 12, 9, 10, 0, tzinfo=UTC))
    values.update(changes)
    return TenderRecord(**values)


def passing_read(rows: int = 23) -> list[CheckResult]:
    ids = [f"T-{i:04d}" for i in range(rows)]
    return [
        transport_check(RUN, Answer(status=200)),
        list_outcome(RUN, ListFacts(rows=rows, printed_total=rows)),
        paging_complete(RUN, reached_end=True, pages=2),
        duplicate_ids(RUN, ids),
        printed_total(RUN, extracted=rows, printed=rows),
        canary(RUN, [], file_valid=True),
    ]


def twice(result: CheckResult) -> CheckResult:
    """A suspect that the second look found again."""
    return confirm(result, result)


OUTAGE_503 = transport_check(RUN, Answer(status=503), tries=3)
OUTAGE_DNS = transport_check(RUN, Answer(error=ErrorKind.dns), tries=3)
CERTIFICATE = transport_check(RUN, Answer(error=ErrorKind.certificate, error_detail="incomplete chain", via="browser"))
LOGIN_WALL = Answer(status=200, login_redirect="/anmelden", password_field=True)
LOGIN = twice(list_outcome(RUN, ListFacts(rows=0, answer=LOGIN_WALL)))
CHALLENGE = twice(list_outcome(RUN, ListFacts(rows=0, answer=Answer(status=403, cf_mitigated="challenge"))))
BROKEN_TOTAL = twice(printed_total(RUN, extracted=9, printed=23))


# == One test per row of the verdict table ====================================

def test_pass():
    d = decide(passing_read(23), facts(now=GOOD, open_tenders=23, new_tenders=2, closed_tenders=1))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.passed, serving, None, False)
    assert d.read_passed and not d.spot_check_needed
    assert plain(d) == "Read at 14:02 UTC found 23 open tenders, 2 new and 1 closed. Every check passed."


def test_pass_empty():
    known = [tender(i) for i in range(4)]
    missing = known_ids_missing(RUN, known, [], now=GOOD)
    looks = [DetailLook(tender_id=t.tender_id, outcome=LookOutcome.closed) for t in known]
    results = [list_outcome(RUN, ListFacts(rows=0, empty_marker=True)),
               confirm_missing(missing, looks, proven_empty=True)]
    d = decide(results, facts(now=GOOD, last_good_tenders=4, closed_tenders=4))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.passed_empty, serving, None, False)
    assert plain(d) == ("The portal lists no open tenders at 14:02 UTC. Its own 'no results' notice is shown, "
                        "and the 4 tenders we knew are closed.")


def test_outage():
    d = decide([OUTAGE_503], facts(outage_since=NOW, next_try_at=NOW + timedelta(minutes=2)))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.outage, failed, Cause.outage, False)
    assert plain(d) == ("The portal has not answered since 14:07 UTC (HTTP 503, 3 tries). Still delivering the 23 "
                        "tenders read at 14:02 UTC. Next try 14:09 UTC. The recipe is unchanged.")


def test_an_outage_is_failed_with_its_cause_from_the_first_read_and_never_healing():
    """Decision of 20 Nov 2026: healing is a repair under way; an outage has none, so it is `failed`
    (cannot deliver) with the cause `outage`. How long it has lasted changes the words, not the state."""
    for minutes in (0, 59, 60, 600):
        d = decide([OUTAGE_503], facts(state_before=serving, outage_since=NOW - timedelta(minutes=minutes)))
        assert (d.state, d.cause, d.start_repair) == (failed, Cause.outage, False)
    first = decide([OUTAGE_503], facts(outage_since=NOW))
    late = decide([OUTAGE_503], facts(state_before=failed, cause_before=Cause.outage,
                                      outage_since=NOW - timedelta(minutes=60)))
    assert (first.verdict, late.verdict) == (Verdict.outage, Verdict.outage_long)


def test_outage_long():
    now = NOW + timedelta(hours=3)
    d = decide([OUTAGE_DNS], facts(now=now, state_before=failed, cause_before=Cause.outage, outage_since=NOW,
                                   next_try_at=now + timedelta(hours=6)))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.outage_long, failed, Cause.outage, False)
    assert plain(d) == ("The portal has been unreachable for 3 hours (DNS failure, 3 tries). This is not a "
                        "login block. We check again at 23:07 UTC and on every refresh.")


def test_outage_certificate():
    d = decide([CERTIFICATE], facts(outage_since=NOW))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.outage, failed, Cause.outage, False)
    assert plain(d).startswith("The portal's certificate cannot be verified (incomplete chain), in the plain "
                               "client and in the browser. We do not read a site we cannot verify.")
    assert "Still delivering the 23 tenders read at 14:02 UTC." in d.reason
    # ... and still failed, with the time it has lasted, as any outage.
    later = decide([CERTIFICATE], facts(now=NOW + timedelta(hours=2), state_before=failed, outage_since=NOW))
    assert (later.state, later.cause, later.start_repair) == (failed, Cause.outage, False)
    assert "certificate" in plain(later) and "2 hours" in later.reason


@pytest.mark.parametrize("row, reason", [
    (LOGIN, "Login required: the tender list redirects to /anmelden and shows a password field. We do not log in."),
    (CHALLENGE, "Bot protection blocks the tender list (Cloudflare challenge). We do not solve captchas."),
])
def test_block(row, reason):
    d = decide([transport_check(RUN, Answer(status=200)), row], facts())
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.block, failed, Cause.block, False)
    assert plain(d).startswith(reason)


def test_breakage():
    d = decide(passing_read(9)[:4] + [BROKEN_TOTAL], facts())
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.breakage, healing, Cause.breakage, True)
    assert not d.read_passed
    assert plain(d) == ("The list reads 9 tenders but the portal prints 23. A second look found the same. "
                        "Repairing; still delivering the 23 tenders read at 14:02 UTC.")


def test_breakage_repair_budget_used():
    d = decide([BROKEN_TOTAL], facts(now=NOW + timedelta(minutes=24), state_before=healing,
                                     cause_before=Cause.breakage, broken_since=NOW, repair_attempts_used=3,
                                     repairs_tried=("list locator", "paging", "full re-learn")))
    assert (d.verdict, d.state) == (Verdict.breakage_budget_used, failed)
    assert (d.cause, d.start_repair) == (Cause.breakage, False)
    reason = plain(d)
    assert reason.startswith("The portal's reads have failed their checks since 14:07 UTC.")
    assert "The list reads 9 tenders but the portal prints 23." in reason
    assert reason.endswith("All 3 repair attempts failed (list locator, paging, full re-learn). A person is needed.")


def test_stale():
    row = stale(RUN, state=serving, last_good_at=NOW - timedelta(minutes=47), now=NOW,
                read_interval=timedelta(minutes=2))
    d = decide([row], facts(last_good_at=NOW - timedelta(minutes=47)))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.stale, failed, Cause.outage, False)
    assert plain(d).startswith("No read has passed since 13:20 UTC. Reads are not completing.")


# == An outage or a block never starts a repair ===============================

NO_REPAIR_ROWS = {
    "outage": OUTAGE_503,
    "certificate": CERTIFICATE,
    "rate limit at the slowest rate": transport_check(RUN, Answer(status=429), at_slowest_rate=True),
    "maintenance page": twice(list_outcome(RUN, ListFacts(rows=0, answer=Answer(status=200, maintenance=True)))),
    "login": LOGIN,
    "challenge": CHALLENGE,
    "robots": robots_check(RUN, forbids_every_path=True),
}


@pytest.mark.parametrize("name", NO_REPAIR_ROWS)
@pytest.mark.parametrize("before", [serving, healing, failed, integrating])
def test_an_outage_or_a_block_never_starts_a_repair(name, before):
    row = NO_REPAIR_ROWS[name]
    for outage_since in (NOW, NOW - timedelta(hours=5)):
        d = decide([row], facts(state_before=before, outage_since=outage_since))
        assert not d.start_repair and not d.spot_check_needed and not d.read_passed
        assert d.cause in (Cause.outage, Cause.block) and d.state is not serving
        plain(d)


def test_an_outage_outranks_a_breakage_seen_in_the_same_read():
    d = decide([BROKEN_TOTAL, OUTAGE_503], facts(outage_since=NOW))
    assert (d.state, d.cause, d.start_repair) == (failed, Cause.outage, False)


def test_a_block_outranks_everything():
    suspect = printed_total(RUN, extracted=9, printed=23)
    d = decide([suspect, BROKEN_TOTAL, OUTAGE_503, LOGIN], facts(outage_since=NOW))
    assert (d.state, d.cause, d.start_repair) == (failed, Cause.block, False)


def test_a_rate_limit_that_persists_at_the_slowest_rate_is_an_outage():
    d = decide([NO_REPAIR_ROWS["rate limit at the slowest rate"]], facts(outage_since=NOW))
    assert (d.state, d.cause) == (failed, Cause.outage)
    assert "HTTP 429" in plain(d)


# == Suspects and spot checks never change the state on their own =============

@pytest.mark.parametrize("before, cause", [(serving, None), (healing, Cause.breakage), (failed, Cause.block)])
def test_an_unconfirmed_suspect_changes_nothing(before, cause):
    first = printed_total(RUN, extracted=9, printed=23)
    d = decide(passing_read(9)[:4] + [first], facts(state_before=before, cause_before=cause))
    assert (d.verdict, d.state, d.cause) == (Verdict.pending, before, cause)
    assert d.unconfirmed == ("printed_total",) and not d.start_repair and not d.read_passed
    assert "second time" in plain(d)


def test_a_suspect_that_clears_lets_the_read_pass():
    first = printed_total(RUN, extracted=22, printed=23)
    cleared = confirm(first, printed_total(RUN, extracted=23, printed=23))
    d = decide(passing_read(23)[:4] + [cleared], facts(open_tenders=23))
    assert (d.state, d.read_passed) == (serving, True) and "Every check passed." in d.reason


def changed_structure() -> CheckResult:
    stored = html_paths('<table class="results"><tr class="row"><td class="title">x</td></tr></table>')
    now = html_paths('<div class="cards"><div class="card"><h3 class="name">x</h3></div></div>')
    return structure(RUN, now, stored, floor=0.8)


def spot_check(passed: bool) -> CheckResult:
    return CheckResult(run_id=RUN, name="spot_check", passed=passed, severity=Severity.fail,
                       message="The model found every value on the page." if passed
                       else "The model could not find the deadline of tender T-0003 on the page.")


def test_a_changed_structure_asks_for_a_spot_check_and_is_never_a_failure_alone():
    d = decide(passing_read() + [changed_structure()], facts())
    assert (d.verdict, d.state, d.cause) == (Verdict.pending, serving, None)
    assert d.spot_check_needed and not d.start_repair and not d.read_passed
    plain(d)
    passed = decide(passing_read() + [changed_structure(), spot_check(True)], facts(open_tenders=23))
    assert (passed.state, passed.read_passed, passed.spot_check_needed) == (serving, True, False)


def test_a_failed_spot_check_is_a_breakage():
    d = decide(passing_read() + [changed_structure(), spot_check(False)], facts())
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.breakage, healing, Cause.breakage, True)
    assert "could not find the deadline of tender T-0003" in plain(d)


def test_changed_values_of_known_tenders_ask_for_a_spot_check():
    good = [tender(i) for i in range(10)]
    swapped = [t.model_copy(update={"title": t.buyer_name, "buyer_name": t.title}) for t in good]
    d = decide(passing_read(10) + known_tenders_reproduce(RUN, swapped, good), facts())
    assert d.spot_check_needed and d.state is serving and d.verdict is Verdict.pending


def test_warnings_do_not_change_the_state():
    notes = [transport_check(RUN, Answer(status=429))] + shape(RUN, [tender(1, title="<b>Road works</b>"), tender(2)])
    d = decide(passing_read(2) + notes, facts(open_tenders=2))
    assert (d.state, d.cause, d.read_passed) == (serving, None, True)
    assert "No check failed; 2 warnings are logged on the run." in plain(d)


# == Going back to serving =====================================================

@pytest.mark.parametrize("before, cause", [(healing, Cause.breakage), (healing, Cause.outage),
                                           (failed, Cause.outage), (failed, Cause.block), (integrating, None)])
def test_one_full_read_that_passes_every_check_serves_the_portal_again(before, cause):
    d = decide(passing_read(23), facts(state_before=before, cause_before=cause, open_tenders=23))
    assert (d.verdict, d.state, d.cause, d.start_repair, d.read_passed) == (Verdict.passed, serving, None, False, True)
    assert ("The portal is served again." in plain(d)) is (before is not integrating)


def test_a_partial_read_cannot_bring_a_portal_back():
    d = decide(passing_read(23), facts(state_before=healing, cause_before=Cause.breakage, full_read=False))
    assert (d.verdict, d.state, d.cause, d.read_passed) == (Verdict.pending, healing, Cause.breakage, False)
    assert "full read must pass" in plain(d)
    assert decide(passing_read(23), facts(full_read=False)).state is serving  # a serving portal stays serving


# == Q14: what a check of a failed portal finds ================================

def test_failed_portal_whose_old_recipe_passes_is_serving():
    d = decide(passing_read(23), facts(state_before=failed, cause_before=Cause.breakage, open_tenders=23))
    assert (d.state, d.cause, d.start_repair) == (serving, None, False)


def test_failed_portal_still_blocked_stays_failed_and_the_reason_gets_the_time_of_the_check():
    d = decide([LOGIN], facts(now=NOW + timedelta(hours=6), state_before=failed, cause_before=Cause.block))
    assert (d.state, d.cause, d.start_repair) == (failed, Cause.block, False)
    assert "Login required" in plain(d) and d.reason.endswith("Still so at 20:07 UTC.")


def test_failed_portal_still_not_answering_stays_failed():
    d = decide([OUTAGE_503], facts(state_before=failed, cause_before=Cause.breakage, outage_since=NOW))
    assert (d.state, d.cause, d.start_repair) == (failed, Cause.outage, False)
    assert "did not answer at 14:07 UTC (HTTP 503, 3 tries). This is not a login block." in plain(d)
    # A portal that was behind a login may still be: the reason does not claim otherwise.
    walled = decide([OUTAGE_503], facts(state_before=failed, cause_before=Cause.block, outage_since=NOW))
    assert walled.state is failed and "login" not in plain(walled)


def test_failed_portal_on_the_structure_we_gave_up_on_stays_failed_without_a_repair():
    d = decide([BROKEN_TOTAL], facts(state_before=failed, cause_before=Cause.breakage, structure_given_up=True))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (
        Verdict.breakage_known_structure, failed, Cause.breakage, False)
    assert "already gave up on" in plain(d) and "Last checked at 14:07 UTC." in d.reason


def test_failed_portal_on_a_new_structure_gets_one_repair():
    d = decide([BROKEN_TOTAL], facts(state_before=failed, cause_before=Cause.breakage, repairs_today=2))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.breakage, healing, Cause.breakage, True)
    assert "one repair attempt starts" in plain(d)


def test_failed_portal_gets_at_most_three_repairs_a_day():
    d = decide([BROKEN_TOTAL], facts(state_before=failed, cause_before=Cause.breakage, repairs_today=3))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (
        Verdict.breakage_daily_limit, failed, Cause.breakage, False)
    assert "3 repairs already ran today" in plain(d)


def test_a_structure_we_gave_up_on_never_gets_a_repair_whatever_the_state_was():
    d = decide([BROKEN_TOTAL], facts(state_before=serving, structure_given_up=True))
    assert (d.state, d.cause, d.start_repair) == (failed, Cause.breakage, False)


# == While attaching ============================================================

def test_attach_block_and_outage_are_failed_and_breakage_learns_again():
    new = dict(state_before=integrating, last_good_at=None, last_good_tenders=0)
    assert decide([LOGIN], facts(**new)).state is failed
    down = decide([OUTAGE_503], facts(outage_since=NOW, **new))
    assert (down.state, down.cause, down.start_repair) == (failed, Cause.outage, False)  # nothing delivered, no repair
    assert "Nothing is delivered yet." in plain(down)
    assert decide([OUTAGE_503], facts(outage_since=NOW - timedelta(hours=2), **new)).state is failed
    again = decide([BROKEN_TOTAL], facts(**new))
    assert (again.state, again.cause, again.start_repair) == (integrating, Cause.breakage, True)
    assert "nothing is delivered yet" in plain(again)
    assert decide([BROKEN_TOTAL], facts(repair_attempts_used=3, **new)).state is failed


# == What must hold whatever a read brings ======================================

@pytest.mark.parametrize("before", [serving, healing, failed, integrating])
def test_invariants_hold_for_every_pair_of_results(before):
    pool = [
        list_outcome(RUN, ListFacts(rows=23)), transport_check(RUN, Answer(status=429)), OUTAGE_503, CERTIFICATE,
        LOGIN, BROKEN_TOTAL, printed_total(RUN, extracted=9, printed=23), changed_structure(), spot_check(True),
        spot_check(False),
        stale(RUN, state=serving, last_good_at=GOOD - timedelta(hours=1), now=NOW, read_interval=timedelta(minutes=2)),
    ]
    passes = (Verdict.passed, Verdict.passed_empty)
    for pair in combinations(pool, 2):
        for given_up in (False, True):
            for used in (0, 3):
                d = decide(list(pair), facts(state_before=before, cause_before=None if before is serving else
                                             Cause.breakage, structure_given_up=given_up, outage_since=NOW,
                                             repair_attempts_used=used, repairs_today=used))
                plain(d)
                served = d.state is serving and d.verdict is not Verdict.pending
                assert (d.verdict in passes) == d.read_passed == served
                assert (d.cause is None) == (d.state is serving)
                if d.start_repair:
                    assert d.cause is Cause.breakage and d.state in (healing, integrating) and not given_up
                if d.verdict is Verdict.pending:
                    assert d.state is before and not d.start_repair
                if d.cause in (Cause.outage, Cause.block):
                    assert not d.start_repair


# == Settings and inputs ========================================================

def test_the_numbers_come_from_the_settings():
    quick = CheckSettings(outage_failed_after_minutes=10, repair_attempts_per_incident=1, repairs_per_day=1)
    assert decide([OUTAGE_503], facts(outage_since=NOW - timedelta(minutes=10)), quick).state is failed
    assert decide([BROKEN_TOTAL], facts(repair_attempts_used=1), quick).state is failed
    assert decide([BROKEN_TOTAL], facts(state_before=failed, repairs_today=1), quick).start_repair is False


def test_a_second_and_third_repair_attempt_say_which_they_are():
    d = decide([BROKEN_TOTAL], facts(state_before=healing, cause_before=Cause.breakage, repair_attempts_used=1))
    assert d.start_repair and "Repairing, attempt 2 of 3;" in plain(d)


def test_times_must_carry_an_offset_and_are_printed_in_utc():
    with pytest.raises(ValueError):
        facts(now=datetime(2026, 11, 20, 14, 7))
    berlin = timezone(timedelta(hours=1))
    d = decide([OUTAGE_503], facts(now=NOW.astimezone(berlin), outage_since=NOW,
                                   last_good_at=GOOD.astimezone(berlin)))
    assert "since 14:07 UTC" in d.reason and "read at 14:02 UTC" in d.reason


def test_a_time_on_another_day_is_shown_with_its_day():
    d = decide([OUTAGE_503], facts(now=NOW + timedelta(days=1), state_before=failed, outage_since=NOW,
                                   last_good_at=GOOD))
    assert "unreachable for 24 hours" in plain(d)
    d = decide([BROKEN_TOTAL], facts(now=NOW + timedelta(days=1)))
    assert "read at 20 Nov 14:02 UTC" in d.reason


# == The cases the question was asked for =======================================

def test_small_portal_one_of_three_tenders_legitimately_withdrawn_stays_serving():
    known = [tender(1), tender(2), tender(3)]
    listed = ["T-0001", "T-0002"]
    read = [list_outcome(RUN, ListFacts(rows=2)), paging_complete(RUN, reached_end=True, pages=1),
            duplicate_ids(RUN, listed), *known_tenders_reproduce(RUN, known[:2], known)]
    missing = known_ids_missing(RUN, known, listed, now=NOW)

    waiting = decide(read + [missing], facts(last_good_tenders=3))
    assert (waiting.verdict, waiting.state) == (Verdict.pending, serving)   # no false alarm on the first look
    assert waiting.unconfirmed == ("known_ids_missing",)

    settled = confirm_missing(missing, [DetailLook(tender_id="T-0003", outcome=LookOutcome.withdrawn)])
    d = decide(read + [settled], facts(last_good_tenders=3, open_tenders=2, closed_tenders=1))
    assert (d.verdict, d.state, d.cause, d.start_repair, d.read_passed) == (Verdict.passed, serving, None, False, True)
    assert plain(d) == "Read at 14:07 UTC found 2 open tenders, 0 new and 1 closed. Every check passed."


def test_small_portal_one_of_three_missing_but_still_open_on_its_page_is_a_breakage():
    known = [tender(1), tender(2), tender(3)]
    missing = known_ids_missing(RUN, known, ["T-0001", "T-0002"], now=NOW)
    settled = confirm_missing(missing, [DetailLook(tender_id="T-0003", outcome=LookOutcome.still_open)])
    d = decide([list_outcome(RUN, ListFacts(rows=2)), settled], facts(last_good_tenders=3))
    assert (d.state, d.cause, d.start_repair) == (healing, Cause.breakage, True)
    assert plain(d) == ("The list no longer shows 1 of 3 known open tenders, but the own page of tender T-0003 "
                        "still shows it open. Repairing; still delivering the 3 tenders read at 14:02 UTC.")


def test_list_that_empties_with_the_portals_own_notice_stays_serving():
    known = [tender(i) for i in range(1, 4)]
    missing = known_ids_missing(RUN, known, [], now=NOW)
    looks = [DetailLook(tender_id=t.tender_id, outcome=LookOutcome.gone) for t in known]
    results = [list_outcome(RUN, ListFacts(rows=0, empty_marker=True)),
               confirm_missing(missing, looks, proven_empty=True)]
    d = decide(results, facts(last_good_tenders=3, closed_tenders=3))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.passed_empty, serving, None, False)
    assert "no open tenders" in plain(d) and "notice" in d.reason and "the 3 tenders we knew are closed" in d.reason


def test_list_that_empties_without_the_notice_is_suspect_and_confirmed_a_breakage():
    first = list_outcome(RUN, ListFacts(rows=0))
    waiting = decide([first], facts())
    assert (waiting.verdict, waiting.state, waiting.start_repair) == (Verdict.pending, serving, False)
    assert waiting.unconfirmed == ("list_outcome",) and not waiting.read_passed   # it must not pass silently

    d = decide([confirm(first, list_outcome(RUN, ListFacts(rows=0)))], facts())
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.breakage, healing, Cause.breakage, True)
    assert "does not say the list is empty" in plain(d) and "still delivering the 23 tenders" in d.reason


def test_a_503_that_persists_is_failed_with_no_repair():
    one_try = decide([transport_check(RUN, Answer(status=503), tries=1)], facts())
    assert (one_try.verdict, one_try.state) == (Verdict.pending, serving)     # two more tries first
    d = decide([transport_check(RUN, Answer(status=503), tries=3)], facts(outage_since=NOW))
    assert (d.state, d.cause, d.start_repair) == (failed, Cause.outage, False)


def test_a_429_changes_no_state():
    slow_down = transport_check(RUN, Answer(status=429))
    for before in (serving, healing, failed):
        alone = decide([slow_down], facts(state_before=before))
        assert alone.state is before and not alone.start_repair
    d = decide(passing_read() + [slow_down], facts(open_tenders=23))
    assert (d.state, d.cause, d.start_repair) == (serving, None, False)
    assert "23 open tenders" in plain(d)


def test_without_a_list_that_arrived_nothing_is_called_a_pass():
    for results in ([], [transport_check(RUN, Answer(status=200))],
                    [stale(RUN, state=healing, last_good_at=GOOD, now=NOW, read_interval=timedelta(minutes=2))]):
        d = decide(results, facts(state_before=healing, cause_before=Cause.outage))
        assert (d.verdict, d.state, d.cause, d.read_passed) == (Verdict.pending, healing, Cause.outage, False)
        plain(d)


def test_a_settled_outage_does_not_wait_for_other_suspects():
    no_list = list_outcome(RUN, ListFacts(rows=0, answer=Answer(status=503)))
    d = decide([OUTAGE_503, no_list], facts(outage_since=NOW))
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.outage, failed, Cause.outage, False)


def test_a_login_wall_is_failed_at_once():
    first = list_outcome(RUN, ListFacts(rows=0, answer=LOGIN_WALL))
    assert first.observed["second_look"] == "browser"                         # one confirming fetch
    through_browser = list_outcome(RUN, ListFacts(rows=0, answer=LOGIN_WALL.model_copy(update={"via": "browser"})))
    d = decide([confirm(first, through_browser)], facts())
    assert (d.verdict, d.state, d.cause, d.start_repair) == (Verdict.block, failed, Cause.block, False)
    assert plain(d).startswith("Login required")


def test_a_login_wall_in_front_of_every_document_is_failed():
    form = Answer(status=200, page_load=False, password_field=True)
    files = [file_outcome(RUN, DownloadFacts(file_name=f"doc{i}.pdf", answer=form, first_bytes=b"<html>",
                                             size_bytes=900, content_type="text/html")) for i in range(4)]
    d = decide(passing_read() + files + [files_failed(RUN, files, earlier_failed=0, earlier_files=30, retried=True)],
               facts())
    assert (d.state, d.cause, d.start_repair) == (failed, Cause.block, False)
    assert "Downloads failed for 4 of 4 files" in plain(d) and "Login required" in d.reason


def test_a_captcha_marker_on_a_page_whose_list_arrived_changes_nothing():
    page = Answer(status=200, captcha="reCAPTCHA", password_field=True)
    results = [transport_check(RUN, page), list_outcome(RUN, ListFacts(rows=23, answer=page)),
               block_check(RUN, page, outcome_missing=False)]
    with_marker = decide(results, facts(open_tenders=23))
    without = decide(passing_read(23), facts(open_tenders=23))
    assert (with_marker.state, with_marker.cause, with_marker.start_repair) == (serving, None, False)
    assert with_marker.reason == without.reason
