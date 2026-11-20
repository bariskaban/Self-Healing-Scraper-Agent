"""The answers of the API as the track description's appendix defines them.

Written from the brief, not from `app/models.py`, so that a drift in our own models is caught.
Each function raises AssertionError with the field that is wrong.
"""
from __future__ import annotations

import re

OFFSET_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CPV = re.compile(r"^\d{8}$")

STATES = {"integrating", "serving", "healing", "failed"}
TENDER_REQUIRED = ("id", "url", "title", "buyerName", "publicationDate", "submissionDeadline",
                   "status", "documents", "lastChangedAt")
TENDER_OPTIONAL = ("referenceNumber", "description", "procedureType", "contractNature", "cpvCodes",
                   "placeOfPerformance")


def is_offset_time(value: object) -> bool:
    """A date and time with offset, such as 2026-12-09T10:00:00+01:00 (never "Z", never without offset)."""
    return isinstance(value, str) and bool(OFFSET_TIME.match(value))


def _text_or_null(obj: dict, key: str) -> None:
    assert obj[key] is None or (isinstance(obj[key], str) and obj[key].strip()), f"{key}: {obj[key]!r}"


def check_portal(portal: object) -> None:
    """One entry of GET /portals."""
    assert isinstance(portal, dict), f"a portal is an object, got {type(portal).__name__}"
    for key in ("id", "url", "state", "reason", "tenderCount", "lastSuccessAt"):
        assert key in portal, f"portal lacks {key}"
    assert isinstance(portal["id"], str) and portal["id"], "id"
    assert isinstance(portal["url"], str) and portal["url"], "url"
    assert portal["state"] in STATES, f"state: {portal['state']!r}"
    assert isinstance(portal["reason"], str) and portal["reason"].strip(), "reason must be words"
    assert isinstance(portal["tenderCount"], int) and not isinstance(portal["tenderCount"], bool), "tenderCount"
    assert portal["tenderCount"] >= 0, "tenderCount"
    assert portal["lastSuccessAt"] is None or is_offset_time(portal["lastSuccessAt"]), \
        f"lastSuccessAt: {portal['lastSuccessAt']!r}"


def check_run(run: object) -> None:
    """One entry of GET /portals/{id}/runs."""
    assert isinstance(run, dict), "a run is an object"
    for key in ("id", "kind", "startedAt", "finishedAt", "result"):
        assert key in run, f"run lacks {key}"
    assert isinstance(run["id"], str) and run["id"], "id"
    assert run["kind"] in ("read", "repair"), f"kind: {run['kind']!r}"
    assert is_offset_time(run["startedAt"]), f"startedAt: {run['startedAt']!r}"
    assert run["finishedAt"] is None or is_offset_time(run["finishedAt"]), f"finishedAt: {run['finishedAt']!r}"
    assert run["result"] in ("ok", "failed", None), f"result: {run['result']!r}"
    if run["finishedAt"] is None:
        assert run["result"] is None, "result is null while the run is running"
    else:
        assert run["result"] is not None, "a finished run has a result"


def check_document(document: object) -> None:
    """One file of a tender. `sha256` and `path` are null together while the bytes load (our addition)."""
    assert isinstance(document, dict), "a document is an object"
    for key in ("fileName", "sizeBytes", "sha256", "path"):
        assert key in document, f"document lacks {key}"
    assert isinstance(document["fileName"], str) and document["fileName"], "fileName"
    size = document["sizeBytes"]
    assert size is None or (isinstance(size, int) and not isinstance(size, bool) and size >= 0), "sizeBytes"
    if document["sha256"] is None:
        assert document["path"] is None, "a document without a hash has no path yet"
        return
    assert SHA256.match(document["sha256"]), f"sha256: {document['sha256']!r}"
    assert isinstance(document["path"], str) and document["path"].startswith("/files/"), "path"
    assert isinstance(size, int), "a fetched document has a size"


def check_tender(tender: object) -> None:
    """One entry of GET /portals/{id}/tenders."""
    assert isinstance(tender, dict), "a tender is an object"
    for key in TENDER_REQUIRED:
        assert key in tender, f"tender lacks {key}: required fields are sent, as null when not shown"
    unknown = set(tender) - set(TENDER_REQUIRED) - set(TENDER_OPTIONAL)
    assert not unknown, f"fields the brief does not name: {sorted(unknown)}"
    assert isinstance(tender["id"], str) and tender["id"].strip(), "id"
    for key in ("url", "title", "buyerName"):
        _text_or_null(tender, key)
    assert tender["publicationDate"] is None or (
        isinstance(tender["publicationDate"], str) and DATE.match(tender["publicationDate"])), "publicationDate"
    assert tender["submissionDeadline"] is None or is_offset_time(tender["submissionDeadline"]), \
        f"submissionDeadline: {tender['submissionDeadline']!r}"
    assert tender["status"] in ("open", "closed", "withdrawn"), f"status: {tender['status']!r}"
    assert tender["documents"] is None or isinstance(tender["documents"], list), "documents"
    for document in tender["documents"] or []:
        check_document(document)
    assert is_offset_time(tender["lastChangedAt"]), f"lastChangedAt: {tender['lastChangedAt']!r}"
    # Optional fields are left out when not shown, never sent as null or empty.
    for key in TENDER_OPTIONAL:
        if key in tender:
            assert tender[key] not in (None, "", [], {}), f"{key} is left out when not shown, not sent empty"
    for key in ("referenceNumber", "description"):
        assert key not in tender or isinstance(tender[key], str), key
    assert tender.get("procedureType", "open") in ("open", "restricted", "negotiated", "other"), "procedureType"
    assert tender.get("contractNature", "works") in ("works", "services", "supplies"), "contractNature"
    if "cpvCodes" in tender:
        codes = tender["cpvCodes"]
        assert isinstance(codes, list) and all(isinstance(c, str) and CPV.match(c) for c in codes), \
            f"cpvCodes are eight digits without the check digit: {codes!r}"
    if "placeOfPerformance" in tender:
        place = tender["placeOfPerformance"]
        assert isinstance(place, dict) and set(place) <= {"postalCode", "city", "countryCode"}, "placeOfPerformance"
        code = place.get("countryCode")
        assert code is None or re.fullmatch(r"[A-Z]{2}", code), f"countryCode: {code!r}"
