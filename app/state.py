"""From the checks of one read to the portal's state and reason (Q10 step 5, Q14).

`decide` is a pure function. It never changes the state on a suspect: while a
first observation still waits for its second look, or a spot check is due, it
answers `Verdict.pending`, keeps the state as it was and says what is still to do.
Call it again with the settled results.

What decides, first match wins:

    a block                     failed at once; never a repair
    an outage                   healing; failed after 60 minutes; never a repair
    a suspect, unconfirmed      pending
    a breakage                  healing and a repair; failed when the budget is used
                                or the page structure is one we already gave up on
    no passing read for long    healing (stale)
    a spot check still due      pending
    nothing failed              serving, if the tender list arrived; otherwise nothing changes
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.checks.result import Cause, Effect, effect_of, observed_of
from app.checks.settings import DEFAULT_SETTINGS, CheckSettings
from app.checks.words import clock, count, span
from app.models import CheckResult, PortalState

__all__ = ["Cause", "Decision", "ReadFacts", "Verdict", "decide"]

_EMPTY_PROOF = {
    "notice": "Its own 'no results' notice is shown",
    "total": "It prints a total of 0",
    "api": "Its API answers with an empty list",
}


class Verdict(StrEnum):
    """The rows of the verdict table, plus the failed-portal rows of Q14 and "not settled yet"."""

    passed = "pass"
    passed_empty = "pass_empty"
    outage = "outage"
    outage_long = "outage_long"
    block = "block"
    breakage = "breakage"
    breakage_budget_used = "breakage_budget_used"
    breakage_known_structure = "breakage_known_structure"
    breakage_daily_limit = "breakage_daily_limit"
    stale = "stale"
    pending = "pending"


class ReadFacts(BaseModel):
    """What the state machine needs to know besides the check results of the read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    now: AwareDatetime = Field(description="When the read ended")
    state_before: PortalState
    cause_before: Cause | None = Field(None, description="The portal's cause before the read, kept while pending")
    full_read: bool = Field(True, description="False for a read of part of the list (Q13's first page)")
    open_tenders: int = Field(0, ge=0, description="Open tenders this read found")
    new_tenders: int = Field(0, ge=0, description="Tenders first seen in this read")
    closed_tenders: int = Field(0, ge=0, description="Known tenders this read closed or saw withdrawn")
    last_good_at: AwareDatetime | None = Field(None, description="End of the last read that passed")
    last_good_tenders: int = Field(0, ge=0, description="Open tenders that read found; still delivered")
    outage_since: AwareDatetime | None = Field(None, description="First request of the running outage that failed")
    next_try_at: AwareDatetime | None = Field(None, description="When the scheduler tries or checks next (Q14)")
    broken_since: AwareDatetime | None = Field(None, description="When the running breakage was first confirmed")
    repair_attempts_used: int = Field(0, ge=0, description="Repair attempts already made in this incident")
    repairs_tried: tuple[str, ...] = Field((), description="What those attempts were, in words")
    repairs_today: int = Field(0, ge=0, description="Repairs started for this portal today")
    structure_given_up: bool = Field(False, description="The page structure is one we already gave up on (Q14)")


