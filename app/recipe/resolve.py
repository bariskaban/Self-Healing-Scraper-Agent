"""From one node and one scope (a page, or one item of the list) to values (Q2).

Pure functions: no network and no model call. For each field every locator is run, each hit is
parsed (`app.extract.parse`), and Q2's rule decides, as the audit corrected it:

  * two or more locators give a value and all agree: the value;
  * two or more give values that differ: null, flagged `conflict`;
  * the field has several locators and only one gives a value: the value, flagged
    `single_witness`. Whether it is kept is settled afterwards by `settle_single_witnesses`,
    because that needs the last good read: a lone survivor is least trustworthy exactly when
    the page has just changed (audit of Q2, point 1);
  * none gives a value: null. Whether that matters is for the checks (C3, C5).

A field with one locator has nobody to disagree with: its value is taken as it is, unflagged.

The raw text is kept beside every value, also when the value is null: check C2 reads it to tell
"the portal shows nothing" from "we could not read what it shows".
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

from app.extract import ParseContext, parse
from app.extract.moments import DATE_ONLY
from app.models import PlaceOfPerformance, TenderRecord
from app.recipe.locate import Doc, Found, find
from app.recipe.schema import FieldName, FieldSpec, Identity, ValueType
from app.recipe.settings import DEFAULT_RECIPE_SETTINGS, RecipeSettings

__all__ = ["FieldRead", "Flag", "IdRead", "fill_record", "merge_fields", "read_fields", "read_id", "row_hash",
           "settle_single_witnesses"]

Flag = Literal["conflict", "single_witness"]

# Value types whose locator may match several times, each match adding to one value.
_MANY = frozenset({ValueType.cpv})


@dataclass(frozen=True)
class FieldRead:
    """What the locators of one field gave in one scope."""

    name: FieldName
    value: Any | None           # the contract's value, or None
    raw: str | None             # the text as found, by the first locator that found any
    flag: Flag | None = None
    problem: str | None = None  # why the value is None although text was found
    note: str | None = None     # e.g. "date_only"
    witnesses: int = 0          # how many locators gave a value
    locators: int = 0           # how many locators the field has


def _one_locator(spec: FieldSpec, locator, scope: Doc | Found, context: ParseContext
                 ) -> tuple[Any | None, str | None, str | None, str | None]:
    """(value, raw, problem, note) of one locator."""
    hits = find(locator, scope)
    if not hits:
        return None, None, None, None
    if spec.value.type in _MANY:
        values: list[str] = []
        raws: list[str] = []
        problem = note = None
        for hit in hits:
            parsed = parse(spec.value, hit.text, context)
            if parsed.raw:
                raws.append(parsed.raw)
            for code in parsed.value or []:
                if code not in values:
                    values.append(code)
            problem, note = problem or parsed.problem, note or parsed.note
        return (values or None), ("; ".join(raws) or None), (None if values else problem), note
    parsed = parse(spec.value, hits[0].text, context)
    return parsed.value, parsed.raw or None, parsed.problem, parsed.note


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return sorted(a) == sorted(b)
    return a == b


def _agreed(found: list[tuple[Any, str | None]]) -> tuple[Any | None, str | None, bool]:
    """(value, note, conflict) of the locators that gave a value.

    A deadline one locator reads as a bare date and another reads with its time on the same
    day is not a conflict: the one with the time says more, and it is taken.
    """
    timed = [(value, note) for value, note in found if note != DATE_ONLY]
    bare = [(value, note) for value, note in found if note == DATE_ONLY]
    if timed and bare and all(isinstance(value, datetime) for value, _ in found):
        if all(value.date() == timed[0][0].date() for value, _ in bare):
            found = timed
    first, note = found[0]
    if all(_same(first, value) for value, _ in found[1:]):
        return first, note, False
    return None, None, True


def read_fields(fields: Sequence[FieldSpec], scope: Doc | Found, context: ParseContext
                ) -> dict[FieldName, FieldRead]:
    """Every field of a node in one scope. Single witnesses come back flagged, with their value."""
    out: dict[FieldName, FieldRead] = {}
    for spec in fields:
        results = [_one_locator(spec, locator, scope, context) for locator in spec.locators]
        raw = next((r for _, r, _, _ in results if r), None)
        found = [(value, note) for value, _, _, note in results if value is not None]
        count = len(spec.locators)
        if not found:
            problem = next((p for _, r, p, _ in results if r and p), None)
            out[spec.name] = FieldRead(spec.name, None, raw, problem=problem, locators=count)
            continue
        if len(found) == 1:
            value, note = found[0]
            flag: Flag | None = "single_witness" if count > 1 else None
            raw_of_value = next((r for v, r, _, _ in results if v is not None), raw)
            out[spec.name] = FieldRead(spec.name, value, raw_of_value, flag=flag, note=note, witnesses=1,
                                       locators=count)
            continue
        value, note, conflict = _agreed(found)
        if conflict:
            out[spec.name] = FieldRead(spec.name, None, raw, flag="conflict",
                                       problem="the locators give different values", witnesses=len(found),
                                       locators=count)
        else:
            out[spec.name] = FieldRead(spec.name, value, raw, note=note, witnesses=len(found), locators=count)
    return out


def merge_fields(first: Mapping[FieldName, FieldRead], second: Mapping[FieldName, FieldRead]
                 ) -> dict[FieldName, FieldRead]:
    """The fields of two pages of one tender (the list row, then its detail page) as one set.

    A value on one page and a different value on the other is a `conflict`: null. Two pages
    are the independent witnesses the audit asks for (Q2, point 2), so a value both pages show
    is no longer a single witness.
    """
    out = dict(first)
    for name, new in second.items():
        old = out.get(name)
        if old is None or (old.value is None and old.flag is None):
            out[name] = new if old is None or new.value is not None or new.raw else old
            continue
        if new.value is None:
            if new.flag == "conflict":
                out[name] = new
            continue
        if old.flag == "conflict":
            continue
        value, note, conflict = _agreed([(old.value, old.note), (new.value, new.note)])
        if conflict:
            out[name] = FieldRead(name, None, old.raw or new.raw, flag="conflict",
                                  problem="the list and the tender's page give different values",
                                  witnesses=old.witnesses + new.witnesses, locators=old.locators + new.locators)
        else:
            raw = new.raw if _same(value, new.value) and new.raw else old.raw
            out[name] = FieldRead(name, value, raw, note=note, witnesses=old.witnesses + new.witnesses,
                                  locators=old.locators + new.locators)
    return out


# == Identity ==

@dataclass(frozen=True)
class IdRead:
    """A tender's id, or why the row has none and is left out."""

    tender_id: str | None
    problem: str | None = None


