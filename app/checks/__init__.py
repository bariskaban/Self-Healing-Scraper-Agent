"""The checks that decide whether a read of a portal was correct (Q10).

Pure logic: no network and no model call. Every check takes plain facts about what
a read observed and returns a `CheckResult` (or a list of them, one per field).
`app/state.py` turns the results of one read into the portal's state and reason.

A read runs them in this order:

    1  transport_check, robots_check             did each request get an answer?
    2  list_outcome, file_outcome, block_check   did what we asked for arrive?
    3  paging_complete, duplicate_ids, printed_total, shape, known_tenders_reproduce,
       known_ids_missing, null_rates, canary, structure, files_failed, stale
    4  confirm, confirm_missing                  the second look at whatever was suspect

`skip_reason` turns a failed `file_outcome` into the `SkipReason` of the file's record,
which is what the `judge` of `app/docs` returns. Settings: `CheckSettings`.

How a result says "suspect", "outage" or "spot check" inside `CheckResult` is
described in `result.py`; `effect_of` reads it back.
"""
from .confirmation import Confirmation, confirm
from .content import (
    REQUIRED_VALUES, CanaryPage, canary, duplicate_ids, known_tenders_reproduce, null_rates,
    paging_complete, printed_total, stale,
)
from .files import files_failed
from .missing import DetailLook, LookOutcome, confirm_missing, known_ids_missing, removal_rate
from .outcome import DownloadFacts, ListFacts, file_outcome, list_outcome, skip_reason
from .result import Cause, Effect, cause_of, effect_of
from .settings import DEFAULT_SETTINGS, CheckSettings
from .skeleton import fingerprint, html_paths, json_paths, overlap, structure, structure_floor
from .stats import (
    binomial_upper_tail, fisher_exact_upper, fisher_significant, smallest_significant_count,
    smallest_significant_hits,
)
from .transport import (
    Answer, BlockSign, ErrorKind, Transport, block_check, block_sign, classify_answer, robots_check,
    transport_check,
)
from .values import ValueProblem, shape, shape_problems, without_bad_values

__all__ = [
    "DEFAULT_SETTINGS", "REQUIRED_VALUES", "Answer", "BlockSign", "CanaryPage", "Cause", "CheckSettings",
    "Confirmation", "DetailLook", "DownloadFacts", "Effect", "ErrorKind", "ListFacts", "LookOutcome", "Transport",
    "ValueProblem", "binomial_upper_tail", "block_check", "block_sign", "canary", "cause_of", "classify_answer",
    "confirm", "confirm_missing", "duplicate_ids", "effect_of", "file_outcome", "files_failed", "fingerprint",
    "fisher_exact_upper", "fisher_significant", "html_paths", "json_paths", "known_ids_missing",
    "known_tenders_reproduce", "list_outcome", "null_rates", "overlap", "paging_complete", "printed_total",
    "removal_rate", "robots_check", "shape", "shape_problems", "skip_reason", "smallest_significant_count",
    "smallest_significant_hits", "stale", "structure", "structure_floor", "transport_check", "without_bad_values",
]