class Decision(BaseModel):
    """What follows from one read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Verdict = Field(description="A pass means serving; pending means nothing changes yet")
    state: PortalState = Field(description="The state after the read")
    reason: str = Field(description="For the operator, in plain words")
    cause: Cause | None = Field(description="Why the portal is not serving; None when it is")
    start_repair: bool = Field(False, description="A repair attempt starts now; never after an outage or a block")
    spot_check_needed: bool = Field(False, description="Run the model's spot check, add its result, decide again")
    read_passed: bool = Field(False, description="The read passed every check: publish it")
    unconfirmed: tuple[str, ...] = Field((), description="Suspect checks still waiting for their second look")
    decided_by: str | None = Field(None, description="Name of the check that decided")


def decide(results: Sequence[CheckResult], facts: ReadFacts,
           settings: CheckSettings = DEFAULT_SETTINGS) -> Decision:
    """The state, reason and cause after a read, and whether a repair or a spot check follows."""
    asked: dict[Effect, list[CheckResult]] = {effect: [] for effect in Effect}
    for result in results:
        asked[effect_of(result)].append(result)

    if asked[Effect.block]:
        return _block(asked[Effect.block][0], facts)
    outages = [result for result in asked[Effect.outage] if result.name != "stale"]
    if outages:
        return _outage(outages[0], facts, settings)
    if asked[Effect.suspect]:
        return _pending(asked[Effect.suspect], facts)
    if asked[Effect.breakage]:
        return _breakage(asked[Effect.breakage][0], facts, settings)
    if asked[Effect.outage]:
        return _stale(asked[Effect.outage][0], facts)
    if asked[Effect.spot_check] and not any(result.name == "spot_check" for result in results):
        return _spot_check(asked[Effect.spot_check][0], facts)
    return _pass(results, asked[Effect.note], facts)


# -- the rows ----------------------------------------------------------------

def _text(*sentences: str) -> str:
    return " ".join(sentence for sentence in sentences if sentence)


def _delivering(facts: ReadFacts) -> str:
    if facts.last_good_at is None:
        return "nothing is delivered yet"
    return (f"still delivering the {count(facts.last_good_tenders, 'tender')} "
            f"read at {clock(facts.last_good_at, facts.now)}")


def _sentence(clause: str) -> str:
    return f"{clause[0].upper()}{clause[1:]}."


def _recheck(facts: ReadFacts) -> str:
    if facts.next_try_at is None:
        return "We keep checking, also on every refresh."
    return f"We check again at {clock(facts.next_try_at, facts.now)} and on every refresh."


def _block(row: CheckResult, facts: ReadFacts) -> Decision:
    again = f"Still so at {clock(facts.now, facts.now)}." if facts.state_before is PortalState.failed else ""
    return Decision(verdict=Verdict.block, state=PortalState.failed, cause=Cause.block,
                    reason=_text(row.message, again), decided_by=row.name)


def _pending(suspects: Sequence[CheckResult], facts: ReadFacts) -> Decision:
    return Decision(verdict=Verdict.pending, state=facts.state_before, cause=facts.cause_before,
                    reason=_text("Looking a second time before deciding.", suspects[0].message),
                    unconfirmed=tuple(result.name for result in suspects), decided_by=suspects[0].name)


def _spot_check(row: CheckResult, facts: ReadFacts) -> Decision:
    return Decision(verdict=Verdict.pending, state=facts.state_before, cause=facts.cause_before,
                    reason=_text("Asking the model to check the values against the page.", row.message),
                    spot_check_needed=True, decided_by=row.name)


def _outage(row: CheckResult, facts: ReadFacts, settings: CheckSettings) -> Decision:
    since = facts.outage_since or facts.now
    lasted = facts.now - since
    long = lasted >= timedelta(minutes=settings.outage_failed_after_minutes)
    detail = observed_of(row).get("detail")
    if long or facts.state_before is PortalState.failed:
        # A portal we knew to be behind a login may still be: do not claim otherwise.
        no_login = "" if facts.cause_before is Cause.block else "This is not a login block."
        if detail and long:
            lead = _text(f"The portal has been unreachable for {span(lasted)} ({detail}).", no_login)
        elif detail:
            lead = _text(f"The portal did not answer at {clock(facts.now, facts.now)} ({detail}).", no_login)
        else:
            lead = _text(row.message, f"This has lasted {span(lasted)}." if long else "")
        return Decision(verdict=Verdict.outage_long, state=PortalState.failed, cause=Cause.outage,
                        reason=_text(lead, _recheck(facts)), decided_by=row.name)
    # An outage is `failed` from the first read that finds it (decision of 20 Nov 2026): the portal cannot
    # deliver, and nobody can do anything about it. The cause says so; the retries are the outage ladder.
    attaching = facts.state_before is PortalState.integrating
    lead = f"The portal has not answered since {clock(since, facts.now)} ({detail})." if detail else row.message
    next_try = f"Next try {clock(facts.next_try_at, facts.now)}." if facts.next_try_at else ""
    return Decision(verdict=Verdict.outage, cause=Cause.outage, state=PortalState.failed,
                    reason=_text(lead, _sentence(_delivering(facts)), next_try,
                                 "" if attaching else "The recipe is unchanged."),
                    decided_by=row.name)


def _breakage(row: CheckResult, facts: ReadFacts, settings: CheckSettings) -> Decision:
    def failed(verdict: Verdict, *why: str) -> Decision:
        return Decision(verdict=verdict, state=PortalState.failed, cause=Cause.breakage,
                        reason=_text(row.message, *why), decided_by=row.name)

    was_failed = facts.state_before is PortalState.failed
    checked = f"Last checked at {clock(facts.now, facts.now)}." if was_failed else ""
    if facts.structure_given_up:
        return failed(Verdict.breakage_known_structure,
                      "The page structure is one we already gave up on, so no repair starts.",
                      "A person is needed.", checked)
    if was_failed:
        if facts.repairs_today >= settings.repairs_per_day:
            return failed(Verdict.breakage_daily_limit,
                          f"The page structure is new, but {count(facts.repairs_today, 'repair')} already ran "
                          f"today and the limit is {settings.repairs_per_day}, so none starts.",
                          "A person is needed.", checked)
        return Decision(verdict=Verdict.breakage, state=PortalState.healing, cause=Cause.breakage, start_repair=True,
                        reason=_text(row.message, "This page structure is new to us, so one repair attempt "
                                     f"starts; {_delivering(facts)}."),
                        decided_by=row.name)
    limit = settings.repair_attempts_per_incident
    if facts.repair_attempts_used >= limit:
        since = (f"The portal's reads have failed their checks since {clock(facts.broken_since, facts.now)}."
                 if facts.broken_since else "The portal's reads keep failing their checks.")
        tried = f" ({', '.join(facts.repairs_tried)})" if facts.repairs_tried else ""
        return Decision(verdict=Verdict.breakage_budget_used, state=PortalState.failed, cause=Cause.breakage,
                        reason=_text(since, row.message, f"All {count(limit, 'repair attempt')} failed{tried}.",
                                     "A person is needed."),
                        decided_by=row.name)
    attempt = f", attempt {facts.repair_attempts_used + 1} of {limit}" if facts.repair_attempts_used else ""
    if facts.state_before is PortalState.integrating:
        return Decision(verdict=Verdict.breakage, state=PortalState.integrating, cause=Cause.breakage,
                        start_repair=True, decided_by=row.name,
                        reason=_text(row.message, f"Learning the portal again{attempt}; {_delivering(facts)}."))
    return Decision(verdict=Verdict.breakage, state=PortalState.healing, cause=Cause.breakage, start_repair=True,
                    reason=_text(row.message, f"Repairing{attempt}; {_delivering(facts)}."), decided_by=row.name)


def _stale(row: CheckResult, facts: ReadFacts) -> Decision:
    return Decision(verdict=Verdict.stale, state=PortalState.failed, cause=Cause.outage,
                    reason=_text(row.message, _sentence(_delivering(facts))), decided_by=row.name)


def _pass(results: Sequence[CheckResult], notes: Sequence[CheckResult], facts: ReadFacts) -> Decision:
    at = clock(facts.now, facts.now)
    if not any(result.name == "list_outcome" and result.passed for result in results):
        # Nothing failed, but nothing shows that the list arrived: that is not a read that passed.
        return Decision(verdict=Verdict.pending, state=facts.state_before, cause=facts.cause_before,
                        reason="No read of the tender list was judged, so nothing changes.")
    if not facts.full_read and facts.state_before is not PortalState.serving:
        return Decision(verdict=Verdict.pending, state=facts.state_before, cause=facts.cause_before,
                        reason=f"The partial read at {at} passed its checks. A full read must pass before the "
                               "portal is served again.")
    checks = ("Every check passed." if not notes
              else f"No check failed; {count(len(notes), 'warning')} {'is' if len(notes) == 1 else 'are'} "
                   "logged on the run.")
    back = "The portal is served again." if facts.state_before in (PortalState.healing, PortalState.failed) else ""
    proof = next((observed_of(result).get("empty") for result in results
                  if result.name == "list_outcome" and result.passed), None)
    if facts.open_tenders == 0 and proof in _EMPTY_PROOF:
        known = (f", and the {count(facts.last_good_tenders, 'tender')} we knew "
                 f"{'is' if facts.last_good_tenders == 1 else 'are'} closed" if facts.last_good_tenders else "")
        return Decision(verdict=Verdict.passed_empty, state=PortalState.serving, cause=None, read_passed=True,
                        reason=_text(f"The portal lists no open tenders at {at}.", f"{_EMPTY_PROOF[proof]}{known}.",
                                     checks if notes else "", back))
    found = (f"Read at {at} found {count(facts.open_tenders, 'open tender')}, "
             f"{facts.new_tenders:,} new and {facts.closed_tenders:,} closed.")
    return Decision(verdict=Verdict.passed, state=PortalState.serving, cause=None, read_passed=True,
                    reason=_text(found, checks, back))
