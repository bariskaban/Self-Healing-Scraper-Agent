"""The test portals of `bench/portals.toml`, validated, for recording and end-to-end runs (Q8).

    from bench.portals import load_portals
    for p in load_portals(priority_max=1):   # Poland first; no unseen ones, only those with an address
        ...

Reading this file makes no request. Never fetch these portals from an agent session or a test
(CLAUDE.md): a person records them once with FETCH_MODE=record.
"""
from __future__ import annotations

import tomllib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    note: str = ""

    @field_validator("url")
    @classmethod
    def _absolute(cls, url: str | None) -> str | None:
        if url is not None and not url.startswith(("https://", "http://")):
            raise ValueError(f"not an absolute address: {url!r}")
        return url

    def model_post_init(self, _: object) -> None:
        if (self.url is None) != (self.address is None):
            raise ValueError(f"{self.id}: an address needs its `address` evidence, and only an address has one")


class Excluded(BaseModel):
    """A site that is not a test portal (an aggregator or a notice publisher), and why."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    reason: str


def read_file(path: Path = PORTALS_FILE) -> tuple[list[TestPortal], list[Excluded]]:
    """Every portal and every excluded site in the file, validated. Raises on a bad entry or a repeated id."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    portals = [TestPortal(**entry) for entry in data.get("portal", [])]
    seen: set[str] = set()
    for portal in portals:
        if portal.id in seen:
            raise ValueError(f"portal id {portal.id!r} is used twice")
        seen.add(portal.id)
    return portals, [Excluded(**entry) for entry in data.get("excluded", [])]


def load_portals(path: Path = PORTALS_FILE, *, include_unseen: bool = False, with_address: bool = True,
                 priority_max: int = 5, expect: Expect | None = None,
                 trusted_only: bool = False) -> list[TestPortal]:
    """The portals to run, in priority order.

    By default: no unseen portal (they are held back for the final test) and only those with an
    address. `trusted_only` keeps addresses someone opened or saw quoted (not examples, not doubtful).
    """
    portals, _ = read_file(path)
    trusted = {Address.fetched, Address.measured, Address.search, Address.survey}
    out = [p for p in portals
           if (include_unseen or not p.unseen)
           and (not with_address or p.url is not None)
           and p.priority <= priority_max
           and (expect is None or p.expect is expect)
           and (not trusted_only or p.address in trusted)]
    return sorted(out, key=lambda p: (p.priority, p.country, p.family, p.id))
