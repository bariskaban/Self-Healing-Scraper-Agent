"""Locators: find the raw text a `Locator` points at, on a page, in one item of a list, or in JSON (Q2).

Pure functions. No network, no model call, and no parsing of values: a date stays the text the
portal printed; turning it into a value is `app/extract/`'s job.

    doc = parse_page(body, NodeKind.html, url, content_type)
    for item in find_items(node.items, doc):
        text = first_text(locator, item)

The kinds:
- css and xpath run relative to the scope. Inside an item, an XPath that starts with `//` stays
  inside the item. `attr` reads that attribute; without it the element's text is read.
- label finds an element whose own text is one of the labels (any case, trailing colon ignored)
  and reads only the value structurally next to it: the next cell of the row, the `dd` after the
  `dt`, the rest of a "Label: value" line, or the next sibling element (research/q02, Decision rule).
- regex runs over the scope's text: the first group, or the whole match.
- jsonpath supports `$`, `@`, `.name`, `['name']`, `[n]`, `[*]`, `..name` and the filters
  `[?(@.key=="value")]` and `[?(@.key)]`. Anything else finds nothing.

Text is cleaned the same way everywhere (`clean`): NFKC, non-breaking spaces to spaces, runs of
whitespace to one space, stripped. A match whose text is empty is not a match.
"""
from __future__ import annotations

import codecs
import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import cssselect
from lxml import etree
from lxml import html as lxml_html

from app.recipe.schema import Locator, LocatorKind, NodeKind

__all__ = ["Doc", "Found", "PageError", "clean", "find", "find_items", "first_text", "parse_page", "try_locator"]


class PageError(ValueError):
    """The body cannot be read as what it is said to be (JSON that does not parse)."""


@dataclass(frozen=True)
class Doc:
    """One parsed page."""

    kind: NodeKind  # html, browser (both parsed as HTML), json, feed (XML)
    url: str
    root: Any       # the lxml element, or the decoded JSON value
    text: str       # the page's visible text (HTML), or its JSON text, for regex locators


@dataclass(frozen=True)
class Found:
    """What one locator match read, and where: `node` can be the scope of a further `find`."""

    text: str  # an attribute's value, or the text content, whitespace collapsed; for JSON a scalar as text
    node: Any  # the element or JSON value it came from
    doc: Doc | None = field(default=None, compare=False, repr=False)  # the page, so `$` reaches its root


# == Text ==

_WHITESPACE = re.compile(r"\s+")
_NOT_TEXT = frozenset({"script", "style"})
_INLINE = frozenset({
    "a", "abbr", "acronym", "b", "bdi", "bdo", "big", "button", "cite", "code", "data", "del", "dfn", "em",
    "font", "i", "img", "input", "ins", "kbd", "label", "mark", "nobr", "q", "s", "samp", "select", "small",
    "span", "strike", "strong", "sub", "sup", "time", "tt", "u", "var", "wbr",
})


