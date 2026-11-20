"""C4 (Q10): known open tenders that are no longer listed.

A tender that was open, has its deadline still ahead and is absent now is never
judged by a count. Its own detail page is looked at (up to five per read): one
that still shows the tender open means the list is broken; closed, withdrawn or
gone is accepted. Only when so many are missing at once that chance does not
explain it must the list also be shown to be whole.
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from app.models import CheckResult, Severity, TenderRecord

from .result import Cause, Effect, Facts, effect_of, failed, observed_of, passed, suspect
from .settings import DEFAULT_SETTINGS, CheckSettings
from .stats import smallest_significant_count
from .words import count, require_aware


class LookOutcome(StrEnum):
    """What the detail page of a missing tender shows."""

    still_open = "still_open"  # the page shows the tender open: the list lost it
    closed = "closed"          # the page says the tender is closed or its deadline passed
    withdrawn = "withdrawn"    # the page says the tender was cancelled
    gone = "gone"              # the page no longer exists (404, 410, "not found")
    unclear = "unclear"        # the page answered but does not say
    no_answer = "no_answer"    # the page did not answer


class DetailLook(Facts):
    """One look at the detail page of a tender that left the list."""

    tender_id: str
    outcome: LookOutcome


def removal_rate(since_last_good: timedelta | None, settings: CheckSettings = DEFAULT_SETTINGS) -> float:
    """Chance that an open tender left the list since the last good read; it grows after a gap of over a day."""
    days = since_last_good.total_seconds() / 86400 if since_last_good is not None else 0.0
    if days <= settings.removal_gap_days:
        return settings.removal_rate_per_read
    grown = 1 - (1 - settings.removal_lifetime_share) ** (days / settings.removal_open_days)
    return max(settings.removal_rate_per_read, round(grown, 3))


def known_ids_missing(run_id: str, last_good: Sequence[TenderRecord], listed_ids: Collection[str], *,
                      now: datetime, since_last_good: timedelta | None = None,
                      settings: CheckSettings = DEFAULT_SETTINGS) -> CheckResult:
    """C4 `known_ids_missing`, first look: which known open tenders are absent, and whose pages to look at.

    A suspect names up to five tenders in `observed["look_at"]`, latest deadline
    first; `confirm_missing` decides from what their detail pages show.
    """
    require_aware(now, "now")
    listed = set(listed_ids)
    known = [record for record in last_good
             if record.listed and not record.withdrawn
             and record.submission_deadline is not None and record.submission_deadline > now]
    missing = sorted((record for record in known if record.tender_id not in listed),
                     key=lambda record: (-record.submission_deadline.timestamp(), record.tender_id))
    rate = removal_rate(since_last_good, settings)
    alarm = smallest_significant_count(len(known), rate, settings.significance)
    observed = {"known": len(known), "missing": len(missing), "rate": rate}
    expected = {"alarm_at": alarm}
    if not known:
        return passed(run_id, "known_ids_missing", "No open tender with its deadline ahead was known before this read.",
                      observed=observed, expected=expected)
    if not missing:
        return passed(run_id, "known_ids_missing", f"All {count(len(known), 'known open tender')} are still listed.",
                      observed=observed, expected=expected)
    ids = [record.tender_id for record in missing]
    observed.update(missing_ids=ids[:50], look_at=ids[:settings.detail_looks_max],
                    mass=alarm is not None and len(missing) >= alarm)
    return suspect(run_id, "known_ids_missing",
                   f"The list no longer shows {len(missing):,} of {count(len(known), 'known open tender')}.",
                   if_confirmed=Cause.breakage, second_look="detail_pages", observed=observed, expected=expected)


def confirm_missing(first: CheckResult, looks: Sequence[DetailLook], *, structure_intact: bool = False,
                    printed_total_agrees: bool = False, proven_empty: bool = False) -> CheckResult:
    """C4 `known_ids_missing`, decided from the detail pages of the tenders that went missing.

    For a mass disappearance the list must also be whole: its structure intact,
    its printed total in agreement, or the portal itself saying the list is empty.
    """
    if first.name != "known_ids_missing" or effect_of(first) is not Effect.suspect:
        raise ValueError("confirm_missing settles a suspect known_ids_missing result")
    was = observed_of(first)
    run_id, missing, known = first.run_id, was["missing"], was["known"]
    found = {look.tender_id: look.outcome for look in looks}
    facts = f"The list no longer shows {missing:,} of {count(known, 'known open tender')}"
    observed = {"first": was, "looks": {tender_id: outcome.value for tender_id, outcome in found.items()}}

    not_looked = [tender_id for tender_id in was["look_at"] if tender_id not in found]
    if not_looked:
        raise ValueError(f"no look at the detail page of {', '.join(not_looked)}")

    def with_outcome(outcome: LookOutcome) -> list[str]:
        return [tender_id for tender_id in was["look_at"] if found[tender_id] is outcome]

    still_open, unclear = with_outcome(LookOutcome.still_open), with_outcome(LookOutcome.unclear)
    no_answer = with_outcome(LookOutcome.no_answer)
    if still_open:
        return failed(run_id, "known_ids_missing",
                      f"{facts}, but the own page of tender {still_open[0]} still shows it open.",
                      cause=Cause.breakage, observed={**observed, "still_open": still_open}, expected=first.expected)
    if unclear:
        return failed(run_id, "known_ids_missing",
                      f"{facts}, and the own page of tender {unclear[0]} does not say whether it is still open.",
                      cause=Cause.breakage, observed={**observed, "unclear": unclear}, expected=first.expected)
    if no_answer:
        # Not evidence that the list is broken: the portal is not answering, so no repair.
        return failed(run_id, "known_ids_missing",
                      f"{facts}, and the own page of tender {no_answer[0]} did not answer.",
                      cause=Cause.outage, observed={**observed, "no_answer": no_answer}, expected=first.expected)
    pages = len(was["look_at"])
    looked = f"The {count(pages, 'page')} we looked at {'says' if pages == 1 else 'say'}"
    if was["mass"] and not (structure_intact or printed_total_agrees or proven_empty):
        return failed(run_id, "known_ids_missing",
                      f"{facts}, all at once. {looked} closed or withdrawn, but neither the list's structure "
                      "nor a printed total confirms that the list is whole.",
                      cause=Cause.breakage, observed={**observed, "list_whole": False}, expected=first.expected)
    withdrawn = with_outcome(LookOutcome.withdrawn)
    closed = with_outcome(LookOutcome.closed) + with_outcome(LookOutcome.gone)
    says = " and ".join(f"{len(ids)} {word}" for ids, word in ((closed, "closed"), (withdrawn, "withdrawn")) if ids)
    return passed(run_id, "known_ids_missing", f"{facts}. {looked}: {says}.", severity=Severity.info,
                  observed={**observed, "closed": closed, "withdrawn": withdrawn}, expected=first.expected)
