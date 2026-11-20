"""Scheduler policy: when a portal is read, what is read first, what an attach reports.

Pure decisions only (Q12, Q13, Q14): plain facts in, a decision out. No event loop,
no network, no database, no model call. The loop that calls these functions is added
to this file later.

Every number the research marks as our own choice is a field of `SchedulerSettings`,
built from environment variables by `SchedulerSettings.from_env()`.

Clock times in reason sentences are printed in UTC and labelled "UTC". Our own
timestamps are UTC (CONVENTIONS.md, rule 4), a portal's zone may be unknown during an
attach, and an operator watching several portals in different countries needs one
clock, so every reason sentence uses the same one.
"""
from __future__ import annotations

import math
import os
import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import StrEnum

from app.models import PortalState

UTC = timezone.utc


# == Settings ==

def _seconds_tuple(raw: str) -> tuple[float, ...]:
    return tuple(float(x) for x in raw.replace(" ", "").split(",") if x)


@dataclass(frozen=True)
class SchedulerSettings:
    """Every number the scheduler policy uses; defaults are the research's values."""

    # Q13: list read every max(floor, multiplier x list read time), at most the cap.
    read_interval_seconds: float = 120.0          # READ_INTERVAL_SECONDS, the floor
    read_interval_list_multiplier: float = 10.0   # 10x = the list may use 10% of the budget
    read_interval_max_seconds: float = 1800.0
    # Q13: a list over 12 pages, newest first, also has its first page read alone.
    first_page_min_list_pages: int = 12           # "longer than 12 pages"
    first_page_interval_seconds: float = 120.0
    # Q12 and the mentor: attach time limit and the 10-minute document rule.
    attach_time_limit_seconds: float = 1200.0
    documents_before_serving_seconds: float = 600.0
    assumed_files_per_tender: int = 9             # measured mean 8.7 (Q12), when a tender's count is unknown
    # Q12: detail-page rotation.
    rotation_budget_share: float = 0.20
    rotation_urgent_seconds: float = 48 * 3600.0
    # Q14: gaps between outage retries while `healing` (sum: the first hour).
    outage_retry_steps_seconds: tuple[float, ...] = (60, 120, 240, 480, 900, 1800)
    # Q14: checks of a failed portal, as times after it failed, then a fixed period.
    failed_check_steps_seconds: tuple[float, ...] = (300, 900, 3600)
    failed_check_every_seconds: float = 6 * 3600.0
    blocked_check_every_seconds: float = 6 * 3600.0
    check_jitter_share: float = 0.20
    retry_after_max_seconds: float = 3600.0
    refresh_check_min_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.read_interval_seconds > self.read_interval_max_seconds:
            raise ValueError("READ_INTERVAL_SECONDS is above READ_INTERVAL_MAX_SECONDS")
        if not 0 <= self.check_jitter_share < 0.5:
            raise ValueError("CHECK_JITTER_SHARE must be in [0, 0.5)")
        if not self.outage_retry_steps_seconds or not self.failed_check_steps_seconds:
            raise ValueError("retry and check steps must not be empty")
        steps = self.failed_check_steps_seconds
        if any(b <= a for a, b in zip(steps, steps[1:])):
            raise ValueError("FAILED_CHECK_STEPS_SECONDS must increase")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SchedulerSettings:
        """Build settings from environment variables; unset ones keep their defaults."""
        env = os.environ if environ is None else environ
        kwargs: dict[str, object] = {}
        for name, f in cls.__dataclass_fields__.items():
            raw = env.get(name.upper())
            if raw is None or raw.strip() == "":
                continue
            if name.endswith("_steps_seconds"):
                kwargs[name] = _seconds_tuple(raw)
            elif f.type == "int":
                kwargs[name] = int(raw)
            else:
                kwargs[name] = float(raw)
        return cls(**kwargs)


DEFAULT_SETTINGS = SchedulerSettings()


# == Helpers ==

def _aware(dt: datetime, name: str) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware (CONVENTIONS.md, rule 4)")
    return dt


