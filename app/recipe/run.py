"""The executor: the steps that read a portal by its recipe (Q1). No model call, ever.

    read_list(recipe, source, portal)          the tender list, page by page, with the facts the checks need
    read_detail(recipe, source, portal, item)  one tender's own pages: its remaining fields and its documents
    known_item(recipe, portal, record)         a tender of an earlier read as an item, to look at its page again
    settle(...)                                Q2's rule for lone witnesses, then `TenderRecord`s
    dry_run(recipe, pages, url=...)            all of the above on cached pages, for the learning agent

Every request goes through the `Fetch` the caller hands in (`app/fetch`). That interface blocks,
so these are plain functions: the read loop runs them in a worker thread.

Not supported yet, each reported as a problem rather than guessed at: browser steps and
`load_more` paging (the fetch interface has no way to click), `platform_ref` nodes, and a
document that is fetched by a POST (`Documents.request`).
"""
from __future__ import annotations

import json as jsonlib
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.checks import Answer, LookOutcome, Transport, classify_answer, html_paths, json_paths
from app.docs import Announced, Download
from app.extract import ParseContext
from app.fetch.interface import BrowsedPage, Fetch, Fetched, RobotsForbidden, RobotsUnavailable
from app.models import Portal, TenderRecord, utcnow
from app.recipe.locate import Doc, Found, PageError, find, find_items, first_text, parse_page
from app.recipe.resolve import (
    FieldRead, fill_record, merge_fields, read_fields, read_id, row_hash, settle_single_witnesses,
)
from app.recipe.schema import (
    Action, AuthoredRecipe, BodyKind, Edge, FieldName, Locator, LocatorKind, Node, NodeKind, NodeRole, PagingKind,
    Request, Via,
)
from app.recipe.settings import DEFAULT_RECIPE_SETTINGS, RecipeSettings

__all__ = [
    "CachedPage", "DetailRead", "DryRun", "Exchange", "Item", "ListRead", "NotCached", "PageCache", "PageSeen",
    "Step", "closed_by_the_portal", "dry_run", "judge_look", "known_item", "read_detail", "read_list", "settle",
]

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_DIGITS = re.compile(r"\d+")
_EXACT_BYTES = re.compile(r"^\s*(\d[\d.,\s' ]*)\s*(bytes?|octets?|b)?\s*$", re.IGNORECASE)


# == What the steps hand back ==

@dataclass(frozen=True)
class Step:
    """One request, ready to send."""

    node: str
    method: str
    url: str
    params: tuple[tuple[str, str], ...] = ()
    data: tuple[tuple[str, str], ...] | None = None
    json: Any = None
    headers: tuple[tuple[str, str], ...] = ()
    via: str = "http"

    @property
    def address(self) -> str:
        """The full address, query included."""
        return str(httpx.URL(self.url, params=dict(self.params))) if self.params else self.url


@dataclass(frozen=True)
class Exchange:
    """The facts of one request, for the transport checks (Q10, step 1)."""

    node: str
    url: str
    answer: Answer
    tries: int = 1
    at_slowest_rate: bool = False
    robots_forbidden: bool = False

    @property
    def answered(self) -> bool:
        return not self.robots_forbidden and classify_answer(self.answer) is Transport.answered

    @property
    def ok(self) -> bool:
        status = self.answer.status
        return self.answered and status is not None and 200 <= status < 300


@dataclass(frozen=True)
class PageSeen:
    """One page as it arrived, for whoever wants to keep it (a snapshot for a repair)."""

    node: str
    url: str
    final_url: str
    status: int | None
    content_type: str | None
    body: bytes
    via: str


Tap = Callable[[PageSeen], None]


@dataclass(frozen=True)
class Item:
    """One tender as the list shows it."""

    tender_id: str
    fields: dict[FieldName, FieldRead]
    row_hash: str
    page_url: str
    steps: tuple[Step, ...] = ()  # one per `per_item` edge that leaves the list
    address: str | None = None    # the tender's own page, when the list links to it

    @property
    def deadline(self) -> datetime | None:
        read = self.fields.get(FieldName.submission_deadline)
        return read.value if read is not None and isinstance(read.value, datetime) else None


@dataclass
class ListRead:
    """What one read of the list observed."""

    items: list[Item] = field(default_factory=list)
    rows: int = 0                        # rows the item locator matched, on all pages
    dropped: list[str] = field(default_factory=list)  # rows left out, each with the reason
    duplicate_ids: list[str] = field(default_factory=list)
    printed_total: int | None = None
    empty_marker: bool = False
    api_empty: bool = False
    pages: int = 0
    reached_end: bool = False
    first_page_only: bool = False
    capped: bool = False                 # the list was cut at `max_tenders_per_portal`
    exchanges: list[Exchange] = field(default_factory=list)
    structure_paths: frozenset[str] = frozenset()  # of the first list page
    seconds: float = 0.0
    problems: list[str] = field(default_factory=list)
    robots_forbidden: bool = False

    @property
    def partial(self) -> bool:
        """Only a part of the list was read, so absence from it says nothing about a tender.

        A cut list (`capped`) is still the full read of what was asked for: the portal may be served
        on it. A first page alone is not (the reader keeps the portal `integrating` after one)."""
        return self.first_page_only or self.capped

    @property
    def ids(self) -> list[str]:
        """Every id in list order, repeats included: what check C1 `duplicate_ids` takes."""
        return [item.tender_id for item in self.items] + self.duplicate_ids

    @property
    def list_answer(self) -> Answer:
        """The answer of the last request of the list, for `ListFacts.answer`."""
        return self.exchanges[-1].answer if self.exchanges else Answer(status=None)


