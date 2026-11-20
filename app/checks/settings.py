"""Settings for the checks and the state machine (Q10, Q14).

Every number the research marks as our own choice lives here, with the default the
research gives. The logic in `app/checks/` and `app/state.py` reads this object and
holds no threshold of its own.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field


class CheckSettings(BaseModel):
    """One object for every threshold, rate and budget the checks use."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # The level every exact test uses (Q10: Lerman's 0.001, Soda's 0.999).
    significance: float = Field(0.001, gt=0, lt=1, description="A result this rare or rarer is an alarm")

    # C4: known open tenders that left the list.
    removal_rate_per_read: float = Field(
        0.05, gt=0, lt=1, description="Chance per read that an open tender leaves the list before its deadline")
    removal_gap_days: float = Field(
        1.0, gt=0, description="Up to this gap since the last good read the per-read rate is used as it is")
    removal_lifetime_share: float = Field(
        0.25, gt=0, lt=1, description="Share of tenders removed before their deadline, used after a longer gap")
    removal_open_days: float = Field(
        15.0, gt=0, description="Days a tender is open, over which that share is spread")
    detail_looks_max: int = Field(5, ge=1, description="Detail pages looked at for missing tenders, per read")

    # C3: the same tender read twice.
    lost_value_rate: float = Field(
        0.01, gt=0, lt=1, description="Chance per read that a required value truly disappears from a tender")
    changed_value_rate: float = Field(
        0.02, gt=0, lt=1, description="Chance per read that a value of a tender truly changes")

    # C6: the canary.
    canary_detail_pages: int = Field(2, ge=0, description="Known detail pages fetched again on every read")
    canary_files: int = Field(1, ge=0, description="Known files fetched again on every read")

    # C7: structure.
    structure_floor_margin: float = Field(
        0.1, ge=0, le=1, description="Subtracted from the lowest overlap measured at attach")

    # D1: files.
    all_files_failed_min: int = Field(2, ge=1, description="From this many files on, 'every file failed' is an alarm")

    # F1: age.
    stale_after_intervals: int = Field(3, ge=1, description="Read intervals without a passing read before `healing`")

    # T1 and T2: requests. The fetch layer acts on these; the checks only count tries.
    request_tries: int = Field(3, ge=1, description="Tries per request inside one read")
    retry_pause_base_seconds: float = Field(2.0, gt=0, description="First pause between tries")
    retry_pause_cap_seconds: float = Field(30.0, gt=0, description="Longest pause between tries")
    retry_after_inline_max_seconds: float = Field(60.0, ge=0, description="Longest Retry-After obeyed in place")
    slowest_request_interval_seconds: float = Field(
        10.0, gt=0, description="The slowest rate a portal is halved down to: one request per this many seconds")

    # Verdict.
    outage_failed_after_minutes: float = Field(60.0, gt=0, description="An outage this long reads `failed`")
    repair_attempts_per_incident: int = Field(3, ge=0, description="Repair attempts before `failed`")
    repairs_per_day: int = Field(3, ge=0, description="Repairs a failed portal may start per day (Q14)")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> CheckSettings:
        """The defaults, overridden by CHECKS_<NAME> environment variables (CHECKS_SIGNIFICANCE=0.01)."""
        env = os.environ if environ is None else environ
        given = {name: env[f"CHECKS_{name.upper()}"] for name in cls.model_fields
                 if env.get(f"CHECKS_{name.upper()}", "").strip()}
        return cls(**given)


DEFAULT_SETTINGS = CheckSettings()
