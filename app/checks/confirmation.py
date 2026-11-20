"""The confirm step (Q10, step 4) in data.

A suspect read repeats the part that failed, at once. The first observation, the
second one and what follows from the two are one record, so a run can store a
single row per check that still shows both looks.
"""
from __future__ import annotations

from app.models import CheckResult, Severity

from .result import (
    SPOT_CHECK, Cause, Effect, Facts, effect_of, failed, observed_of, wants_spot_check, without_marks,
)


class Confirmation(Facts):
    """A suspect first observation, the second observation of the same check, and the result."""

    first: CheckResult
    second: CheckResult

    @property
    def cleared(self) -> bool:
        """True when the second look was clean, so the read passes this check."""
        return self.second.passed

    @property
    def result(self) -> CheckResult:
        """The one row to keep: a passed `info` row when cleared, the confirmed failure otherwise."""
        first, second = self.first, self.second
        if effect_of(first) is not Effect.suspect:
            raise ValueError(f"{first.name}: only a suspect result is confirmed")
        if (first.run_id, first.name) != (second.run_id, second.name):
            raise ValueError(f"{first.name}: the second look must be the same check in the same run")
        if second.passed:
            return CheckResult(
                run_id=first.run_id, name=first.name, passed=True, severity=Severity.info,
                observed={"first": first.observed, "second": second.observed}, expected=first.expected,
                message=f"The first look found a problem and the second did not. First look: {first.message}",
            )
        both = {**without_marks(observed_of(second)), "first": first.observed, "confirmed": True}
        if effect_of(second) is not Effect.suspect:
            # The second look already settled it on its own (a third failed try, for one).
            return second.model_copy(update={"observed": both})
        message = f"{second.message} A second look found the same."
        outcome = observed_of(second).get("if_confirmed")
        if outcome == SPOT_CHECK:
            return wants_spot_check(first.run_id, first.name, message, observed=both, expected=second.expected)
        return failed(first.run_id, first.name, message, cause=Cause(outcome), observed=both,
                      expected=second.expected)


def confirm(first: CheckResult, second: CheckResult) -> CheckResult:
    """Settle a suspect with its second observation: cleared (passed, `info`) or confirmed."""
    return Confirmation(first=first, second=second).result
