"""The recipe: how one portal is read, as a typed navigation graph (Q1). Format `recipe/v1`.

A recipe is what the learner writes once and the executor runs on every read without a model.
It is the `body` of a `Recipe` record in `app/models.py`.

SHARED INTERFACE. The learner (app/agent), the executor (app/recipe) and the store all build
against this file. It changes only in a pull request of its own, approved by a person.

Shape. `nodes` and `edges` are flat lists that refer to node ids. A node is a page or an API
answer; an edge is one step from a node to the next. One node is the tender list: the executor
pages through it, reads one record per item, and for each item walks the edges marked
`per_item` (to its detail page, to its documents). A node's `kind` says what it is made of
(HTML, JSON, a browser state, a feed); its `role` says what it is for (the list, a tender's
page, its documents).

How DESIGN.md's closed sets map onto this file: "next page" is `Paging`, "for each item" is
`Edge.per_item`, "download" is the `Documents` rule of a node, and "a documents node" is a node
with the role documents. `custom_code` is not in v1 (DESIGN.md adds it only if the node kinds
cannot express half of the test set).

Written for OpenAI's strict structured output, so the learner can return it directly:
every field is required (one that may be absent is `X | None`), no object takes unknown keys,
there is no map with free keys (pairs are lists of `Pair`), and every choice is a closed enum.
Nothing here has a default value. Each field's description goes into the JSON schema, so the
model reads it. Rules that a JSON schema cannot say are checked by `problems`.

What is NOT in a recipe: the portal's time zone (`Portal.timezone`), its address, and anything
we measure rather than learn. Measured facts are in `Expectations`, written by the system.

URLs. A relative URL resolves against the address of the page it was found on; a request
template resolves against the portal's address. Templates may hold `{page}`, `{offset}`,
`{size}`, `{cursor}` (paging) and `{<field>}`, the raw value of a field of the current tender,
for example `{id}`.
"""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

try:  # Python's own parser of regular expressions, to look at a pattern's structure
    from re import _parser as _regex_parser
except ImportError:  # before Python 3.11 it had this name
    import sre_parse as _regex_parser

FORMAT = "recipe/v1"

PAGING_PLACEHOLDERS = frozenset({"page", "offset", "size", "cursor"})
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_POSITIONAL_XPATH = re.compile(r"\[\s*\d+\s*\]|position\(\)|last\(\)")
# The one position that is an anchor: `[n]` straight after the node test of a sibling step,
# as in `//dt[.='Angebotsfrist']/following-sibling::dd[1]`, "the value next to this label" (Q2).
_SIBLING_INDEX = re.compile(r"((?:following|preceding)-sibling::(?:\*|[A-Za-z_][\w.-]*))\[\s*\d+\s*\]")
# What every tender must have (the brief's required fields); `id` may also come from the address.
REQUIRED_FIELDS = ("id", "url", "title", "buyer_name", "publication_date", "submission_deadline")


class Part(BaseModel):
    """Base of every part of a recipe: no unknown keys, as strict output requires."""

    model_config = ConfigDict(extra="forbid")


# == Closed sets ==

class NodeKind(StrEnum):
    html = "html"                  # a server-rendered page
    json = "json"                  # a JSON API answer
    browser = "browser"            # a page that only exists after scripts ran or a control was used
    feed = "feed"                  # an Atom or RSS feed, read as XML
    platform_ref = "platform_ref"  # documents held on another platform: run that family's recipe there


class NodeRole(StrEnum):
    entry = "entry"          # where the portal's address leads, when that is not the list
    list = "list"            # the tender list: exactly one node
    detail = "detail"        # one tender's own page or API answer
    documents = "documents"  # one tender's files
    step = "step"            # a page passed through on the way (a search form, a terms page)


class Action(StrEnum):
    follow_link = "follow_link"  # GET the address a locator finds
    call_api = "call_api"        # send the edge's request (GET, or POST with a body)
    submit_form = "submit_form"  # send a form found on the page, hidden fields included


