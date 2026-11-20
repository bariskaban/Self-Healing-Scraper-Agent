"""D1 (Q10): what the failed files of one read mean together.

One file is not the portal. The files that failed `file_outcome` are held against
the failure share of earlier good reads with Fisher's exact test, and "every file
failed" (two or more) always counts. Below that the rest is published and the
failures are logged on the run. Above it the failed files are tried once more, and
then the cause they share decides: outage, block or breakage.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from app.models import CheckResult, Severity

from .result import Cause, cause_of, failed, note, passed, suspect
from .settings import DEFAULT_SETTINGS, CheckSettings
from .stats import fisher_significant
from .words import count

# When two causes tie, the one that costs least if it is wrong comes first.
_TIE_ORDER = (Cause.outage, Cause.breakage, Cause.block)


def files_failed(run_id: str, file_results: Sequence[CheckResult], *, earlier_failed: int, earlier_files: int,
                 retried: bool, settings: CheckSettings = DEFAULT_SETTINGS) -> CheckResult:
    """D1 `files_failed`: this read's `file_outcome` results against the failures of earlier good reads.

    `retried` says whether the failed files were already tried once more at the end
    of the read; until then an alarm is only a suspect.
    """
    total = len(file_results)
    bad = [result for result in file_results if not result.passed]
    seen = {"files": total, "failed": len(bad), "earlier_files": earlier_files, "earlier_failed": earlier_failed}
    if not bad:
        text = f"All {count(total, 'file')} arrived." if total else "No file was fetched in this read."
        return passed(run_id, "files_failed", text, severity=Severity.warn, observed=seen)

    causes = Counter(cause_of(result) or Cause.breakage for result in bad)
    cause = max(_TIE_ORDER, key=lambda c: (causes[c], -_TIE_ORDER.index(c)))
    seen["causes"] = {c.value: n for c, n in causes.items()}
    example = next(result for result in bad if (cause_of(result) or Cause.breakage) is cause).message
    facts = f"Downloads failed for {len(bad):,} of {count(total, 'file')}"

    every_file = len(bad) == total and total >= settings.all_files_failed_min
    alarm = every_file or fisher_significant(len(bad), total, earlier_failed, earlier_files, settings.significance)
    if not alarm:
        rest = "the rest are published" if len(bad) < total else "that is too few files to judge the portal by"
        return note(run_id, "files_failed", f"{facts}; {rest}. For example: {example}", cause=cause, observed=seen)
    if not retried:
        return suspect(run_id, "files_failed", f"{facts}. For example: {example}", if_confirmed=cause,
                       second_look="retry", observed=seen)
    if cause is Cause.block and causes[Cause.block] * 2 <= total:
        # The mentor's rule: the portal is failed only when most files are blocked.
        return note(run_id, "files_failed",
                    f"A wall stands in front of {causes[Cause.block]:,} of {count(total, 'file')}; those "
                    f"documents are left out and the rest are published. For example: {example}",
                    cause=cause, observed=seen)
    if cause is Cause.outage:
        seen["detail"] = f"{len(bad):,} of {count(total, 'file')} did not download"
    return failed(run_id, "files_failed", f"{facts}, also on a second try. For example: {example}", cause=cause,
                  observed=seen)