def clean(text: str | None) -> str:
    """NFKC, non-breaking spaces to spaces, whitespace runs to one space, stripped."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).replace(" ", " ")
    return _WHITESPACE.sub(" ", text).strip()


def _is_element(node: Any) -> bool:
    return isinstance(node, etree._Element) and isinstance(node.tag, str)


def _is_block(element: Any) -> bool:
    return element.tag not in _INLINE


def _raw_text(element: Any) -> str:
    """The text content, with a line break where a block element or `<br>` separates text."""
    parts: list[str] = []

    def visit(el: Any) -> None:
        if el.text:
            parts.append(el.text)
        for child in el:
            if _is_element(child) and child.tag not in _NOT_TEXT:
                block = child.tag == "br" or _is_block(child)
                if block:
                    parts.append("\n")
                visit(child)
                if block:
                    parts.append("\n")
            if child.tail:
                parts.append(child.tail)

    if _is_element(element) and element.tag not in _NOT_TEXT:
        visit(element)
    return "".join(parts)


def _element_text(element: Any) -> str:
    return clean(_raw_text(element))


# == Parsing ==

_CHARSET = re.compile(r"""charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)
_META_CHARSET = re.compile(rb"""<meta[^>]*?charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)
_XML_DECLARATION = re.compile(r"^\s*<\?xml[^>]*\?>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# What browsers do: a page that says Latin-1 is read as Windows-1252 (WHATWG Encoding).
_ENCODING_ALIASES = {"iso-8859-1": "cp1252", "latin-1": "cp1252", "latin1": "cp1252", "l1": "cp1252",
                     "us-ascii": "cp1252", "ascii": "cp1252", "iso8859-1": "cp1252"}


def _codec(name: str | bytes | None) -> str | None:
    if not name:
        return None
    if isinstance(name, bytes):
        name = name.decode("ascii", "ignore")
    name = name.strip().lower()
    name = _ENCODING_ALIASES.get(name, name)
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def _decode(body: bytes | str, content_type: str | None, sniff_meta: bool) -> str:
    if isinstance(body, str):
        return body
    for bom, encoding in ((codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"),
                          (codecs.BOM_UTF16_BE, "utf-16-be")):
        if body.startswith(bom):
            return body[len(bom):].decode(encoding, "replace")
    match = _CHARSET.search(content_type or "")
    encoding = _codec(match.group(1)) if match else None
    if encoding is None and sniff_meta:
        meta = _META_CHARSET.search(body[:4096])
        encoding = _codec(meta.group(1)) if meta else None
    return body.decode(encoding or "utf-8", "replace")


def _parse_html(text: str) -> Any:
    text = _CONTROL.sub("", _XML_DECLARATION.sub("", text, count=1))
    try:
        return lxml_html.document_fromstring(text)
    except (etree.ParserError, etree.XMLSyntaxError, ValueError):
        return lxml_html.document_fromstring("<html><body></body></html>")


def _strip_namespaces(root: Any) -> None:
    for element in root.iter():
        if not _is_element(element):
            continue
        if element.tag.startswith("{"):
            element.tag = etree.QName(element).localname
        for name in [n for n in element.attrib if n.startswith("{")]:
            value = element.attrib.pop(name)
            element.attrib.setdefault(etree.QName(name).localname, value)
    etree.cleanup_namespaces(root)


def _parse_feed(body: bytes | str) -> Any:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
                             huge_tree=False, recover=True)
    if isinstance(body, str):
        body = _XML_DECLARATION.sub("", body, count=1).lstrip()
    try:
        root = etree.fromstring(body, parser)
    except (etree.XMLSyntaxError, ValueError) as error:
        raise PageError(f"the feed is not XML: {error}") from error
    if root is None:
        raise PageError("the feed is not XML: nothing could be parsed")
    _strip_namespaces(root)
    return root


def parse_page(body: bytes | str, kind: NodeKind, url: str, content_type: str | None = None) -> Doc:
    """Parse a fetched body as the node kind says. Raises PageError when JSON or XML cannot be read.

    HTML never raises: bytes are decoded by the charset in `content_type`, else the page's own
    meta charset, else UTF-8 with replacement, and broken markup is repaired by lxml.
    """
    kind = NodeKind(kind)
    if kind in (NodeKind.html, NodeKind.browser):
        root = _parse_html(_decode(body, content_type, sniff_meta=True))
        body_element = root.find("body")
        text = _element_text(body_element if body_element is not None else root)
        return Doc(kind=kind, url=url, root=root, text=text)
    if kind is NodeKind.feed:
        root = _parse_feed(body)
        return Doc(kind=kind, url=url, root=root, text=_element_text(root))
    if kind is NodeKind.json:
        body = _decode(body, content_type, sniff_meta=False)
        try:
            value = json.loads(body)
        except (ValueError, RecursionError) as error:
            raise PageError(f"the answer is not JSON: {error}") from error
        return Doc(kind=kind, url=url, root=value, text=body)
    raise PageError(f"a {kind.value} node has no page of its own to parse")


# == Finding ==

def _scope(scope: Doc | Found) -> tuple[Any, str, Doc | None, bool]:
    """(node, text, doc, is_item)."""
    if isinstance(scope, Doc):
        return scope.root, scope.text, scope, False
    return scope.node, scope.text, scope.doc, True


def find(locator: Locator, scope: Doc | Found) -> list[Found]:
    """Every match of the locator in the scope, in document order; [] when none or when it cannot run."""
    node, text, doc, is_item = _scope(scope)
    kind = locator.kind
    if kind is LocatorKind.regex:
        return _find_regex(locator.expr or "", text, node, doc)
    if kind is LocatorKind.jsonpath:
        if isinstance(node, etree._Element):
            return []
        root = doc.root if doc is not None else node
        return [_json_found(value, doc) for value in _jsonpath(locator.expr or "", root, node)
                if _json_text(value)]
    if not _is_element(node):
        return []
    if kind is LocatorKind.label:
        return _find_label(locator.labels, node, doc)
    if kind is LocatorKind.css:
        results = _run_xpath(_css_to_xpath(locator.expr or "", isinstance(node, lxml_html.HtmlElement)), node)
    else:
        expr = locator.expr or ""
        results = _run_xpath(_relative_xpath(expr) if is_item else expr, node)
    return [found for found in (_read(result, locator.attr, node, doc) for result in results) if found is not None]


def find_items(locator: Locator, doc: Doc) -> list[Found]:
    """One match per tender of a list, each usable as the scope of `find`. Items with no text count too."""
    node = doc.root
    if locator.kind is LocatorKind.jsonpath:
        if _is_element(node):
            return []
        return [_json_found(value, doc) for value in _jsonpath(locator.expr or "", node, node) if value is not None]
    if locator.kind in (LocatorKind.css, LocatorKind.xpath) and _is_element(node):
        if locator.kind is LocatorKind.css:
            results = _run_xpath(_css_to_xpath(locator.expr or "", isinstance(node, lxml_html.HtmlElement)), node)
        else:
            results = _run_xpath(locator.expr or "", node)
        return [Found(text=_element_text(r), node=r, doc=doc) for r in results if _is_element(r)]
    return find(locator, doc)


def first_text(locator: Locator, scope: Doc | Found) -> str | None:
    """The text of the first match, or None."""
    matches = find(locator, scope)
    return matches[0].text if matches else None


def try_locator(locator: Locator, doc: Doc, *, items: Locator | None = None, limit: int = 5) -> list[str]:
    """For the learning agent: the texts a locator finds.

    With `items`, the texts found inside each of the first `limit` items, in order. Without, the
    first `limit` texts found on the page.
    """
    if items is None:
        return [found.text for found in find(locator, doc)][:limit]
    return [found.text for item in find_items(items, doc)[:limit] for found in find(locator, item)]


# == CSS and XPath ==

@lru_cache(maxsize=1024)
def _css_to_xpath(selector: str, html: bool) -> str | None:
    translator = cssselect.HTMLTranslator() if html else cssselect.GenericTranslator()
    try:
        return translator.css_to_xpath(selector, prefix="descendant-or-self::")
    except (cssselect.SelectorError, ValueError, TypeError):
        return None


def _relative_xpath(expr: str) -> str:
    """Make a `//` that starts a path relative to the context node, so it cannot leave an item."""
    out: list[str] = []
    quote: str | None = None
    starts_path = True  # at the start, or after `|`, `(`, `[` or `,`
    i = 0
    while i < len(expr):
        char = expr[i]
        if quote:
            out.append(char)
            if char == quote:
                quote = None
            i += 1
            continue
        if starts_path and expr.startswith("//", i):
            out.append(".//")
            starts_path = False
            i += 2
            continue
        if char in "'\"":
            quote = char
            starts_path = False
        elif char in "|([,":
            starts_path = True
        elif not char.isspace():
            starts_path = False
        out.append(char)
        i += 1
    return "".join(out)


def _run_xpath(expr: str | None, node: Any) -> list[Any]:
    if not expr:
        return []
    try:
        result = node.xpath(expr)
    except (etree.XPathError, ValueError, TypeError, RecursionError):
        return []
    return result if isinstance(result, list) else [result]


def _read(result: Any, attr: str | None, scope_node: Any, doc: Doc | None) -> Found | None:
    if _is_element(result):
        raw = result.get(attr) if attr else None
        if attr and raw is None:
            return None
        text = clean(raw) if attr else _element_text(result)
        return Found(text=text, node=result, doc=doc) if text else None
    if isinstance(result, bool):
        return Found(text="true" if result else "false", node=scope_node, doc=doc)
    if isinstance(result, float):
        text = str(int(result)) if result.is_integer() else repr(result)
        return Found(text=text, node=scope_node, doc=doc)
    if isinstance(result, str):
        text = clean(result)
        parent = result.getparent() if hasattr(result, "getparent") else None
        return Found(text=text, node=parent if parent is not None else scope_node, doc=doc) if text else None
    return None  # comments, processing instructions


# == Regex ==

def _find_regex(pattern: str, text: str, node: Any, doc: Doc | None) -> list[Found]:
    try:
        compiled = re.compile(pattern)
    except (re.error, OverflowError, RecursionError):
        return []
    out: list[Found] = []
    for match in compiled.finditer(text or ""):
        value = clean(match.group(1) if compiled.groups else match.group(0))
        if value:
            out.append(Found(text=value, node=node, doc=doc))
    return out


# == Labels ==

# Elements that hold rows or cells; never a label themselves, so a lone cell stays the label.
_CONTAINERS = frozenset({"html", "body", "table", "thead", "tbody", "tfoot", "tr", "dl", "ul", "ol"})


def _label_key(text: str) -> str:
    return clean(text).rstrip(":").rstrip().casefold()


def _layout(owner: Any) -> tuple[list[str], dict[Any, tuple[int, int]]]:
    """The owner's own lines (block children excluded) and, per inline descendant, (line, start)."""
    lines = [""]
    spans: dict[Any, tuple[int, int]] = {}

    def add(text: str | None) -> None:
        if text:
            lines[-1] += text

    def visit(el: Any) -> None:
        add(el.text)
        for child in el:
            if not _is_element(child) or child.tag in _NOT_TEXT:
                pass
            elif child.tag == "br" or _is_block(child):
                lines.append("")
            else:
                spans[child] = (len(lines) - 1, len(lines[-1]))
                visit(child)
            add(child.tail)

    visit(owner)
    return lines, spans


def _next_element(element: Any) -> Any:
    sibling = element.getnext()
    while sibling is not None and (not _is_element(sibling) or sibling.tag in _NOT_TEXT):
        sibling = sibling.getnext()
    return sibling


def _owner(element: Any, top: Any) -> Any:
    parent = element.getparent()
    while parent is not None and parent is not top and not _is_block(parent):
        parent = parent.getparent()
    return parent if parent is not None else top


def _find_label(labels: list[str], top: Any, doc: Doc | None) -> list[Found]:
    wanted = {_label_key(label) for label in labels if clean(label)}
    if not wanted:
        return []
    line_patterns = [re.compile(re.escape(clean(label).rstrip(":").rstrip()) + r"\s*:\s*(\S.*)$", re.I)
                     for label in labels if clean(label)]
    elements = [el for el in top.iter() if _is_element(el)
                and not any(a.tag in _NOT_TEXT for a in [el, *el.iterancestors()])]
    order = {el: i for i, el in enumerate(elements)}
    texts = {el: _element_text(el) for el in elements}
    hits: dict[tuple[int, int], Found] = {}
    layouts: dict[Any, tuple[list[str], dict[Any, tuple[int, int]]]] = {}

    def layout(owner: Any) -> tuple[list[str], dict[Any, tuple[int, int]]]:
        if owner not in layouts:
            layouts[owner] = _layout(owner)
        return layouts[owner]

    def hit(key: tuple[int, int], value: str, node: Any) -> None:
        if value and key not in hits:
            hits[key] = Found(text=value, node=node, doc=doc)

    for el in elements:
        # "Label: value" in one line of one element.
        if el is top or _is_block(el):
            for number, line in enumerate(layout(el)[0]):
                line = clean(line)
                for pattern in line_patterns:
                    match = pattern.match(line)
                    if match:
                        hit((order[el], number), clean(match.group(1)), el)
                        break
        # An element that is the label, outermost if nested ones say the same.
        if _label_key(texts[el]) not in wanted or el is top or el.tag in _CONTAINERS:
            continue
        parent = el.getparent()
        if (parent is not None and parent is not top and parent in texts and parent.tag not in _CONTAINERS
                and _label_key(texts[parent]) == _label_key(texts[el])):
            continue
        if el.tag in ("td", "th"):
            cell = _next_element(el)
            if cell is not None and cell.tag == "td":
                hit((order[el], -1), texts.get(cell, _element_text(cell)), cell)
        elif el.tag == "dt":
            sibling = _next_element(el)
            while sibling is not None and sibling.tag == "dt":
                sibling = _next_element(sibling)
            if sibling is not None and sibling.tag == "dd":
                hit((order[el], -1), texts.get(sibling, _element_text(sibling)), sibling)
        elif clean(el.tail):
            continue  # text follows the label directly: only the "Label: value" line rule may read it
        elif _is_block(el):
            sibling = _next_element(el)
            if sibling is not None:
                hit((order[el], -1), texts.get(sibling, _element_text(sibling)), sibling)
        else:
            owner = _owner(el, top)
            lines, spans = layout(owner)
            line, start = spans.get(el, (0, 0))
            if clean(lines[line][:start]):
                continue  # the label is in the middle of a line: running text, not a label
            sibling = _next_element(el)
            if sibling is not None:
                hit((order.get(owner, -1), line), texts.get(sibling, _element_text(sibling)), sibling)
    return [hits[key] for key in sorted(hits)]


# == JSONPath ==

_JSON_NAME = re.compile(r"[^.\[\]\s()=!<>@'\"]+")
_INDEX = re.compile(r"\s*(-?\d+)\s*\]")
_FILTER = re.compile(r"""\s*@((?:\.[^.\s=!<>()'"]+)+)\s*(?:==\s*(.+?))?\s*$""")


class _Unsupported(Exception):
    pass


def _quoted(text: str, i: int) -> tuple[str, int]:
    """A quoted string starting at text[i]; returns it and the index after the closing quote."""
    quote, out, i = text[i], [], i + 1
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text):
            out.append(text[i + 1])
            i += 2
            continue
        if char == quote:
            return "".join(out), i + 1
        out.append(char)
        i += 1
    raise _Unsupported


