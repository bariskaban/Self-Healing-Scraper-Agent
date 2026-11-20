"""robots.txt, as RFC 9309 reads it, obeyed by default (the mentor's answer; Q10, Q3).

  * 2xx: parsed, and obeyed for every address of that origin.
  * 4xx: "unavailable": the portal set no rules, and everything may be fetched.
  * 5xx, or no answer: "unreachable": nothing may be fetched. The fetcher raises
    `RobotsUnavailable`, and the checks treat it as an outage, not as a block.

Rules are kept per portal and origin for at most 24 hours (RFC 9309, section 2.4).

The file is read by our own small matcher, not by `urllib.robotparser`: the standard library
takes the first rule that matches and knows neither `*` nor `$`, where RFC 9309 (section 2.2.2)
says the longest match wins, Allow wins a tie, and both special characters count.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

# RFC 9309, section 2.5: parse at least the first 500 KiB.
MAX_ROBOTS_BYTES = 500 * 1024


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def robots_url(url: str) -> str:
    return origin_of(url) + "/robots.txt"


@dataclass(frozen=True)
class Rule:
    """One Allow or Disallow line: a path pattern, where `*` is any text and a last `$` is the end."""

    allow: bool
    pattern: str


@dataclass(frozen=True)
class Group:
    """The user agents one block of the file names, lowercased, and the rules it gives them."""

    agents: tuple[str, ...]
    rules: tuple[Rule, ...]


@lru_cache(maxsize=1024)
def _matcher(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    parts = (pattern[:-1] if anchored else pattern).split("*")
    return re.compile(".*".join(re.escape(part) for part in parts) + ("$" if anchored else ""), re.DOTALL)


def product_token(agent: str) -> str:
    """The name a robots.txt addresses us by: "Watchtower/0.1 (...)" is "watchtower"."""
    return agent.split("/")[0].strip().lower()


def parse_groups(text: str) -> tuple[Group, ...]:
    """The groups of a robots.txt. Lines that are not User-agent, Allow or Disallow are passed over."""
    groups: list[tuple[list[str], list[Rule]]] = []
    naming = False  # the last line read was a User-agent line, so the next one names the same group
    for line in text.splitlines():
        key, colon, value = line.split("#", 1)[0].partition(":")
        key, value = key.strip().lower(), value.strip()
        if not colon:
            continue
        if key == "user-agent":
            if not naming:
                groups.append(([], []))
            groups[-1][0].append(product_token(value))
            naming = True
        elif key in ("allow", "disallow"):
            naming = False
            if groups and value:  # a rule before any User-agent belongs to nobody; an empty one matches nothing
                groups[-1][1].append(Rule(allow=key == "allow", pattern=value))
    return tuple(Group(tuple(agents), tuple(rules)) for agents, rules in groups)


@dataclass(frozen=True)
class RobotsRules:
    """The rules of one origin. `groups` None means no rules: everything is allowed."""

    origin: str
    fetched_at: float
    groups: tuple[Group, ...] | None = None

    @classmethod
    def parse(cls, origin: str, body: bytes, fetched_at: float) -> "RobotsRules":
        # utf-8-sig: a byte order mark must not hide the first User-agent line.
        text = body[:MAX_ROBOTS_BYTES].decode("utf-8-sig", errors="replace")
        return cls(origin=origin, fetched_at=fetched_at, groups=parse_groups(text))

    @classmethod
    def allow_all(cls, origin: str, fetched_at: float) -> "RobotsRules":
        return cls(origin=origin, fetched_at=fetched_at)

    def rules_for(self, agent: str) -> tuple[Rule, ...]:
        """The rules that apply to us: those of every group naming us, else those of the `*` groups."""
        if self.groups is None:
            return ()
        token = product_token(agent)
        ours = [g for g in self.groups if token in g.agents] or [g for g in self.groups if "*" in g.agents]
        return tuple(rule for group in ours for rule in group.rules)

    def allowed(self, url: str, agent: str) -> bool:
        parts = urlsplit(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        best: Rule | None = None
        for rule in self.rules_for(agent):
            if not _matcher(rule.pattern).match(target):
                continue
            longer = best is None or len(rule.pattern) > len(best.pattern)
            if longer or (len(rule.pattern) == len(best.pattern) and rule.allow):
                best = rule
        return best is None or best.allow

    def forbids_every_path(self, agent: str) -> bool:
        """True when the group that applies to us disallows "/" and allows nothing back."""
        rules = self.rules_for(agent)
        blocks_root = any(not rule.allow and rule.pattern.rstrip("*") in ("", "/") for rule in rules)
        return blocks_root and not any(rule.allow for rule in rules)
