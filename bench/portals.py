"""The test portals of `bench/portals.toml`, validated, for recording and end-to-end runs (Q8).

    from bench.portals import load_portals
    for p in load_portals(priority_max=1):   # Poland first; no unseen ones, only those with an address
        ...

Reading this file makes no request. Never fetch these portals from an agent session or a test
(CLAUDE.md): a person records them once with FETCH_MODE=record.

`bench/` is repo-only on purpose: it is not a package of the installed project (`pyproject.toml`)
and is not copied into the image (`Dockerfile`), so the list of live addresses never ships with the
app. Run it from the repo root (`python -m ...`, or pytest, which puts the root on the path).
"""
from __future__ import annotations

import re
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit  # parsing only: nothing here opens an address

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.models import url_key

PORTALS_FILE = Path(__file__).with_name("portals.toml")


class Kind(StrEnum):
    server_html = "server_html"
    json_api = "json_api"
    js_app = "js_app"
    mixed = "mixed"
    unknown = "unknown"


class Expect(StrEnum):
    serve = "serve"              # should reach serving
    fail_login = "fail_login"    # should end failed: a login stands in the way
    unavailable = "unavailable"  # down or suspended when last checked: a control


class Address(StrEnum):
    fetched = "fetched"    # opened by our research on 20 Nov 2026
    other_page = "other_page"  # our research opened another page of this portal, not this one
    measured = "measured"  # measured in research/q04-page-views-measured.md
    search = "search"      # seen only in a search result or a TED notice quoting it
    survey = "survey"      # opened once in a browser by the portal survey
    example = "example"    # a buyer subdomain nobody has confirmed
    doubtful = "doubtful"  # evidence points to another address


class TestPortal(BaseModel):
    """One portal to test against."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    __test__ = False  # not a pytest test class, despite its name

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    country: str = Field(pattern=r"^[A-Z]{2}$", description="two letters; EU for a platform across countries")
    family: str
    url: str | None = None
    kind: Kind
    expect: Expect
    unseen: bool = False
    priority: int = Field(ge=1, le=5)
    buyer_sites: int | None = Field(None, ge=1)
    address: Address | None = None
    robots_disallow_all: bool = False
    note: str = ""

    @field_validator("url")
    @classmethod
    def _absolute(cls, url: str | None) -> str | None:
        if url is None:
            return url
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"not an absolute address: {url!r}")
        if any(c.isspace() for c in url):
            raise ValueError(f"an address has no white space: {url!r}")
        parts = urlsplit(url)
        if not parts.hostname or "." not in parts.hostname:
            raise ValueError(f"not an absolute address, no host name: {url!r}")
        if parts.username is not None or parts.password is not None:
            raise ValueError("an address must not carry a user name or password")
        if parts.fragment:
            raise ValueError(f"an address has no #fragment (it is never sent): {url!r}")
        # A session id or a key in the file would be one person's, and it rots.
        names = [k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)]
        names += [seg.partition("=")[0].lower() for seg in parts.path.split(";")[1:]]
        secret = sorted(n for n in names if _SECRET_PARAM.search(n))
        if secret or "@" in parts.path or "@" in parts.query:
            raise ValueError(f"an address must not carry a session id, key or e-mail address: {secret or '@'}")
        return url

    def model_post_init(self, _: object) -> None:
        if (self.url is None) != (self.address is None):
            raise ValueError(f"{self.id}: an address needs its `address` evidence, and only an address has one")


# Names of address parameters that carry a session or a secret, whatever the portal software.
_SECRET_PARAM = re.compile(r"(^|[_.-])(jsessionid|phpsessid|sessionid|session|sid|token|access_token|auth|apikey|"
                           r"api_key|key|password|passwd|pwd|secret|signature|sig|email|e-mail)$")
# A host name inside the free text of an excluded entry, such as "TED (ted.europa.eu)".
_HOST_IN_TEXT = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b")


class Excluded(BaseModel):
    """A site that is not a test portal (an aggregator or a notice publisher), and why."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    reason: str