def _literal(text: str) -> Any:
    text = text.strip()
    if text[:1] in ("'", '"'):
        value, end = _quoted(text, 0)
        if end != len(text):
            raise _Unsupported
        return value
    try:
        return json.loads(text)
    except ValueError as error:
        raise _Unsupported from error


@lru_cache(maxsize=1024)
def _compile_jsonpath(expr: str) -> tuple[str, tuple[tuple, ...]]:
    expr = expr.strip()
    if not expr or expr[0] not in "$@":
        raise _Unsupported
    steps: list[tuple] = []
    i = 1
    while i < len(expr):
        if expr.startswith("..", i):
            match = _JSON_NAME.match(expr, i + 2)
            if not match or match.group(0) == "*":
                raise _Unsupported
            steps.append(("deep", match.group(0)))
            i = match.end()
        elif expr[i] == ".":
            if expr.startswith("*", i + 1):
                steps.append(("all",))
                i += 2
                continue
            match = _JSON_NAME.match(expr, i + 1)
            if not match:
                raise _Unsupported
            steps.append(("key", match.group(0)))
            i = match.end()
        elif expr[i] == "[":
            rest = expr[i + 1:].lstrip()
            j = len(expr) - len(rest)
            if rest[:1] in ("'", '"'):
                name, end = _quoted(expr, j)
                close = expr.find("]", end)
                if close < 0 or expr[end:close].strip():
                    raise _Unsupported
                steps.append(("key", name))
                i = close + 1
            elif rest.startswith("*"):
                close = expr.find("]", j + 1)
                if close < 0 or expr[j + 1:close].strip():
                    raise _Unsupported
                steps.append(("all",))
                i = close + 1
            elif rest.startswith("?("):
                k, quote = j + 2, None
                while k < len(expr):  # find the `)]` that closes the filter, outside quotes
                    if quote:
                        if expr[k] == "\\":
                            k += 1
                        elif expr[k] == quote:
                            quote = None
                    elif expr[k] in "'\"":
                        quote = expr[k]
                    elif expr.startswith(")]", k):
                        break
                    k += 1
                else:
                    raise _Unsupported
                match = _FILTER.match(expr[j + 2:k])
                if not match:
                    raise _Unsupported
                keys = tuple(match.group(1).split(".")[1:])
                if match.group(2) is None:
                    steps.append(("has", keys))
                else:
                    steps.append(("equals", keys, json.dumps(_literal(match.group(2)))))
                i = k + 2
            else:
                match = _INDEX.match(expr, i + 1)
                if not match:
                    raise _Unsupported
                steps.append(("index", int(match.group(1))))
                i = match.end()
        else:
            raise _Unsupported
    return expr[0], tuple(steps)