class LocatorKind(StrEnum):
    jsonpath = "jsonpath"  # `$.a.b`, `$.items[*]`, `$.a[0]`, `$.a[?(@.k=="v")].x`: this subset only
    css = "css"            # a CSS selector, relative to the item on a list
    xpath = "xpath"        # a relative XPath on ids, attributes or text; never absolute; `[n]` only after a sibling step
    label = "label"        # the value structurally next to a label text ("Angebotsfrist")
    regex = "regex"        # first group of a pattern over the page's or the item's text


class FieldName(StrEnum):
    """The values a recipe reads. They map one to one onto `TenderRecord`."""

    id = "id"
    url = "url"
    title = "title"
    buyer_name = "buyer_name"
    publication_date = "publication_date"
    submission_deadline = "submission_deadline"
    status = "status"
    reference_number = "reference_number"
    description = "description"
    procedure_type = "procedure_type"
    contract_nature = "contract_nature"
    cpv_codes = "cpv_codes"
    postal_code = "postal_code"
    city = "city"
    country_code = "country_code"


class ValueType(StrEnum):
    text = "text"            # as the portal states it, whitespace collapsed
    id = "id"                # text that must match the identity's shape
    url = "url"              # made absolute
    date = "date"            # a calendar date
    datetime = "datetime"    # date and time; the zone comes from the portal, never from the recipe
    cpv = "cpv"              # one or more 8-digit CPV codes, check digit dropped
    status = "status"        # the portal's words mapped to open, closed, withdrawn
    procedure = "procedure"  # mapped to open, restricted, negotiated, other
    nature = "nature"        # mapped to works, services, supplies
    country = "country"      # mapped to two letters
    postal_code = "postal_code"


class PagingKind(StrEnum):
    none = "none"                  # the list is one page
    next_link = "next_link"        # a link to the next page
    page_param = "page_param"      # a page number in the request
    offset_param = "offset_param"  # an offset in the request
    cursor = "cursor"              # the answer names the next cursor or the next address
    form_post = "form_post"        # the next page is a form post that carries hidden state
    load_more = "load_more"        # a button that loads more rows, in the browser


class BodyKind(StrEnum):
    none = "none"
    form = "form"  # `body` pairs sent as a form
    json = "json"  # `body` pairs sent as the members of a JSON object, or `body_json` as written


class Via(StrEnum):
    http = "http"        # the plain client
    browser = "browser"  # the headless browser


# == Parts ==

class Pair(Part):
    """One name and value. Lists of pairs stand in for maps, which strict output does not allow."""

    name: str
    value: str


class Locator(Part):
    """One way to find a value on a page, in an item of a list, or in a JSON answer."""

    kind: LocatorKind
    expr: str | None = Field(description="the JSONPath, CSS selector, XPath or regular expression; null for a label")
    labels: list[str] = Field(description="label texts to look for, any of them; empty unless kind is label")
    attr: str | None = Field(description="CSS and XPath: the attribute to read (href, data-id, datetime); null reads the text")


class ValueSpec(Part):
    """How the text a locator found becomes a value of the contract."""

    type: ValueType
    formats: list[str] = Field(description="date and datetime: strptime formats tried in order; empty means ISO 8601")
    words: list[Pair] = Field(description="status, procedure, nature, country: the portal's word and the contract's value")
    pattern: str | None = Field(description="a regular expression; its first group, or the whole match, is the value")


class FieldSpec(Part):
    """One value of a tender: where to find it (two or three ways) and how to read it."""

    name: FieldName
    locators: list[Locator] = Field(description="every one is tried on every read; when two find a value they must agree")
    value: ValueSpec


class Request(Part):
    """One HTTP request, as a template."""

    method: Literal["GET", "POST"]
    url: str = Field(description="may hold placeholders; relative to the portal's address")
    params: list[Pair] = Field(description="query parameters")
    body_kind: BodyKind
    body: list[Pair] = Field(description="form fields, or members of a JSON object")
    body_json: str | None = Field(description="a JSON body that pairs cannot express, as text with placeholders")
    headers: list[Pair]
    via: Via


