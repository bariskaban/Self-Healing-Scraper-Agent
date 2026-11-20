"""The tools the model may call (Q4), on the fetch interface and on the executor's `try_locator`
and `dry_run`.

A `Workspace` is the state of one learn or repair: the pages fetched so far, the request budget,
and the working recipe. Every page is cached the first time it is fetched; viewing it again,
trying a locator on it and dry-running the recipe cost no request. Every request goes through
`app/fetch` (CONVENTIONS.md, rule 1) and only to the portal's own site: a page cannot send the
model elsewhere.

The tools:
  open_page, view_page, page_links, search_page   look at the portal
  call_api                                        one HTTP request with parameters or a body
  try_locator                                     what a locator finds on a cached page
  propose_recipe, replace_node, check_recipe      write the recipe; each one validates and dry-runs it

Browser pages are not offered: the network layer has no live browser yet, and the executor
does not run browser steps.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent import views
from app.agent.runner import Said, Tool, strict_schema
from app.agent.settings import DEFAULT_AGENT_SETTINGS, AgentSettings
from app.fetch.interface import Fetch, RobotsForbidden, RobotsUnavailable
from app.models import Portal
from app.recipe.locate import PageError, parse_page, try_locator
from app.recipe.run import CachedPage, DryRun, dry_run
from app.recipe.schema import AuthoredRecipe, Locator, Node, NodeKind, NodeRole, Pair, problems
from app.recipe.settings import DEFAULT_RECIPE_SETTINGS, RecipeSettings

# The fields a tender must carry for the contract (DESIGN.md, "Tender record"); a recipe that
# fills none of one of them is accepted only with a warning the model has read.
WANTED = ("url", "title", "buyer_name", "publication_date", "submission_deadline")
# Not required, but delivered when the portal states them: a recipe that reads none is told once.
WELCOME = ("reference_number", "description", "cpv_codes", "procedure_type", "contract_nature")


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenPage(_Args):
    url: str = Field(description="absolute, or relative to the portal's address; on the portal's own site")


class ViewPage(_Args):
    url: str = Field(description="a page opened before")
    part: int = Field(description="which part of the view, from 1")
    all_rows: bool = Field(description="true shows every row of a long list instead of the first three")


class PageLinks(_Args):
    url: str = Field(description="a page opened before")
    contains: str | None = Field(description="only links whose address contains this text, or null")


class SearchPage(_Args):
    url: str = Field(description="a page opened before (HTML, JSON or a script file)")
    pattern: str = Field(description="a regular expression, matched without regard to case in the raw body")


class CallApi(_Args):
    method: Literal["GET", "POST"]
    url: str
    params: list[Pair] = Field(description="query parameters")
    body_kind: Literal["none", "form", "json"]
    body: list[Pair] = Field(description="form fields, or members of a JSON object")
    body_json: str | None = Field(description="a JSON body as text when pairs cannot express it, else null")


class TryLocator(_Args):
    url: str = Field(description="a page opened before")
    page_kind: Literal["html", "json", "feed"] = Field(description="how to parse the page")
    locator: Locator
    items: Locator | None = Field(description="the list's item locator: the locator is then tried inside each of the first items; null tries it on the whole page")


class ProposeRecipe(_Args):
    recipe: AuthoredRecipe
    timezone: str | None = Field(description="the portal's IANA time zone, e.g. Europe/Berlin; without it a deadline that carries no offset reads as null")
    country_code: str | None = Field(description="the portal's country, two letters, or null")


class ReplaceNode(_Args):
    node: Node = Field(description="replaces the node of the working recipe that has this id")


class CheckRecipe(_Args):
    show_recipe: bool = Field(description="true also returns the working recipe as JSON")


def site_of(host: str) -> str:
    """The part of a host name that names the site: the last two labels, or three when the
    second-level label is a short generic one (gov.uk, com.tr)."""
    labels = host.lower().strip(".").split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    take = 3 if len(labels[-2]) <= 3 and len(labels[-1]) == 2 else 2
    return ".".join(labels[-take:])


class OffSite(ValueError):
    pass


class BudgetSpent(RuntimeError):
    pass


@dataclass
class Accepted:
    """A working recipe whose dry run passed."""

    recipe: AuthoredRecipe
    timezone: str | None
    country_code: str | None
    result: DryRun


class Workspace:
    """The state of one learn or repair on one portal."""

    def __init__(self, portal: Portal, fetch: Fetch, *, max_requests: int,
                 settings: AgentSettings = DEFAULT_AGENT_SETTINGS,
                 recipes: RecipeSettings = DEFAULT_RECIPE_SETTINGS) -> None:
        self.portal, self.fetch, self.settings, self.recipes = portal, fetch, settings, recipes
        self.max_requests = max_requests
        self.requests = 0
        self.pages: dict[tuple[str, str], CachedPage] = {}
        self.recipe: AuthoredRecipe | None = None
        self.timezone: str | None = portal.timezone
        self.country_code: str | None = portal.country_code
        self.accepted: Accepted | None = None   # the working recipe, when its last dry run passed
        self.passed: Accepted | None = None     # the newest recipe that ever passed in this run
        self.last_check: DryRun | None = None

    # -- pages --

    def absolute(self, url: str) -> str:
        address = urljoin(self.portal.url, url.strip())
        parts = urlsplit(address)
        home = urlsplit(self.portal.url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise OffSite(f"{url} is not an http or https address.")
        if site_of(parts.hostname) != site_of(home.hostname or ""):
            raise OffSite(f"{parts.hostname} is not part of the portal's site ({site_of(home.hostname or '')}). "
                          "Only the portal we were given is read.")
        return address

    def cached(self, url: str, method: str = "GET") -> CachedPage | None:
        try:
            address = self.absolute(url)
        except OffSite:
            return None
        return self.pages.get(_key(method, address)) or self.pages.get(_key("POST" if method == "GET" else "GET", address))

    def get(self, url: str, *, method: str = "GET", params: dict[str, str] | None = None,
            data: dict[str, str] | None = None, body: Any = None) -> tuple[CachedPage, bool]:
        """The page, from the cache or fetched now. Returns it and whether a request was sent.
        Raises OffSite, BudgetSpent, or LookupError with a sentence when no page came."""
        address = self.absolute(url)
        if params:
            address = str(httpx.URL(address, params=params))
        key = _key(method, address)
        if key in self.pages and data is None and body is None:
            return self.pages[key], False
        if self.requests >= self.max_requests:
            raise BudgetSpent(f"The budget of {self.max_requests} requests to the portal is spent. "
                              "Work with the pages already opened.")
        self.requests += 1
        try:
            got = self.fetch.fetch(self.portal.id, address, method=method, data=data, json=body)
        except RobotsForbidden:
            raise LookupError(f"The portal's robots.txt disallows {address}; we obey it.") from None
        except RobotsUnavailable:
            raise LookupError("The portal's robots.txt could not be read, so nothing may be fetched now.") from None
        except (LookupError, NotImplementedError) as error:  # a replay with no recording of this page
            raise LookupError(f"{address} could not be fetched: {error}") from None
        if got.status is None:
            raise LookupError(f"{address} gave no answer ({got.answer.error or 'no response'}).")
        page = CachedPage(url=address, body=got.body, status=got.status, content_type=got.headers.get("content-type"),
                          method=method, final_url=got.final_url)
        self.pages[key] = page
        return page, True

    def text(self, page: CachedPage) -> str:
        if isinstance(page.body, str):
            return page.body
        got = httpx.Response(page.status, headers={"content-type": page.content_type} if page.content_type else {},
                             content=page.body)
        try:
            return got.text
        except (LookupError, UnicodeDecodeError):
            return page.body.decode("utf-8", errors="replace")

    def view(self, page: CachedPage, part: int = 1, all_rows: bool = False) -> str:
        body = self.text(page)
        kind = "text"
        shown: str | None = None
        if views.looks_like_json(body, page.content_type):
            shown = views.json_view(body, settings=self.settings)
            kind = "JSON, arrays cut short"
        if shown is None and views.looks_like_html(body, page.content_type):
            shown = views.html_view(body, all_rows=all_rows, settings=self.settings)
            kind = "trimmed HTML"
        if shown is None:
            shown = body
        text, parts = views.part_of(shown, part, self.settings)
        head = [f"{page.method} {page.url} answered {page.status}"
                + (f", content type {page.content_type}" if page.content_type else "")
                + f", {len(page.body):,} bytes."]
        if page.final_url and page.final_url != page.url:
            head.append(f"Redirected to {page.final_url}.")
        title = views.title_of(body) if kind == "trimmed HTML" else None
        if title:
            head.append(f"Title: {title}")
        head.append(f"View ({kind}), part {min(max(part, 1), parts)} of {parts}:")
        return "\n".join(head) + "\n" + text

    # -- the recipe --

    def check(self) -> tuple[DryRun | None, list[str]]:
        """Dry-run the working recipe on the cached pages, fetching the pages it lacks while the
        budgets last. Returns the result and warnings; sets `accepted` when it passed."""
        recipe = self.recipe
        self.accepted = None
        if recipe is None:
            return None, ["There is no working recipe yet. Call propose_recipe."]
        limited, capped = self._limited(recipe)
        ceiling = f"Paging was stopped at the ceiling of {self.settings.dry_run_list_pages} pages."
        fetched = 0
        asked: set[str] = set()
        while True:
            result = dry_run(limited, list(self.pages.values()), url=self.portal.url, timezone=self.timezone,
                             max_details=self.settings.dry_run_details, settings=self.recipes)
            wanted = [page[4:] for page in result.missing_pages if page.startswith("GET ") and page[4:] not in asked]
            if not wanted or fetched >= self.settings.dry_run_fetches:
                break
            progressed = False
            for address in wanted:
                asked.add(address)
                if fetched >= self.settings.dry_run_fetches:
                    break
                try:
                    _, sent = self.get(address)
                except BudgetSpent:
                    fetched = self.settings.dry_run_fetches
                    break
                except (OffSite, LookupError) as error:
                    result.problems.append(str(error))
                    continue
                fetched += 1 if sent else 0
                progressed = True
            if not progressed:
                break
        if capped:
            result.problems = [problem for problem in result.problems if problem != ceiling]
        self.last_check = result
        warnings = self._warnings(result)
        missing = [page for page in result.missing_pages if page[4:] not in asked or page.startswith("POST ")]
        if result.records and not result.problems and not missing and \
                result.filled.get("title", 0) == len(result.records):
            self.accepted = self.passed = Accepted(recipe, self.timezone, self.country_code, result)
        return result, warnings

    def _limited(self, recipe: AuthoredRecipe) -> tuple[AuthoredRecipe, bool]:
        """The recipe with its list paging capped for the dry run: two pages show that paging works."""
        cap = self.settings.dry_run_list_pages
        nodes, capped = [], False
        for node in recipe.nodes:
            if node.role is NodeRole.list and node.paging is not None and \
                    (node.paging.max_pages is None or node.paging.max_pages > cap):
                node = node.model_copy(update={"paging": node.paging.model_copy(update={"max_pages": cap})})
                capped = True
            nodes.append(node)
        return recipe.model_copy(update={"nodes": nodes}), capped

    def _warnings(self, result: DryRun) -> list[str]:
        out = []
        total = len(result.records)
        if total:
            for name in WANTED:
                filled = result.filled.get(name, 0)
                if filled == 0:
                    out.append(f"No record has a {name}. The contract wants it: find it on the list or on the "
                               "tender's own page, unless the portal truly does not state it.")
                elif filled < total:
                    out.append(f"{name} is filled on {filled} of {total} records.")
            for name, count in result.conflicts.items():
                out.append(f"{name}: its locators disagreed on {count} record(s), so the value was dropped there. "
                           "Make them point at the same value.")
            absent = [name for name in WELCOME if result.filled.get(name, 0) == 0]
            if absent:
                out.append(f"No record has {', '.join(absent)}. They are not required, but read each one the "
                           "portal states on the tender's page or in its API answer.")
        if self.timezone is None:
            out.append("No time zone is set: a deadline without an offset reads as null. Pass `timezone`.")
        return out

    def report(self, result: DryRun | None, warnings: list[str], show_recipe: bool = False) -> Said:
        """What the model reads after a dry run, and the operator's line."""
        if result is None:
            return Said(warnings[0], "No working recipe yet.")
        settings = self.settings
        accepted = self.accepted is not None
        total = len(result.records)
        samples = []
        for record in result.records[: settings.dry_run_samples]:
            samples.append({
                "id": record.tender_id, "url": record.url, "title": record.title, "buyer_name": record.buyer_name,
                "publication_date": record.publication_date.isoformat() if record.publication_date else None,
                "submission_deadline": record.submission_deadline.isoformat() if record.submission_deadline else None,
                "reference_number": record.reference_number, "procedure_type": record.procedure_type,
                "contract_nature": record.contract_nature, "cpv_codes": record.cpv_codes,
                "description": (record.description or "")[:160] or None,
                "documents": [doc.source_url for doc in result.documents.get(record.tender_id, [])][:5]})
        out: dict[str, Any] = {
            "accepted": accepted,
            "records": total, "list_rows": result.rows, "list_pages_read": result.pages,
            "printed_total": result.printed_total, "tender_pages_read": result.details_read,
            "filled": {name: f"{count} of {total}" for name, count in sorted(result.filled.items())},
            "problems": result.problems[: settings.dry_run_problems],
            "pages_not_fetched": result.missing_pages[:5],
            "warnings": warnings, "notes": result.notes,
            "sample_records": json.loads(json.dumps(samples, default=str)),
            "requests_left": max(self.max_requests - self.requests, 0),
        }
        if len(result.problems) > settings.dry_run_problems:
            out["problems"].append(f"… and {len(result.problems) - settings.dry_run_problems} more")
        if accepted:
            out["next"] = ("The dry run passed. Fix the warnings that can be fixed, then give your final answer; "
                           "the first full read checks the recipe on the whole portal.")
        else:
            out["next"] = "Not accepted yet: fix the problems (replace_node changes one node), then it is checked again."
        if show_recipe and self.recipe is not None:
            out["working_recipe"] = self.recipe.model_dump(mode="json")
        line = (f"Dry run of the recipe: {total} record(s) from {result.rows} row(s), "
                f"{result.details_read} tender page(s) read; "
                + ("it passed." if accepted else f"{len(result.problems)} problem(s), not accepted."))
        return Said(json.dumps(out, ensure_ascii=False, indent=1), line)