def read_id(identity: Identity, fields: Mapping[FieldName, FieldRead], url: str | None,
            settings: RecipeSettings = DEFAULT_RECIPE_SETTINGS) -> IdRead:
    """The portal's own id: from the `id` field, or from the tender's address, checked against the shape.

    The recipe's two patterns run on bounded text, because Python's re has no timeout: an
    address longer than `pattern_address_limit` gives no id, and an id longer than
    `pattern_id_limit` is not one of this portal's ids.
    """
    on_page = fields.get(FieldName.id)
    page_id = str(on_page.value) if on_page is not None and on_page.value is not None else None
    if on_page is not None and on_page.flag == "conflict":
        return IdRead(None, "the id locators give different ids")
    url_id = None
    if identity.from_url and url and len(url) <= settings.pattern_address_limit:
        match = re.search(identity.from_url, url)
        if match is not None and match.groups():
            url_id = match.group(1)
    if identity.must_agree and page_id is not None and url_id is not None and page_id != url_id:
        return IdRead(None, f"the id on the page ({page_id}) and in the address ({url_id}) differ")
    tender_id = page_id if page_id is not None else url_id
    if tender_id is None:
        return IdRead(None, "no id was found")
    if len(tender_id) > settings.pattern_id_limit:
        return IdRead(None, f"the id found is {len(tender_id)} characters long, more than the "
                            f"{settings.pattern_id_limit} an id may have")
    if not re.fullmatch(identity.shape, tender_id):
        return IdRead(None, f"{tender_id!r} does not look like this portal's ids")
    return IdRead(tender_id)


# == Single witnesses, settled against the last good read ==

def _last_value(record: TenderRecord, name: FieldName) -> Any | None:
    if name is FieldName.id:
        return record.tender_id
    if name is FieldName.status:
        return "withdrawn" if record.withdrawn else None
    if name in (FieldName.postal_code, FieldName.city, FieldName.country_code):
        if record.place is None:
            return None
        return {FieldName.postal_code: record.place.postalCode, FieldName.city: record.place.city,
                FieldName.country_code: record.place.countryCode}[name]
    value = getattr(record, name.value)  # the enums are strings, so they compare with the parsed words
    return (value or None) if name is FieldName.cpv_codes else value


