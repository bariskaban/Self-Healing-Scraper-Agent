"""`parse`: the text a locator found, made into a value of the contract, or into nothing.

Null over guess (CONVENTIONS.md rule 3): every branch below returns None with a short problem
whenever it is not sure. Pure functions: no network, no files, no model.

`spec.pattern`, when set, is applied first for every type: the value is read from its first
group (or the whole match when it has no group), and no match means None. Python's `re` has no
timeout, so the pattern only sees the first `ExtractSettings.pattern_text_limit` characters of
the text (20,000 by default): longer text is cut before the search, and what lies beyond the cut
cannot match. `Parsed.raw` still holds the whole text.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from app.extract import moments
from app.extract.core import Parsed, ParseContext, clean
from app.extract.words import country_code, match_words, valid_country
from app.models import ContractNature, ProcedureType, TenderStatus
from app.recipe.schema import ValueSpec, ValueType

_ENUMS: dict[ValueType, frozenset[str]] = {
    ValueType.status: frozenset(s.value for s in TenderStatus),
    ValueType.procedure: frozenset(p.value for p in ProcedureType),
    ValueType.nature: frozenset(n.value for n in ContractNature),
}

# An 8-digit code, an optional check digit after a hyphen, not part of a longer number.
_CPV = re.compile(r"(?<![\d.,])(\d{8})(?:\s?-\s?\d)?(?![\d])")
# The 45 divisions of CPV 2008: an 8-digit number outside them is not a CPV code (a date, a phone).
_CPV_DIVISIONS = frozenset(
    "03 09 14 15 16 18 19 22 24 30 31 32 33 34 35 37 38 39 41 42 43 44 45 48 50 51 55 60 63 64 65 "
    "66 70 71 72 73 75 76 77 79 80 85 90 92 98".split())
_POSTAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 -]{1,8}[A-Za-z0-9]")
_NOT_LINKS = ("javascript:", "mailto:", "tel:", "data:", "about:", "#")


def parse(spec: ValueSpec, raw: str | None, context: ParseContext) -> Parsed:
    text = clean(raw)
    if not text:
        return Parsed(value=None, raw="", problem=None)
    source = text
    if spec.pattern:
        try:
            match = re.search(spec.pattern, text[:context.settings.pattern_text_limit])
        except re.error:
            return Parsed(None, text, "pattern is not a valid regular expression")
        if match is None:
            return Parsed(None, text, "pattern did not match")
        source = clean(match.group(1) if match.re.groups else match.group(0))
        if not source:
            return Parsed(None, text, "pattern matched nothing")
    value, problem, note = _READERS[spec.type](spec, source, context)
    if value is None:
        return Parsed(None, text, problem or "not readable", note)
    return Parsed(value, text, None, note)


Result = tuple[object | None, str | None, str | None]


def _text(spec: ValueSpec, text: str, context: ParseContext) -> Result:
    return text, None, None


def _url(spec: ValueSpec, text: str, context: ParseContext) -> Result:
    if text.casefold().startswith(_NOT_LINKS):
        return None, "not a link", None
    text = text.replace(" ", "%20")
    parts = urlsplit(text)
    if not parts.scheme:
        if not context.page_url:
            return None, "relative link without the page's address", None
        page = urlsplit(context.page_url)
        if page.scheme.lower() not in ("http", "https") or not page.netloc:
            return None, "page address is not http(s)", None
        text = urljoin(context.page_url, text)
        parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None, "not an http(s) link", None
    return text, None, None


def _date(spec: ValueSpec, text: str, context: ParseContext) -> Result:
    value, problem = moments.read_date(text, spec.formats, context)
    return value, problem, None


def _datetime(spec: ValueSpec, text: str, context: ParseContext) -> Result:
    return moments.read_datetime(text, spec.formats, context)


def _cpv(spec: ValueSpec, text: str, context: ParseContext) -> Result:
    codes: list[str] = []
    skipped = False
    for match in _CPV.finditer(text):
        code = match.group(1)
        if code[:2] not in _CPV_DIVISIONS:
            skipped = True
        elif code not in codes:
            codes.append(code)
    note = "skipped 8-digit numbers outside the CPV divisions" if skipped else None
    if not codes:
        return None, "no CPV code", note
    return codes, None, note


def _mapped(spec: ValueSpec, text: str, context: ParseContext) -> Result:
    if not spec.words:
        return None, "no word map", None
    value, problem = match_words(((p.name, p.value) for p in spec.words), text)
    if value is None:
        return None, problem, None
    value = value.lower()
    if value not in _ENUMS[spec.type]:
        return None, "word map gives a value outside the contract", None
    return value, None, None


def _country(spec: ValueSpec, text: str, context: ParseContext) -> Result:
    if spec.words:
        value, problem = match_words(((p.name, p.value) for p in spec.words), text)
        if problem == "ambiguous":
            return None, problem, None
        if value is not None:
            code = valid_country(value)
            return (code, None, None) if code else (None, "word map gives no ISO country code", None)
    code = country_code(text)
    return (code, None, None) if code else (None, "not a country", None)


def _postal_code(spec: ValueSpec, text: str, context: ParseContext) -> Result:
    if _POSTAL.fullmatch(text) and any(c.isdigit() for c in text):
        return text, None, None
    return None, "not a postal code", None


_READERS = {
    ValueType.text: _text,
    ValueType.id: _text,
    ValueType.url: _url,
    ValueType.date: _date,
    ValueType.datetime: _datetime,
    ValueType.cpv: _cpv,
    ValueType.status: _mapped,
    ValueType.procedure: _mapped,
    ValueType.nature: _mapped,
    ValueType.country: _country,
    ValueType.postal_code: _postal_code,
}