class Paging(Part):
    """How the list continues. The executor also stops when a page brings no id it has not seen."""

    kind: PagingKind
    next: Locator | None = Field(description="next_link: the link; cursor: the next cursor or address; load_more: the button")
    param: str | None = Field(description="page_param, offset_param, cursor: the request parameter that carries it")
    first: int | None = Field(description="page_param: the number of the first page (0 or 1)")
    size_param: str | None = Field(description="the page-size parameter, when the portal has one")
    size: int | None = Field(description="the page size to ask for: the largest the portal accepts (Q12)")
    form: Locator | None = Field(description="form_post: the form to submit for the next page")
    max_pages: int | None = Field(description="a ceiling against a loop; null uses the setting")


class ListFacts(Part):
    """What the checks read on the list (Q10, Q12, Q13)."""

    total: Locator | None = Field(description="where the portal prints how many tenders it lists")
    total_counts_closed: bool | None = Field(description="whether that total includes tenders that are closed")
    empty_marker: Locator | None = Field(description="what the page shows when the list is empty, learned at attach")
    newest_first: bool | None = Field(description="the list is sorted newest first")
    has_all_required: bool = Field(description="the list alone carries every required field: no detail page needed")
    change_mark: Locator | None = Field(description="the portal's own \"last changed\" mark on an item")


class Documents(Part):
    """Where a tender's files are on a page, and how each one is fetched."""

    links: Locator = Field(description="one match per file: its address, or an id for `url`")
    url: str | None = Field(description="a template for the file's address when the link gives an id: `/download/{file}`")
    then: Locator | None = Field(description="the link leads to a page, not to the file: where the file's address is there")
    name: Locator | None = Field(description="the file's name, relative to the link")
    size: Locator | None = Field(description="the size the portal announces, relative to the link")
    all_in_one_zip: bool = Field(description="the link is one ZIP that holds every document of the tender")
    request: Request | None = Field(description="when a file is fetched by a POST instead of a GET of its address")


class BrowserStep(Part):
    """One thing to do in the browser before the page is read."""

    action: Literal["click", "fill", "select", "wait_for"]
    target: Locator
    value: str | None = Field(description="fill and select: what to enter")


class Node(Part):
    """A page, an API answer, or a tender's documents."""

    id: str
    kind: NodeKind
    role: NodeRole
    request: Request | None = Field(description="how to fetch it when no edge leads here (the first node), else null")
    items: Locator | None = Field(description="list: one match per tender; fields are then read inside each match")
    fields: list[FieldSpec] = Field(description="read once per item on the list, once per page elsewhere")
    paging: Paging | None = Field(description="list only")
    facts: ListFacts | None = Field(description="list only")
    documents: Documents | None = Field(description="the files this page lists; required when the role is documents")
    steps: list[BrowserStep] = Field(description="browser nodes: done in order before reading")
    family: str | None = Field(description="platform_ref only: the software family whose recipe reads the documents")


class Edge(Part):
    """One step from a node to the next."""

    source: str = Field(description="node id")
    target: str = Field(description="node id")
    action: Action
    per_item: bool = Field(description="true: taken once for each tender of the list (the brief's \"for each item\")")
    link: Locator | None = Field(description="follow_link: where the address is; submit_form: the form")
    request: Request | None = Field(description="call_api: the request; submit_form: fields to set on top of the form's own")


class Identity(Part):
    """Where a tender's id comes from. It is the portal's own identifier, never a position or a hash of ours."""

    from_url: str | None = Field(description="a regular expression with one group over the tender's address, or null")
    shape: str = Field(description="a regular expression every id of this portal matches, learned from examples")
    must_agree: bool = Field(description="the id shows both in the address and on the page: the two must be equal")


class HostSettings(Part):
    """What differs between two portals of one software family (Q11)."""

    language: str | None = Field(description="the language of the labels, two letters")
    settings: list[Pair] = Field(description="page size, fixed filters and the like")


