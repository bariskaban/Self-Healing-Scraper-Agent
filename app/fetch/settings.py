"""Settings for the network layer (Q4, Q10). Built with `FetchSettings.from_env()`.

The retry and slow-down numbers of rules T1 and T2 are not here: they live in
`app.checks.CheckSettings`, beside the checks that count them, and the fetch layer reads
them from there. What is here is what only the network layer uses.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import Any


class FetchMode(StrEnum):
    """Where answers come from (CONVENTIONS.md, rule 11)."""

    live = "live"      # the real portal: only in the container and in bench/, run by a person
    record = "record"  # the real portal, and every exchange is written to the recordings
    replay = "replay"  # the recordings only; nothing leaves the machine


_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class FetchSettings:
    """Everything the network layer needs to know."""

    # Replay unless told otherwise, so code run by an agent or a test never reaches a live
    # portal by accident (CLAUDE.md). The Dockerfile sets FETCH_MODE=live.
    mode: FetchMode = FetchMode.replay
    recordings_dir: Path = Path("tests/fixtures/recordings")
    # The brief: at most 1 request per second per portal. The mentor: it counts request starts.
    requests_per_second: float = 1.0
    # Ours. Each hop is its own request and waits for its own slot.
    max_redirects: int = 10
    # CONVENTIONS.md, rule 8.
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 30.0
    # Ours: how much of a page is looked at for block signs (password field, bot walls).
    sniff_bytes: int = 65536
    # The mentor: obey robots.txt by default; a switch ignores it for a test.
    ignore_robots_txt: bool = False
    # RFC 9309: a robots.txt should not be used from cache for more than 24 hours.
    robots_cache_seconds: float = 86400.0
    user_agent: str = "Watchtower/0.1 (public tender monitoring)"

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", FetchMode(self.mode))
        object.__setattr__(self, "recordings_dir", Path(self.recordings_dir))
        for name in ("requests_per_second", "connect_timeout_seconds", "read_timeout_seconds",
                     "robots_cache_seconds"):
            if not getattr(self, name) > 0:
                raise ValueError(f"fetch setting {name} must be positive")
        if self.max_redirects < 0 or self.sniff_bytes < 1:
            raise ValueError("max_redirects must not be negative and sniff_bytes must be positive")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "FetchSettings":
        """FETCH_MODE, FETCH_RECORDINGS_DIR, FETCH_<NAME> for the numbers, IGNORE_ROBOTS_TXT."""
        env = os.environ if environ is None else environ
        kw: dict[str, Any] = {}
        if env.get("FETCH_MODE"):
            kw["mode"] = FetchMode(env["FETCH_MODE"].strip().lower())
        if env.get("FETCH_RECORDINGS_DIR"):
            kw["recordings_dir"] = Path(env["FETCH_RECORDINGS_DIR"])
        if env.get("IGNORE_ROBOTS_TXT"):
            kw["ignore_robots_txt"] = env["IGNORE_ROBOTS_TXT"].strip().lower() in _TRUE
        if env.get("FETCH_USER_AGENT"):
            kw["user_agent"] = env["FETCH_USER_AGENT"]
        for f in fields(cls):
            raw = env.get(f"FETCH_{f.name.upper()}")
            if raw and f.name not in ("mode", "recordings_dir", "user_agent", "ignore_robots_txt"):
                kw[f.name] = int(raw) if f.type in ("int", int) else float(raw)
        return cls(**kw)


DEFAULT_FETCH_SETTINGS = FetchSettings()
