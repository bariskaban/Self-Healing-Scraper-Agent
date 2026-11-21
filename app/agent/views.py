"""What the model sees of a page (Q4, measured in research/q04-page-views-measured.md).

  * `html_view`: trimmed HTML. Scripts, styles, SVG and comments go; `id`, `class`, `href`,
    `src`, `name`, `role`, `aria-label` and every `data-*` attribute stay, because recipes are
    written against them. Long runs of alike rows are cut to three, with a line that says how
    many were left out; `all_rows` shows them all (a cut on a detail page once removed the
    deadline, so the cut is taken only where the rows look like list rows).
  * `json_view`: the answer with its arrays cut to three items and a count.
  * `links_view`: a page's links grouped by the pattern of their address.
  * `search`: where a pattern occurs in the raw body, for addresses inside scripts and app state.

No request is made here, and nothing here is used to read a value: recipes read pages through
`app/recipe/locate.py`.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any
from urllib.parse import urljoin, urlsplit

from lxml import etree, html as lxml_html

from app.agent.settings import DEFAULT_AGENT_SETTINGS, AgentSettings

_DROPPED = frozenset({"script", "style", "svg", "noscript", "template", "iframe", "canvas", "path", "picture",
                      "source", "video", "audio", "object", "embed"})
# The hooks a recipe is written against (DESIGN.md, "What the model sees"), and what a form,
# a time and a feed link need to be understood.
_KEPT = frozenset({"id", "class", "href", "src", "name", "role", "aria-label", "action", "method", "type",
                   "value", "datetime", "rel", "for", "title", "content", "property", "lang", "colspan"})
_HEAD_KEPT = frozenset({"title", "meta", "link", "base"})
_VOID = frozenset({"br", "hr", "img", "input", "meta", "link", "base", "col", "wbr", "area"})
_SPACE = re.compile(r"\s+")
_NUMBER_PART = re.compile(r"\d+")
_LONG_TOKEN = re.compile(r"^[0-9a-fA-F-]{16,}$")


def _cut(text: str, limit: int) -> str:
    text = _SPACE.sub(" ", text).strip()
    return text if len(text) <= limit else text[:limit] + f"…[{len(text)} chars]"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _signature(element: Any) -> tuple[str, str]:
    return element.tag, " ".join(sorted((element.get("class") or "").split()))


def _has_hook(element: Any) -> bool:
    """A row of a list carries a link or a data-* hook; a label-and-value row usually carries neither."""
    for node in element.iter():
        if not isinstance(node.tag, str):
            continue
        if node.tag == "a" and node.get("href"):
            return True
        if any(name.startswith("data-") for name in node.attrib):
            return True
    return False


def _hidden_rows(parent: Any, settings: AgentSettings) -> dict[Any, int]:
    """Children to leave out, as {the last child shown of a run: how many alike rows follow it}."""
    children = [child for child in parent if isinstance(child.tag, str)]
    groups: dict[tuple[str, str], list[Any]] = {}
    for child in children:
        groups.setdefault(_signature(child), []).append(child)
    out: dict[Any, int] = {}
    for rows in groups.values():
        if len(rows) < settings.view_rows_min:
            continue
        if sum(1 for row in rows if _has_hook(row)) * 2 < len(rows):
            continue
        shown = rows[: settings.view_rows_shown]
        out[shown[-1]] = len(rows) - len(shown)
        for row in rows[len(shown):]:
            out[row] = -1  # hidden
    return out


def _render(element: Any, settings: AgentSettings, all_rows: bool, out: list[str], in_head: bool = False) -> None:
    tag = element.tag
    if not isinstance(tag, str) or tag in _DROPPED:
        return
    if in_head and tag not in _HEAD_KEPT:
        return
    if tag == "meta" and not (element.get("name") or element.get("property")):
        return
    if tag == "link" and "alternate" not in (element.get("rel") or "") and "next" not in (element.get("rel") or ""):
        return
    attrs = "".join(
        f' {name}="{_escape(_cut(value, settings.view_attr_chars))}"'
        for name, value in element.attrib.items()
        if isinstance(name, str) and (name in _KEPT or name.startswith("data-")) and value.strip())
    if tag in _VOID:
        out.append(f"<{tag}{attrs}>")
        return
    out.append(f"<{tag}{attrs}>")
    if element.text and element.text.strip():
        out.append(_escape(_cut(element.text, settings.view_text_chars)))
    hidden = {} if all_rows else _hidden_rows(element, settings)
    for child in element:
        if hidden.get(child) == -1:
            continue
        _render(child, settings, all_rows, out, in_head=in_head or tag == "head")
        left_out = hidden.get(child, 0)
        if left_out > 0 and isinstance(child.tag, str):
            css_class = "." + ".".join(child.get("class").split()) if child.get("class") else ""
            out.append(f"<!-- {left_out} more {child.tag}{css_class} rows like these are not shown -->")
        if child.tail and child.tail.strip():
            out.append(_escape(_cut(child.tail, settings.view_text_chars)))
    out.append(f"</{tag}>")


def html_view(body: str, *, all_rows: bool = False, settings: AgentSettings = DEFAULT_AGENT_SETTINGS) -> str:
    """The page as trimmed HTML, on one line per element run."""
    try:
        root = lxml_html.document_fromstring(body) if body.strip() else None
    except (etree.ParserError, ValueError):
        root = None
    if root is None:
        return _cut(body, settings.view_chars)
    out: list[str] = []
    _render(root, settings, all_rows, out)
    text = "".join(out)
    # A line break after each closing block keeps the view readable and cheap to page.
    return re.sub(r"(</(?:tr|li|div|p|section|article|table|ul|ol|dl|dd|form|h[1-6]|nav|header|footer|main|head|thead|tbody)>)",
                  r"\1\n", text)


def title_of(body: str) -> str | None:
    found = re.search(r"<title[^>]*>(.*?)</title>", body[:20_000], re.IGNORECASE | re.DOTALL)
    return _cut(found.group(1), 200) if found else None


def _short_json(value: Any, settings: AgentSettings) -> Any:
    if isinstance(value, dict):
        return {key: _short_json(item, settings) for key, item in value.items()}
    if isinstance(value, list):
        shown = [_short_json(item, settings) for item in value[: settings.view_json_items]]
        if len(value) > len(shown):
            shown.append(f"… {len(value) - len(shown)} more item(s); {len(value)} in all")
        return shown
    if isinstance(value, str) and len(value) > settings.view_json_string_chars:
        return value[: settings.view_json_string_chars] + f"…[{len(value)} chars]"
    return value


def json_view(body: str, *, settings: AgentSettings = DEFAULT_AGENT_SETTINGS) -> str | None:
    """A JSON answer with arrays cut short, or None when the body is not JSON."""
    try:
        value = json.loads(body)
    except (ValueError, RecursionError):
        return None
    return json.dumps(_short_json(value, settings), ensure_ascii=False, indent=1)


def looks_like_json(body: str, content_type: str | None) -> bool:
    if content_type and "json" in content_type.lower():
        return True
    return body.lstrip()[:1] in ("{", "[")


def looks_like_html(body: str, content_type: str | None) -> bool:
    if content_type and "html" in content_type.lower():
        return True
    head = body.lstrip()[:400].lower()
    return head.startswith("<!doctype html") or "<html" in head


def part_of(text: str, part: int, settings: AgentSettings = DEFAULT_AGENT_SETTINGS) -> tuple[str, int]:
    """Part `part` (from 1) of a view, cut at a line break where one is near, and how many parts there are."""
    size = settings.view_chars
    parts: list[str] = []
    rest = text
    while len(rest) > size:
        at = rest.rfind("\n", int(size * 0.6), size)
        at = size if at < 0 else at + 1
        parts.append(rest[:at])
        rest = rest[at:]
    parts.append(rest)
    index = min(max(part, 1), len(parts))
    return parts[index - 1], len(parts)


def _pattern(address: str) -> str:
    parts = urlsplit(address)
    segments = []
    for segment in parts.path.split("/"):
        if _LONG_TOKEN.match(segment):
            segments.append("{id}")
        else:
            segments.append(_NUMBER_PART.sub("{n}", segment))
    query = "&".join(sorted(f"{pair.split('=')[0]}=…" for pair in parts.query.split("&") if pair))
    return f"{parts.netloc}{'/'.join(segments)}" + (f"?{query}" if query else "")


def links_view(body: str, page_url: str, *, contains: str | None = None,
               settings: AgentSettings = DEFAULT_AGENT_SETTINGS) -> str:
    """The page's links and forms, grouped by the pattern of their address, with one sample each."""
    try:
        root = lxml_html.document_fromstring(body)
    except (etree.ParserError, ValueError):
        return "The page has no HTML to take links from."
    groups: dict[str, list[tuple[str, str]]] = {}
    counts: Counter[str] = Counter()
    for element in root.iter("a", "link", "form", "area"):
        raw = element.get("action") if element.tag == "form" else element.get("href")
        if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        address = urljoin(page_url, raw.strip())
        if contains and contains.lower() not in address.lower():
            continue
        kind = {"form": f"form {(element.get('method') or 'get').upper()} ",
                "link": f"<link rel={element.get('rel') or ''}> "}.get(element.tag, "")
        key = kind + _pattern(address)
        counts[key] += 1
        text = _cut(element.text_content() if element.tag == "a" else (element.get("title") or ""), 80)
        groups.setdefault(key, []).append((address, text))
    if not groups:
        return "No links" + (f" whose address contains {contains!r}." if contains else " on this page.")
    lines = []
    for key, count in counts.most_common(settings.links_groups):
        address, text = groups[key][0]
        lines.append(f"{count} x {key}\n    e.g. {address}" + (f"  “{text}”" if text else ""))
    more = len(counts) - settings.links_groups
    if more > 0:
        lines.append(f"… and {more} more group(s); narrow with `contains`.")
    return "\n".join(lines)


