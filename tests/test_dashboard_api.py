"""The dashboard's data routes (docs/DASHBOARD_API.md). Run: pytest tests/test_dashboard_api.py

Three parts: the projections on records built by hand; the routes on the in-memory store;
and the app end to end on the mock portal (attach, an outage, back), as in tests/test_loop.py.

`fits_page` mirrors `dashboard/src/data/schema.ts`, the schemas the page checks every answer
with: one field that does not fit turns the whole page into demo data. With
DASHBOARD_API_DUMP_DIR set, the end-to-end test also writes its answers there as JSON, so
that they can be checked against the real schemas with bun (not part of this suite).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ModelSettings
from app.dashboard_api import (
    DashboardSettings, PortalHistory, changed_parts, check_out, dashboard_answer, delivered_by, history_from_runs,
    minutes_of, portal_row, recipe_change, run_out, settings_out, stats_out, step_out, timeline_answer, usage_out,
)
from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter
from app.loop import ReadLoop
from app.main import create_app
from app.memory_store import IdleWorker, MemoryStore
from app.models import (
    AgentStep, Cause, CheckResult, Portal, PortalState, Recipe, RecipeStatus, Run, RunKind, RunResult, RunStats,
    RunTrigger, Severity, StepKind, TokenUsage, url_key,
)
from app.reader import Reader
from mock_portal import MockPortal

UTC = timezone.utc
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
URL = "https://mock.example"
RATE = 0.5
SETTINGS = DashboardSettings(eur_per_usd=RATE)


# == The page's schemas, mirrored ==

def _time(value) -> bool:
    try:
        return isinstance(value, str) and datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _result(value) -> bool:
    return value in ("ok", "failed", None)


def _keys(found: dict, required: set[str], optional: set[str] = frozenset()) -> None:
    assert required <= set(found) <= required | optional, (sorted(found), sorted(required))


def fits_usage(u) -> None:
    _keys(u, {"inputTokens", "outputTokens", "costUsd", "costEur"}, {"cachedInputTokens", "reasoningTokens"})
    assert all(_number(value) and value >= 0 for value in u.values()), u


def fits_settings(s) -> None:
    _keys(s, {"attachTimeLimitMinutes", "ignoreRobotsTxt"})
    assert _count(s["attachTimeLimitMinutes"]) and s["attachTimeLimitMinutes"] > 0
    assert isinstance(s["ignoreRobotsTxt"], bool)


def fits_dashboard(d) -> None:
    _keys(d, {"asOf", "eurPerUsd", "settings", "portals"})
    assert _time(d["asOf"]) and _number(d["eurPerUsd"]) and d["eurPerUsd"] > 0
    fits_settings(d["settings"])
    for p in d["portals"]:
        _keys(p, {"id", "url", "state", "reason", "tenderCount", "lastSuccessAt", "cause", "fingerprint", "timezone",
                  "recipeVersion", "nextReadAt", "lastRun", "recentReads", "deliveryTrend", "readsLastHour", "usage"},
              {"reusedFrom"})
        assert isinstance(p["id"], str) and p["id"] and isinstance(p["url"], str) and isinstance(p["reason"], str)
        assert p["state"] in ("failed", "healing", "integrating", "serving")
        assert p["cause"] in ("outage", "block", "breakage", None)
        assert _count(p["tenderCount"]) and _count(p["readsLastHour"])
        assert all(p[key] is None or _time(p[key]) for key in ("lastSuccessAt", "nextReadAt"))
        assert all(p[key] is None or isinstance(p[key], str) for key in ("fingerprint", "timezone"))
        assert p["recipeVersion"] is None or _number(p["recipeVersion"])
        if p["lastRun"] is not None:
            _keys(p["lastRun"], {"id", "kind", "result"})
            assert p["lastRun"]["kind"] in ("read", "repair") and _result(p["lastRun"]["result"])
        assert all(_result(r) for r in p["recentReads"]) and all(_number(n) for n in p["deliveryTrend"])
        if p["usage"] is not None:
            fits_usage(p["usage"])


def fits_timeline(runs) -> None:
    assert isinstance(runs, list)
    for r in runs:
        _keys(r, {"id", "kind", "trigger", "startedAt", "finishedAt", "result", "summary", "modelCalls"},
              {"recipeVersion", "publishedCount", "stats", "usage", "checks", "steps", "recipeChange"})
        assert isinstance(r["id"], str) and r["id"] and r["kind"] in ("read", "repair") and _result(r["result"])
        assert r["trigger"] in ("attach", "schedule", "refresh", "recheck", "heal")
        assert _time(r["startedAt"]) and (r["finishedAt"] is None or _time(r["finishedAt"]))
        assert isinstance(r["summary"], str) and _count(r["modelCalls"])
        assert "recipeVersion" not in r or _number(r["recipeVersion"])
        assert "publishedCount" not in r or _count(r["publishedCount"])
        assert all(_number(v) for v in r.get("stats", {}).values())
        if r.get("usage") is not None:
            fits_usage(r["usage"])
        for c in r.get("checks", []):
            _keys(c, {"name", "passed", "severity", "message"}, {"observed", "expected"})
            assert isinstance(c["name"], str) and isinstance(c["passed"], bool) and isinstance(c["message"], str)
            assert c["severity"] in ("info", "warn", "fail", "block")
        for s in r.get("steps", []):
            _keys(s, {"seq", "at", "kind", "name", "summary", "durationMs"}, {"usage"})
            assert _number(s["seq"]) and _time(s["at"]) and s["kind"] in ("tool", "llm", "note", "decision")
            assert isinstance(s["name"], str) and isinstance(s["summary"], str)
            assert s["durationMs"] is None or (_number(s["durationMs"]) and s["durationMs"] >= 0)
            if s.get("usage") is not None:
                fits_usage(s["usage"])
        if "recipeChange" in r:
            _keys(r["recipeChange"], {"from", "to", "rationale", "changedParts"})


# == Records built by hand ==

def a_portal(**changes) -> Portal:
    return Portal(**{**dict(id="p1", url="https://vergabe.example/tenders", url_key=url_key("https://vergabe.example/tenders"),
                            created_at=T0, updated_at=T0), **changes})


def a_run(run_id: str = "r1", minute: int = 0, ended: bool = True, **changes) -> Run:
    start = T0 + timedelta(minutes=minute)
    base = dict(id=run_id, portal_id="p1", kind=RunKind.read, trigger=RunTrigger.schedule, started_at=start,
                state_before=PortalState.serving)
    if ended:
        base |= dict(finished_at=start + timedelta(seconds=30), result=RunResult.ok)
    return Run(**{**base, **changes})


def a_step(seq: int, name: str = "read_list", **changes) -> AgentStep:
    return AgentStep(**{**dict(run_id="r1", seq=seq, at=T0 + timedelta(seconds=seq), kind=StepKind.note, name=name,
                               summary=f"Step {seq}."), **changes})


# == Projections ==

def test_settings_come_from_the_environment_and_refuse_nonsense():
    assert DashboardSettings.from_env({}) == DashboardSettings()
    custom = DashboardSettings.from_env({"EUR_PER_USD": "0.9", "DASHBOARD_RECENT_READS": "5",
                                         "DASHBOARD_ATTACH_TIME_LIMIT_MAX_MINUTES": "60"})
    assert (custom.eur_per_usd, custom.recent_reads, custom.attach_time_limit_max_minutes) == (0.9, 5, 60)
    # One euro rate for the dashboard and the README: EUR_PER_USD, with config's default; no dashboard copy.
    assert DashboardSettings().eur_per_usd == ModelSettings().eur_per_usd == 0.90
    assert DashboardSettings.from_env({"DASHBOARD_EUR_PER_USD": "0.5"}).eur_per_usd == 0.90
    for bad in ({"eur_per_usd": 0}, {"recent_reads": 0}, {"timeline_runs": 0}, {"reads_window_seconds": 0},
                {"attach_time_limit_min_minutes": 10, "attach_time_limit_max_minutes": 5}):
        with pytest.raises(ValueError):
            DashboardSettings(**bad)


def test_usage_is_priced_in_euros_at_the_one_rate():
    usage = TokenUsage(input_tokens=1000, cached_input_tokens=400, output_tokens=200, reasoning_tokens=50, cost_usd=0.5)
    assert usage_out(usage, RATE) == {"inputTokens": 1000, "outputTokens": 200, "cachedInputTokens": 400,
                                      "reasoningTokens": 50, "costUsd": 0.5, "costEur": 0.25}


def test_a_time_limit_is_shown_in_whole_minutes():
    assert [minutes_of(s) for s in (1200.0, 60.0, 61.0, 90.0, 1.0)] == [20, 1, 2, 2, 1]
    assert settings_out(1200.0, False) == {"attachTimeLimitMinutes": 20, "ignoreRobotsTxt": False}


def test_a_running_run_says_only_what_is_known():
    out = run_out(a_run(ended=False, trigger=RunTrigger.attach, state_before=PortalState.integrating),
                  checks=[], steps=[a_step(1)], eur_per_usd=RATE)
    assert out == {"id": "r1", "kind": "read", "trigger": "attach", "startedAt": "2026-11-20T12:00:00.000+00:00",
                   "finishedAt": None, "result": None, "summary": "Step 1.", "modelCalls": 0, "checks": [],
                   "steps": [{"seq": 1, "at": "2026-11-20T12:00:01.000+00:00", "kind": "note", "name": "read_list",
                              "summary": "Step 1.", "durationMs": None}]}
    fits_timeline([out])


def test_a_finished_read_shows_its_counters_its_publication_and_its_reason():
    run = a_run(recipe_version=3, reason_after="Read at 12:00 UTC found 45 open tenders.", error="ignored",
                stats=RunStats(http_requests=48, pages_fetched=3, tenders_seen=45, tenders_new=2))
    steps = [a_step(1, duration_ms=120), a_step(2, "publish", args={"delivered": 47})]
    out = run_out(run, checks=None, steps=steps, eur_per_usd=RATE)
    assert out["summary"] == "Read at 12:00 UTC found 45 open tenders."
    assert (out["recipeVersion"], out["publishedCount"], out["finishedAt"]) == (3, 47, "2026-11-20T12:00:30.000+00:00")
    assert out["stats"] == {"httpRequests": 48, "pagesFetched": 3, "tendersSeen": 45, "tendersNew": 2,
                            "tendersChanged": 0, "tendersUnlisted": 0, "filesDownloaded": 0, "filesSkipped": 0,
                            "bytesDownloaded": 0}
    assert "usage" not in out and "checks" not in out and "recipeChange" not in out  # no model call: a known zero
    assert out["steps"][0]["durationMs"] == 120
    fits_timeline([out])


def test_what_is_not_recorded_is_left_out_not_made_up():
    # No publish step, no reason: no publishedCount, and the short error is the summary.
    cut = run_out(a_run(result=RunResult.failed, error="The run was cut short by a restart."), eur_per_usd=RATE)
    assert cut["summary"] == "The run was cut short by a restart."
    assert not {"publishedCount", "stats", "recipeVersion", "checks", "steps", "usage"} & set(cut)
    assert stats_out(a_run(ended=False, stats=RunStats(pages_fetched=2))) is None  # still counting
    assert run_out(a_run(ended=False), eur_per_usd=RATE)["summary"] == ""
    # A publish step that recorded no count, or a count that is no count, gives none.
    for args in (None, {}, {"delivered": "45"}, {"delivered": True}, {"delivered": -1}):
        assert delivered_by(a_step(1, "publish", args=args)) is None
    assert delivered_by(a_step(1, "read_list", args={"delivered": 45})) is None
    assert delivered_by(a_step(1, "publish", args={"delivered": 0})) == 0  # an empty publication is one


def test_model_usage_of_a_run_is_shown_when_recorded_and_null_when_a_call_was_not_accounted_for():
    paid = a_run(kind=RunKind.repair, trigger=RunTrigger.heal, model_calls=3,
                 usage=TokenUsage(input_tokens=90_000, output_tokens=8_000, cost_usd=0.4))
    assert run_out(paid, eur_per_usd=RATE)["usage"]["costEur"] == 0.2
    unknown = run_out(a_run(model_calls=1), eur_per_usd=RATE)
    assert unknown["usage"] is None and unknown["modelCalls"] == 1
    fits_timeline([run_out(paid, eur_per_usd=RATE), unknown])


def test_checks_keep_their_words_and_an_outage_is_shown_as_a_failed_check():
    outage = CheckResult(run_id="r1", name="outage", passed=False, severity=Severity.outage,
                         observed={"status": 503, "tries": 3}, message="The portal answered 503 three times.")
    assert check_out(outage) == {"name": "outage", "passed": False, "severity": "fail",
                                 "observed": {"status": 503, "tries": 3}, "message": "The portal answered 503 three times."}
    plain = CheckResult(run_id="r1", name="paging_complete", passed=True, severity=Severity.fail, expected=3,
                        message="<b>Every</b> page was read.")
    assert check_out(plain) == {"name": "paging_complete", "passed": True, "severity": "fail", "expected": 3,
                                "message": "<b>Every</b> page was read."}  # text is data: the page escapes it
    assert [check_out(CheckResult(run_id="r1", name="x", passed=True, severity=s, message="."))["severity"]
            for s in Severity] == ["info", "warn", "fail", "block", "fail"]


def test_a_model_step_without_usage_has_unknown_cost_and_a_tool_step_has_none():
    llm = a_step(1, kind=StepKind.llm, name="gpt", usage=TokenUsage(input_tokens=10, output_tokens=2, cost_usd=0.1))
    assert step_out(llm, RATE)["usage"]["costEur"] == 0.05
    assert step_out(a_step(2, kind=StepKind.llm), RATE)["usage"] is None
    assert "usage" not in step_out(a_step(3, kind=StepKind.tool), RATE)
    assert step_out(a_step(4, duration_ms=-5), RATE)["durationMs"] == 0  # a clock that stepped back


def test_a_recipe_change_is_a_validated_recipe_compared_with_the_one_it_replaced():
    old = {"identity": {"shape": "T-\\d+"}, "nodes": [{"id": "list", "locator": "table tr"}, {"id": "detail", "x": 1}],
           "edges": [1], "expectations": {"list_pages": 3}}
    new = {"identity": {"shape": "T-\\d+"}, "nodes": [{"id": "list", "locator": "div.card"}, {"id": "detail", "x": 1},
                                                      {"id": "files", "y": 2}],
           "edges": [1, 2], "expectations": {"list_pages": 4}}
    assert changed_parts(old, new) == ["edges", "nodes.files", "nodes.list"]  # what a read measures is no change
    assert changed_parts(old, old) == [] and changed_parts({"a": 1}, {"b": [1]}) == ["a", "b"]

    first = Recipe(portal_id="p1", version=1, body=old, status=RecipeStatus.retired, created_by_run_id="r0",
                   validated_at=T0)
    second = Recipe(portal_id="p1", version=2, parent_version=1, body=new, status=RecipeStatus.active,
                    created_by_run_id="r1", validated_at=T0, rationale="The list is cards now.")
    recipes = {1: first, 2: second}
    assert recipe_change(a_run("r1"), recipes) == {"from": 1, "to": 2, "rationale": "The list is cards now.",
                                                  "changedParts": ["edges", "nodes.files", "nodes.list"]}
    assert recipe_change(a_run("r0"), recipes) is None  # the first recipe replaced nothing
    for status, validated in ((RecipeStatus.candidate, None), (RecipeStatus.rejected, None),
                              (RecipeStatus.rejected, T0)):
        tried = second.model_copy(update={"status": status, "validated_at": validated})
        assert recipe_change(a_run("r1"), {1: first, 2: tried}) is None  # a candidate is not an active version
    assert recipe_change(a_run("r1"), {2: second}) is None  # the parent is not on record
    out = run_out(a_run("r1", kind=RunKind.repair, trigger=RunTrigger.heal), recipes=recipes, eur_per_usd=RATE)
    assert out["recipeChange"]["to"] == 2
    fits_timeline([out])


def test_a_portal_row_and_its_history():
    runs = [a_run("r1", 0), a_run("r2", 10, result=RunResult.failed),
            a_run("r3", 20, kind=RunKind.repair, trigger=RunTrigger.heal, model_calls=2,
                  usage=TokenUsage(input_tokens=100, output_tokens=10, cost_usd=1.0)),
            a_run("r4", 50, ended=False)]
    since = T0 + timedelta(minutes=5)
    history = history_from_runs(runs, since, DashboardSettings(recent_reads=2))
    assert history.last_run == runs[3] and list(history.recent_reads) == [runs[1], runs[3]]
    assert (history.reads_in_window, history.usage.cost_usd, list(history.delivery_trend)) == (2, 1.0, [])

    portal = a_portal(state=PortalState.healing, cause=Cause.outage, reason="The portal has not answered.",
                      fingerprint="netserver", timezone="Europe/Amsterdam", recipe_version=2,
                      last_success_at=T0, next_read_at=T0 + timedelta(hours=2))
    row = portal_row(portal, 45, history, next_read_at=T0 + timedelta(hours=1), eur_per_usd=RATE)
    assert row == {
        "id": "p1", "url": "https://vergabe.example/tenders", "state": "healing", "cause": "outage",
        "reason": "The portal has not answered.", "tenderCount": 45, "lastSuccessAt": "2026-11-20T12:00:00.000+00:00",
        "fingerprint": "netserver", "timezone": "Europe/Amsterdam", "recipeVersion": 2,
        "nextReadAt": None,  # a run is going on: the next one is not planned yet
        "lastRun": {"id": "r4", "kind": "read", "result": None}, "recentReads": ["failed", None],
        "deliveryTrend": [], "readsLastHour": 2,
        "usage": {"inputTokens": 100, "outputTokens": 10, "cachedInputTokens": 0, "reasoningTokens": 0,
                  "costUsd": 1.0, "costEur": 0.5}}

    idle = PortalHistory(last_run=runs[0], recent_reads=runs[:1], reads_in_window=1, delivery_trend=[44, 45])
    row = portal_row(portal, 45, idle, next_read_at=T0 + timedelta(hours=1), eur_per_usd=RATE)
    assert (row["nextReadAt"], row["deliveryTrend"]) == ("2026-11-20T13:00:00.000+00:00", [44, 45])
    assert portal_row(portal, 45, idle, next_read_at=None, eur_per_usd=RATE)["nextReadAt"] == "2026-11-20T14:00:00.000+00:00"
    assert portal_row(a_portal(), 0, PortalHistory(), next_read_at=None, eur_per_usd=RATE)["lastRun"] is None

    # One model call nobody accounted for: the portal's total cost is not known.
    unknown = history_from_runs([*runs[:3], a_run("r5", 30, model_calls=1)], since, SETTINGS)
    assert unknown.usage is None
    assert portal_row(portal, 45, unknown, next_read_at=None, eur_per_usd=RATE)["usage"] is None


# == The routes on the in-memory store ==

@pytest.fixture
def memory():
    store = MemoryStore()
    with TestClient(create_app(store, IdleWorker(store))) as client:
        yield store, client


def test_an_empty_system_answers_with_an_empty_dashboard(memory):
    _, client = memory
    answer = client.get("/api/dashboard")
    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
    body = answer.json()
    fits_dashboard(body)
    assert body["portals"] == [] and body["settings"] == {"attachTimeLimitMinutes": 20, "ignoreRobotsTxt": False}
    assert body["eurPerUsd"] == DashboardSettings().eur_per_usd
    assert client.get("/api/portals/nope/timeline").status_code == 404


def test_the_in_memory_store_gives_honest_answers_without_checks_steps_or_publications(memory):
    store, client = memory
    pid = client.post("/portals", json={"url": "https://vergabe.example/tenders"}).json()["id"]
    done = Run(id="a", portal_id=pid, kind=RunKind.read, trigger=RunTrigger.schedule, state_before=PortalState.serving,
               started_at=datetime.now(UTC) - timedelta(hours=3), finished_at=datetime.now(UTC) - timedelta(hours=3),
               result=RunResult.ok, reason_after="Every check passed.", stats=RunStats(tenders_seen=4))
    store.put_run(done)

    body = client.get("/api/dashboard").json()
    fits_dashboard(body)
    (row,) = body["portals"]
    assert (row["id"], row["state"], row["tenderCount"], row["cause"]) == (pid, "integrating", 0, None)
    assert row["recentReads"] == ["ok", None] and row["readsLastHour"] == 1 and row["deliveryTrend"] == []
    assert row["lastRun"]["result"] is None and row["nextReadAt"] is None and row["recipeVersion"] is None
    assert row["usage"] == {"inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "reasoningTokens": 0,
                            "costUsd": 0.0, "costEur": 0.0}

    runs = client.get(f"/api/portals/{pid}/timeline").json()
    fits_timeline(runs)
    assert [run["id"] for run in runs][0] == "a" and len(runs) == 2
    assert runs[0]["summary"] == "Every check passed." and runs[0]["stats"]["tendersSeen"] == 4
    assert all(not {"checks", "steps", "publishedCount", "usage"} & set(run) for run in runs)
    assert runs[1]["trigger"] == "attach" and runs[1]["finishedAt"] is None and "stats" not in runs[1]


def test_settings_cannot_change_where_nothing_reads_and_the_answer_says_so(memory):
    _, client = memory
    answer = client.post("/api/settings", json={"attachTimeLimitMinutes": 5, "ignoreRobotsTxt": True})
    assert answer.status_code == 200
    assert answer.json() == {"attachTimeLimitMinutes": 20, "ignoreRobotsTxt": False}
    assert client.get("/api/dashboard").json()["settings"] == answer.json()


@pytest.mark.parametrize("body", [
    {"attachTimeLimitMinutes": 0, "ignoreRobotsTxt": False},
    {"attachTimeLimitMinutes": -3, "ignoreRobotsTxt": False},
    {"attachTimeLimitMinutes": 1441, "ignoreRobotsTxt": False},      # above the upper bound (a setting)
    {"attachTimeLimitMinutes": 20.5, "ignoreRobotsTxt": False},
    {"attachTimeLimitMinutes": 20.0, "ignoreRobotsTxt": False},      # a whole number, written as one
    {"attachTimeLimitMinutes": "20", "ignoreRobotsTxt": False},
    {"attachTimeLimitMinutes": True, "ignoreRobotsTxt": False},
    {"attachTimeLimitMinutes": None, "ignoreRobotsTxt": False},
    {"attachTimeLimitMinutes": 20, "ignoreRobotsTxt": "false"},
    {"attachTimeLimitMinutes": 20, "ignoreRobotsTxt": 0},
    {"attachTimeLimitMinutes": 20, "ignoreRobotsTxt": None},
    {"attachTimeLimitMinutes": 20},
    {"ignoreRobotsTxt": True},
    {"attachTimeLimitMinutes": 20, "ignoreRobotsTxt": False, "eurPerUsd": 2},
    {},
    [20, False],
])
def test_settings_that_are_not_exactly_a_whole_number_of_minutes_and_a_boolean_are_refused(memory, body):
    _, client = memory
    assert client.post("/api/settings", json=body).status_code == 422
    assert client.get("/api/dashboard").json()["settings"] == {"attachTimeLimitMinutes": 20, "ignoreRobotsTxt": False}


def test_the_read_loop_applies_the_settings_to_the_reader_and_the_network_layer():
    fetcher = Fetcher(FetchSettings(mode=FetchMode.replay))
    reader = Reader(None, fetcher, lambda: None)
    loop = ReadLoop(None, reader, fetcher)
    assert (loop.attach_time_limit_seconds, loop.ignore_robots_txt) == (1200.0, False)
    before = fetcher.settings
    loop.apply_settings(attach_time_limit_seconds=300.0, ignore_robots_txt=True)
    assert reader.schedule.attach_time_limit_seconds == loop.schedule.attach_time_limit_seconds == 300.0
    assert fetcher.settings.ignore_robots_txt is True and reader.ignore_robots is True
    assert (loop.attach_time_limit_seconds, loop.ignore_robots_txt) == (300.0, True)
    # Nothing else moved.
    assert fetcher.settings.requests_per_second == before.requests_per_second and fetcher.settings.mode is before.mode
    assert reader.schedule.read_interval_seconds == 120.0

    class Bare:  # a network layer without settings: the switch cannot be thrown, and is not said to be
        pass

    loop = ReadLoop(None, Reader(None, Bare(), lambda: None), Bare())
    loop.apply_settings(attach_time_limit_seconds=60.0, ignore_robots_txt=True)
    assert (loop.attach_time_limit_seconds, loop.ignore_robots_txt, loop.reader.ignore_robots) == (60.0, False, False)
    fetcher.close()


def test_the_answers_are_built_on_the_database_thread_only(tmp_path):
    import threading

    seen: set[str] = set()

    class Watched(MemoryStore):
        def __getattribute__(self, name):
            if name in ("list_portals", "get_portal", "count_tenders", "list_runs"):
                seen.add(threading.current_thread().name)
            return super().__getattribute__(name)

    store = Watched()
    with TestClient(create_app(store, IdleWorker(store))) as client:
        pid = client.post("/portals", json={"url": "https://vergabe.example/tenders"}).json()["id"]
        seen.clear()
        assert client.get("/api/dashboard").status_code == 200
        assert client.get(f"/api/portals/{pid}/timeline").status_code == 200
    assert seen and all(name.startswith("watchtower-db") for name in seen)


# == End to end on the mock portal ==

@pytest.fixture
def site(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    mock = MockPortal()
    clock = [0.0]
    limiter = PortalLimiter(1.0, 10.0, clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    fetcher = Fetcher(FetchSettings(mode=FetchMode.live), transport=httpx.MockTransport(mock.handle),
                      limiter=limiter, clock=lambda: clock[0], rng=lambda: 0.0)
    with TestClient(create_app(fetch=fetcher, mock=mock)) as client:
        yield mock, client


def settled(client: TestClient, pid: str, run_id: str | None = None, seconds: float = 30.0) -> dict:
    """The portal once the given run (or every run) has ended."""
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        runs = client.get(f"/portals/{pid}/runs").json()
        mine = [run for run in runs if run_id is None or run["id"] == run_id]
        if mine and all(run["finishedAt"] is not None for run in mine):
            return client.get(f"/portals/{pid}").json()
        time.sleep(0.02)
    raise AssertionError("the read did not end in time")


def refresh(client: TestClient, pid: str) -> dict:
    run_id = client.post(f"/portals/{pid}/refresh").json()["runId"]
    return settled(client, pid, run_id)


def snapshot(client: TestClient, pid: str, name: str) -> tuple[dict, list[dict]]:
    """The dashboard's row of the portal and its timeline, checked against the page's schemas."""
    dashboard = client.get("/api/dashboard").json()
    timeline = client.get(f"/api/portals/{pid}/timeline").json()
    fits_dashboard(dashboard)
    fits_timeline(timeline)
    folder = os.environ.get("DASHBOARD_API_DUMP_DIR")
    if folder:
        tenders = client.get(f"/portals/{pid}/tenders").json()
        for kind, payload in (("dashboard", dashboard), ("timeline", timeline), ("tenders", tenders)):
            Path(folder, f"{name}.{kind}.json").write_text(json.dumps(payload), encoding="utf-8")
    (row,) = dashboard["portals"]
    return row, timeline


def test_attach_an_outage_and_recovery_as_the_dashboard_shows_them(site):
    mock, client = site
    pid = client.post("/portals", json={"url": URL}).json()["id"]
    fits_dashboard(client.get("/api/dashboard").json())  # also while the attach runs
    fits_timeline(client.get(f"/api/portals/{pid}/timeline").json())
    assert settled(client, pid)["state"] == "serving"

    # Attached and serving.
    row, timeline = snapshot(client, pid, "serving")
    assert (row["state"], row["cause"], row["tenderCount"]) == ("serving", None, 45)
    assert (row["recipeVersion"], row["timezone"], row["fingerprint"]) == (1, "Europe/Amsterdam", row["fingerprint"])
    assert row["recentReads"] == ["ok"] and row["deliveryTrend"] == [45] and row["readsLastHour"] == 1
    assert row["lastSuccessAt"] is not None and row["nextReadAt"] > row["lastSuccessAt"] and "reusedFrom" not in row
    assert row["usage"] == {"inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "reasoningTokens": 0,
                            "costUsd": 0.0, "costEur": 0.0}  # the mock portal's recipe is written by hand
    (attach,) = timeline
    assert row["lastRun"] == {"id": attach["id"], "kind": "read", "result": "ok"}
    assert (attach["kind"], attach["trigger"], attach["result"], attach["modelCalls"]) == ("read", "attach", "ok", 0)
    assert (attach["recipeVersion"], attach["publishedCount"]) == (1, 45)
    assert attach["summary"] == row["reason"] and "usage" not in attach and "recipeChange" not in attach
    assert attach["stats"]["tendersSeen"] == 45 and attach["stats"]["tendersNew"] == 45
    assert attach["stats"]["httpRequests"] > 45 and attach["stats"]["filesDownloaded"] > 0
    assert [step["name"] for step in attach["steps"]][:3] == ["learn", "read_list", "read_details"]
    assert "publish" in [step["name"] for step in attach["steps"]]
    assert [step["seq"] for step in attach["steps"]] == sorted(step["seq"] for step in attach["steps"])
    assert attach["checks"] and all(check["passed"] or check["severity"] in ("info", "warn")
                                    for check in attach["checks"])
    assert {"list_outcome", "robots"} <= {check["name"] for check in attach["checks"]}

    # The portal stops answering: healing, the last good tenders stay, and nothing new is published.
    mock.outage = True
    assert refresh(client, pid)["state"] == "healing"
    row, timeline = snapshot(client, pid, "outage")
    assert (row["state"], row["cause"], row["tenderCount"]) == ("healing", "outage", 45)
    assert row["recentReads"] == ["ok", "failed"] and row["deliveryTrend"] == [45] and row["readsLastHour"] == 2
    assert row["lastRun"]["result"] == "failed" and row["nextReadAt"] is not None
    assert [run["id"] for run in timeline][0] == attach["id"] and len(timeline) == 2  # oldest first
    failed = timeline[1]
    assert (failed["trigger"], failed["result"], failed["summary"]) == ("refresh", "failed", row["reason"])
    assert "publishedCount" not in failed and "not answered" in failed["summary"]
    broken = [check for check in failed["checks"] if not check["passed"]]
    assert broken and all(check["severity"] in ("info", "warn", "fail", "block") for check in broken)
    assert failed["stats"]["httpRequests"] > 0 and failed["stats"]["tendersSeen"] == 0

    # It answers again: serving, and the read is a new publication.
    mock.reset()
    assert refresh(client, pid)["state"] == "serving"
    row, timeline = snapshot(client, pid, "recovered")
    assert (row["state"], row["cause"], row["tenderCount"]) == ("serving", None, 45)
    assert row["recentReads"] == ["ok", "failed", "ok"] and row["deliveryTrend"] == [45, 45]
    assert [run["result"] for run in timeline] == ["ok", "failed", "ok"]
    assert timeline[2]["publishedCount"] == 45 and timeline[2]["modelCalls"] == 0
    assert timeline == sorted(timeline, key=lambda run: run["startedAt"])
    assert client.get("/api/portals/nope/timeline").status_code == 404

    # Deleted: gone from the dashboard, and its timeline with it.
    assert client.delete(f"/portals/{pid}").status_code == 204
    assert client.get("/api/dashboard").json()["portals"] == []
    assert client.get(f"/api/portals/{pid}/timeline").status_code == 404


@pytest.mark.parametrize("ignore", [False, True])
def test_the_robots_switch_and_the_time_limit_take_effect_for_the_next_read(site, ignore):
    mock, client = site
    mock.robots_disallow_all = True
    answer = client.post("/api/settings", json={"attachTimeLimitMinutes": 7, "ignoreRobotsTxt": ignore})
    assert answer.status_code == 200 and answer.json() == {"attachTimeLimitMinutes": 7, "ignoreRobotsTxt": ignore}
    assert client.get("/api/dashboard").json()["settings"] == answer.json()

    pid = client.post("/portals", json={"url": URL}).json()["id"]
    portal = settled(client, pid)
    (attach,) = client.get(f"/api/portals/{pid}/timeline").json()
    robots = next(check for check in attach["checks"] if check["name"] == "robots")
    if ignore:
        assert (portal["state"], portal["tenderCount"]) == ("serving", 45)
        assert robots["passed"] and robots["observed"] == {"forbids_every_path": True, "ignored": True}
    else:
        assert (portal["state"], portal["cause"], portal["tenderCount"]) == ("failed", "block", 0)
        assert not robots["passed"] and robots["severity"] == "block"
        assert not any(path.startswith("/tenders") for _, path in mock.requests)  # we obeyed
    fits_timeline([attach])
    fits_dashboard(client.get("/api/dashboard").json())


def test_a_mistyped_euro_rate_does_not_stop_the_app(monkeypatch, caplog):
    # The rate comes from EUR_PER_USD (app/config.py). A value that is no number, or a blank model
    # variable, must leave the app able to start: the default rate is shown and the log says why.
    from app.config import ModelSettings
    from app.main import create_app

    for bad in ("abc", "0,87", "-1", "nan"):
        with caplog.at_level("WARNING", logger="watchtower.dashboard"):
            assert DashboardSettings.from_env({"EUR_PER_USD": bad}).eur_per_usd == ModelSettings().eur_per_usd
        assert "EUR_PER_USD" in caplog.text
        caplog.clear()
    assert DashboardSettings.from_env({"EUR_PER_USD": "", "MODEL_LEARN": ""}).eur_per_usd == ModelSettings().eur_per_usd
    monkeypatch.setenv("EUR_PER_USD", "abc")
    monkeypatch.setenv("MODEL_LEARN", "")
    monkeypatch.delenv("DATA_DIR", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/api/dashboard").json()["eurPerUsd"] == ModelSettings().eur_per_usd