def _clock(at: datetime, now: datetime) -> str:
    """'15:10 UTC', or '21 Nov 04:40 UTC' when it falls on another day than `now`."""
    at, now = at.astimezone(UTC), now.astimezone(UTC)
    day = "" if at.date() == now.date() else f"{at.day} {at:%b} "
    return f"{day}{at:%H:%M} UTC"


def _n(count: int, noun: str) -> str:
    """'1 open tender', '1,000 open tenders'."""
    return f"{count:,} {noun}" + ("" if count == 1 else "s")


def _budget(share: float, seconds: float, rate: float) -> int:
    return max(0, math.floor(share * seconds * rate + 1e-9))


# == Read interval (Q13) ==

def read_interval(list_read_seconds: float, settings: SchedulerSettings = DEFAULT_SETTINGS) -> timedelta:
    """Interval between full list reads of a serving portal, from how long its list takes."""
    if list_read_seconds < 0:
        raise ValueError("list_read_seconds must not be negative")
    seconds = max(settings.read_interval_seconds, settings.read_interval_list_multiplier * list_read_seconds)
    return timedelta(seconds=min(settings.read_interval_max_seconds, seconds))


@dataclass(frozen=True)
class ReadPlan:
    interval: timedelta
    first_page_every: timedelta | None  # None: no first-page-only reads


def read_plan(list_read_seconds: float, list_pages: int, newest_first: bool,
              settings: SchedulerSettings = DEFAULT_SETTINGS) -> ReadPlan:
    """The interval, and whether a long newest-first list also gets its first page read alone."""
    long_list = list_pages > settings.first_page_min_list_pages and newest_first
    every = timedelta(seconds=settings.first_page_interval_seconds) if long_list else None
    return ReadPlan(interval=read_interval(list_read_seconds, settings), first_page_every=every)


@dataclass(frozen=True)
class NextRead:
    at: datetime
    first_page_only: bool


def next_read(plan: ReadPlan, last_full_read_started_at: datetime,
              last_first_page_read_started_at: datetime | None = None) -> NextRead:
    """When the next read is due, counted from the start of the last one, and of which kind."""
    # Counted from the start: the longest wrong `serving` is then interval + list time (Q13).
    full_due = _aware(last_full_read_started_at, "last_full_read_started_at") + plan.interval
    if plan.first_page_every is not None:
        base = last_full_read_started_at
        if last_first_page_read_started_at is not None:
            base = max(base, _aware(last_first_page_read_started_at, "last_first_page_read_started_at"))
        page_due = base + plan.first_page_every
        if page_due < full_due:
            return NextRead(at=page_due, first_page_only=True)
    return NextRead(at=full_due, first_page_only=False)


# == Outage retries and failed-portal checks (Q14, Q10) ==

def parse_retry_after(value: str | None, now: datetime) -> timedelta | None:
    """A `Retry-After` header (seconds or HTTP date) as a wait from `now`; None if absent or unreadable."""
    if value is None or not value.strip():
        return None
    value = value.strip()
    if value.isdigit():
        return timedelta(seconds=int(value))
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:  # an HTTP date is GMT by definition (RFC 9110)
        when = when.replace(tzinfo=UTC)
    return max(timedelta(0), when - _aware(now, "now"))


def _not_before(base: datetime, retry_after: timedelta | None, settings: SchedulerSettings) -> datetime:
    if retry_after is None:
        return base
    cap = timedelta(seconds=settings.retry_after_max_seconds)
    return base + min(max(retry_after, timedelta(0)), cap)