@dataclass
class DetailRead:
    """What one tender's own pages gave."""

    tender_id: str
    fields: dict[FieldName, FieldRead]            # the list row merged with every page read
    page_fields: dict[FieldName, FieldRead] = field(default_factory=dict)  # the pages alone, for the canary
    documents: list[Announced] | None = None      # None: not known (no page that lists them arrived)
    exchanges: list[Exchange] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    structure_paths: dict[str, frozenset[str]] = field(default_factory=dict)  # by node id
    problems: list[str] = field(default_factory=list)
    complete: bool = True                         # every page of this tender arrived and was read

    @property
    def gone(self) -> bool:
        """The tender's page no longer exists (404 or 410)."""
        return any(e.answer.status in (404, 410) for e in self.exchanges)


# == Cached pages: a page source that makes no request ==

class NotCached(LookupError):
    """The recipe asks for a page that is not among the cached ones."""

    def __init__(self, method: str, url: str) -> None:
        super().__init__(f"{method} {url} is not among the cached pages")
        self.method, self.url = method, url


@dataclass(frozen=True)
class CachedPage:
    """A page fetched earlier, by the agent's tools or written in a test."""

    url: str
    body: bytes | str
    status: int = 200
    content_type: str | None = "text/html; charset=utf-8"
    method: str = "GET"
    final_url: str | None = None