class AuthoredRecipe(Part):
    """What the learner returns: everything a model writes, and nothing we measure."""

    start: str = Field(description="id of the node the portal's address leads to")
    nodes: list[Node]
    edges: list[Edge]
    identity: Identity
    family: str | None = Field(description="the portal software, e.g. \"cosinex-vmp\", when recognised (Q11)")
    host: HostSettings
    rationale: str = Field(description="two or three sentences on how the portal is read, for the dashboard")


class FieldExpectation(Part):
    """How often a field was filled in the reads that passed."""

    name: FieldName
    rows: int
    filled: int


class StructureProfile(Part):
    """The structure fingerprint of one kind of page, and how much this portal's pages vary (Q10, C7)."""

    node: str = Field(description="node id")
    paths: list[str] = Field(description="the sorted set of tag-and-class paths, or key paths for JSON")
    floor: float = Field(description="lowest overlap among the pages fetched at attach, minus the margin")


class Expectations(Part):
    """What we measured on this portal, written by the system after a read that passed. Never by the model."""

    fields: list[FieldExpectation]
    structures: list[StructureProfile]
    usual_signs: list[str] = Field(description="block signs the working pages always carry (a login box, a captcha product)")
    list_pages: int | None
    list_read_seconds: float | None


class RecipeBody(AuthoredRecipe):
    """The `body` of a `Recipe` record: the authored recipe, its format, and what we measured."""

    format: Literal["recipe/v1"]
    expectations: Expectations | None = Field(description="null until the first read has passed")

    @classmethod
    def from_authored(cls, authored: AuthoredRecipe) -> RecipeBody:
        """A learner's answer as a body ready to store, with nothing measured yet."""
        return cls(format=FORMAT, expectations=None, **authored.model_dump())


# == Rules a JSON schema cannot say ==

def _locator_problems(where: str, locator: Locator) -> list[str]:
    out: list[str] = []
    if locator.kind is LocatorKind.label:
        if not [label for label in locator.labels if label.strip()]:
            out.append(f"{where}: a label locator needs at least one label text.")
        return out
    expr = (locator.expr or "").strip()
    if not expr:
        return [f"{where}: a {locator.kind.value} locator needs `expr`."]
    if locator.labels:
        out.append(f"{where}: `labels` belongs to label locators only.")
    if locator.kind is LocatorKind.jsonpath and not expr.startswith(("$", "@")):
        out.append(f"{where}: a JSONPath starts with `$` (or `@` inside an item).")
    if locator.kind is LocatorKind.xpath:
        if expr.startswith("/") and not expr.startswith("//"):
            out.append(f"{where}: no absolute XPath. Anchor on an id, an attribute or a text.")
        if _POSITIONAL_XPATH.search(_SIBLING_INDEX.sub(r"\1", expr)):
            out.append(f"{where}: no positional XPath (`[2]`, `position()`, `last()`): a position is not an anchor. "
                       "Only `[n]` straight after `following-sibling::name` or `preceding-sibling::name` is allowed.")
    if locator.kind is LocatorKind.css and re.search(r":nth-(child|of-type)|:first-child|:last-child", expr):
        out.append(f"{where}: no position in a CSS selector (`nth-child` and the like).")
    if locator.kind is LocatorKind.regex:
        out.extend(_regex_problems(where, expr))
    return out


def _regex_problems(where: str, pattern: str) -> list[str]:
    try:
        re.compile(pattern)
    except re.error as error:
        return [f"{where}: not a valid regular expression ({error})."]
    if nested_quantifier(pattern):
        return [f"{where}: the pattern repeats without limit something that itself repeats without limit, as "
                "`(a+)+` does. Such a pattern can run for hours on one text. Give the inner or the outer repeat "
                "an upper bound, for example `(?:-\\d{1,9})+`, or write it without the group."]
    return []


