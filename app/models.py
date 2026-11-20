"""Watchtower records (Q7). Pydantic v2, Python 3.12+.

Two layers:
  * API models (PortalOut, RunOut, TenderOut, DocumentOut): the exact answers from
    the Patterno appendix. Call .to_api() / model_dump(mode="json") to serialize.
  * Internal records (Portal, Recipe, Run, CheckResult, AgentStep, PortalSnapshot,
    TenderRecord, FileRecord, TenderFile): one SQLite table each, see schema.sql.

Tender fields are mapped onto OCDS 1.1 and eForms in their descriptions.
BT numbers marked (*) are from memory: verify on docs.ted.europa.eu before relying on them.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
)

# Datetimes always serialize as "2026-12-09T10:00:00+01:00" (never "Z").
OffsetDT = Annotated[
    AwareDatetime,
    PlainSerializer(lambda v: v.isoformat(timespec="seconds"), return_type=str, when_used="json"),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# == Enums ==

class PortalState(StrEnum):
    integrating = "integrating"  # being attached, nothing delivered yet
    serving = "serving"          # delivering correctly
    healing = "healing"          # broken, repair running, last good tenders still served
    failed = "failed"            # cannot deliver, a person is needed


class RunKind(StrEnum):
    read = "read"
    repair = "repair"


class RunResult(StrEnum):
    ok = "ok"
    failed = "failed"


class RunTrigger(StrEnum):
    attach = "attach"      # first read after POST /portals (API kind is still "read")
    schedule = "schedule"  # periodic read (Q13)
    refresh = "refresh"    # POST /portals/{id}/refresh
    recheck = "recheck"    # model-free probe of a failed portal (Q14)
    heal = "heal"          # repair started because a read failed its checks


class TenderStatus(StrEnum):
    open = "open"
    closed = "closed"
    withdrawn = "withdrawn"


class ProcedureType(StrEnum):
    open = "open"
    restricted = "restricted"
    negotiated = "negotiated"
    other = "other"


class ContractNature(StrEnum):
    works = "works"
    services = "services"
    supplies = "supplies"


class Severity(StrEnum):
    info = "info"    # recorded only
    warn = "warn"    # shown on the dashboard, state unchanged
    fail = "fail"    # the read is wrong: portal goes healing
    block = "block"  # login, captcha or other block: portal goes failed


class RecipeStatus(StrEnum):
    candidate = "candidate"  # produced by learn/repair, not yet validated
    active = "active"        # the one regular reads use (exactly one per portal)
    retired = "retired"      # replaced by a newer version
    rejected = "rejected"    # failed validation, kept for the trace


class StepKind(StrEnum):
    llm = "llm"
    tool = "tool"
    decision = "decision"
    note = "note"


class DocsStatus(StrEnum):
    pending = "pending"
    complete = "complete"
    partial = "partial"
    blocked = "blocked"


class SkipReason(StrEnum):
    too_large = "too_large"          # over 250 MB, allowed to leave out
    login_required = "login_required"
    captcha = "captcha"
    http_error = "http_error"
    not_a_file = "not_a_file"        # link led to an HTML page, not a document


# eForms BT-105 codes -> our procedureType.
BT105_TO_PROCEDURE: dict[str, ProcedureType] = {
    "open": ProcedureType.open,
    "restricted": ProcedureType.restricted,
    "neg-w-call": ProcedureType.negotiated,
    "neg-wo-call": ProcedureType.negotiated,
    "comp-dial": ProcedureType.other,
    "innovation": ProcedureType.other,
    "oth-single": ProcedureType.other,
    "oth-mult": ProcedureType.other,
}

# OCDS tender.mainProcurementCategory -> our contractNature.
OCDS_CATEGORY_TO_NATURE: dict[str, ContractNature] = {
    "goods": ContractNature.supplies,
    "works": ContractNature.works,
    "services": ContractNature.services,
}


# == Helpers ==

_CPV_RE = re.compile(r"^(\d{8})(?:-\d)?$")


def normalize_cpv(code: str) -> str:
    """'45000000-7' -> '45000000'. Raises ValueError on anything else."""
    m = _CPV_RE.match(code.strip())
    if not m:
        raise ValueError(f"not a CPV code: {code!r}")
    return m.group(1)


def url_key(url: str) -> str:
    """Normalize an address so the same portal posted twice gets the same id."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, host, path, query, ""))


# == API models (exact answers from the appendix) ==

class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortalCreate(ApiModel):
    """Body of POST /portals."""
    url: str


class CreatedId(ApiModel):
    """201 answer of POST /portals."""
    id: str


class RunAccepted(ApiModel):
    """202 answer of POST /portals/{id}/refresh."""
    runId: str


