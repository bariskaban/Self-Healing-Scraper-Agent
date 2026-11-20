"""C2 (Q10): does every value have the shape a value of its kind must have?

The result is per value. A value that fails is sent as null (a record whose id
fails is left out), never published wrong, and counts as lost in C3. The rule
warns; it never changes the state alone.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator, Sequence
from html.entities import html5
from typing import Literal

from app.models import CheckResult, Severity, TenderRecord

from .result import Facts, note, passed
from .words import count, field_word

SHAPE_FIELDS = ("tender_id", "url", "title", "buyer_name", "publication_date", "submission_deadline",
                "reference_number", "description")
_TEXT_FIELDS = ("tender_id", "url", "title", "buyer_name", "reference_number", "description")
_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(\s[^<>]*)?/?>|<!--")
_ENTITY = re.compile(r"&(#\d+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")

Problem = Literal["markup", "id shape", "not read", "deadline before publication"]
_PROBLEM_WORDS = {
    "markup": "with markup in it",
    "id shape": "that does not look like this portal's ids",
    "not read": "that could not be read",
    "deadline before publication": "where the deadline lies before the publication date",
}


class ValueProblem(Facts):
    """One value of one tender that must not be published."""

    tender_id: str
    field: str
    problem: Problem


def has_markup(text: str) -> bool:
    """True when a value still carries an HTML tag, comment or character reference."""
    if _TAG.search(text):
        return True
    return any(m.group(1).startswith("#") or m.group(1) + ";" in html5 for m in _ENTITY.finditer(text))


def _record_problems(record: TenderRecord, id_pattern: str | None) -> Iterator[tuple[str, Problem]]:
    if id_pattern is not None and not re.fullmatch(id_pattern, record.tender_id):
        yield "tender_id", "id shape"
    for field in SHAPE_FIELDS:
        value = getattr(record, field)
        if field in _TEXT_FIELDS and isinstance(value, str) and has_markup(value):
            yield field, "markup"
        if field != "tender_id" and value is None and (record.raw.get(field) or "").strip():
            yield field, "not read"
    published, deadline = record.publication_date, record.submission_deadline
    if published is not None and deadline is not None and deadline.date() < published:
        # Either value may be the wrong one, so neither is published.
        yield "publication_date", "deadline before publication"
        yield "submission_deadline", "deadline before publication"


def shape_problems(records: Sequence[TenderRecord], *, id_pattern: str | None = None) -> list[ValueProblem]:
    """C2, per value: every value of these records that fails its shape.

    `id_pattern` is the id shape learned at attach, as a regular expression. A value
    counts as not read when it is null while `record.raw` holds text under the same
    field name. Take the bad values out with `without_bad_values` before C3 runs, so
    that they count as lost there.
    """
    return [ValueProblem(tender_id=record.tender_id, field=field, problem=problem)
            for record in records for field, problem in _record_problems(record, id_pattern)]


def without_bad_values(record: TenderRecord, problems: Sequence[ValueProblem]) -> TenderRecord | None:
    """The record with its failed values set to null; None when its id failed and it must be left out."""
    fields = {p.field for p in problems if p.tender_id == record.tender_id}
    if "tender_id" in fields:
        return None
    return record.model_copy(update={field: None for field in fields}) if fields else record


def shape(run_id: str, records: Sequence[TenderRecord], *, id_pattern: str | None = None) -> list[CheckResult]:
    """C2 `shape.<field>`: one row per field, a warning where values of that field failed their shape."""
    problems = shape_problems(records, id_pattern=id_pattern)
    rows: list[CheckResult] = []
    for field in SHAPE_FIELDS:
        mine = [p for p in problems if p.field == field]
        tenders = sorted({p.tender_id for p in mine})
        word = field_word(field)
        seen = {"tenders": len(records), "bad": len(tenders), "examples": tenders[:5],
                "problems": dict(Counter(p.problem for p in mine))}
        if not mine:
            rows.append(passed(run_id, f"shape.{field}", f"Every {word} has the shape it should have.",
                               severity=Severity.warn, observed=seen))
            continue
        why = ", ".join(f"{n} {_PROBLEM_WORDS[problem]}" for problem, n in Counter(p.problem for p in mine).items())
        then = ("Such a tender is left out." if field == "tender_id"
                else "Such a value is sent as null, never as a wrong one.")
        rows.append(note(run_id, f"shape.{field}",
                         f"The {word} of {len(tenders):,} of {count(len(records), 'tender')} cannot be used "
                         f"({why}). {then}", observed=seen))
    return rows