def nested_quantifier(pattern: str) -> bool:
    """True when a repeat without an upper bound holds another one: `(a+)+`, `(\\d*)*`, `(?:x+|y)+`.

    The executor runs a recipe's patterns with Python's `re`, which has no timeout, and this
    shape is the common cause of a match that never ends. The test is a heuristic on the
    pattern's own structure, as Python parses it:

      * a repeat is without an upper bound when it is `*`, `+` or `{n,}`, greedy or lazy;
      * it is refused when anything inside what it repeats is such a repeat too, at any depth
        (in a group, a branch of `|`, a lookahead);
      * possessive repeats and atomic groups are left alone: they do not backtrack.

    It refuses some harmless patterns, such as `(?:\\d+\\.)+` (the dot keeps the repeats
    apart), and it lets pass slow ones without nesting, such as `a*a*a*b`. The first costs the
    learner one bounded rewrite; the second is bounded by the length of the text the executor
    hands a pattern, not here.
    """
    try:
        tree = _regex_parser.parse(pattern)
    except (re.error, RecursionError, OverflowError):
        return False  # not a pattern at all: `_regex_problems` says so
    return _nested(tree, inside=False)


def _nested(items, inside: bool) -> bool:
    """Whether a repeat without an upper bound is found while `inside` another one."""
    constants = _regex_parser
    for op, argument in items:
        if op in (constants.MAX_REPEAT, constants.MIN_REPEAT):
            _, most, repeated = argument
            unbounded = most == constants.MAXREPEAT
            if unbounded and inside:
                return True
            if _nested(repeated, inside or unbounded):
                return True
        elif op is constants.SUBPATTERN:
            if _nested(argument[-1], inside):
                return True
        elif op is constants.BRANCH:
            if any(_nested(branch, inside) for branch in argument[1]):
                return True
        elif op in (constants.ASSERT, constants.ASSERT_NOT):
            if _nested(argument[1], inside):
                return True
        elif op is constants.GROUPREF_EXISTS:
            if any(_nested(branch, inside) for branch in argument[1:] if branch is not None):
                return True
    return False


def _template_problems(where: str, template: str | None, allowed: frozenset[str]) -> list[str]:
    unknown = sorted(set(_PLACEHOLDER.findall(template or "")) - allowed)
    return [f"{where}: unknown placeholder {{{name}}}. Allowed: {', '.join(sorted(allowed))}."
            for name in unknown]


_VALUE_TYPES = {
    FieldName.id: {ValueType.id, ValueType.text},
    FieldName.url: {ValueType.url},
    FieldName.publication_date: {ValueType.date, ValueType.datetime},
    FieldName.submission_deadline: {ValueType.datetime, ValueType.date},
    FieldName.status: {ValueType.status},
    FieldName.procedure_type: {ValueType.procedure},
    FieldName.contract_nature: {ValueType.nature},
    FieldName.cpv_codes: {ValueType.cpv},
    FieldName.country_code: {ValueType.country},
    FieldName.postal_code: {ValueType.postal_code, ValueType.text},
}
_WORD_VALUES = {
    ValueType.status: {"open", "closed", "withdrawn"},
    ValueType.procedure: {"open", "restricted", "negotiated", "other"},
    ValueType.nature: {"works", "services", "supplies"},
}
_PAGING_NEEDS = {
    PagingKind.next_link: ("next",), PagingKind.page_param: ("param", "first"),
    PagingKind.offset_param: ("param",), PagingKind.cursor: ("next",),
    PagingKind.form_post: ("form",), PagingKind.load_more: ("next",),
}


def _request_problems(where: str, request: Request, allowed: frozenset[str], *,
                      need_url: bool = True) -> list[str]:
    out = [] if request.url.strip() or not need_url else [f"{where}: the request needs a url."]
    out += _template_problems(f"{where}.url", request.url, allowed)
    for pair in [*request.params, *request.body, *request.headers]:
        out += _template_problems(f"{where}.{pair.name}", pair.value, allowed)
    out += _template_problems(f"{where}.body_json", request.body_json, allowed)
    if request.body_kind is BodyKind.none and (request.body or request.body_json):
        out.append(f"{where}: a body is given but `body_kind` is none.")
    if request.method == "GET" and request.body_kind is not BodyKind.none:
        out.append(f"{where}: a GET request has no body.")
    return out