class PortalOut(ApiModel):
    """One entry of GET /portals, and the answer of GET /portals/{id}."""
    id: str
    url: str
    state: PortalState
    reason: str = Field(description="In words, for the operator")
    tenderCount: int = Field(ge=0)
    lastSuccessAt: OffsetDT | None


class RunOut(ApiModel):
    """One entry of GET /portals/{id}/runs."""
    id: str
    kind: RunKind
    startedAt: OffsetDT
    finishedAt: OffsetDT | None
    result: RunResult | None = Field(description="null while the run is running")


class PlaceOfPerformance(ApiModel):
    """OCDS: items[].deliveryAddresses (extension). eForms: BT-5121 post code*, BT-5131 city*, BT-5141 country*."""
    postalCode: str | None = None
    city: str | None = None
    countryCode: str | None = Field(None, description="Two letters, e.g. DE")

    @field_validator("countryCode")
    @classmethod
    def _country(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError(f"bad country code {v!r}")
        return v

    def is_empty(self) -> bool:
        return self.postalCode is None and self.city is None and self.countryCode is None


class DocumentOut(ApiModel):
    """One file of a tender. OCDS: tender.documents[]. eForms: BT-15 documents URL* (we deliver bytes)."""
    fileName: str
    sizeBytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: str = Field(description="Our API path that returns the bytes, e.g. /files/ab12")


REQUIRED_TENDER_FIELDS = (
    "id", "url", "title", "buyerName", "publicationDate",
    "submissionDeadline", "status", "documents", "lastChangedAt",
)
OPTIONAL_TENDER_FIELDS = (
    "referenceNumber", "description", "procedureType",
    "contractNature", "cpvCodes", "placeOfPerformance",
)


class TenderOut(ApiModel):
    """One tender in GET /portals/{id}/tenders.

    Required fields are always present (null when the portal does not show them).
    Optional fields are left out when not shown. A wrong value is worse than a missing one.
    """
    id: str = Field(description="Portal's own id, stable across reads. OCDS tender.id")
    url: str | None = Field(description="Address of the tender's page")
    title: str | None = Field(description="As the portal states it. OCDS tender.title, eForms BT-21*")
    buyerName: str | None = Field(description="Public body that buys. OCDS buyer.name, eForms BT-500*")
    publicationDate: date | None = Field(description="OCDS release date / tenderPeriod.startDate, eForms BT-05*")
    submissionDeadline: OffsetDT | None = Field(description="With offset. OCDS tender.tenderPeriod.endDate, eForms BT-131")
    status: TenderStatus = Field(description="OCDS tender.status: active->open, complete/unsuccessful->closed, cancelled->withdrawn")
    documents: list[DocumentOut] = Field(default_factory=list, description="ZIPs unpacked")
    lastChangedAt: OffsetDT = Field(description="When we last saw this tender change")
    referenceNumber: str | None = Field(None, description="Buyer's file number. eForms BT-22 internal identifier*")
    description: str | None = Field(None, description="What is bought. OCDS tender.description, eForms BT-24*")
    procedureType: ProcedureType | None = Field(None, description="OCDS tender.procurementMethod(+Details), eForms BT-105, see BT105_TO_PROCEDURE")
    contractNature: ContractNature | None = Field(None, description="OCDS tender.mainProcurementCategory (goods=supplies), eForms BT-23")
    cpvCodes: list[str] | None = Field(None, description="8 digits, no check digit. OCDS classification scheme CPV, eForms BT-262 main + BT-263 additional")
    placeOfPerformance: PlaceOfPerformance | None = None

    @field_validator("cpvCodes")
    @classmethod
    def _cpv(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out: list[str] = []
        for code in v:
            c = normalize_cpv(code)
            if c not in out:
                out.append(c)
        return out or None

    def to_api(self) -> dict[str, Any]:
        d = self.model_dump(mode="json")
        for k in OPTIONAL_TENDER_FIELDS:
            v = d.get(k)
            if v is None or v == [] or (isinstance(v, dict) and all(x is None for x in v.values())):
                d.pop(k, None)
        return d


# == Internal records ==

class TokenUsage(BaseModel):
    """OpenAI semantics: cached tokens are part of input, reasoning tokens part of output."""
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


class Portal(BaseModel):
    """Table: portals. API view: PortalOut."""
    id: str
    url: str = Field(description="Address as given in POST /portals")
    url_key: str = Field(description="url_key(url); same address twice gives the same id")
    state: PortalState = PortalState.integrating
    reason: str = Field("Attaching: nothing delivered yet.", description="One sentence; becomes the API reason")
    fingerprint: str | None = Field(None, description="Detected portal software, e.g. 'cosinex' (Q11)")
    recipe_version: int | None = Field(None, description="Active recipe version, null until the first learn succeeds")
    list_url: str | None = Field(None, description="Where the tender list actually is (entry URL may be a summary page)")
    country_code: str | None = None
    timezone: str | None = Field(None, description="IANA zone used to read local deadlines, e.g. Europe/Berlin")
    last_success_at: datetime | None = None
    next_read_at: datetime | None = None
    consecutive_failures: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def to_api(self, tender_count: int) -> PortalOut:
        return PortalOut(
            id=self.id, url=self.url, state=self.state, reason=self.reason,
            tenderCount=tender_count, lastSuccessAt=self.last_success_at,
        )


class Recipe(BaseModel):
    """Table: recipes. Versioned envelope; `body` follows the Q1 format."""
    portal_id: str
    version: int
    parent_version: int | None = Field(None, description="Version this was repaired from; diff against it")
    body_format: str = Field("recipe/v1", description="Q1 format id; bump when the format changes")
    body: dict[str, Any]
    fingerprint: str | None = Field(None, description="Software this recipe is valid for, enables reuse (Q11)")
    status: RecipeStatus = RecipeStatus.candidate
    created_by_run_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    validated_at: datetime | None = None
    rationale: str | None = Field(None, description="Model's short explanation, shown on the dashboard")


class RunStats(BaseModel):
    http_requests: int = 0
    pages_fetched: int = 0
    tenders_seen: int = 0
    tenders_new: int = 0
    tenders_changed: int = 0
    tenders_unlisted: int = 0
    files_downloaded: int = 0
    files_skipped: int = 0
    bytes_downloaded: int = 0


class Run(BaseModel):
    """Table: runs. API view: RunOut. The first attach is a read."""
    id: str
    portal_id: str
    kind: RunKind
    trigger: RunTrigger
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    result: RunResult | None = None
    recipe_version: int | None = Field(None, description="Recipe used (read) or produced (repair)")
    state_before: PortalState
    state_after: PortalState | None = None
    reason_after: str | None = None
    stats: RunStats = Field(default_factory=RunStats)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model_calls: int = Field(0, description="Must stay 0 for a regular read")
    error: str | None = Field(None, description="Short error for the dashboard; details in agent_steps")

    def to_api(self) -> RunOut:
        return RunOut(id=self.id, kind=self.kind, startedAt=self.started_at,
                      finishedAt=self.finished_at, result=self.result)


class CheckResult(BaseModel):
    """Table: run_checks. One row per validator check per run (rules from Q10)."""
    run_id: str
    name: str = Field(description="Stable id, e.g. count_drop, null_rate.title, known_ids_missing, captcha")
    passed: bool
    severity: Severity = Field(description="What a failure of this check does to the portal state")
    observed: Any = None
    expected: Any = None
    message: str = Field(description="Human sentence; used as portal reason when this check decides the state")


class AgentStep(BaseModel):
    """Table: agent_steps. The 'what the system did' trail shown on the dashboard."""
    run_id: str
    seq: int
    at: datetime = Field(default_factory=utcnow)
    kind: StepKind
    name: str = Field(description="Tool name, model name or decision id")
    summary: str = Field(description="One line for the operator, e.g. 'Found JSON API /api/tenders?page=N'")
    prompt_id: str | None = Field(None, description="e.g. learn/system@3, only for kind=llm")
    args: dict[str, Any] | None = Field(None, description="Tool args, truncated")
    result: str | None = Field(None, description="Result preview, truncated")
    duration_ms: int | None = None
    usage: TokenUsage | None = Field(None, description="Only for kind=llm")
    error: str | None = None


class SnapshotPage(BaseModel):
    url: str
    final_url: str
    status: int
    content_type: str | None = None
    fetched_at: datetime = Field(default_factory=utcnow)
    via: Literal["http", "browser"]
    body_path: str = Field(description="Raw body on disk")
    view_path: str | None = Field(None, description="Compact model view on disk (Q4)")
    screenshot_path: str | None = None


class NetworkEntry(BaseModel):
    url: str
    method: str = "GET"
    status: int | None = None
    resource_type: str | None = Field(None, description="document, xhr, fetch, script, ...")
    content_type: str | None = None
    request_body_path: str | None = None
    response_body_path: str | None = None
    size_bytes: int | None = None
    looks_like_tender_list: bool = Field(False, description="Heuristic: JSON array of objects with title/date-like keys")


class PortalSnapshot(BaseModel):
    """Table: snapshots (JSON) plus files under data/snapshots/{id}/. Handed to a repair."""
    id: str
    portal_id: str
    run_id: str
    captured_at: datetime = Field(default_factory=utcnow)
    pages: list[SnapshotPage] = Field(default_factory=list)
    network: list[NetworkEntry] = Field(default_factory=list)
    last_good_tender_ids: list[str] = Field(default_factory=list, description="Repair oracle: ids the new recipe must find again")
    last_good_sample: list[dict[str, Any]] = Field(default_factory=list, description="3 to 5 last good tenders (API shape) to compare values")


class FileRecord(BaseModel):
    """Table: files. Content-addressed: one row per unique blob, shared across tenders."""
    file_id: str = Field(description="Public id in /files/{file_id}: first 16 hex chars of sha256")
    sha256: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None
    storage_path: str | None = None
    source_url: str
    parent_file_id: str | None = Field(None, description="Set when unpacked from a ZIP")
    is_archive: bool = Field(False, description="Archives are unpacked; only their members are delivered")
    skipped: SkipReason | None = None
    downloaded_at: datetime | None = None

    @property
    def deliverable(self) -> bool:
        return self.skipped is None and not self.is_archive and self.sha256 is not None


class TenderFile(BaseModel):
    """Table: tender_files. Links a tender to a file under the name the portal gives it."""
    portal_id: str
    tender_id: str
    file_id: str
    file_name: str
    position: int = 0


class TenderRecord(BaseModel):
    """Table: tenders. Internal superset of TenderOut."""
    portal_id: str
    tender_id: str = Field(description="Portal's own id, API 'id'")
    url: str | None = None
    title: str | None = None
    buyer_name: str | None = None
    publication_date: date | None = None
    submission_deadline: AwareDatetime | None = None
    reference_number: str | None = None
    description: str | None = None
    procedure_type: ProcedureType | None = None
    contract_nature: ContractNature | None = None
    cpv_codes: list[str] = Field(default_factory=list)
    place: PlaceOfPerformance | None = None
    withdrawn: bool = Field(False, description="Portal marks it cancelled")
    listed: bool = Field(True, description="Seen in the latest complete list read; false means closed")
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    last_changed_at: datetime = Field(default_factory=utcnow)
    content_hash: str = ""
    detail_fetched_at: datetime | None = None
    docs_status: DocsStatus = DocsStatus.pending
    source_run_id: str | None = None
    source_urls: list[str] = Field(default_factory=list, description="Pages and API calls this record was read from")
    raw: dict[str, str | None] = Field(default_factory=dict, description="Values as extracted before normalization")

    @field_validator("cpv_codes")
    @classmethod
    def _cpv(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for code in v:
            c = normalize_cpv(code)
            if c not in out:
                out.append(c)
        return out

    def compute_hash(self, doc_sha256s: list[str]) -> str:
        """Hash of everything an API user can see, except status and lastChangedAt."""
        content = {
            "url": self.url, "title": self.title, "buyer": self.buyer_name,
            "pub": self.publication_date.isoformat() if self.publication_date else None,
            "deadline": self.submission_deadline.isoformat() if self.submission_deadline else None,
            "ref": self.reference_number, "desc": self.description,
            "proc": self.procedure_type, "nature": self.contract_nature,
            "cpv": self.cpv_codes, "place": self.place.model_dump() if self.place else None,
            "withdrawn": self.withdrawn, "docs": sorted(doc_sha256s),
        }
        return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()

    def effective_status(self, now: datetime | None = None) -> TenderStatus:
        """Computed at answer time, so closing never waits for a read."""
        now = now or utcnow()
        if self.withdrawn:
            return TenderStatus.withdrawn
        if not self.listed:
            return TenderStatus.closed
        if self.submission_deadline is not None and self.submission_deadline <= now:
            return TenderStatus.closed
        return TenderStatus.open

    def effective_last_changed(self, now: datetime | None = None) -> datetime:
        """A deadline passing is a change: report it so ?changedSince= picks it up."""
        now = now or utcnow()
        if (not self.withdrawn and self.listed and self.submission_deadline is not None
                and self.submission_deadline <= now and self.submission_deadline > self.last_changed_at):
            return self.submission_deadline
        return self.last_changed_at

    def to_api(self, files: list[tuple[TenderFile, FileRecord]], now: datetime | None = None) -> dict[str, Any]:
        docs = [
            DocumentOut(fileName=link.file_name, sizeBytes=f.size_bytes or 0,
                        sha256=f.sha256, path=f"/files/{f.file_id}")
            for link, f in sorted(files, key=lambda x: x[0].position)
            if f.deliverable
        ]
        place = self.place if self.place and not self.place.is_empty() else None
        return TenderOut(
            id=self.tender_id, url=self.url, title=self.title, buyerName=self.buyer_name,
            publicationDate=self.publication_date, submissionDeadline=self.submission_deadline,
            status=self.effective_status(now), documents=docs,
            lastChangedAt=self.effective_last_changed(now),
            referenceNumber=self.reference_number, description=self.description,
            procedureType=self.procedure_type, contractNature=self.contract_nature,
            cpvCodes=self.cpv_codes or None, placeOfPerformance=place,
        ).to_api()
