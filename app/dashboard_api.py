"""The dashboard's data routes: what the page at `GET /` reads (docs/DASHBOARD_API.md).

    GET  /api/dashboard               every portal on one page, with the settings
    GET  /api/portals/{id}/timeline   the runs of one portal with their checks and steps
    POST /api/settings                the attach time limit and the robots.txt test switch

These are extra routes beside the public contract, which they do not touch. The page checks
every answer against `dashboard/src/data/schema.ts` and treats one that does not fit as the API
being offline ("API offline, retrying", the last good answer kept), so that file is the contract here.

Everything shown is what the records say. What the system does not record is null or left
out, never filled in: a run without a publication has no `publishedCount`, a portal whose
model usage is not fully accounted for has `usage: null`. Text that came from a portal's
pages is passed on as data; the page escapes it.

The projections are plain functions over records (`app/models.py`). They read the store
through the small protocol below and get by on a store that has only the methods of
`app.interfaces.Store`, such as the in-memory one: then there are no checks, steps or
publications to show, and the answers say so by leaving them out.

No route here calls a model or sends a request. Every store call of a route runs inside one
call on the app's database thread (`app/main.py`).
"""
from __future__ import annotations

import logging
import math
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt

from app.models import (
    AgentStep, CheckResult, Portal, Recipe, RecipeStatus, Run, RunKind, Severity, StepKind, TokenUsage, utcnow,
)
from app.reader import PUBLISH_STEP
from app.scheduler import DEFAULT_SETTINGS as DEFAULT_SCHEDULE

UTC = timezone.utc
log = logging.getLogger("watchtower.dashboard")

# The severities the page knows. `outage` is ours (Q10) and newer than the page: a check that
# failed with it is shown as a failed check, and its name and message say it is an outage.
_PAGE_SEVERITY = {Severity.outage: Severity.fail}
_NOT_PART_OF_A_CHANGE = ("expectations",)  # measured again by every read, not written by a repair


# == Settings ==

@dataclass(frozen=True)
class DashboardSettings:
    """The numbers of the dashboard's routes that are our own choice. Built with `from_env()`."""

    recent_reads: int = 30                  # reads shown per portal on the overview (the page draws 30 slots)
    trend_points: int = 30                  # publications in a portal's small delivery chart
    reads_window_seconds: float = 3600.0    # "reads in the last hour"
    timeline_runs: int = 200                # newest runs a timeline answers with
    # Euros for one US dollar, for showing model cost. A fixed figure, not a live rate: set
    # DASHBOARD_EUR_PER_USD to the rate of the day the costs are reported.
    eur_per_usd: float = 0.86
    # What POST /api/settings accepts as the attach time limit, in whole minutes.
    attach_time_limit_min_minutes: int = 1
    attach_time_limit_max_minutes: int = 1440

    def __post_init__(self) -> None:
        for name in ("recent_reads", "trend_points", "timeline_runs", "attach_time_limit_min_minutes"):
            if getattr(self, name) < 1:
                raise ValueError(f"dashboard setting {name} must be at least 1")
        if not self.reads_window_seconds > 0 or not self.eur_per_usd > 0 or not math.isfinite(self.eur_per_usd):
            raise ValueError("reads_window_seconds and eur_per_usd must be positive")
        if self.attach_time_limit_max_minutes < self.attach_time_limit_min_minutes:
            raise ValueError("attach_time_limit_max_minutes is below attach_time_limit_min_minutes")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "DashboardSettings":
        """DASHBOARD_<NAME> for each field, for example DASHBOARD_EUR_PER_USD=0.9."""
        env = os.environ if environ is None else environ
        kw: dict[str, Any] = {}
        for f in fields(cls):
            raw = env.get(f"DASHBOARD_{f.name.upper()}")
            if raw is not None and raw.strip():
                kw[f.name] = int(raw) if f.type in ("int", int) else float(raw)
        return cls(**kw)


# == What is read from the store ==

