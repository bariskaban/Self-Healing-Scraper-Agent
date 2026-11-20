"""The dashboard's own routes (docs/DASHBOARD_API.md), beside the public contract, which they do not change.

  GET  /api/dashboard                  one snapshot of every portal, polled every 5 s
  GET  /api/portals/{id}/timeline      a portal's runs with their checks, steps, usage and recipe change
  POST /api/settings                   the attach time limit and the robots.txt test switch (mentor, 1b and 7)

The answers are built from the store on the API's database thread, like every other route
(Q15). A store without checks, steps or recipes (the in-memory stand-in) gives runs without
those parts, which the page shows as "No checks recorded", never as "All passed".

Every field here is what the store holds; nothing is estimated. In particular `deliveryTrend`
stays empty and `publishedCount` absent until the read loop records how many tenders each read
published: the page then shows "No trend yet" rather than a trend made up from other numbers.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.fetch.settings import FetchSettings
from app.interfaces import Store
from app.models import Portal, Run, RunKind, RunStats
from app.scheduler import SchedulerSettings

UTC = timezone.utc
RECENT_READS = 30
# Ours: the rate the page converts model cost at. Set EUR_PER_USD at hand-in to the ECB
# reference rate of that day (Q9); the page says which rate it used.
EUR_PER_USD = 0.9
SETTINGS_FILE = "settings.json"


# == Settings an operator may change while the system runs ==

class Settings(BaseModel):
    """`POST /api/settings` body and answer. Positive whole minutes, a strict boolean, no other keys."""

    model_config = ConfigDict(extra="forbid")

    attachTimeLimitMinutes: StrictInt = Field(gt=0)
    ignoreRobotsTxt: StrictBool


class LiveSettings:
    """The two settings the dashboard shows and changes (the mentor's answers 1b and 7).

    Starts from the environment (ATTACH_TIME_LIMIT_SECONDS, IGNORE_ROBOTS_TXT). A change is kept
    in DATA_DIR/settings.json when DATA_DIR is set, so a restart keeps it. The read loop reads
    `current()` at the start of each attach and read; it is on `app.state.live_settings`.
    """

    def __init__(self, settings: Settings, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._settings = settings
        self._path = path

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "LiveSettings":
        env = os.environ if environ is None else environ
        seconds = SchedulerSettings.from_env(env).attach_time_limit_seconds
        settings = Settings(attachTimeLimitMinutes=max(1, round(seconds / 60)),
                            ignoreRobotsTxt=FetchSettings.from_env(env).ignore_robots_txt)
        path = Path(env["DATA_DIR"]) / SETTINGS_FILE if env.get("DATA_DIR") else None
        if path is not None and path.is_file():
            try:
                settings = Settings.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                pass  # a damaged file is not a reason to refuse to start: the environment's values stand
        return cls(settings, path)

    def current(self) -> Settings:
        with self._lock:
            return self._settings

    def change(self, settings: Settings) -> Settings:
        with self._lock:
            self._settings = settings
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(settings.model_dump_json(), encoding="utf-8")
                tmp.replace(self._path)
            return settings


# == The answers ==

def _time(value: datetime | None) -> str | None:
    """With its offset, to the second: what the page's `Date.parse` reads everywhere."""
    if value is None:
        return None
    if value.tzinfo is None:  # our own timestamps are UTC (CONVENTIONS.md, rule 4)
        value = value.replace(tzinfo=UTC)
    return value.isoformat(timespec="seconds")


def _usage(runs: list[Run], eur_per_usd: float) -> dict[str, Any]:
    tokens_in = sum(r.usage.input_tokens for r in runs)
    cost = sum(r.usage.cost_usd for r in runs)
    return {
        "inputTokens": tokens_in,
        "outputTokens": sum(r.usage.output_tokens for r in runs),
        "cachedInputTokens": sum(r.usage.cached_input_tokens for r in runs),
        "reasoningTokens": sum(r.usage.reasoning_tokens for r in runs),
        "costUsd": round(cost, 6),
        "costEur": round(cost * eur_per_usd, 6),
    }


def _result(run: Run) -> str | None:
    return run.result.value if run.result is not None else None


def portal_row(store: Store, portal: Portal, now: datetime, eur_per_usd: float) -> dict[str, Any]:
    """One row of the overview, from the portal and its runs."""
    runs = store.list_runs(portal.id)  # oldest first
    reads = [r for r in runs if r.kind is RunKind.read]
    hour_ago = now - timedelta(hours=1)
    last = runs[-1] if runs else None
    return {
        "id": portal.id,
        "url": portal.url,
        "state": portal.state.value,
        "reason": portal.reason,
        "tenderCount": store.count_tenders(portal.id),
        "lastSuccessAt": _time(portal.last_success_at),
        "cause": portal.cause.value if portal.cause else None,
        "fingerprint": portal.fingerprint,
        "timezone": portal.timezone,
        "recipeVersion": portal.recipe_version,
        "nextReadAt": _time(portal.next_read_at),
        "lastRun": {"id": last.id, "kind": last.kind.value, "result": _result(last)} if last else None,
        "recentReads": [_result(r) for r in reads[-RECENT_READS:]],
        "deliveryTrend": [],  # needs each read's published count, which the read loop will record
        "readsLastHour": sum(1 for r in reads if _aware(r.started_at) >= hour_ago),
        "usage": _usage(runs, eur_per_usd),
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def dashboard_snapshot(store: Store, settings: Settings, now: datetime, eur_per_usd: float) -> dict[str, Any]:
    """`GET /api/dashboard`: every portal in one answer."""
    return {
        "asOf": _time(now),
        "eurPerUsd": eur_per_usd,
        "settings": settings.model_dump(),
        "portals": [portal_row(store, p, now, eur_per_usd) for p in store.list_portals()],
    }


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _stats(stats: RunStats) -> dict[str, int]:
    return {_camel(k): v for k, v in stats.model_dump().items()}


def changed_parts(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What a repair changed in a recipe: each node that differs by id, and each other part that differs."""
    parts: list[str] = []
    old_nodes = {n.get("id"): n for n in old.get("nodes", []) if isinstance(n, dict)}
    new_nodes = {n.get("id"): n for n in new.get("nodes", []) if isinstance(n, dict)}
    for node_id in sorted(set(old_nodes) | set(new_nodes), key=str):
        if old_nodes.get(node_id) != new_nodes.get(node_id):
            parts.append(f"node {node_id}")
    for key in sorted((set(old) | set(new)) - {"nodes", "expectations"}):
        if old.get(key) != new.get(key):
            parts.append(key)
    return parts


def run_entry(store: Store, run: Run, eur_per_usd: float) -> dict[str, Any]:
    """One run of the timeline, with what the store holds about it."""
    list_checks = getattr(store, "list_checks", None)
    list_steps = getattr(store, "list_steps", None)
    get_recipe = getattr(store, "get_recipe", None)
    steps = list_steps(run.id) if list_steps else None
    summary = run.reason_after or run.error or (steps[-1].summary if steps and run.finished_at is None else "")
    entry: dict[str, Any] = {
        "id": run.id,
        "kind": run.kind.value,
        "trigger": run.trigger.value,
        "startedAt": _time(run.started_at),
        "finishedAt": _time(run.finished_at),
        "result": _result(run),
        "summary": summary,
        "modelCalls": run.model_calls,
        "stats": _stats(run.stats),
    }
    if run.recipe_version is not None:
        entry["recipeVersion"] = run.recipe_version
    if run.model_calls or run.usage.cost_usd or run.usage.input_tokens:
        entry["usage"] = _usage([run], eur_per_usd)
    if list_checks is not None:
        entry["checks"] = [
            {"name": c.name, "passed": c.passed, "severity": c.severity.value, "message": c.message,
             **({"observed": c.observed} if c.observed is not None else {}),
             **({"expected": c.expected} if c.expected is not None else {})}
            for c in list_checks(run.id)]
    if steps is not None:
        entry["steps"] = [
            {"seq": s.seq, "at": _time(s.at), "kind": s.kind.value, "name": s.name, "summary": s.summary,
             "durationMs": s.duration_ms,
             **({"usage": {"inputTokens": s.usage.input_tokens, "outputTokens": s.usage.output_tokens,
                           "cachedInputTokens": s.usage.cached_input_tokens,
                           "reasoningTokens": s.usage.reasoning_tokens, "costUsd": s.usage.cost_usd,
                           "costEur": round(s.usage.cost_usd * eur_per_usd, 6)}} if s.usage else {})}
            for s in steps]
    if run.kind is RunKind.repair and run.recipe_version is not None and get_recipe is not None:
        recipe = get_recipe(run.portal_id, run.recipe_version)
        parent = get_recipe(run.portal_id, recipe.parent_version) if recipe and recipe.parent_version else None
        if recipe is not None and parent is not None:
            entry["recipeChange"] = {"from": parent.version, "to": recipe.version, "rationale": recipe.rationale or "",
                                     "changedParts": changed_parts(parent.body, recipe.body)}
    return entry


def portal_timeline(store: Store, portal_id: str, eur_per_usd: float) -> list[dict[str, Any]]:
    """`GET /api/portals/{id}/timeline`: every run, oldest first."""
    return [run_entry(store, run, eur_per_usd) for run in store.list_runs(portal_id)]


# == The routes ==

def add_dashboard_routes(app: FastAPI, store: Store, on_db: Callable[..., Awaitable[Any]], live: LiveSettings,
                         eur_per_usd: float | None = None) -> None:
    """Register the three routes on `app`. `on_db` runs a call on the API's database thread."""
    rate = eur_per_usd if eur_per_usd is not None else float(os.environ.get("EUR_PER_USD", EUR_PER_USD))
    app.state.live_settings = live
    no_store = {"Cache-Control": "no-store"}

    @app.get("/api/dashboard", include_in_schema=False)
    async def dashboard() -> JSONResponse:
        snapshot = await on_db(dashboard_snapshot, store, live.current(), datetime.now(UTC), rate)
        return JSONResponse(snapshot, headers=no_store)

    @app.get("/api/portals/{portal_id}/timeline", include_in_schema=False)
    async def timeline(portal_id: str) -> JSONResponse:
        if await on_db(store.get_portal, portal_id) is None:
            raise HTTPException(status_code=404, detail="No portal has this id.")
        return JSONResponse(await on_db(portal_timeline, store, portal_id, rate), headers=no_store)

    @app.post("/api/settings", include_in_schema=False)
    async def change_settings(body: Settings) -> JSONResponse:
        return JSONResponse(live.change(body).model_dump(), headers=no_store)
