"""How a check says what it found, inside the `CheckResult` of `app/models.py`.

`Severity` has four values and no way to say "the portal is down" or "look again
first". Until `app/models.py` gains them, every result built here keeps `observed`
as a dict and uses three reserved keys in it:

    cause         "outage", "block" or "breakage", on a result that failed
    effect        "suspect" (a second look must confirm it before the state may change)
                  or "spot_check" (the model must check the values)
    if_confirmed  on a suspect: the cause it gets when the second look agrees,
                  or "spot_check"
    second_look   on a suspect, what to do again: "reread" (the part that failed),
                  "browser" (fetch once more, through the browser), "retry" (the
                  same request) or "detail_pages" (of the tenders that went missing)

`effect_of` reads them back. A plain `CheckResult` built elsewhere (the spot check's
own result, for one) is read by its severity alone.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import CheckResult, Severity


class Facts(BaseModel):
    """Base for the small records a read hands to the checks: frozen, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Cause(StrEnum):
    """Why a portal is not `serving` (the `cause` field of DESIGN.md)."""

    outage = "outage"      # not answering: healing, never a repair
    block = "block"        # a login or bot wall: failed
    breakage = "breakage"  # the read is wrong: healing, repair


class Effect(StrEnum):
    """What one check result asks of the state machine."""

    none = "none"              # passed, or recorded only
    note = "note"              # a warning: shown, state unchanged
    suspect = "suspect"        # needs its second observation first
    spot_check = "spot_check"  # needs the model's spot check
    outage = "outage"
    block = "block"
    breakage = "breakage"


SPOT_CHECK = "spot_check"
_RESERVED = ("effect", "if_confirmed", "second_look")


def _seen(observed: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
    return {**(observed or {}), **{k: v for k, v in extra.items() if v is not None}}


def passed(run_id: str, name: str, message: str, *, severity: Severity = Severity.fail,
           observed: dict[str, Any] | None = None, expected: Any = None) -> CheckResult:
    """A check that passed; `severity` is what its failure would do."""
    return CheckResult(run_id=run_id, name=name, passed=True, severity=severity,
                       observed=_seen(observed), expected=expected, message=message)


def note(run_id: str, name: str, message: str, *, cause: Cause | None = None,
         observed: dict[str, Any] | None = None, expected: Any = None) -> CheckResult:
    """A warning: logged on the run, the state does not change."""
    return CheckResult(run_id=run_id, name=name, passed=False, severity=Severity.warn,
                       observed=_seen(observed, cause=cause), expected=expected, message=message)


def suspect(run_id: str, name: str, message: str, *, if_confirmed: Cause | str,
            second_look: str = "reread", observed: dict[str, Any] | None = None,
            expected: Any = None) -> CheckResult:
    """A first observation that must be confirmed before it may change the state."""
    seen = _seen(observed, effect=Effect.suspect.value, if_confirmed=str(if_confirmed), second_look=second_look)
    return CheckResult(run_id=run_id, name=name, passed=False, severity=Severity.warn,
                       observed=seen, expected=expected, message=message)


def wants_spot_check(run_id: str, name: str, message: str, *, observed: dict[str, Any] | None = None,
                     expected: Any = None) -> CheckResult:
    """A finding only the model's spot check can settle; never a failure alone."""
    return CheckResult(run_id=run_id, name=name, passed=False, severity=Severity.warn,
                       observed=_seen(observed, effect=Effect.spot_check.value),
                       expected=expected, message=message)


def failed(run_id: str, name: str, message: str, *, cause: Cause,
           observed: dict[str, Any] | None = None, expected: Any = None) -> CheckResult:
    """A confirmed failure. An outage is `fail` with cause "outage" until `Severity.outage` exists."""
    severity = Severity.block if cause is Cause.block else Severity.fail
    return CheckResult(run_id=run_id, name=name, passed=False, severity=severity,
                       observed=_seen(observed, cause=cause.value), expected=expected, message=message)


def observed_of(result: CheckResult) -> dict[str, Any]:
    """`observed` as a dict; empty when a result built elsewhere holds something else."""
    return result.observed if isinstance(result.observed, dict) else {}


def effect_of(result: CheckResult) -> Effect:
    """What this result asks of the state machine."""
    if result.passed:
        return Effect.none
    marked = observed_of(result).get("effect")
    if marked in (Effect.suspect.value, Effect.spot_check.value):
        return Effect(marked)
    if result.severity is Severity.block:
        return Effect.block
    if result.severity is Severity.fail:
        return Effect.outage if observed_of(result).get("cause") == Cause.outage.value else Effect.breakage
    return Effect.note if result.severity is Severity.warn else Effect.none


def cause_of(result: CheckResult) -> Cause | None:
    """The cause a failed result carries, or the one a suspect would get when confirmed."""
    if result.passed:
        return None
    for key in ("cause", "if_confirmed"):
        value = observed_of(result).get(key)
        if value in (Cause.outage.value, Cause.block.value, Cause.breakage.value):
            return Cause(value)
    effect = effect_of(result)
    return Cause(effect.value) if effect.value in Cause.__members__ else None


def without_marks(observed: dict[str, Any]) -> dict[str, Any]:
    """`observed` without the keys that mark a suspect."""
    return {k: v for k, v in observed.items() if k not in _RESERVED}
