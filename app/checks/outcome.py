"""Step 2 of a read (Q10): did what we asked for arrive?

Only the outcome counts. A list arrived when a row was found or the portal itself
says the list is empty; a file arrived when it is a file of its kind. Block signs
are consulted only after the outcome is found missing.
"""
from __future__ import annotations

from collections.abc import Collection

from pydantic import Field

from app.models import CheckResult, Severity, SkipReason

from .result import Cause, Facts, cause_of, note, observed_of, passed, suspect
from .transport import Answer, Transport, answer_words, block_sentence, block_sign, classify_answer
from .words import count

# The first bytes each kind of file may start with. A file named .doc, .xls or .ppt is in
# practice also an RTF text or a new-format (ZIP) file saved under the old name: both are real
# documents, so they are accepted. A web page under such a name is caught before this test.
_MAGIC = {
    "PDF": (b"%PDF",),
    "ZIP": (b"PK\x03\x04",),
    "old Office": (b"\xd0\xcf\x11\xe0", b"PK\x03\x04", b"{\\rtf"),
}
_KIND_BY_EXTENSION = {
    "pdf": "PDF",
    "zip": "ZIP", "docx": "ZIP", "xlsx": "ZIP", "pptx": "ZIP",
    "doc": "old Office", "xls": "old Office", "ppt": "old Office",
}
_HTML_STARTS = (b"<!doctype html", b"<html")


class ListFacts(Facts):
    """What a read of the tender list observed, for the outcome test."""

    rows: int = Field(ge=0, description="Rows the recipe's row locator matched")
    answer: Answer = Answer(status=200)
    printed_total: int | None = Field(None, ge=0, description="The total the portal prints, when it prints one")
    empty_marker: bool = Field(False, description="The empty-state marker learned at attach is on the page")
    api_empty: bool = Field(False, description="A JSON API answered with its usual keys and an empty list")


class DownloadFacts(Facts):
    """What a download observed, for the outcome test. Field names follow `FileFacts` of `app/docs`."""

    file_name: str = Field(description="The file's name as the portal gives it")
    answer: Answer = Answer(status=200, page_load=False)
    first_bytes: bytes = b""
    size_bytes: int = Field(0, ge=0, description="Bytes received")
    announced_size: int | None = Field(None, ge=0, description="Exact size in bytes, when one was announced; "
                                                               "leave a rounded figure ('1.2 MB') out")
    content_type: str | None = Field(None, description="The Content-Type header")


def _missing(answer: Answer, subject: str, plain: str,
             usual_signs: Collection[str]) -> tuple[Cause, str, dict[str, object]]:
    """Why an outcome is missing: (cause, sentence, what was seen). Same classification for list and file."""
    if classify_answer(answer) is not Transport.answered:
        return Cause.outage, f"{subject[0].upper()}{subject[1:]} did not arrive ({answer_words(answer)}).", {}
    sign = block_sign(answer, usual_signs)
    if sign is not None:
        return Cause.block, block_sentence(sign, subject), {"block_sign": sign.name, "sign": sign.what}
    if answer.maintenance:
        return Cause.outage, f"The portal shows a maintenance page in place of {subject}.", {"maintenance": True}
    return Cause.breakage, plain, {}


def list_outcome(run_id: str, facts: ListFacts, *, usual_signs: Collection[str] = ()) -> CheckResult:
    """O1 `list_outcome`: the list arrived, is provably empty, or is missing (suspect, by cause)."""
    seen: dict[str, object] = {"rows": facts.rows, "status": facts.answer.status, "via": facts.answer.via}
    if facts.rows > 0:
        return passed(run_id, "list_outcome", f"The tender list arrived: {count(facts.rows, 'row')}.", observed=seen)
    proof = None
    if facts.empty_marker:
        proof, words = "notice", "its own 'no results' notice is shown"
    elif facts.printed_total == 0:
        proof, words = "total", "it prints a total of 0"
    elif facts.api_empty:
        proof, words = "api", "its API answers with its usual keys and an empty list"
    if proof is not None:
        return passed(run_id, "list_outcome", f"The portal lists no tenders: {words}.",
                      observed={**seen, "empty": proof})
    cause, message, extra = _missing(
        facts.answer, "the tender list",
        "The tender list did not arrive: no row was found, and the portal does not say the list is empty.",
        usual_signs)
    # A block is confirmed by one more fetch, through the browser if plain HTTP was used.
    second_look = "browser" if cause is Cause.block and facts.answer.via == "http" else "reread"
    return suspect(run_id, "list_outcome", message, if_confirmed=cause, second_look=second_look,
                   observed={**seen, **extra})


def _file_kind(name: str) -> str | None:
    return _KIND_BY_EXTENSION.get(name.rsplit(".", 1)[-1].lower()) if "." in name else None


def _file_problem(facts: DownloadFacts) -> tuple[str, str] | None:
    """(problem, sentence) for a download that is not the file we asked for; None when it is."""
    name, status = facts.file_name, facts.answer.status
    if status is None or not 200 <= status < 300:
        return "status", f"{name} did not download ({answer_words(facts.answer)})."
    wants_html = name.lower().endswith((".html", ".htm"))
    content_type = (facts.content_type or "").lower()
    looks_html = (content_type.startswith(("text/html", "application/xhtml"))
                  or facts.first_bytes.lstrip().lower().startswith(_HTML_STARTS))
    if looks_html and not wants_html:
        return "html", f"A web page came in place of the file {name}."
    kind = _file_kind(name)
    if kind is not None and not facts.first_bytes.startswith(_MAGIC[kind]):
        return "first_bytes", f"{name} does not start like a {kind} file."
    if facts.size_bytes == 0:
        return "empty", f"{name} arrived empty."
    if facts.announced_size is not None and facts.size_bytes != facts.announced_size:
        return "size", (f"{name} arrived with {count(facts.size_bytes, 'byte')}; "
                        f"the portal announced {facts.announced_size:,}.")
    return None


def file_outcome(run_id: str, facts: DownloadFacts, *, usual_signs: Collection[str] = ()) -> CheckResult:
    """O2 `file_outcome`: one download is a file of its kind, or a warning that carries its cause.

    A file that fails is never stored as a document. One file is not the portal:
    `files_failed` (D1) decides what the failures of a read mean together.
    """
    name = facts.file_name
    seen: dict[str, object] = {"file": name, "status": facts.answer.status, "size": facts.size_bytes}
    found = _file_problem(facts)
    if found is None:
        return passed(run_id, "file_outcome", f"{name} arrived ({count(facts.size_bytes, 'byte')}).",
                      severity=Severity.warn, observed=seen)
    problem, plain = found
    cause, message, extra = _missing(facts.answer, f"the file {name}", plain, usual_signs)
    return note(run_id, "file_outcome", message, cause=cause, observed={**seen, **extra, "problem": problem})


def skip_reason(result: CheckResult) -> SkipReason | None:
    """The `SkipReason` to store on the file's record for a `file_outcome` result; None when the file arrived."""
    if result.passed:
        return None
    seen = observed_of(result)
    if seen.get("block_sign") == "login":
        return SkipReason.login_required
    if seen.get("block_sign") == "captcha":
        return SkipReason.captcha
    if cause_of(result) is Cause.breakage and seen.get("problem") in ("html", "first_bytes", "empty"):
        return SkipReason.not_a_file
    return SkipReason.http_error
