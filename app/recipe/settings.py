"""Settings of the recipe executor. Built with `RecipeSettings.from_env()`.

Every number here is our own choice, so it is a setting and not a constant in the logic
(CLAUDE.md). Each field can be overridden by RECIPE_<NAME>.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class RecipeSettings:
    # The ceiling on list pages when the recipe's paging names none: a guard against a loop.
    max_pages: int = 500
    # The page size asked for when a request holds `{size}` and the recipe names none.
    default_page_size: int = 100
    # A value only one of several locators found is kept on a tender we cannot compare it on
    # when, among the tenders of this read that we can compare, at least this share of such
    # values equals the last good value (Q2, audit point 1 and 2).
    single_witness_vouch_share: float = 0.8
    # How many pages one tender's edges may fetch (detail, documents, a terms page per file).
    max_requests_per_tender: int = 40
    # How many problems a dry run reports before it only counts them.
    max_problems: int = 50

    def __post_init__(self) -> None:
        if self.max_pages < 1 or self.default_page_size < 1 or self.max_requests_per_tender < 1:
            raise ValueError("max_pages, default_page_size and max_requests_per_tender must be at least 1")
        if not 0 < self.single_witness_vouch_share <= 1:
            raise ValueError("single_witness_vouch_share must be above 0 and at most 1")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RecipeSettings":
        env = os.environ if environ is None else environ
        kw = {}
        for f in fields(cls):
            raw = env.get(f"RECIPE_{f.name.upper()}")
            if raw:
                kw[f.name] = float(raw) if f.type in ("float", float) else int(raw)
        return cls(**kw)


DEFAULT_RECIPE_SETTINGS = RecipeSettings()