def _descend(value: Any):
    """Every value under this one, itself first, in document order."""
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _descend(child)
    elif isinstance(value, list):
        for child in value:
            yield from _descend(child)


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    return a == b


def _lookup(value: Any, keys: tuple[str, ...]) -> tuple[bool, Any]:
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return False, None
        value = value[key]
    return True, value


def _step(step: tuple, values: list[Any]) -> list[Any]:
    out: list[Any] = []
    for value in values:
        kind = step[0]
        if kind == "key":
            if isinstance(value, dict) and step[1] in value:
                out.append(value[step[1]])
        elif kind == "index":
            if isinstance(value, list) and -len(value) <= step[1] < len(value):
                out.append(value[step[1]])
        elif kind == "all":
            if isinstance(value, list):
                out.extend(value)
            elif isinstance(value, dict):
                out.extend(value.values())
        elif kind == "deep":
            out.extend(d[step[1]] for d in _descend(value) if isinstance(d, dict) and step[1] in d)
        else:  # has, equals: filter the members of a list (or the values of an object)
            children = value if isinstance(value, list) else list(value.values()) if isinstance(value, dict) else []
            for child in children:
                present, member = _lookup(child, step[1])
                if kind == "has" and present and member is not None:
                    out.append(child)
                elif kind == "equals" and present and _same(member, json.loads(step[2])):
                    out.append(child)
    return out


def _jsonpath(expr: str, root: Any, current: Any) -> list[Any]:
    try:
        start, steps = _compile_jsonpath(expr)
    except (_Unsupported, ValueError, IndexError):
        return []
    values = [root if start == "$" else current]
    for step in steps:
        values = _step(step, values)
        if not values:
            break
    return values


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_found(value: Any, doc: Doc | None) -> Found:
    return Found(text=_json_text(value), node=value, doc=doc)