def _entries(data: dict[str, Any], table: str, path: Path) -> list[dict[str, Any]]:
    entries = data.get(table, [])
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise ValueError(f"{path}: `{table}` must be written as [[{table}]] tables")
    return entries


def _label(table: str, number: int, entry: dict[str, Any]) -> str:
    name = entry.get("id", entry.get("name"))
    return f"[[{table}]] entry {number}" + (f" ({name!r})" if isinstance(name, str) else "")


def read_file(path: Path = PORTALS_FILE) -> tuple[list[TestPortal], list[Excluded]]:
    """Every portal and every excluded site in the file, validated.

    Raises ValueError, naming the file and the entry, on: TOML that does not parse, a top-level
    table other than `portal` and `excluded` (a misspelt one would otherwise be read as an empty
    list), no portal at all, a bad entry, an id used twice, one address listed twice
    (`app.models.url_key`), or a test portal on the host of an excluded site.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: not valid TOML: {error}") from error
    unknown = sorted(set(data) - {"portal", "excluded"})
    if unknown:
        raise ValueError(f"{path}: unknown top-level tables {unknown}; only [[portal]] and [[excluded]] are read")

    portals: list[TestPortal] = []
    ids: dict[str, str] = {}
    addresses: dict[str, str] = {}
    for number, entry in enumerate(_entries(data, "portal", path), start=1):
        label = _label("portal", number, entry)
        try:
            portal = TestPortal(**entry)
        except (ValidationError, ValueError, TypeError) as error:
            raise ValueError(f"{path}: {label}: {error}") from error
        if portal.id in ids:
            raise ValueError(f"{path}: {label}: portal id {portal.id!r} is used twice (also {ids[portal.id]})")
        ids[portal.id] = label
        if portal.url is not None:
            key = url_key(portal.url)
            if key in addresses:
                raise ValueError(f"{path}: {label}: the address {portal.url!r} is listed twice (also {addresses[key]})")
            addresses[key] = label
        portals.append(portal)
    if not portals:
        raise ValueError(f"{path}: no [[portal]] entry")

    excluded: list[Excluded] = []
    for number, entry in enumerate(_entries(data, "excluded", path), start=1):
        try:
            excluded.append(Excluded(**entry))
        except (ValidationError, TypeError) as error:
            raise ValueError(f"{path}: {_label('excluded', number, entry)}: {error}") from error
    barred = {host: site.name for site in excluded for host in _HOST_IN_TEXT.findall(site.name.lower())}
    for portal in portals:
        host = (urlsplit(portal.url).hostname or "").lower() if portal.url else ""
        for domain, name in barred.items():
            if host == domain or host.endswith("." + domain):
                raise ValueError(f"{path}: portal {portal.id!r} is on {domain}, which the file excludes ({name!r})")
    return portals, excluded


GUESSED = frozenset({Address.example, Address.doubtful})  # addresses nobody has seen in use


def load_portals(path: Path = PORTALS_FILE, *, include_unseen: bool = False, with_address: bool = True,
                 priority_max: int = 5, expect: Expect | None = None,
                 include_guessed: bool = False, include_robots_forbidden: bool = False) -> list[TestPortal]:
    """The portals to run, in priority order.

    By default: no unseen portal (they are held back for the final test) and only those with an
    address, and no guessed address (`example`, `doubtful`): check those in a browser first, then
    pass `include_guessed=True` or update their `address`.
    A portal whose robots.txt forbids every path (`robots_disallow_all`) is left out unless
    `include_robots_forbidden`: the mentor wants robots.txt obeyed, so recording it is a decision.
    """
    portals, _ = read_file(path)
    out = [p for p in portals
           if (include_unseen or not p.unseen)
           and (not with_address or p.url is not None)
           and (include_robots_forbidden or not p.robots_disallow_all)
           and p.priority <= priority_max
           and (expect is None or p.expect is expect)
           and (include_guessed or p.address not in GUESSED)]
    return sorted(out, key=lambda p: (p.priority, p.country, p.family, p.id))