def next_outage_retry(last_try_at: datetime, retries_done: int,
                      settings: SchedulerSettings = DEFAULT_SETTINGS,
                      retry_after: timedelta | None = None) -> datetime | None:
    """When to try a portal that stopped answering again; None once the ladder is used up."""
    # The steps are gaps between tries (1, 2, 4, 8, 15, 30 min: 60 min in all, "the first
    # hour"). `last_try_at` is the moment the outage was found when retries_done is 0.
    # After the last step the state module's 60-minute rule makes the portal `failed`,
    # and next_failed_check takes over.
    _aware(last_try_at, "last_try_at")
    if retries_done < 0:
        raise ValueError("retries_done must not be negative")
    steps = settings.outage_retry_steps_seconds
    if retries_done >= len(steps):
        return None
    due = last_try_at + timedelta(seconds=steps[retries_done])
    # A Retry-After is obeyed as "not before", up to the cap; it never brings a try forward.
    return max(due, _not_before(last_try_at, retry_after, settings))


def _failed_check_nominal(index: int, blocked: bool, settings: SchedulerSettings) -> tuple[float, float]:
    """(seconds after the failure, gap since the check before) of check number `index`."""
    if blocked:
        every = settings.blocked_check_every_seconds
        return (index + 1) * every, every
    steps = settings.failed_check_steps_seconds
    if index < len(steps):
        return steps[index], steps[index] - (steps[index - 1] if index else 0.0)
    every = settings.failed_check_every_seconds
    return steps[-1] + (index - len(steps) + 1) * every, every


def next_failed_check(failed_at: datetime, checks_done: int,
                      settings: SchedulerSettings = DEFAULT_SETTINGS, *,
                      blocked: bool = False,
                      rng: Callable[[], float] = random.random,
                      last_check_at: datetime | None = None,
                      retry_after: timedelta | None = None) -> datetime:
    """When the next scheduled check of a `failed` portal is due, shifted at random."""
    # Nominal times: 5 min, 15 min, 1 h after the failure, then every 6 h (blocked: every
    # 6 h from the start). Each is shifted by up to +-20% of its gap from the nominal time
    # before it, so the shifts never reorder the checks and never accumulate.
    # `checks_done` counts scheduled checks only: a check on refresh does not move the ladder.
    _aware(failed_at, "failed_at")
    if checks_done < 0:
        raise ValueError("checks_done must not be negative")
    offset, gap = _failed_check_nominal(checks_done, blocked, settings)
    r = rng()
    if not 0.0 <= r <= 1.0:
        raise ValueError("rng must return a number in [0, 1]")
    shift = (2.0 * r - 1.0) * settings.check_jitter_share * gap
    due = failed_at + timedelta(seconds=offset + shift)
    base = _aware(last_check_at, "last_check_at") if last_check_at is not None else failed_at
    return max(due, _not_before(base, retry_after, settings))


def may_check_on_refresh(last_check_at: datetime | None, now: datetime,
                         settings: SchedulerSettings = DEFAULT_SETTINGS) -> bool:
    """Whether a refresh call may check a failed portal now (at most once a minute)."""
    _aware(now, "now")
    if last_check_at is None:
        return True
    elapsed = now - _aware(last_check_at, "last_check_at")
    return elapsed >= timedelta(seconds=settings.refresh_check_min_seconds)


# == First attach (Q12) ==

@dataclass(frozen=True)
class DocumentNeed:
    """What is known about one tender's documents after the list and record phases."""
    tender_id: str
    deadline: datetime | None
    files: int | None = None        # None: count not known yet, assume settings.assumed_files_per_tender
    zip: bool = False               # one all-documents ZIP replaces the files
    reach_requests: int = 0         # requests before the files (a document list page, ...)
    size_bytes: int | None = None   # announced total, when known

    def requests(self, settings: SchedulerSettings = DEFAULT_SETTINGS) -> int:
        """Requests this tender's documents take."""
        files = 1 if self.zip else (settings.assumed_files_per_tender if self.files is None else self.files)
        return self.reach_requests + files


