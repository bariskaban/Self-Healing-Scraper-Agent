"""C7 (Q10): the structure fingerprint of a page.

The fingerprint is the set of distinct tag-and-class paths of an HTML page, or the
set of key paths of a JSON answer. Text, row positions and numeric ids are left
out, so more or fewer tenders never look like a change. An equal hash means
unchanged; otherwise the overlap of the two sets is held against a floor measured
on this portal at attach. The rule only ever asks for a spot check.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Sequence
from html.parser import HTMLParser
from itertools import combinations
from typing import Any

from app.models import CheckResult, Severity

from .result import passed, wants_spot_check
from .settings import DEFAULT_SETTINGS, CheckSettings
from .words import share

_DIGITS = re.compile(r"\d+")
# Class names that only say where a row stands in its list.
_POSITION_CLASSES = frozenset({"odd", "even", "first", "last", "alt"})
_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
# An opening tag ends these still-open tags, searched up to the nearest boundary tag.
# Without this, a list written without end tags would nest deeper with every row.
_ENDS = {
    "li": (("li",), ("ul", "ol", "menu")),
    "dt": (("dt", "dd"), ("dl",)),
    "dd": (("dt", "dd"), ("dl",)),
    "tr": (("tr", "td", "th"), ("table",)),
    "td": (("td", "th"), ("tr", "table")),
    "th": (("td", "th"), ("tr", "table")),
    "thead": (("thead", "tbody", "tfoot", "tr", "td", "th"), ("table",)),
    "tbody": (("thead", "tbody", "tfoot", "tr", "td", "th"), ("table",)),
    "tfoot": (("thead", "tbody", "tfoot", "tr", "td", "th"), ("table",)),
    "option": (("option",), ("select", "datalist")),
}


class _Paths(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open: list[tuple[str, str]] = []  # (tag, tag with its classes)
        self.paths: set[str] = set()

    def _close_through(self, depth: int) -> None:
        del self.open[depth:]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "p" and self.open and self.open[-1][0] == "p":
            self.open.pop()
        ends, boundaries = _ENDS.get(tag, ((), ()))
        cut = None
        for depth in range(len(self.open) - 1, -1, -1):
            if self.open[depth][0] in boundaries:
                break
            if self.open[depth][0] in ends:
                cut = depth  # keep looking: a new row ends the open cell and the open row
        if cut is not None:
            self._close_through(cut)
        classes = next((value or "" for name, value in attrs if name == "class"), "")
        names = sorted({_DIGITS.sub("#", name) for name in classes.split()} - _POSITION_CLASSES)
        label = ".".join([tag, *names])
        self.paths.add("/".join([*(label for _, label in self.open), label]))
        if tag not in _VOID:
            self.open.append((tag, label))

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self.open) - 1, -1, -1):
            if self.open[depth][0] == tag:
                self._close_through(depth)
                return


def html_paths(html: str) -> frozenset[str]:
    """The distinct tag-and-class paths of an HTML page, without text, positions or numeric ids."""
    parser = _Paths()
    parser.feed(html)
    parser.close()
    return frozenset(parser.paths)


def json_paths(data: Any) -> frozenset[str]:
    """The distinct key paths of a JSON answer; list positions and all-digit keys are left out."""
    paths: set[str] = set()

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                name = "#" if str(key).isdigit() else str(key)
                below = f"{path}.{name}" if path else name
                paths.add(below)
                walk(value, below)
        elif isinstance(node, list):
            below = f"{path}[]"
            paths.add(below)
            for item in node:
                walk(item, below)

    walk(data, "")
    return frozenset(paths)


def fingerprint(paths: Collection[str]) -> str:
    """The hash of a path set: equal hashes mean the structure is unchanged."""
    return hashlib.sha256("\n".join(sorted(set(paths))).encode()).hexdigest()


def overlap(a: Collection[str], b: Collection[str]) -> float:
    """Share of paths two pages have in common, of all paths either has (1.0 for the same set)."""
    first, second = set(a), set(b)
    union = first | second
    return len(first & second) / len(union) if union else 1.0


def structure_floor(pages: Sequence[Collection[str]], settings: CheckSettings = DEFAULT_SETTINGS) -> float:
    """This portal's floor: the lowest overlap among the pages fetched at attach, minus the margin."""
    lowest = min((overlap(a, b) for a, b in combinations(pages, 2)), default=1.0)
    return max(0.0, lowest - settings.structure_floor_margin)


def structure(run_id: str, paths: Collection[str], stored: Collection[str], *, floor: float,
              page: str = "list") -> CheckResult:
    """C7 `structure`: the page's structure against the stored one; a change asks for a spot check."""
    name = "structure" if page == "list" else f"structure.{page}"
    now_hash, stored_hash = fingerprint(paths), fingerprint(stored)
    seen: dict[str, Any] = {"page": page, "hash": now_hash, "stored_hash": stored_hash}
    if now_hash == stored_hash:
        return passed(run_id, name, f"The {page} page's structure is unchanged.", severity=Severity.warn,
                      observed={**seen, "overlap": 1.0}, expected={"floor": floor})
    shared = overlap(paths, stored)
    seen["overlap"] = round(shared, 4)
    if shared >= floor:
        return passed(run_id, name, f"The {page} page's structure differs a little: it shares {share(shared)} "
                      f"of its paths with the stored one, and this portal's floor is {share(floor)}.",
                      severity=Severity.warn, observed=seen, expected={"floor": floor})
    return wants_spot_check(run_id, name, f"The {page} page's structure changed: it shares {share(shared)} of "
                            f"its paths with the stored one, and this portal's floor is {share(floor)}.",
                            observed=seen, expected={"floor": floor})