def problems(recipe: AuthoredRecipe) -> list[str]:
    """Everything wrong with a recipe that its JSON schema cannot express, one sentence each.

    An empty list means the executor can run it. The sentences go back to the learner as they
    are when its answer is refused, so each one says what to change.
    """
    out: list[str] = []
    ids = [node.id for node in recipe.nodes]
    known = set(ids)
    for node_id in sorted({i for i in ids if ids.count(i) > 1}):
        out.append(f"Node id {node_id!r} is used more than once.")
    if recipe.start not in known:
        out.append(f"`start` names {recipe.start!r}, which is not a node.")
    lists = [node for node in recipe.nodes if node.role is NodeRole.list]
    if len(lists) != 1:
        out.append(f"A recipe has exactly one node with the role list; this one has {len(lists)}.")
    out += _regex_problems("identity.shape", recipe.identity.shape)
    if recipe.identity.from_url is not None:
        out += _regex_problems("identity.from_url", recipe.identity.from_url)
        if not _regex_problems("", recipe.identity.from_url) and re.compile(recipe.identity.from_url).groups != 1:
            out.append("identity.from_url: the pattern needs exactly one group, which is the id.")

    field_names = frozenset(name.value for name in FieldName)
    for node in recipe.nodes:
        where = f"node {node.id}"
        is_list = node.role is NodeRole.list
        if is_list:
            if node.items is None:
                out.append(f"{where}: the list node needs `items`, the locator of one tender.")
            if node.facts is None:
                out.append(f"{where}: the list node needs `facts`.")
            if recipe.identity.from_url is None and not any(f.name is FieldName.id for f in node.fields):
                out.append(f"{where}: the list reads no id field and `identity.from_url` is null, "
                           "so a tender has no id.")
        elif node.paging is not None or node.facts is not None or node.items is not None:
            out.append(f"{where}: `items`, `paging` and `facts` belong to the list node only.")
        if node.role is NodeRole.documents and node.documents is None:
            out.append(f"{where}: a node with the role documents needs `documents`.")
        if (node.kind is NodeKind.platform_ref) != (node.family is not None):
            out.append(f"{where}: `family` is set on platform_ref nodes, and only there.")
        if node.steps and node.kind is not NodeKind.browser:
            out.append(f"{where}: `steps` belong to browser nodes only.")
        if node.id == recipe.start and node.request is None:
            out.append(f"{where}: the start node needs a `request`.")
        allowed = (field_names | PAGING_PLACEHOLDERS) if is_list else field_names
        if node.request is not None:
            out += _request_problems(f"{where}.request", node.request, allowed)
        for locator, name in ((node.items, "items"),):
            if locator is not None:
                out += _locator_problems(f"{where}.{name}", locator)
        seen: set[FieldName] = set()
        for field in node.fields:
            at = f"{where}.{field.name.value}"
            if field.name in seen:
                out.append(f"{at}: the field is listed twice on this node.")
            seen.add(field.name)
            if not 1 <= len(field.locators) <= 3:
                out.append(f"{at}: a field has one to three locators, this one has {len(field.locators)}.")
            for number, locator in enumerate(field.locators, 1):
                out += _locator_problems(f"{at} locator {number}", locator)
            wanted = _VALUE_TYPES.get(field.name)
            if wanted is not None and field.value.type not in wanted:
                out.append(f"{at}: its value type is one of {', '.join(sorted(t.value for t in wanted))}, "
                           f"not {field.value.type.value}.")
            if field.value.pattern is not None:
                out += _regex_problems(f"{at}.pattern", field.value.pattern)
            targets = _WORD_VALUES.get(field.value.type)
            if targets is not None:
                if not field.value.words:
                    out.append(f"{at}: a {field.value.type.value} needs `words`: the portal's words and what "
                               f"each means ({', '.join(sorted(targets))}).")
                for pair in field.value.words:
                    if pair.value not in targets:
                        out.append(f"{at}: {pair.name!r} maps to {pair.value!r}, which is not one of "
                                   f"{', '.join(sorted(targets))}.")
        if node.paging is not None:
            if node.paging.kind is PagingKind.load_more and node.kind is not NodeKind.browser:
                out.append(f"{where}.paging: load_more paging presses a button, which only a browser node can do; "
                           f"this node is {node.kind.value}.")
            for need in _PAGING_NEEDS.get(node.paging.kind, ()):
                if getattr(node.paging, need) is None:
                    out.append(f"{where}.paging: {node.paging.kind.value} paging needs `{need}`.")
            for locator in (node.paging.next, node.paging.form):
                if locator is not None:
                    out += _locator_problems(f"{where}.paging", locator)
        if node.facts is not None:
            for locator, name in ((node.facts.total, "total"), (node.facts.empty_marker, "empty_marker"),
                                  (node.facts.change_mark, "change_mark")):
                if locator is not None:
                    out += _locator_problems(f"{where}.facts.{name}", locator)
        if node.documents is not None:
            out += _locator_problems(f"{where}.documents.links", node.documents.links)
            for locator, name in ((node.documents.then, "then"), (node.documents.name, "name"),
                                  (node.documents.size, "size")):
                if locator is not None:
                    out += _locator_problems(f"{where}.documents.{name}", locator)
            out += _template_problems(f"{where}.documents.url", node.documents.url, field_names | {"file"})
            if node.documents.request is not None:
                out += _request_problems(f"{where}.documents.request", node.documents.request,
                                         field_names | {"file"})

    for number, edge in enumerate(recipe.edges, 1):
        where = f"edge {number} ({edge.source} to {edge.target})"
        for end in (edge.source, edge.target):
            if end not in known:
                out.append(f"{where}: {end!r} is not a node.")
        if edge.action in (Action.follow_link, Action.submit_form) and edge.link is None:
            out.append(f"{where}: {edge.action.value} needs `link`.")
        if edge.action is Action.call_api and edge.request is None:
            out.append(f"{where}: call_api needs `request`.")
        if edge.link is not None:
            out += _locator_problems(f"{where}.link", edge.link)
        if edge.request is not None:
            # A submitted form goes to the form's own address; the request only adds fields.
            out += _request_problems(f"{where}.request", edge.request, field_names,
                                     need_url=edge.action is not Action.submit_form)

    out += _required_field_problems(recipe, lists)

    # Every node must be reachable from the start, or it is never read.
    reached, frontier = {recipe.start}, [recipe.start]
    while frontier:
        here = frontier.pop()
        for edge in recipe.edges:
            if edge.source == here and edge.target not in reached:
                reached.add(edge.target)
                frontier.append(edge.target)
    for node_id in sorted(known - reached):
        out.append(f"Node {node_id!r} cannot be reached from the start node.")
    return out