def document_order(needs: Iterable[DocumentNeed],
                   settings: SchedulerSettings = DEFAULT_SETTINGS) -> list[DocumentNeed]:
    """Order of the document phase: soonest deadline first, smallest tender first among equals."""
    # "Smallest" is the fewest requests, then the fewest announced bytes (unknown last),
    # then the id, so the order is total. A tender with no deadline goes after every
    # tender with one: we cannot say it is urgent, and one closing soon without its
    # documents is the worst case (Q12).
    def key(n: DocumentNeed):
        if n.deadline is not None:
            _aware(n.deadline, f"deadline of {n.tender_id}")
        return (n.deadline is None, n.deadline.astimezone(UTC) if n.deadline else datetime.min.replace(tzinfo=UTC),
                n.requests(settings), n.size_bytes is None, n.size_bytes or 0, n.tender_id)
    return sorted(needs, key=key)


def estimate_document_seconds(needs: Iterable[DocumentNeed], requests_per_second: float = 1.0,
                              settings: SchedulerSettings = DEFAULT_SETTINGS) -> float:
    """Seconds the remaining documents take at the portal's request rate (request starts only)."""
    if requests_per_second <= 0:
        raise ValueError("requests_per_second must be positive")
    return sum(n.requests(settings) for n in needs) / requests_per_second


class Publish(StrEnum):
    none = "none"            # GET /tenders answers []
    validated = "validated"  # the tenders validated so far
    all = "all"              # every tender; documents may still be loading


class AttachPhase(StrEnum):
    reading = "reading"                      # list and record phases
    time_limit = "time_limit"                # limit passed before the records gate
    documents_short = "documents_short"      # gate reached, documents within the 10-minute rule
    documents_following = "documents_following"  # gate reached, documents follow while serving
    complete = "complete"                    # everything in


@dataclass(frozen=True)
class AttachProgress:
    """Plain facts about a running first attach."""
    started_at: datetime
    now: datetime
    tenders_total: int | None          # open tenders in the list; None while the list is still read
    records_done: int                  # records read and validated
    documents_done: int = 0            # tenders whose documents are all in
    documents_remaining_seconds: float = 0.0  # from estimate_document_seconds
    list_pages_read: int = 0
    detail_requests_per_tender: int = 1  # 0 when the list carries every required field
    requests_per_second: float = 1.0
    already_serving: bool = False      # once published, an attach never goes back to integrating


@dataclass(frozen=True)
class AttachDecision:
    phase: AttachPhase
    state: PortalState
    publish: Publish
    reason: str


def attach_decision(p: AttachProgress, settings: SchedulerSettings = DEFAULT_SETTINGS) -> AttachDecision:
    """State, what is published, and the reason, at one moment of a first attach."""
    now = _aware(p.now, "now")
    elapsed = (now - _aware(p.started_at, "started_at")).total_seconds()
    limit_passed = elapsed >= settings.attach_time_limit_seconds
    total = p.tenders_total
    gate = total is not None and p.records_done >= total

    if not gate:
        if (limit_passed or p.already_serving) and p.records_done > 0:
            if total is None:
                reason = (f"Delivering {_n(p.records_done, 'open tender')} so far. "
                          "The tender list is still being read.")
            else:
                rest = (total - p.records_done) * p.detail_requests_per_tender / p.requests_per_second
                by = _clock(now + timedelta(seconds=rest), now)
                reason = (f"Delivering {p.records_done:,} of about {_n(total, 'open tender')} so far. "
                          f"The rest follow by {by}.")
            return AttachDecision(AttachPhase.time_limit, PortalState.serving, Publish.validated, reason)
        # Nothing validated yet: nothing to publish, so stay integrating even past the limit.
        if total is None:
            reason = f"Reading the tender list: {_n(p.list_pages_read, 'page')} so far."
        else:
            reason = f"Reading tender {min(p.records_done + 1, total):,} of {total:,}."
        return AttachDecision(AttachPhase.reading, PortalState.integrating, Publish.none, reason)

    if p.documents_done >= total:
        reason = (f"Read at {_clock(p.started_at, now)} found "
                  f"{_n(total, 'open tender') if total else 'no open tenders'}. Every check passed.")
        return AttachDecision(AttachPhase.complete, PortalState.serving, Publish.all, reason)

    short = p.documents_remaining_seconds <= settings.documents_before_serving_seconds
    if short and not limit_passed and not p.already_serving:
        reason = f"All {_n(total, 'tender')} read. Fetching documents: {p.documents_done:,} of {total:,}."
        return AttachDecision(AttachPhase.documents_short, PortalState.integrating, Publish.none, reason)

    by = _clock(now + timedelta(seconds=p.documents_remaining_seconds), now)
    are = "is" if total == 1 else "are"
    reason = (f"All {_n(total, 'open tender')} {are} delivered. Documents are in for "
              f"{p.documents_done:,} of them, soonest deadlines first; the rest follow by {by}.")
    return AttachDecision(AttachPhase.documents_following, PortalState.serving, Publish.all, reason)


