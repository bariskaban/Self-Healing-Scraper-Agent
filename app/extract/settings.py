"""Settings for the normalisers: every value here is our own choice (CLAUDE.md, Source of truth)."""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields

DATE_ONLY_CHOICES = ("end_of_day", "null")


@dataclass(frozen=True)
class ExtractSettings:
    """Built with `from_env()`; each field can be overridden by EXTRACT_<NAME>."""

    # What a deadline shown as a date with no time becomes: the end of that day in the portal's
    # zone (DESIGN.md, "Where the brief is silent"; mentor answer 12), or "null".
    date_only_deadline: str = "end_of_day"
    # Years outside this range are refused: a two-digit year read by %Y ("26") or a typo.
    min_year: int = 2000
    max_year: int = 2100
    # The most characters of a text a recipe's regular expression is run over. Python's re has
    # no timeout, so a slow pattern on a very long text would hold a read up; longer text is cut.
    pattern_text_limit: int = 20_000

    def __post_init__(self) -> None:
        if self.date_only_deadline not in DATE_ONLY_CHOICES:
            raise ValueError(f"date_only_deadline must be one of {DATE_ONLY_CHOICES}")
        if not 1 <= self.min_year <= self.max_year <= 9999:
            raise ValueError("min_year and max_year must satisfy 1 <= min_year <= max_year <= 9999")
        if self.pattern_text_limit < 1:
            raise ValueError("pattern_text_limit must be at least 1")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ExtractSettings":
        """The defaults, overridden by EXTRACT_<NAME> environment variables (EXTRACT_MIN_YEAR=2010)."""
        env = os.environ if environ is None else environ
        kw: dict[str, object] = {}
        for f in fields(cls):
            raw = env.get(f"EXTRACT_{f.name.upper()}", "").strip()
            if raw:
                kw[f.name] = raw if f.name == "date_only_deadline" else int(raw)
        return cls(**kw)