class Records(Protocol):
    """The reads every store has (`app.interfaces.Store`). The projections also use, when the
    store has them (`app.db.Database` does): `recent_runs`, `run_totals`, `recent_steps`,
    `list_checks`, `list_steps`, `next_recipe_version` and `get_recipe`."""

    def get_portal(self, portal_id: str) -> Portal | None: ...
    def list_portals(self) -> list[Portal]: ...
    def count_tenders(self, portal_id: str) -> int: ...
    def list_runs(self, portal_id: str) -> list[Run]: ...


@dataclass(frozen=True)
class PortalHistory:
    """What a portal's runs say about it on the overview."""

    last_run: Run | None = None
    recent_reads: Sequence[Run] = ()        # oldest first
    reads_in_window: int = 0
    usage: TokenUsage | None = field(default_factory=TokenUsage)  # None: some model call was not accounted for
    delivery_trend: Sequence[int] = ()      # tenders delivered after each publication, oldest first


def history_from_runs(runs: Sequence[Run], since: datetime, settings: DashboardSettings) -> PortalHistory:
    """The history of one portal from all of its runs, oldest first: for a store that cannot
    add them up itself. Such a store records no publications, so the trend is empty."""
    reads = [run for run in runs if run.kind is RunKind.read]
    usage: TokenUsage | None = TokenUsage()
    for run in runs:
        usage = usage.add(run.usage)
    if any(_unaccounted(run.model_calls, run.usage) for run in runs):
        usage = None
    return PortalHistory(last_run=runs[-1] if runs else None, recent_reads=reads[-settings.recent_reads:],
                         reads_in_window=sum(1 for run in reads if _utc(run.started_at) >= since), usage=usage)


def histories(store: Records, portals: Sequence[Portal], since: datetime,
              settings: DashboardSettings) -> dict[str, PortalHistory]:
    """Every portal's history: in four queries where the store can, from each portal's runs otherwise."""
    if not all(hasattr(store, name) for name in ("recent_runs", "run_totals", "recent_steps")):
        return {portal.id: history_from_runs(store.list_runs(portal.id), since, settings) for portal in portals}
    last = store.recent_runs(1)
    reads = store.recent_runs(settings.recent_reads, kind=RunKind.read)
    totals = store.run_totals(since)
    published = store.recent_steps(PUBLISH_STEP, settings.trend_points)
    out: dict[str, PortalHistory] = {}
    for portal in portals:
        total = totals.get(portal.id)
        counts = [delivered_by(step) for step in published.get(portal.id, [])]
        out[portal.id] = PortalHistory(
            last_run=(last.get(portal.id) or [None])[-1], recent_reads=reads.get(portal.id, []),
            reads_in_window=total.reads_since if total else 0,
            usage=TokenUsage() if total is None else None if total.unaccounted_runs else total.usage,
            delivery_trend=[count for count in counts if count is not None])
    return out


def delivered_by(step: AgentStep) -> int | None:
    """How many tenders the portal delivered once this publication was in, when the step recorded it."""
    count = (step.args or {}).get("delivered") if step.name == PUBLISH_STEP else None
    return count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else None


# == Records to wire shapes (pure) ==

def _utc(at: datetime) -> datetime:
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


def time_out(at: datetime | None) -> str | None:
    """Our own timestamps on the wire: UTC with its offset, to the millisecond."""
    return None if at is None else _utc(at).isoformat(timespec="milliseconds")


def _unaccounted(model_calls: int, usage: TokenUsage) -> bool:
    """A model was called and no tokens were recorded: what it cost is not known."""
    return model_calls > 0 and usage.input_tokens == 0 and usage.output_tokens == 0


def usage_out(usage: TokenUsage, eur_per_usd: float) -> dict[str, Any]:
    return {"inputTokens": usage.input_tokens, "outputTokens": usage.output_tokens,
            "cachedInputTokens": usage.cached_input_tokens, "reasoningTokens": usage.reasoning_tokens,
            "costUsd": usage.cost_usd, "costEur": usage.cost_usd * eur_per_usd}