def _address_key(method: str, url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return method.upper(), urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", query, ""))


class PageCache:
    """`Fetch` on pages held in memory. A page that is not there raises `NotCached`; nothing is requested.

    A page is found by its method and address; the order of query parameters does not matter.
    A POST is found by its address alone, so cache one answer per form address.
    """

    def __init__(self, pages: Iterable[CachedPage] | Mapping[str, CachedPage | bytes | str]) -> None:
        self._pages: dict[tuple[str, str], CachedPage] = {}
        if isinstance(pages, Mapping):
            pages = [page if isinstance(page, CachedPage) else CachedPage(url=url, body=page)
                     for url, page in pages.items()]
        for page in pages:
            self._pages[_address_key(page.method, page.url)] = page
        self.asked: list[tuple[str, str]] = []

    def _page(self, method: str, url: str) -> CachedPage:
        self.asked.append((method.upper(), url))
        page = self._pages.get(_address_key(method, url))
        if page is None:
            raise NotCached(method.upper(), url)
        return page

    def fetch(self, portal_id: str, url: str, *, method: str = "GET", params: dict[str, Any] | None = None,
              data: dict[str, Any] | None = None, json: Any = None, headers: dict[str, str] | None = None,
              page_load: bool = True) -> Fetched:
        address = str(httpx.URL(url, params=params)) if params else url
        page = self._page(method, address)
        body = page.body.encode("utf-8") if isinstance(page.body, str) else page.body
        head = httpx.Headers({"content-type": page.content_type} if page.content_type else {})
        return Fetched(url=address, final_url=page.final_url or address, status=page.status, headers=head, body=body,
                       answer=Answer(status=page.status, page_load=page_load))

    def browse(self, portal_id: str, url: str) -> BrowsedPage:
        page = self._page("GET", url)
        html = page.body.decode("utf-8", errors="replace") if isinstance(page.body, bytes) else page.body
        return BrowsedPage(url=url, final_url=page.final_url or url, status=page.status, html=html,
                           answer=Answer(status=page.status, via="browser"))

    def download(self, portal_id: str, url: str, *, headers: dict[str, str] | None = None
                 ) -> AbstractContextManager[Download]:
        raise NotCached("GET", url)

    def robots_forbids_every_path(self, portal_id: str, url: str) -> bool:
        return False

    def limit(self, portal_id: str, requests_per_second: float) -> None:
        return None

    def forget(self, portal_id: str) -> None:
        return None


# == Requests ==

@dataclass(frozen=True)
class _Target:
    """The portal as the executor needs it."""

    portal_id: str
    url: str
    zone: ZoneInfo | None
    language: str | None
    pattern_text_limit: int = DEFAULT_RECIPE_SETTINGS.pattern_text_limit  # for the pages' regex locators

    def context(self, page_url: str | None, settings: RecipeSettings) -> ParseContext:
        return ParseContext(zone=self.zone, page_url=page_url, language=self.language)


def _target(recipe: AuthoredRecipe, portal: Portal,
            settings: RecipeSettings = DEFAULT_RECIPE_SETTINGS) -> _Target:
    zone = None
    if portal.timezone:
        try:
            zone = ZoneInfo(portal.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            zone = None
    return _Target(portal.id, portal.list_url or portal.url, zone, recipe.host.language,
                   settings.pattern_text_limit)


def _fill(template: str, values: Mapping[str, str], *, in_path: bool = False) -> str:
    def put(match: re.Match[str]) -> str:
        value = values.get(match.group(1), "")
        return quote(value, safe="") if in_path else value
    return _PLACEHOLDER.sub(put, template)


def _plan(request: Request, node: str, base: str, values: Mapping[str, str]) -> Step:
    """A request template with its placeholders filled. A parameter whose value comes out empty is left out."""
    url = urljoin(base, _fill(request.url, values, in_path=True)) if request.url.strip() else base
    params = tuple((p.name, v) for p in request.params if (v := _fill(p.value, values)) != "")
    headers = tuple((p.name, _fill(p.value, values)) for p in request.headers)
    data, body = None, None
    if request.method == "POST":
        if request.body_kind is BodyKind.form:
            data = tuple((p.name, _fill(p.value, values)) for p in request.body)
        elif request.body_kind is BodyKind.json:
            if request.body_json:
                try:
                    body = jsonlib.loads(_fill(request.body_json, values))
                except ValueError:
                    body = None
            else:
                body = {p.name: _fill(p.value, values) for p in request.body}
    return Step(node=node, method=request.method, url=url, params=params, data=data, json=body, headers=headers,
                via=request.via.value)


def _with_param(step: Step, name: str, value: str) -> Step:
    """The step with one parameter set: in the body of a POST that has one, in the query otherwise."""
    if step.method == "POST" and step.data is not None:
        return replace(step, data=tuple((k, v) for k, v in step.data if k != name) + ((name, value),))
    if step.method == "POST" and isinstance(step.json, dict):
        return replace(step, json={**step.json, name: value})
    parts = urlsplit(step.url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != name]
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
    return replace(step, url=url, params=tuple((k, v) for k, v in step.params if k != name) + ((name, value),))


def _form_step(form: Found, page_url: str, node: str, extra: Request | None, values: Mapping[str, str]) -> Step | None:
    """A form found on a page as a request: its own fields, hidden ones included, then the recipe's on top."""
    element = form.node
    if not hasattr(element, "iter"):
        return None
    if getattr(element, "tag", None) != "form":
        forms = [el for el in element.iter("form")]
        if not forms:
            return None
        element = forms[0]
    fields: dict[str, str] = {}
    for control in element.iter("input", "select", "textarea"):
        name = control.get("name")
        if not name or control.get("disabled") is not None:
            continue
        kind = (control.get("type") or "").lower()
        if control.tag == "input":
            if kind in ("submit", "button", "image", "reset", "file"):
                continue
            if kind in ("checkbox", "radio") and control.get("checked") is None:
                continue
            fields[name] = control.get("value") or ""
        elif control.tag == "select":
            options = control.findall(".//option")
            chosen = next((o for o in options if o.get("selected") is not None), options[0] if options else None)
            if chosen is not None:
                fields[name] = chosen.get("value") if chosen.get("value") is not None else (chosen.text or "").strip()
        else:
            fields[name] = control.text or ""
    if extra is not None:
        for pair in [*extra.body, *extra.params]:
            fields[pair.name] = _fill(pair.value, values)
    method = (element.get("method") or "GET").upper()
    url = urljoin(page_url, element.get("action") or "")
    via = extra.via.value if extra is not None else "http"
    if method == "POST":
        return Step(node=node, method="POST", url=url, data=tuple(fields.items()), via=via)
    parts = urlsplit(url)
    return Step(node=node, method="GET", url=urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
                params=tuple(fields.items()), via=via)


@dataclass
class _Got:
    exchange: Exchange | None
    doc: Doc | None
    text: str = ""
    problem: str | None = None
    missing: str | None = None  # the address of a page that is not cached (dry run)


def _send(source: Fetch, target: _Target, step: Step, node: Node, tap: Tap | None) -> _Got:
    """Send one step and parse what came. Never raises for what a portal does."""
    via_browser = step.via == "browser" or node.kind is NodeKind.browser
    address = step.address
    try:
        if via_browser and step.method == "GET":
            page = source.browse(target.portal_id, address)
            exchange = Exchange(node.id, address, page.answer, page.tries, page.at_slowest_rate)
            status, final_url, body, content_type = page.status, page.final_url, page.html.encode("utf-8"), "text/html"
        else:
            fetched = source.fetch(
                target.portal_id, step.url, method=step.method, params=dict(step.params) or None,
                data=dict(step.data) if step.data is not None else None, json=step.json,
                headers=dict(step.headers) or None, page_load=node.kind is not NodeKind.json)
            exchange = Exchange(node.id, address, fetched.answer, fetched.tries, fetched.at_slowest_rate)
            status, final_url, body, content_type = (fetched.status, fetched.final_url, fetched.body,
                                                     fetched.headers.get("content-type"))
    except NotCached as miss:
        return _Got(None, None, problem=str(miss), missing=f"{miss.method} {miss.url}")
    except RobotsForbidden:
        return _Got(Exchange(node.id, address, Answer(status=None), robots_forbidden=True), None,
                    problem=f"robots.txt disallows {address}")
    except RobotsUnavailable as error:
        seen = error.fetched
        return _Got(Exchange(node.id, address, seen.answer, seen.tries, seen.at_slowest_rate), None,
                    problem=f"robots.txt could not be read, so {address} was not fetched")
    except NotImplementedError as error:
        return _Got(None, None, problem=f"{address}: {error}")
    if tap is not None:
        tap(PageSeen(node.id, address, final_url, status, content_type, body, "browser" if via_browser else "http"))
    if not exchange.ok:
        return _Got(exchange, None, problem=f"{address} did not arrive (status {status})")
    kind = NodeKind.html if node.kind is NodeKind.platform_ref else node.kind
    try:
        doc = parse_page(body, kind, final_url, content_type, pattern_text_limit=target.pattern_text_limit)
    except PageError as error:
        return _Got(exchange, None, problem=f"{address}: {error}")
    text = doc.text if kind is NodeKind.json else body.decode("utf-8", errors="replace")
    return _Got(exchange, doc, text=text)


def _paths(node: Node, got: _Got) -> frozenset[str]:
    if got.doc is None:
        return frozenset()
    return json_paths(got.doc.root) if node.kind is NodeKind.json else html_paths(got.text)


def _edge_step(edge: Edge, scope: Doc | Found, page_url: str, target: _Target, values: Mapping[str, str]
               ) -> tuple[Step | None, str | None]:
    """The request an edge makes from a page or an item: (step, problem)."""
    if edge.action is Action.call_api:
        return _plan(edge.request, edge.target, target.url, values), None
    if edge.link is None:
        return None, f"the edge to {edge.target} has no link"
    if edge.action is Action.follow_link:
        href = first_text(edge.link, scope)
        if not href:
            return None, f"the link to {edge.target} was not found"
        return Step(node=edge.target, method="GET", url=urljoin(page_url, href)), None
    forms = find_items(edge.link, scope) if isinstance(scope, Doc) else find(edge.link, scope)
    step = _form_step(forms[0], page_url, edge.target, edge.request, values) if forms else None
    return step, (None if step is not None else f"the form that leads to {edge.target} was not found")


# == The list ==

def _route(recipe: AuthoredRecipe, list_id: str) -> list[Edge] | None:
    """The edges from the start node to the list, none of them `per_item`; None when there is no way."""
    frontier: list[tuple[str, list[Edge]]] = [(recipe.start, [])]
    seen = {recipe.start}
    while frontier:
        here, path = frontier.pop(0)
        if here == list_id:
            return path
        for edge in recipe.edges:
            if edge.source == here and not edge.per_item and edge.target not in seen:
                seen.add(edge.target)
                frontier.append((edge.target, [*path, edge]))
    return None


def _number(text: str | None) -> int | None:
    """A count the portal prints: the first run of digits, thousands separators allowed."""
    if not text:
        return None
    match = re.search(r"\d[\d.,'   ]*", text)
    if match is None:
        return None
    digits = "".join(_DIGITS.findall(match.group(0)))
    return int(digits) if digits else None


def _api_empty(node: Node, doc: Doc) -> bool:
    """A JSON answer whose list of items is there and empty: the API's own way of saying "no tenders"."""
    if node.kind is not NodeKind.json or node.items is None or node.items.kind is not LocatorKind.jsonpath:
        return False
    expr = (node.items.expr or "").strip()
    if not expr.endswith("[*]"):
        return False
    holder = Locator(kind=LocatorKind.jsonpath, expr=expr[:-3], labels=[], attr=None)
    found = find_items(holder, doc)
    return len(found) == 1 and found[0].node == []


def _raw_values(fields: Mapping[FieldName, FieldRead], tender_id: str | None) -> dict[str, str]:
    values = {name.value: read.raw for name, read in fields.items() if read.raw}
    if tender_id is not None:
        values["id"] = tender_id
    return values


def _read_rows(recipe: AuthoredRecipe, node: Node, doc: Doc, target: _Target, settings: RecipeSettings,
               out: ListRead, seen: set[str]) -> int:
    """Read every row of one list page into `out`. Returns how many ids were new."""
    context = target.context(doc.url, settings)
    edges = [edge for edge in recipe.edges if edge.source == node.id and edge.per_item]
    by_id = {n.id: n for n in recipe.nodes}
    rows = find_items(node.items, doc) if node.items is not None else []
    out.rows += len(rows)
    new = 0
    for row in rows:
        fields = read_fields(node.fields, row, context)
        links: list[tuple[Edge, Step]] = []
        address = None
        for edge in edges:
            if edge.action is Action.call_api:
                continue  # needs the id, planned below
            step, _ = _edge_step(edge, row, doc.url, target, _raw_values(fields, None))
            if step is not None:
                links.append((edge, step))
                if address is None and step.method == "GET" and by_id[edge.target].role is NodeRole.detail:
                    address = step.address
        url_read = fields.get(FieldName.url)
        url = url_read.value if url_read is not None and url_read.value else address
        found = read_id(recipe.identity, fields, url, settings)
        if found.tender_id is None:
            if len(out.dropped) < settings.max_problems:
                out.dropped.append(f"A row on {doc.url} was left out: {found.problem}.")
            continue
        tender_id = found.tender_id
        if tender_id in seen:
            out.duplicate_ids.append(tender_id)
            continue
        seen.add(tender_id)
        new += 1
        values = _raw_values(fields, tender_id)
        steps = []
        for edge in edges:
            planned = next((step for e, step in links if e is edge), None)
            if planned is None and edge.action is Action.call_api:
                planned, _ = _edge_step(edge, row, doc.url, target, values)
            if planned is not None:
                steps.append(planned)
        mark = first_text(node.facts.change_mark, row) if node.facts and node.facts.change_mark else None
        out.items.append(Item(tender_id=tender_id, fields=fields, row_hash=row_hash(fields, mark),
                              page_url=doc.url, steps=tuple(steps), address=address or (url if url else None)))
    return new


def read_list(recipe: AuthoredRecipe, source: Fetch, portal: Portal, *, first_page_only: bool = False,
              settings: RecipeSettings = DEFAULT_RECIPE_SETTINGS, tap: Tap | None = None,
              clock: Callable[[], float] = time.monotonic) -> ListRead:
    """Walk from the start node to the list and page through it.

    Paging stops at the end of the list, when a page brings no id that was not seen before, at
    the ceiling on pages (then `reached_end` is false), or when a page does not arrive. The
    fields come back as read, lone witnesses flagged: `settle` decides on them.
    """
    started = clock()
    out = ListRead(first_page_only=first_page_only)
    target = _target(recipe, portal, settings)
    by_id = {node.id: node for node in recipe.nodes}
    node = next((n for n in recipe.nodes if n.role is NodeRole.list), None)
    route = _route(recipe, node.id) if node is not None else None
    start = by_id.get(recipe.start)
    if node is None or route is None or start is None or start.request is None:
        out.problems.append("The recipe has no way from its start node to a list node.")
        return out
    if node.kind is NodeKind.platform_ref:
        out.problems.append("A platform_ref list is not supported yet.")
        return out

    paging = node.paging
    kind = paging.kind if paging is not None else PagingKind.none
    size = (paging.size if paging is not None and paging.size else None)
    first_number = paging.first if paging is not None and paging.first is not None else 1
    ceiling = (paging.max_pages if paging is not None and paging.max_pages else None) or settings.max_pages
    limit = settings.max_tenders_per_portal

    def values(page_index: int, offset: int, cursor: str) -> dict[str, str]:
        return {"page": str(first_number + page_index), "offset": str(offset),
                "size": str(size or settings.default_page_size), "cursor": cursor}

    def paged(step: Step, page_index: int, offset: int, cursor: str) -> Step:
        """The list's request for one page: the paging parameter set on top of the template."""
        if paging is None:
            return step
        if paging.size_param and size:
            step = _with_param(step, paging.size_param, str(size))
        if paging.param:
            if kind is PagingKind.page_param:
                step = _with_param(step, paging.param, str(first_number + page_index))
            elif kind is PagingKind.offset_param:
                step = _with_param(step, paging.param, str(offset))
            elif kind is PagingKind.cursor and cursor:
                step = _with_param(step, paging.param, cursor)
        return step

    def fail(got: _Got) -> None:
        if got.exchange is not None:
            out.exchanges.append(got.exchange)
            out.robots_forbidden = out.robots_forbidden or got.exchange.robots_forbidden
        if got.problem:
            out.problems.append(got.problem)

    # The way to the list: the start node, then one edge after the other.
    template: Request | None = start.request if start.id == node.id else None
    step = _plan(start.request, start.id, target.url, values(0, 0, ""))
    here = start
    got = _send(source, target, paged(step, 0, 0, "") if here.id == node.id else step, here, tap)
    for edge in route:
        if got.doc is None:
            break
        out.exchanges.append(got.exchange)
        step, problem = _edge_step(edge, got.doc, got.doc.url, target, values(0, 0, ""))
        if step is None:
            out.problems.append(f"On {got.doc.url}, {problem}.")
            out.seconds = clock() - started
            return out
        here = by_id[edge.target]
        if here.id == node.id:
            template = edge.request if edge.action is Action.call_api else None
            step = paged(step, 0, 0, "")
        got = _send(source, target, step, here, tap)
    first_step = step

    seen: set[str] = set()
    page_index = 0
    while True:
        if got.doc is None:
            fail(got)
            break
        out.exchanges.append(got.exchange)
        out.pages += 1
        doc = got.doc
        rows_before = out.rows
        new = _read_rows(recipe, node, doc, target, settings, out, seen)
        rows_here = out.rows - rows_before
        if out.pages == 1:
            out.structure_paths = _paths(node, got)
            facts = node.facts
            if facts is not None:
                out.printed_total = _number(first_text(facts.total, doc)) if facts.total else None
                out.empty_marker = bool(find(facts.empty_marker, doc)) if facts.empty_marker else False
            out.api_empty = rows_here == 0 and _api_empty(node, doc)
        if limit and len(out.items) > limit:
            del out.items[limit:]  # more than we were asked for: keep the first ones and stop paging
            out.capped = True
            break
        if first_page_only:
            break
        if kind is PagingKind.none:
            out.reached_end = True
            break
        if rows_here == 0 or new == 0:
            out.reached_end = True  # an empty page, or one that only repeats what we have
            break
        if out.pages >= ceiling:
            out.problems.append(f"Paging was stopped at the ceiling of {ceiling} pages.")
            break

        page_index += 1
        cursor = ""
        if kind in (PagingKind.next_link, PagingKind.cursor):
            cursor = first_text(paging.next, doc) or "" if paging.next is not None else ""
            if not cursor:
                out.reached_end = True
                break
        if kind is PagingKind.next_link or (kind is PagingKind.cursor and not paging.param
                                             and "{cursor}" not in _template_text(template)):
            step = Step(node=node.id, method="GET", url=urljoin(doc.url, cursor), via=first_step.via)
        elif kind is PagingKind.form_post:
            forms = find_items(paging.form, doc) if paging.form is not None else []
            next_step = _form_step(forms[0], doc.url, node.id, None, {}) if forms else None
            if next_step is None:
                out.reached_end = True
                break
            step = next_step
        elif kind is PagingKind.load_more:
            out.problems.append("load_more paging is not supported yet: only the first page was read.")
            break
        else:
            if kind in (PagingKind.page_param, PagingKind.offset_param) and size and rows_here < size:
                out.reached_end = True  # a short page is the last one
                break
            base = (_plan(template, node.id, target.url, values(page_index, out.rows, cursor))
                    if template is not None else first_step)
            step = paged(base, page_index, out.rows, cursor)
        got = _send(source, target, step, node, tap)

    out.seconds = clock() - started
    return out


def _template_text(request: Request | None) -> str:
    if request is None:
        return ""
    return " ".join([request.url, request.body_json or "", *(p.value for p in [*request.params, *request.body])])


# == One tender ==

def _exact_bytes(text: str | None) -> int | None:
    """A size the portal announces, only when it is an exact count of bytes ("12,345 bytes"). "1.2 MB" is not."""
    if not text:
        return None
    match = _EXACT_BYTES.match(text)
    if match is None or (match.group(2) is None and not text.strip().isdigit()):
        return None
    digits = "".join(_DIGITS.findall(match.group(1)))
    return int(digits) if digits else None


def _documents(node: Node, doc: Doc, target: _Target, source: Fetch, values: Mapping[str, str], out: DetailRead,
               budget: list[int], tap: Tap | None) -> list[Announced]:
    rule = node.documents
    found: list[Announced] = []
    if rule.request is not None:
        out.problems.append("A document fetched by a POST is not supported yet.")
        return found
    for link in find(rule.links, doc):
        if rule.url:
            address = urljoin(target.url, _fill(rule.url, {**values, "file": link.text}, in_path=True))
        else:
            address = urljoin(doc.url, link.text)
        name = first_text(rule.name, link) if rule.name is not None else None
        size = _exact_bytes(first_text(rule.size, link)) if rule.size is not None else None
        if rule.then is not None:  # the link leads to a page; the file's address is on that page
            if budget[0] <= 0:
                out.problems.append("The limit of requests for one tender was reached before all files were found.")
                out.complete = False
                break
            budget[0] -= 1
            got = _send(source, target, Step(node=node.id, method="GET", url=address), node, tap)
            if got.exchange is not None:
                out.exchanges.append(got.exchange)
            href = first_text(rule.then, got.doc) if got.doc is not None else None
            if not href:
                out.problems.append(got.problem or f"On {address}, the file's address was not found.")
                out.complete = False
                continue
            address = urljoin(got.doc.url, href)
        if urlsplit(address).scheme not in ("http", "https"):
            continue
        if all(known.source_url != address for known in found):
            found.append(Announced(source_url=address, name=name, size_bytes=size))
    return found


def read_detail(recipe: AuthoredRecipe, source: Fetch, portal: Portal, item: Item, *,
                settings: RecipeSettings = DEFAULT_RECIPE_SETTINGS, tap: Tap | None = None) -> DetailRead:
    """Walk one tender's edges: its detail page, its documents, whatever the recipe names.

    The fields of every page are merged with the list row's; a value that differs between two
    pages becomes a `conflict` (null). `documents` stays None unless a page that lists the
    files arrived, so "no documents" and "not known" stay apart.
    """
    target = _target(recipe, portal, settings)
    by_id = {node.id: node for node in recipe.nodes}
    out = DetailRead(tender_id=item.tender_id, fields=dict(item.fields))
    values = _raw_values(item.fields, item.tender_id)
    budget = [settings.max_requests_per_tender]
    queue: list[Step] = list(item.steps)
    visited: set[str] = set()
    documents: list[Announced] = []
    listed = False
    while queue:
        step = queue.pop(0)
        node = by_id.get(step.node)
        if node is None or node.id in visited:
            continue
        visited.add(node.id)
        if node.kind is NodeKind.platform_ref:
            out.problems.append(f"Node {node.id}: documents on another platform are not supported yet.")
            out.complete = False
            continue
        if budget[0] <= 0:
            out.problems.append("The limit of requests for one tender was reached.")
            out.complete = False
            break
        budget[0] -= 1
        got = _send(source, target, step, node, tap)
        if got.exchange is not None:
            out.exchanges.append(got.exchange)
        if got.doc is None:
            out.problems.append(got.problem or f"{step.address} did not arrive")
            out.complete = False
            continue
        doc = got.doc
        out.urls.append(doc.url)
        out.structure_paths[node.id] = _paths(node, got)
        if node.fields:
            page = read_fields(node.fields, doc, target.context(doc.url, settings))
            out.page_fields = merge_fields(out.page_fields, page)
            out.fields = merge_fields(out.fields, page)
            values = {**_raw_values(out.fields, item.tender_id), **values}
        if node.documents is not None:
            listed = True
            for announced in _documents(node, doc, target, source, values, out, budget, tap):
                if all(known.source_url != announced.source_url for known in documents):
                    documents.append(announced)
        for edge in recipe.edges:
            if edge.source != node.id or edge.target in visited or by_id[edge.target].role is NodeRole.list:
                continue
            nxt, problem = _edge_step(edge, doc, doc.url, target, values)
            if nxt is None:
                out.problems.append(f"On {doc.url}, {problem}.")
                out.complete = False
            else:
                queue.append(nxt)
    if listed:
        out.documents = documents
    return out


def known_item(recipe: AuthoredRecipe, portal: Portal, record: TenderRecord) -> Item | None:
    """A tender of an earlier read as an item, so its own page can be read without the list (C4, C6, rotation).

    An edge that calls an API is planned from the id; an edge that follows a link uses the
    address stored on the record. None when the recipe has no way to the tender's page.
    """
    target = _target(recipe, portal)
    by_id = {node.id: node for node in recipe.nodes}
    node = next((n for n in recipe.nodes if n.role is NodeRole.list), None)
    if node is None:
        return None
    values = {name: text for name, text in record.raw.items() if text}
    values["id"] = record.tender_id
    steps: list[Step] = []
    for edge in recipe.edges:
        if edge.source != node.id or not edge.per_item:
            continue
        if edge.action is Action.call_api:
            steps.append(_plan(edge.request, edge.target, target.url, values))
        elif edge.action is Action.follow_link and by_id[edge.target].role is NodeRole.detail and record.url:
            steps.append(Step(node=edge.target, method="GET", url=record.url))
    if not steps:
        return None
    return Item(tender_id=record.tender_id, fields={}, row_hash="", page_url=target.url, steps=tuple(steps),
                address=record.url)


def judge_look(recipe: AuthoredRecipe, read: DetailRead, now: datetime,
               settings: RecipeSettings = DEFAULT_RECIPE_SETTINGS) -> LookOutcome:
    """What the own page of a tender that left the list shows, for `confirm_missing` (C4)."""
    if read.gone:
        return LookOutcome.gone
    if not read.exchanges or any(not exchange.answered for exchange in read.exchanges):
        return LookOutcome.no_answer
    if not read.urls:
        return LookOutcome.unclear
    status = read.page_fields.get(FieldName.status)
    if status is not None and status.value == "withdrawn":
        return LookOutcome.withdrawn
    if status is not None and status.value == "closed":
        return LookOutcome.closed
    deadline = read.page_fields.get(FieldName.submission_deadline)
    when = deadline.value if deadline is not None and isinstance(deadline.value, datetime) else None
    if when is not None and when <= now:
        return LookOutcome.closed
    page_id = read_id(recipe.identity, read.page_fields, read.urls[0], settings).tender_id
    shows_open = (status is not None and status.value == "open") or when is not None
    if page_id == read.tender_id and shows_open:
        return LookOutcome.still_open
    return LookOutcome.unclear


# == Records ==

def settle(portal_id: str, reads: Mapping[str, Mapping[FieldName, FieldRead]], *,
           last_good: Mapping[str, TenderRecord] | None, urls: Mapping[str, Iterable[str]] | None = None,
           addresses: Mapping[str, str | None] | None = None, run_id: str | None = None,
           settings: RecipeSettings = DEFAULT_RECIPE_SETTINGS) -> dict[str, TenderRecord]:
    """The fields of every tender of one read as records, lone witnesses settled against the last good read.

    `last_good` is None at the attach. `addresses` gives the tender's own page where the list
    links to it: it becomes the record's `url` when no `url` field was read.
    """
    settled = settle_single_witnesses(reads, last_good, settings)
    records: dict[str, TenderRecord] = {}
    for tender_id, fields in settled.items():
        record = fill_record(portal_id, tender_id, fields, source_urls=(urls or {}).get(tender_id, ()),
                             run_id=run_id)
        address = (addresses or {}).get(tender_id)
        if record.url is None and address and FieldName.url not in fields:
            record = record.model_copy(update={"url": address})
        records[tender_id] = record
    return records


# == Dry run ==

@dataclass
class DryRun:
    """What a recipe gives on cached pages: for the learning agent, which fixes what `problems` says."""

    records: list[TenderRecord] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    # What the recipe reads that a record cannot carry: said here, and no reason to refuse the recipe.
    notes: list[str] = field(default_factory=list)
    missing_pages: list[str] = field(default_factory=list)  # pages the recipe asks for that are not cached
    rows: int = 0
    pages: int = 0
    printed_total: int | None = None
    reached_end: bool = False
    details_read: int = 0
    documents: dict[str, list[Announced]] = field(default_factory=dict)  # by tender id
    filled: dict[str, int] = field(default_factory=dict)     # field name: how many records have a value
    conflicts: dict[str, int] = field(default_factory=dict)  # field name: how often the locators disagreed
    single_witnesses: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """The recipe ran on every cached page it asked for and gave at least one record."""
        return bool(self.records) and not self.problems


def dry_run(recipe: AuthoredRecipe, pages: PageCache | Iterable[CachedPage] | Mapping[str, Any], *, url: str,
            timezone: str | None = None, max_details: int | None = None,
            settings: RecipeSettings = DEFAULT_RECIPE_SETTINGS) -> DryRun:
    """Run a recipe on cached pages only. No request is made.

    `url` is the portal's address and `timezone` its IANA zone (without one, a deadline that
    carries no offset reads as null). A page the recipe asks for that is not cached is named in
    `missing_pages`, not in `problems`: fetch it and run again. There is no last good read
    here, so lone witnesses are kept and counted.
    """
    from app.models import url_key
    from app.recipe.schema import problems as recipe_problems

    out = DryRun()
    faults = recipe_problems(recipe)
    if faults:
        out.problems = faults
        return out
    source = pages if isinstance(pages, PageCache) else PageCache(pages)
    portal = Portal(id="dry-run", url=url, url_key=url_key(url), timezone=timezone)

    def keep(problems: Iterable[str]) -> None:
        for problem in problems:
            if " is not among the cached pages" in problem:
                page = problem.split(" is not among the cached pages")[0]
                if page not in out.missing_pages:
                    out.missing_pages.append(page)
            elif problem not in out.problems and len(out.problems) < settings.max_problems:
                out.problems.append(problem)

    listed = read_list(recipe, source, portal, settings=settings)
    keep([*listed.problems, *listed.dropped])
    out.rows, out.pages, out.printed_total = listed.rows, listed.pages, listed.printed_total
    out.reached_end = listed.reached_end
    if listed.duplicate_ids:
        keep([f"The list shows the id {listed.duplicate_ids[0]} more than once."])
    if listed.pages and not listed.rows and not (listed.empty_marker or listed.api_empty or listed.printed_total == 0):
        keep(["The item locator matched no row on the list."])

    reads: dict[str, Mapping[FieldName, FieldRead]] = {}
    urls: dict[str, list[str]] = {}
    addresses: dict[str, str | None] = {}
    for number, item in enumerate(listed.items):
        fields: Mapping[FieldName, FieldRead] = item.fields
        urls[item.tender_id] = [item.page_url]
        addresses[item.tender_id] = item.address
        if item.steps and (max_details is None or number < max_details):
            detail = read_detail(recipe, source, portal, item, settings=settings)
            keep(detail.problems)
            if detail.urls:
                out.details_read += 1
                fields = detail.fields
                urls[item.tender_id] += detail.urls
            if detail.documents is not None:
                out.documents[item.tender_id] = detail.documents
        reads[item.tender_id] = fields
        for name, read in fields.items():
            if read.flag == "conflict":
                out.conflicts[name.value] = out.conflicts.get(name.value, 0) + 1
            elif read.flag == "single_witness":
                out.single_witnesses[name.value] = out.single_witnesses.get(name.value, 0) + 1
            if read.value is not None:
                out.filled[name.value] = out.filled.get(name.value, 0) + 1
    out.records = list(settle(portal.id, reads, last_good=None, urls=urls, addresses=addresses,
                              settings=settings).values())
    closed = closed_by_the_portal(reads)
    if closed:
        out.notes.append(
            f"The portal words {len(closed)} listed tender(s) as closed (for example {closed[0]}). A record has "
            "no place for that: such a tender is delivered as open until it leaves the list or its deadline "
            "passes. The portal's word is kept in the record's raw status.")
    return out


def closed_by_the_portal(reads: Mapping[str, Mapping[FieldName, FieldRead]]) -> list[str]:
    """The ids of the tenders whose status the portal words as closed.

    `fill_record` cannot store that: `TenderRecord` knows `withdrawn` and `listed` only, so a
    tender the portal calls closed while it still lists it, with its deadline ahead, comes out
    open (docs/SHARED-INTERFACE-REQUESTS.md). Callers use this to say so.
    """
    return [tender_id for tender_id, fields in reads.items()
            if FieldName.status in fields and fields[FieldName.status].value == "closed"]