def _key(method: str, url: str) -> tuple[str, str]:
    from app.recipe.run import _address_key  # the same key the dry run finds pages by

    return _address_key(method, url)


# == The tools ==

def _tool(name: str, description: str, args: type[BaseModel], run: Callable[[Any], Said]) -> Tool:
    def call(raw: dict[str, Any]) -> Said:
        try:
            parsed = args.model_validate(raw)
        except ValidationError as error:
            faults = "; ".join(f"{'.'.join(str(p) for p in fault['loc'])}: {fault['msg']}"
                               for fault in error.errors()[:12])
            return Said(f"The arguments do not fit the tool's schema: {faults}", f"{name}: arguments refused")
        return run(parsed)

    return Tool(name=name, description=description, parameters=strict_schema(args), run=call)


def tools(space: Workspace) -> list[Tool]:
    """The tools of one learn or repair, bound to its workspace."""

    def fetched(url: str, **how: Any) -> tuple[CachedPage | None, Said | None]:
        try:
            page, sent = space.get(url, **how)
        except (OffSite, BudgetSpent, LookupError) as error:
            return None, Said(str(error), f"Could not open {url}: {error}")
        return page, None

    def known(url: str) -> tuple[CachedPage | None, Said | None]:
        page = space.cached(url)
        if page is None:
            return None, Said(f"{url} has not been opened in this run. Open it first with open_page.",
                              f"{url} is not among the opened pages.")
        return page, None

    def open_page(args: OpenPage) -> Said:
        page, problem = fetched(args.url)
        if page is None:
            return problem  # type: ignore[return-value]
        return Said(space.view(page), f"Opened {page.url}: status {page.status}, {len(page.body):,} bytes.")

    def view_page(args: ViewPage) -> Said:
        page, problem = known(args.url)
        if page is None:
            return problem  # type: ignore[return-value]
        return Said(space.view(page, args.part, args.all_rows), f"Viewed part {args.part} of {page.url}.")

    def page_links(args: PageLinks) -> Said:
        page, problem = known(args.url)
        if page is None:
            return problem  # type: ignore[return-value]
        text = views.links_view(space.text(page), page.final_url or page.url, contains=args.contains,
                                settings=space.settings)
        return Said(text, f"Listed the links of {page.url}" + (f" containing {args.contains!r}." if args.contains else "."))

    def search_page(args: SearchPage) -> Said:
        page, problem = known(args.url)
        if page is None:
            return problem  # type: ignore[return-value]
        text = views.search(space.text(page), args.pattern, settings=space.settings)
        return Said(text, f"Searched {page.url} for /{args.pattern}/: {text.splitlines()[0]}")

    def call_api(args: CallApi) -> Said:
        params = {pair.name: pair.value for pair in args.params} or None
        data = body = None
        if args.method == "POST" and args.body_kind == "form":
            data = {pair.name: pair.value for pair in args.body}
        elif args.method == "POST" and args.body_kind == "json":
            try:
                body = json.loads(args.body_json) if args.body_json else {pair.name: pair.value for pair in args.body}
            except ValueError as error:
                return Said(f"`body_json` is not JSON: {error}", "call_api: the body was not JSON.")
        page, problem = fetched(args.url, method=args.method, params=params, data=data, body=body)
        if page is None:
            return problem  # type: ignore[return-value]
        return Said(space.view(page), f"Called {args.method} {page.url}: status {page.status}, {len(page.body):,} bytes.")

    def locate(args: TryLocator) -> Said:
        page, problem = known(args.url)
        if page is None:
            return problem  # type: ignore[return-value]
        faults = [fault for where, locator in (("locator", args.locator), ("items", args.items))
                  if locator is not None for fault in _locator_faults(where, locator)]
        if faults:
            return Said("\n".join(faults), f"try_locator: the locator was refused ({faults[0]})")
        try:
            doc = parse_page(page.body, NodeKind(args.page_kind), page.final_url or page.url, page.content_type,
                             pattern_text_limit=space.recipes.pattern_text_limit)
            found = try_locator(args.locator, doc, items=args.items)
            rows = None
            if args.items is not None:
                from app.recipe.locate import find_items
                rows = len(find_items(args.items, doc))
        except (PageError, ValueError, TypeError) as error:
            return Said(f"The locator could not be run: {error}", f"try_locator failed: {error}")
        what = args.locator.expr or ", ".join(args.locator.labels)
        out = {"matches_shown": found, "items_matched": rows}
        if not found:
            out["hint"] = ("Nothing found. Look at the view again: the locator must match the trimmed HTML's "
                           "tags, ids and classes; inside `items` it is relative to one item.")
        return Said(json.dumps(out, ensure_ascii=False, indent=1),
                    f"Tried {args.locator.kind.value} locator {what!r} on {page.url}: {len(found)} value(s)"
                    + (f" in {rows} item(s)." if rows is not None else "."))

    def propose(args: ProposeRecipe) -> Said:
        space.recipe = args.recipe
        space.timezone = args.timezone or space.timezone
        space.country_code = (args.country_code or space.country_code or None)
        result, warnings = space.check()
        return space.report(result, warnings)

    def replace(args: ReplaceNode) -> Said:
        if space.recipe is None:
            return Said("There is no working recipe yet. Call propose_recipe.", "replace_node: no working recipe.")
        ids = [node.id for node in space.recipe.nodes]
        if args.node.id not in ids:
            return Said(f"The working recipe has no node {args.node.id!r}. Its nodes: {', '.join(ids)}.",
                        f"replace_node: no node {args.node.id!r}.")
        nodes = [args.node if node.id == args.node.id else node for node in space.recipe.nodes]
        space.recipe = space.recipe.model_copy(update={"nodes": nodes})
        result, warnings = space.check()
        said = space.report(result, warnings)
        return Said(said.text, f"Replaced node {args.node.id!r}. {said.summary}")

    def check(args: CheckRecipe) -> Said:
        result, warnings = space.check()
        return space.report(result, warnings, show_recipe=args.show_recipe)

    return [
        _tool("open_page", "Fetch a page of the portal with a GET (one request, then cached) and see its first "
              "part: trimmed HTML, or JSON with arrays cut short. Long lists show three rows.", OpenPage, open_page),
        _tool("view_page", "See another part of a page opened before, or all rows of its list. No request.",
              ViewPage, view_page),
        _tool("page_links", "The links and forms of an opened page, grouped by address pattern with a sample "
              "each: the way to find the tender list, feeds and detail pages. No request.", PageLinks, page_links),
        _tool("search_page", "Search the raw body of an opened page with a regular expression: finds API "
              "addresses in scripts and embedded app state the trimmed view leaves out. No request.",
              SearchPage, search_page),
        _tool("call_api", "One HTTP request with query parameters or a body (a JSON API, a search form). "
              "Cached under its address.", CallApi, call_api),
        _tool("try_locator", "What a locator finds on an opened page, before it goes into the recipe. No request.",
              TryLocator, locate),
        _tool("propose_recipe", "Set the whole working recipe. It is validated and dry-run on the cached pages "
              "(pages it lacks are fetched within the budget); the answer says what it read and what is wrong.",
              ProposeRecipe, propose),
        _tool("replace_node", "Replace one node of the working recipe, then validate and dry-run it again. "
              "Cheaper than proposing the whole recipe.", ReplaceNode, replace),
        _tool("check_recipe", "Dry-run the working recipe again, and optionally show it.", CheckRecipe, check),
    ]


def _locator_faults(where: str, locator: Locator) -> list[str]:
    from app.recipe.schema import _locator_problems  # the same sentences a refused recipe gets

    return _locator_problems(where, locator)


__all__ = ["Accepted", "BudgetSpent", "OffSite", "WANTED", "Workspace", "problems", "site_of", "tools"]