def minutes_of(seconds: float) -> int:
    """A time limit in whole minutes, rounded up, as the page shows it."""
    return max(1, math.ceil(seconds / 60 - 1e-9))


def settings_out(attach_time_limit_seconds: float, ignore_robots_txt: bool) -> dict[str, Any]:
    return {"attachTimeLimitMinutes": minutes_of(attach_time_limit_seconds), "ignoreRobotsTxt": bool(ignore_robots_txt)}


def portal_row(portal: Portal, tender_count: int, history: PortalHistory, *, next_read_at: datetime | None,
               eur_per_usd: float) -> dict[str, Any]:
    """One portal on the overview. `reusedFrom` is left out: no record says where a recipe came from."""
    last = history.last_run
    running = last is not None and last.finished_at is None
    return {
        "id": portal.id, "url": portal.url, "state": portal.state.value, "reason": portal.reason,
        "tenderCount": tender_count, "lastSuccessAt": time_out(portal.last_success_at),
        "cause": portal.cause.value if portal.cause else None, "fingerprint": portal.fingerprint,
        "timezone": portal.timezone, "recipeVersion": portal.recipe_version,
        # While a run is going on, the time planned before it is over; the next one is not planned yet.
        "nextReadAt": None if running else time_out(next_read_at or portal.next_read_at),
        "lastRun": None if last is None else {"id": last.id, "kind": last.kind.value, "result": _value(last.result)},
        "recentReads": [_value(run.result) for run in history.recent_reads],
        "deliveryTrend": list(history.delivery_trend),
        "readsLastHour": history.reads_in_window,
        "usage": None if history.usage is None else usage_out(history.usage, eur_per_usd),
    }


def _value(member: Any) -> Any:
    return None if member is None else member.value


def check_out(check: CheckResult) -> dict[str, Any]:
    out: dict[str, Any] = {"name": check.name, "passed": check.passed,
                           "severity": _PAGE_SEVERITY.get(check.severity, check.severity).value,
                           "message": check.message}
    if check.observed is not None:
        out["observed"] = check.observed
    if check.expected is not None:
        out["expected"] = check.expected
    return out


def step_out(step: AgentStep, eur_per_usd: float) -> dict[str, Any]:
    """One step. A model step without recorded usage has `usage: null` (cost unknown); a step
    that called no model has no `usage` at all."""
    out: dict[str, Any] = {"seq": step.seq, "at": time_out(step.at), "kind": step.kind.value, "name": step.name,
                           "summary": step.summary,
                           "durationMs": None if step.duration_ms is None else max(0, step.duration_ms)}
    if step.usage is not None:
        out["usage"] = usage_out(step.usage, eur_per_usd)
    elif step.kind is StepKind.llm:
        out["usage"] = None
    return out


