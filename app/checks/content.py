"""Step 3 of a read (Q10): is what we extracted right? No model is called.

C1 (the list is complete), C3 (known tenders reproduce), C5 (new tenders are as
complete as earlier ones), C6 (the canary) and F1 (age). C2 is in `values.py`,
C4 in `missing.py`, C7 in `skeleton.py` and D1 in `files.py`.

A first failure of C1, C3 (lost), C5 or C6 is a suspect: the part that failed is
read again and `confirm` settles it. Nothing here changes the state on one look.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from app.models import CheckResult, PortalState, TenderRecord

from .result import SPOT_CHECK, Cause, Facts, failed, passed, suspect, wants_spot_check
from .settings import DEFAULT_SETTINGS, CheckSettings
from .stats import fisher_exact_upper, fisher_significant, smallest_significant_count, smallest_significant_hits
from .words import clock, count, field_word, require_aware

# The required values a read extracts. `id` is the key, and `status`, `documents`
# and `lastChangedAt` are ours to compute.
REQUIRED_VALUES = ("url", "title", "buyer_name", "publication_date", "submission_deadline")


# -- C1: the list is complete ------------------------------------------------

def paging_complete(run_id: str, *, reached_end: bool, pages: int) -> CheckResult:
    """C1 `paging_complete`: paging reached the end of the list."""
    seen = {"pages": pages, "reached_end": reached_end}
    if reached_end:
        return passed(run_id, "paging_complete", f"Paging reached the end of the list after {count(pages, 'page')}.",
                      observed=seen)
    return suspect(run_id, "paging_complete",
                   f"Paging stopped after {count(pages, 'page')} without reaching the end of the list.",
                   if_confirmed=Cause.breakage, observed=seen)


def duplicate_ids(run_id: str, ids: Sequence[str]) -> CheckResult:
    """C1 `duplicate_ids`: no tender id appears twice in the list."""
    twice = sorted(tender_id for tender_id, n in Counter(ids).items() if n > 1)
    seen = {"rows": len(ids), "duplicates": len(twice), "examples": twice[:5]}
    if not twice:
        return passed(run_id, "duplicate_ids", f"No id appears twice among {count(len(ids), 'row')}.", observed=seen)
    return suspect(run_id, "duplicate_ids",
                   f"The list shows {count(len(twice), 'tender id')} more than once, for example {twice[0]}.",
                   if_confirmed=Cause.breakage, observed=seen)


def printed_total(run_id: str, *, extracted: int, printed: int | None) -> CheckResult:
    """C1 `printed_total`: when the portal prints a total, the list holds exactly that many."""
    seen = {"extracted": extracted}
    if printed is None:
        return passed(run_id, "printed_total", "The portal prints no total to compare with.", observed=seen)
    if extracted == printed:
        return passed(run_id, "printed_total",
                      f"The list reads {count(extracted, 'tender')}, as many as the portal prints.",
                      observed=seen, expected=printed)
    return suspect(run_id, "printed_total",
                   f"The list reads {count(extracted, 'tender')} but the portal prints {printed:,}.",
                   if_confirmed=Cause.breakage, observed=seen, expected=printed)


# -- C3: known tenders reproduce ---------------------------------------------

def known_tenders_reproduce(run_id: str, records: Sequence[TenderRecord], last_good: Sequence[TenderRecord], *,
                            fields: Sequence[str] = REQUIRED_VALUES,
                            settings: CheckSettings = DEFAULT_SETTINGS) -> list[CheckResult]:
    """C3 `lost.<field>` and `changed.<field>`: tenders in this read and the last good one, compared pairwise.

    Lost values are a suspect (read again, then `confirm`); changed values ask for
    the model's spot check. The count that alarms comes from the exact test.
    """
    before = {record.tender_id: record for record in last_good}
    pairs = [(before[record.tender_id], record) for record in records if record.tender_id in before]
    rows: list[CheckResult] = []
    for field in fields:
        had = [(old, new) for old, new in pairs if getattr(old, field) is not None]
        lost = [new.tender_id for old, new in had if getattr(new, field) is None]
        changed = [new.tender_id for old, new in had
                   if getattr(new, field) is not None and getattr(new, field) != getattr(old, field)]
        rows.append(_lost(run_id, field, lost, len(had), settings))
        rows.append(_changed(run_id, field, changed, len(had), settings))
    return rows


def _lost(run_id: str, field: str, lost: list[str], known: int, settings: CheckSettings) -> CheckResult:
    name, word = f"lost.{field}", field_word(field)
    alarm = smallest_significant_count(known, settings.lost_value_rate, settings.significance)
    seen, expected = {"known": known, "lost": len(lost), "examples": lost[:5]}, {"alarm_at": alarm}
    gone = f"The {word} is gone from {len(lost):,} of {count(known, 'known tender')}"
    if not lost:
        return passed(run_id, name, f"No known tender lost its {word}.", observed=seen, expected=expected)
    if alarm is None:
        # Too few known tenders for any count to be rare: read again, then let the model look.
        return suspect(run_id, name, f"{gone}; too few tenders are known to judge that by numbers.",
                       if_confirmed=SPOT_CHECK, observed=seen, expected=expected)
    if len(lost) >= alarm:
        return suspect(run_id, name, f"{gone}.", if_confirmed=Cause.breakage, observed=seen, expected=expected)
    return passed(run_id, name, f"{gone}; a portal does that now and then, and an alarm needs {alarm:,}.",
                  observed=seen, expected=expected)


def _changed(run_id: str, field: str, changed: list[str], known: int, settings: CheckSettings) -> CheckResult:
    name, word = f"changed.{field}", field_word(field)
    alarm = smallest_significant_count(known, settings.changed_value_rate, settings.significance)
    seen, expected = {"known": known, "changed": len(changed), "examples": changed[:5]}, {"alarm_at": alarm}
    differs = f"The {word} differs from the last good read on {len(changed):,} of {count(known, 'known tender')}"
    if alarm is not None and len(changed) >= alarm:
        return wants_spot_check(run_id, name, f"{differs}.", observed=seen, expected=expected)
    if changed:
        return passed(run_id, name, f"{differs}; tenders do change, and that many is not unusual.",
                      observed=seen, expected=expected)
    return passed(run_id, name, f"No known tender shows a different {word}.", observed=seen, expected=expected)


# -- C5: new tenders are as complete as before -------------------------------

def null_rates(run_id: str, new_records: Sequence[TenderRecord], *, earlier_nulls: Mapping[str, int],
               earlier_rows: int, fields: Sequence[str] = REQUIRED_VALUES,
               settings: CheckSettings = DEFAULT_SETTINGS) -> list[CheckResult]:
    """C5 `null_rate.<field>`: nulls among tenders first seen in this read, against all rows of earlier good reads."""
    rows: list[CheckResult] = []
    new = len(new_records)
    for field in fields:
        word, name = field_word(field), f"null_rate.{field}"
        nulls = sum(1 for record in new_records if getattr(record, field) is None)
        before = earlier_nulls.get(field, 0)
        seen = {"new_rows": new, "new_nulls": nulls, "earlier_rows": earlier_rows, "earlier_nulls": before}
        if new == 0 or earlier_rows == 0:
            nothing = "No new tender in this read." if new == 0 else "No earlier read to compare the new tenders with."
            rows.append(passed(run_id, name, nothing, observed=seen))
            continue
        seen["chance"] = fisher_exact_upper(nulls, new, before, earlier_rows)
        expected = {"alarm_at": smallest_significant_hits(new, before, earlier_rows, settings.significance)}
        facts = (f"The {word} is missing on {nulls:,} of {count(new, 'new tender')}, "
                 f"against {before:,} of {earlier_rows:,} rows in earlier reads")
        if fisher_significant(nulls, new, before, earlier_rows, settings.significance):
            rows.append(suspect(run_id, name, f"{facts}.", if_confirmed=Cause.breakage,
                                observed=seen, expected=expected))
        else:
            rows.append(passed(run_id, name, f"{facts}. That is not unusual.", observed=seen, expected=expected))
    return rows


# -- C6: the canary ----------------------------------------------------------

class CanaryPage(Facts):
    """A known detail page fetched again: what it gave before and what it gives now."""

    tender_id: str
    title: str | None
    read_id: str | None
    read_title: str | None


def canary(run_id: str, pages: Sequence[CanaryPage], *, file_valid: bool | None = None) -> CheckResult:
    """C6 `canary`: known detail pages give the same id and title, and the known file is a valid file.

    `file_valid` is whether the known file passed `file_outcome`; None when the
    portal has no known file. A failure is a suspect: it must fail twice.
    """
    wrong = [page.tender_id for page in pages if (page.read_id, page.read_title) != (page.tender_id, page.title)]
    seen = {"pages": len(pages), "pages_wrong": wrong, "file_valid": file_valid}
    if not wrong and file_valid is not False:
        same = (f"The {count(len(pages), 'known tender page')} gave the same id and title as before" if pages
                else "No known tender page was fetched again")
        with_file = "" if file_valid is None else ", and the known file is valid"
        return passed(run_id, "canary", f"{same}{with_file}.", observed=seen)
    parts = []
    if wrong:
        parts.append(f"the page of tender {wrong[0]} no longer gives the same id and title")
    if file_valid is False:
        parts.append("the known file no longer arrives as a valid file")
    text = " and ".join(parts)
    return suspect(run_id, "canary", f"A known page or file reads differently: {text}.",
                   if_confirmed=Cause.breakage, observed=seen)


# -- F1: age -----------------------------------------------------------------

def stale(run_id: str, *, state: PortalState, last_good_at: datetime | None, now: datetime,
          read_interval: timedelta, settings: CheckSettings = DEFAULT_SETTINGS) -> CheckResult:
    """F1 `stale`: a `serving` portal whose last passing read is older than three read intervals."""
    require_aware(now, "now")
    limit = read_interval * settings.stale_after_intervals
    seen = {"state": state.value, "last_good_at": last_good_at.isoformat() if last_good_at else None,
            "limit_seconds": limit.total_seconds()}
    if state is not PortalState.serving or last_good_at is None:
        return passed(run_id, "stale", "The portal is not serving, so the age of its last read is not judged.",
                      observed=seen)
    age = now - require_aware(last_good_at, "last_good_at")
    seen["age_seconds"] = age.total_seconds()
    if age <= limit:
        return passed(run_id, "stale", f"The last read that passed was at {clock(last_good_at, now)}.", observed=seen)
    return failed(run_id, "stale", f"No read has passed since {clock(last_good_at, now)}. Reads are not completing.",
                  cause=Cause.outage, observed=seen)