def settle_single_witnesses(rows: Mapping[str, Mapping[FieldName, FieldRead]],
                            last_good: Mapping[str, TenderRecord] | None,
                            settings: RecipeSettings = DEFAULT_RECIPE_SETTINGS
                            ) -> dict[str, dict[FieldName, FieldRead]]:
    """Keep or drop every value only one of several locators found (audit of Q2, point 1).

    `rows` maps tender id to its fields; `last_good` maps tender id to the record of the last
    good read, or is None when there is none (the attach), in which case every value is kept.

    A single witness on a tender we know is kept only when it equals the last good value. On a
    tender we cannot compare (a new one, or one whose last good value is null) it is kept when
    the same field's single witnesses on the tenders we can compare reproduce their last good
    values (at least `single_witness_vouch_share` of them): this read against the last good one
    is the independent witness the lone locator lacks. With nothing to compare, it is null.
    A dropped value keeps its flag and its raw text.
    """
    if last_good is None:
        return {tender_id: dict(fields) for tender_id, fields in rows.items()}
    same: dict[FieldName, int] = {}
    compared: dict[FieldName, int] = {}
    for tender_id, fields in rows.items():
        record = last_good.get(tender_id)
        if record is None:
            continue
        for name, read in fields.items():
            if read.flag != "single_witness" or read.value is None:
                continue
            before = _last_value(record, name)
            if before is None:
                continue
            compared[name] = compared.get(name, 0) + 1
            same[name] = same.get(name, 0) + (1 if _same(before, read.value) else 0)
    vouched = {name for name, n in compared.items() if same.get(name, 0) / n >= settings.single_witness_vouch_share}

    out: dict[str, dict[FieldName, FieldRead]] = {}
    for tender_id, fields in rows.items():
        record = last_good.get(tender_id)
        settled = dict(fields)
        for name, read in fields.items():
            if read.flag != "single_witness" or read.value is None:
                continue
            before = _last_value(record, name) if record is not None else None
            keep = _same(before, read.value) if before is not None else name in vouched
            if not keep:
                settled[name] = replace(read, value=None, note=None,
                                        problem="only one locator found a value, and nothing confirms it")
        out[tender_id] = settled
    return out


# == Records ==

_PLACE = (FieldName.postal_code, FieldName.city, FieldName.country_code)
_PLAIN = (FieldName.url, FieldName.title, FieldName.buyer_name, FieldName.publication_date,
          FieldName.submission_deadline, FieldName.reference_number, FieldName.description,
          FieldName.procedure_type, FieldName.contract_nature)


def fill_record(portal_id: str, tender_id: str, fields: Mapping[FieldName, FieldRead], *,
                source_urls: Iterable[str] = (), run_id: str | None = None) -> TenderRecord:
    """One tender's settled fields as a `TenderRecord`. Times of ours (first seen, changed) are the loop's.

    Of the status only `withdrawn` has a place on the record. A status the portal words as
    closed is not stored as a value: its text stays in `raw["status"]`, and the tender reads
    as open while it is listed and its deadline is ahead (`run.closed_by_the_portal` names them).
    """
    def value(name: FieldName) -> Any | None:
        read = fields.get(name)
        return read.value if read is not None else None

    place = PlaceOfPerformance(postalCode=value(FieldName.postal_code), city=value(FieldName.city),
                               countryCode=value(FieldName.country_code))
    raw = {("tender_id" if name is FieldName.id else name.value): read.raw
           for name, read in fields.items() if read.raw is not None}
    return TenderRecord(
        portal_id=portal_id, tender_id=tender_id,
        cpv_codes=value(FieldName.cpv_codes) or [],
        place=None if place.is_empty() else place,
        withdrawn=value(FieldName.status) == "withdrawn",
        source_run_id=run_id, source_urls=list(dict.fromkeys(source_urls)), raw=raw,
        **{name.value: value(name) for name in _PLAIN},
    )


def row_hash(fields: Mapping[FieldName, FieldRead], extra: str | None = None) -> str:
    """A hash of what the list shows of one tender, for `plan_incremental_read`: a changed row is re-read.

    It is made of the raw texts, so it moves when the portal changes what it prints and not when
    we change how we read it. `extra` is the portal's own "last changed" mark, when it has one.
    """
    parts = [f"{name.value}={fields[name].raw or ''}" for name in sorted(fields, key=lambda n: n.value)]
    if extra:
        parts.append(f"mark={extra}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