def stats_out(run: Run) -> dict[str, int] | None:
    """The counters of a run that ended and counted something. A run still going on, or cut
    short before it counted anything, has zeros nobody measured: those are left out."""
    counters = run.stats.model_dump()
    if run.finished_at is None or not any(counters.values()):
        return None
    return {_camel(name): value for name, value in counters.items()}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def changed_parts(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """The parts of a recipe body that differ: its top-level keys, and `key.id` for an entry
    of a list whose entries carry an id (the nodes)."""
    out: list[str] = []
    for key in sorted({*old, *new} - set(_NOT_PART_OF_A_CHANGE)):
        before, after = old.get(key), new.get(key)
        if before == after:
            continue
        if _with_ids(before) and _with_ids(after):
            a, b = ({str(entry["id"]): entry for entry in side} for side in (before, after))
            out += [f"{key}.{ident}" for ident in sorted({*a, *b}) if a.get(ident) != b.get(ident)]
        else:
            out.append(key)
    return out


def _with_ids(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(entry, dict) and "id" in entry for entry in value)


def recipe_change(run: Run, recipes: Mapping[int, Recipe]) -> dict[str, Any] | None:
    """The recipe this run put in place of another one, if it did.

    Only a recipe that passed its validation counts (a candidate or a rejected one changed
    nothing), and only when the record names the version it replaced.
    """
    for recipe in recipes.values():
        if recipe.created_by_run_id != run.id or recipe.parent_version is None or recipe.validated_at is None:
            continue
        parent = recipes.get(recipe.parent_version)
        if parent is None or recipe.status not in (RecipeStatus.active, RecipeStatus.retired):
            continue
        return {"from": parent.version, "to": recipe.version, "rationale": recipe.rationale or "",
                "changedParts": changed_parts(parent.body, recipe.body)}
    return None


def run_out(run: Run, *, checks: Sequence[CheckResult] | None = None, steps: Sequence[AgentStep] | None = None,
            recipes: Mapping[int, Recipe] | None = None, eur_per_usd: float) -> dict[str, Any]:
    """One run of the timeline. `checks` and `steps` are None when the store cannot say; then
    the keys are left out, which the page shows as "not recorded" and not as "all passed"."""
    summary = run.reason_after or run.error or (steps[-1].summary if steps else "")
    out: dict[str, Any] = {
        "id": run.id, "kind": run.kind.value, "trigger": run.trigger.value, "startedAt": time_out(run.started_at),
        "finishedAt": time_out(run.finished_at), "result": _value(run.result), "summary": summary,
        "modelCalls": run.model_calls,
    }
    if run.recipe_version is not None:
        out["recipeVersion"] = run.recipe_version
    published = [count for count in map(delivered_by, steps or ()) if count is not None]
    if published:
        out["publishedCount"] = published[-1]
    stats = stats_out(run)
    if stats is not None:
        out["stats"] = stats
    if _unaccounted(run.model_calls, run.usage):
        out["usage"] = None  # a model was called and what it used was not recorded
    elif run.model_calls or run.usage != TokenUsage():
        out["usage"] = usage_out(run.usage, eur_per_usd)
    if checks is not None:
        out["checks"] = [check_out(check) for check in checks]
    if steps is not None:
        out["steps"] = [step_out(step, eur_per_usd) for step in steps]
    change = recipe_change(run, recipes) if recipes else None
    if change is not None:
        out["recipeChange"] = change
    return out


# == The answers of the routes (each runs on the database thread) ==

def dashboard_answer(store: Records, settings: DashboardSettings, *, live: Mapping[str, Any],
                     next_reads: Mapping[str, datetime] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """`GET /api/dashboard`: every portal, oldest first, with the settings in force."""
    now = now or utcnow()
    portals = store.list_portals()
    history = histories(store, portals, now - timedelta(seconds=settings.reads_window_seconds), settings)
    return {
        "asOf": time_out(now), "eurPerUsd": settings.eur_per_usd, "settings": dict(live),
        "portals": [portal_row(portal, store.count_tenders(portal.id), history[portal.id],
                               next_read_at=(next_reads or {}).get(portal.id), eur_per_usd=settings.eur_per_usd)
                    for portal in portals],
    }


def timeline_answer(store: Records, portal_id: str, settings: DashboardSettings) -> list[dict[str, Any]] | None:
    """`GET /api/portals/{id}/timeline`: the newest runs of a portal, oldest first. None for an unknown id."""
    if store.get_portal(portal_id) is None:
        return None
    if hasattr(store, "recent_runs"):
        runs = store.recent_runs(settings.timeline_runs, portal_id=portal_id).get(portal_id, [])
    else:
        runs = store.list_runs(portal_id)[-settings.timeline_runs:]
    list_checks, list_steps = getattr(store, "list_checks", None), getattr(store, "list_steps", None)
    recipes: dict[int, Recipe] = {}
    if hasattr(store, "next_recipe_version") and hasattr(store, "get_recipe"):
        for version in range(1, store.next_recipe_version(portal_id)):
            recipe = store.get_recipe(portal_id, version)
            if recipe is not None:
                recipes[version] = recipe
    return [run_out(run, checks=list_checks(run.id) if list_checks else None,
                    steps=list_steps(run.id) if list_steps else None, recipes=recipes,
                    eur_per_usd=settings.eur_per_usd)
            for run in runs]


# == The two settings an operator can change ==

class Controls(Protocol):
    """What holds the two settings: the read loop (`app.loop.ReadLoop`), when the app has one."""

    @property
    def attach_time_limit_seconds(self) -> float: ...
    @property
    def ignore_robots_txt(self) -> bool: ...
    def apply_settings(self, *, attach_time_limit_seconds: float, ignore_robots_txt: bool) -> None: ...


class NoReader:
    """The settings of an app that has no read loop of ours (the in-memory stand-in, or a
    worker handed in): nothing here reads a portal, so nothing can be changed. It reports
    the defaults and keeps them, rather than pretend a change took effect."""

    attach_time_limit_seconds: float = DEFAULT_SCHEDULE.attach_time_limit_seconds
    ignore_robots_txt: bool = False

    def apply_settings(self, *, attach_time_limit_seconds: float, ignore_robots_txt: bool) -> None:
        return None


class SettingsBody(BaseModel):
    """Body of POST /api/settings: both values, of exactly these types, and nothing else."""

    model_config = ConfigDict(extra="forbid")

    attachTimeLimitMinutes: StrictInt
    ignoreRobotsTxt: StrictBool


# == Routes ==

def add_dashboard_routes(app: FastAPI, store: Records, on_db: Callable[..., Awaitable[Any]], worker: Any,
                         settings: DashboardSettings | None = None) -> None:
    """Register the three routes on the app. `on_db` runs a call on the database thread."""
    settings = settings or DashboardSettings.from_env()
    controls: Controls = worker if hasattr(worker, "apply_settings") else NoReader()
    next_reads: Callable[[], Mapping[str, datetime]] = getattr(worker, "next_reads", dict)

    def live() -> dict[str, Any]:
        return settings_out(controls.attach_time_limit_seconds, controls.ignore_robots_txt)

    @app.get("/api/dashboard")
    async def dashboard() -> JSONResponse:
        """Every portal with its state, last reads, deliveries and model cost, and the settings."""
        current, due = live(), dict(next_reads())  # the worker is read on the event loop
        return JSONResponse(await on_db(lambda: dashboard_answer(store, settings, live=current, next_reads=due)),
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/portals/{portal_id}/timeline")
    async def timeline(portal_id: str) -> JSONResponse:
        """The portal's runs, oldest first, each with its checks, steps and counters."""
        answer = await on_db(timeline_answer, store, portal_id, settings)
        if answer is None:
            raise HTTPException(status_code=404, detail="No portal has this id.")
        return JSONResponse(answer, headers={"Cache-Control": "no-store"})

    @app.post("/api/settings")
    async def change_settings(body: SettingsBody) -> JSONResponse:
        """Set the attach time limit and the robots.txt test switch; answers with the values in force.

        The change holds from the next attach decision and the next request on, for every
        portal. It is kept in memory only: after a restart both values are again what the
        environment says. On an app without a read loop nothing changes, and the answer shows that.
        """
        low, high = settings.attach_time_limit_min_minutes, settings.attach_time_limit_max_minutes
        if not low <= body.attachTimeLimitMinutes <= high:
            raise HTTPException(status_code=422,
                                detail=f"attachTimeLimitMinutes must be a whole number from {low} to {high}.")
        controls.apply_settings(attach_time_limit_seconds=body.attachTimeLimitMinutes * 60.0,
                                ignore_robots_txt=body.ignoreRobotsTxt)
        now = live()
        log.info("settings asked for %s, in force %s", body.model_dump(), now)
        return JSONResponse(now, headers={"Cache-Control": "no-store"})