# == Incremental reads (Q12) ==

@dataclass(frozen=True)
class KnownTender:
    """What we know of a tender from earlier reads."""
    tender_id: str
    row_hash: str
    deadline: datetime | None
    detail_read_at: datetime | None
    documents_in: bool


@dataclass(frozen=True)
class ListRow:
    """One row of the new list read."""
    tender_id: str
    row_hash: str
    deadline: datetime | None = None


@dataclass(frozen=True)
class IncrementalPlan:
    fetch: tuple[str, ...]              # new or list row changed: detail page and documents now
    documents_pending: tuple[str, ...]  # listed, unchanged, documents not all in yet
    unlisted: tuple[str, ...]           # known but no longer listed: for check C4
    rotation: tuple[str, ...]           # known tenders whose detail page is re-read in this read
    rotation_budget: int = 0


def _by_deadline(item: tuple[str, datetime | None]):
    tender_id, deadline = item
    return (deadline is None, deadline.astimezone(UTC) if deadline else datetime.min.replace(tzinfo=UTC), tender_id)


def plan_incremental_read(known: Iterable[KnownTender], rows: Iterable[ListRow], now: datetime,
                          interval: timedelta, settings: SchedulerSettings = DEFAULT_SETTINGS,
                          requests_per_second: float = 1.0) -> IncrementalPlan:
    """What one read after the attach fetches, re-reads, and reports as no longer listed."""
    _aware(now, "now")
    known_by_id = {k.tender_id: k for k in known}
    listed: dict[str, ListRow] = {}
    for row in rows:  # a repeated id is check C1's business; the first row counts here
        listed.setdefault(row.tender_id, row)

    fetch, pending, unchanged = [], [], []
    for tid, row in listed.items():
        k = known_by_id.get(tid)
        deadline = row.deadline if row.deadline is not None else (k.deadline if k else None)
        if deadline is not None:
            _aware(deadline, f"deadline of {tid}")
        if k is None or k.row_hash != row.row_hash:
            fetch.append((tid, deadline))
            continue
        unchanged.append((k, deadline))
        if not k.documents_in:
            pending.append((tid, deadline))
    unlisted = sorted(tid for tid in known_by_id if tid not in listed)

    # Even rotation: least recently read first, those closing within 48 hours ahead of all.
    budget = _budget(settings.rotation_budget_share, interval.total_seconds(), requests_per_second)
    urgent_until = now + timedelta(seconds=settings.rotation_urgent_seconds)
    oldest = datetime.min.replace(tzinfo=UTC)

    def rotation_key(item: tuple[KnownTender, datetime | None]):
        k, deadline = item
        urgent = deadline is not None and now < deadline <= urgent_until
        read_at = _aware(k.detail_read_at, "detail_read_at") if k.detail_read_at else oldest
        return (not urgent, read_at, k.tender_id)

    rotation = tuple(k.tender_id for k, _ in sorted(unchanged, key=rotation_key)[:budget])
    return IncrementalPlan(
        fetch=tuple(t for t, _ in sorted(fetch, key=_by_deadline)),
        documents_pending=tuple(t for t, _ in sorted(pending, key=_by_deadline)),
        unlisted=tuple(unlisted),
        rotation=rotation,
        rotation_budget=budget,
    )
