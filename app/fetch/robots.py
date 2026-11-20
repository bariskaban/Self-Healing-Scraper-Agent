"""robots.txt, as RFC 9309 reads it, obeyed by default (the mentor's answer; Q10, Q3).

  * 2xx: parsed, and obeyed for every address of that origin.
  * 4xx: "unavailable": the portal set no rules, and everything may be fetched.
  * 5xx, or no answer: "unreachable": nothing may be fetched. The fetcher raises
    `RobotsUnavailable`, and the checks treat it as an outage, not as a block.

Rules are kept per portal and origin for at most 24 hours (RFC 9309, section 2.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

# RFC 9309, section 2.5: parse at least the first 500 KiB.
MAX_ROBOTS_BYTES = 500 * 1024


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def robots_url(url: str) -> str:
    return origin_of(url) + "/robots.txt"


@dataclass(frozen=True)
class RobotsRules:
    """The rules of one origin. `parser` None means no rules: everything is allowed."""

    origin: str
    fetched_at: float
    parser: RobotFileParser | None = None

    @classmethod
    def parse(cls, origin: str, body: bytes, fetched_at: float) -> "RobotsRules":
        parser = RobotFileParser()
        parser.parse(body[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace").splitlines())
        return cls(origin=origin, fetched_at=fetched_at, parser=parser)

    @classmethod
    def allow_all(cls, origin: str, fetched_at: float) -> "RobotsRules":
        return cls(origin=origin, fetched_at=fetched_at)

    def allowed(self, url: str, agent: str) -> bool:
        return self.parser is None or self.parser.can_fetch(agent, url)

    def forbids_every_path(self, agent: str) -> bool:
        """True when the group that applies to us disallows "/" and allows nothing back."""
        if self.parser is None:
            return False
        entry = next((e for e in self.parser.entries if e.applies_to(agent)), self.parser.default_entry)
        if entry is None:
            return False
        lines = entry.rulelines
        blocks_root = any(not line.allowance and line.path in ("/", "") for line in lines)
        allows_some = any(line.allowance and line.path not in ("",) for line in lines)
        return blocks_root and not allows_some
