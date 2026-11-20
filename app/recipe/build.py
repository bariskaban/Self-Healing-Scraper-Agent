"""Short ways to write the parts of a recipe by hand, for tests and the mock portal's recipes.

The schema has no default values, because strict output allows none. These helpers fill the
parts that are usually empty, so a hand-written recipe stays readable. The learner does not
use them: it returns the whole `AuthoredRecipe`.
"""
from __future__ import annotations

from app.recipe.schema import (
    Action, BodyKind, Documents, Edge, FieldName, FieldSpec, HostSettings, Identity, ListFacts, Locator,
    LocatorKind, Node, NodeKind, NodeRole, Pair, Paging, PagingKind, Request, ValueSpec, ValueType, Via,
)


def css(expr: str, attr: str | None = None) -> Locator:
    """A CSS selector; `attr` reads an attribute instead of the text."""
    return Locator(kind=LocatorKind.css, expr=expr, labels=[], attr=attr)


def xpath(expr: str, attr: str | None = None) -> Locator:
    """A relative XPath."""
    return Locator(kind=LocatorKind.xpath, expr=expr, labels=[], attr=attr)


def jsonpath(expr: str) -> Locator:
    """A JSONPath of the supported subset."""
    return Locator(kind=LocatorKind.jsonpath, expr=expr, labels=[], attr=None)


def label(*labels: str) -> Locator:
    """The value structurally next to any of these label texts."""
    return Locator(kind=LocatorKind.label, expr=None, labels=list(labels), attr=None)


def regex(expr: str) -> Locator:
    """The first group of a pattern over the text."""
    return Locator(kind=LocatorKind.regex, expr=expr, labels=[], attr=None)


def pairs(**values: str) -> list[Pair]:
    """Keyword arguments as a list of pairs."""
    return [Pair(name=name, value=value) for name, value in values.items()]


def value(type: ValueType = ValueType.text, *, formats: list[str] | None = None,
          words: dict[str, str] | None = None, pattern: str | None = None) -> ValueSpec:
    """A value spec; `words` maps the portal's words to the contract's values."""
    return ValueSpec(type=type, formats=formats or [], pattern=pattern,
                     words=[Pair(name=name, value=meaning) for name, meaning in (words or {}).items()])


def field(name: FieldName, *locators: Locator, type: ValueType = ValueType.text, formats: list[str] | None = None,
          words: dict[str, str] | None = None, pattern: str | None = None) -> FieldSpec:
    """One field with its locators and value spec."""
    return FieldSpec(name=name, locators=list(locators),
                     value=value(type, formats=formats, words=words, pattern=pattern))


def get(url: str, *, via: Via = Via.http, **params: str) -> Request:
    """A GET request."""
    return Request(method="GET", url=url, params=pairs(**params), body_kind=BodyKind.none, body=[],
                   body_json=None, headers=[], via=via)


def post(url: str, *, form: dict[str, str] | None = None, json: dict[str, str] | None = None,
         body_json: str | None = None, via: Via = Via.http) -> Request:
    """A POST request with a form, with JSON members, or with a JSON text."""
    kind = BodyKind.form if form is not None else BodyKind.json if (json is not None or body_json) else BodyKind.none
    return Request(method="POST", url=url, params=[], body_kind=kind, body=pairs(**(form or json or {})),
                   body_json=body_json, headers=[], via=via)


def paging(kind: PagingKind = PagingKind.none, *, next: Locator | None = None, param: str | None = None,
           first: int | None = None, size_param: str | None = None, size: int | None = None,
           form: Locator | None = None, max_pages: int | None = None) -> Paging:
    """How the list continues."""
    return Paging(kind=kind, next=next, param=param, first=first, size_param=size_param, size=size,
                  form=form, max_pages=max_pages)


def facts(*, total: Locator | None = None, total_counts_closed: bool | None = None,
          empty_marker: Locator | None = None, newest_first: bool | None = None,
          has_all_required: bool = False, change_mark: Locator | None = None) -> ListFacts:
    """What the checks read on the list."""
    return ListFacts(total=total, total_counts_closed=total_counts_closed, empty_marker=empty_marker,
                     newest_first=newest_first, has_all_required=has_all_required, change_mark=change_mark)


def documents(links: Locator, *, url: str | None = None, then: Locator | None = None, name: Locator | None = None,
              size: Locator | None = None, all_in_one_zip: bool = False,
              request: Request | None = None) -> Documents:
    """Where a tender's files are on a page."""
    return Documents(links=links, url=url, then=then, name=name, size=size, all_in_one_zip=all_in_one_zip,
                     request=request)


def node(id: str, role: NodeRole, kind: NodeKind = NodeKind.html, *, request: Request | None = None,
         items: Locator | None = None, fields: list[FieldSpec] | None = None, paging: Paging | None = None,
         facts: ListFacts | None = None, documents: Documents | None = None, family: str | None = None) -> Node:
    """A node."""
    return Node(id=id, kind=kind, role=role, request=request, items=items, fields=fields or [], paging=paging,
                facts=facts, documents=documents, steps=[], family=family)


def follow(source: str, target: str, link: Locator, *, per_item: bool = True) -> Edge:
    """Follow a link from one node to the next."""
    return Edge(source=source, target=target, action=Action.follow_link, per_item=per_item, link=link, request=None)


def call(source: str, target: str, request: Request, *, per_item: bool = True) -> Edge:
    """Call an API to get from one node to the next."""
    return Edge(source=source, target=target, action=Action.call_api, per_item=per_item, link=None, request=request)


def submit(source: str, target: str, form: Locator, *, request: Request | None = None,
           per_item: bool = True) -> Edge:
    """Submit a form found on the source node."""
    return Edge(source=source, target=target, action=Action.submit_form, per_item=per_item, link=form,
                request=request)


def identity(shape: str, *, from_url: str | None = None, must_agree: bool = False) -> Identity:
    """Where the id comes from."""
    return Identity(from_url=from_url, shape=shape, must_agree=must_agree)


def host(language: str | None = None, **settings: str) -> HostSettings:
    """What differs between portals of one family."""
    return HostSettings(language=language, settings=pairs(**settings))