def search(body: str, pattern: str, *, settings: AgentSettings = DEFAULT_AGENT_SETTINGS) -> str:
    """Where a regular expression matches in the raw body, each with some text around it."""
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        return f"Not a valid regular expression: {error}."
    around = settings.search_context_chars
    lines = []
    total = 0
    for found in compiled.finditer(body[:500_000]):
        total += 1
        if len(lines) < settings.search_matches:
            start, end = max(found.start() - around, 0), min(found.end() + around, len(body))
            lines.append(f"at {found.start()}: …{_SPACE.sub(' ', body[start:end])}…")
        if total >= 1000:
            break
    if not lines:
        return "No match."
    head = f"{total} match(es)" + (f", the first {len(lines)} shown" if total > len(lines) else "") + ":"
    return head + "\n" + "\n".join(lines)


_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


def sitemap_addresses(body: bytes, settings: AgentSettings = DEFAULT_AGENT_SETTINGS) -> tuple[list[str], bool]:
    """The addresses a sitemap file names (a part of it, when it is large), and whether it is an
    index of further sitemaps. A gzipped file is unpacked; anything that is no sitemap gives none."""
    import gzip
    import zlib

    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.GzipFile(fileobj=__import__("io").BytesIO(body)).read(settings.hints_sitemap_bytes)
        except (OSError, EOFError, zlib.error):
            return [], False
    text = body[: settings.hints_sitemap_bytes].decode("utf-8", errors="replace")
    found = [place.replace("&amp;", "&") for place in _LOC.findall(text)]
    return found[: settings.hints_addresses], "<sitemapindex" in text[:2000].lower()


def addresses_view(addresses: list[str], settings: AgentSettings = DEFAULT_AGENT_SETTINGS) -> str:
    """Addresses grouped by their pattern, the largest groups first, each with a few samples."""
    groups: dict[str, list[str]] = {}
    for address in addresses:
        groups.setdefault(_pattern(address), []).append(address)
    ranked = sorted(groups.items(), key=lambda item: -len(item[1]))
    lines = [f"{len(found)} x {pattern}\n    e.g. " + "  ".join(found[: settings.hints_samples])
             for pattern, found in ranked[: settings.links_groups]]
    if len(ranked) > settings.links_groups:
        lines.append(f"… and {len(ranked) - settings.links_groups} more group(s).")
    return "\n".join(lines)