def _required_field_problems(recipe: AuthoredRecipe, lists: list[Node]) -> list[str]:
    """Each required field is read by some node, and by the list when it says it carries them all.

    `id` may come from the address instead (`identity.from_url`). A recipe that never reads a
    required field would deliver null for it on every tender, on every read.
    """
    out: list[str] = []
    from_address = {"id"} if recipe.identity.from_url is not None else set()
    read_somewhere = {field.name.value for node in recipe.nodes for field in node.fields} | from_address
    for name in REQUIRED_FIELDS:
        if name == "id" and lists:
            continue  # the list node's own rule already says that a tender has no id
        if name not in read_somewhere:
            out.append(f"No node reads the required field `{name}`: every tender would be delivered without it. "
                       "Add it to the list node or to the tender's own page.")
    for node in lists:
        if node.facts is None or not node.facts.has_all_required:
            continue
        on_list = {field.name.value for field in node.fields} | from_address
        for name in REQUIRED_FIELDS:
            if name in read_somewhere and name not in on_list:
                out.append(f"node {node.id}: `has_all_required` is true, but the list does not read `{name}`. "
                           "Add the field to the list, or set `has_all_required` to false.")
    return out


def validate(recipe: AuthoredRecipe) -> None:
    """Raise ValueError with every problem when the executor cannot run this recipe."""
    found = problems(recipe)
    if found:
        raise ValueError("The recipe cannot be run:\n- " + "\n- ".join(found))
