"""The dashboard's routes (app/dashboard_api.py, docs/DASHBOARD_API.md) on the SQLite store.

Run: pytest tests/test_dashboard_api.py
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.dashboard_api import LiveSettings, Settings, changed_parts
from app.db import Database
from app.main import create_app
from app.memory_store import IdleWorker, MemoryStore
from app.models import (
    AgentStep, Cause, CheckResult, DocsStatus, FileRecord, Portal, PortalState, Recipe, Run, RunKind, RunResult,
    RunStats, RunTrigger, Severity, StepKind, TenderFile, TenderRecord, TokenUsage, url_key,
)
from app.standin_worker import DatabaseIdleWorker

UTC = timezone.utc
CET = timezone(timedelta(hours=1))


def _portal(db: Database, pid: str, host: str, state: PortalState, reason: str, **kw) -> Portal:
    url = f"https://{host}/tenders"
    db.add_portal(Portal(id=pid, url=url, url_key=url_key(url), created_at=kw.pop("created_at")))
    portal = db.get_portal(pid).model_copy(update={"state": state, "reason": reason, **kw})
    db.update_portal(portal)
    return portal


def _run(db: Database, pid: str, rid: str, at: datetime, *, kind=RunKind.read, trigger=RunTrigger.schedule,
         result: RunResult | None = RunResult.ok, minutes: float = 1, **kw) -> Run:
    run = Run(id=rid, portal_id=pid, kind=kind, trigger=trigger, started_at=at, state_before=PortalState.serving)
    db.start_run(run)
    if result is not None:
        run = run.model_copy(update={"finished_at": at + timedelta(minutes=minutes), "result": result, **kw})
    else:
        run = run.model_copy(update=kw)
    db.save_run(run)
    return run


def seed(db: Database, now: datetime) -> None:
    """Five portals, one in each situation the dashboard has to show."""
    ago = lambda minutes: now - timedelta(minutes=minutes)  # noqa: E731
    body = {"format": "recipe/v1", "start": "list", "nodes": [{"id": "list", "kind": "html"},
                                                             {"id": "detail", "kind": "html"}], "edges": []}

    # Serving, learned once with the model, then read without it.
    _portal(db, "tn", "tenderned.example", PortalState.serving,
            "Read at 20:55 found 2 open tenders, 1 new and 0 closed. Every check passed.",
            created_at=ago(90), last_success_at=ago(2), fingerprint="tenderned", timezone="Europe/Amsterdam",
            next_read_at=now + timedelta(minutes=2))
    db.add_recipe(Recipe(portal_id="tn", version=1, body=body, fingerprint="tenderned", created_at=ago(80),
                         rationale="A JSON API with one ZIP per tender."))
    db.activate_recipe("tn", 1, at=ago(80))
    _run(db, "tn", "tn-1", ago(85), trigger=RunTrigger.attach, model_calls=12, recipe_version=1,
         reason_after="Learned the list API and the documents.",
         stats=RunStats(http_requests=40, pages_fetched=12, tenders_seen=2, tenders_new=2),
         usage=TokenUsage(input_tokens=300_000, cached_input_tokens=100_000, output_tokens=40_000,
                          reasoning_tokens=25_000, cost_usd=1.12))
    db.add_checks([CheckResult(run_id="tn-1", name="paging_complete", passed=True, severity=Severity.fail,
                               message="Paging reached the last page."),
                   CheckResult(run_id="tn-1", name="spot_check", passed=True, severity=Severity.fail,
                               message="Every value is quoted on its page.")])
    db.add_step(AgentStep(run_id="tn-1", seq=1, at=ago(85), kind=StepKind.tool, name="open",
                          summary="Opened the entry page; found 1 JSON list call.", duration_ms=900))
    db.add_step(AgentStep(run_id="tn-1", seq=2, at=ago(84), kind=StepKind.llm, name="gpt-6.2-sol",
                          summary="Wrote the list node.", prompt_id="learn/system@1", duration_ms=8000,
                          usage=TokenUsage(input_tokens=30_000, output_tokens=4_000, cost_usd=0.10)))
    for n, minutes in enumerate((40, 20, 2), 2):
        _run(db, "tn", f"tn-{n}", ago(minutes), recipe_version=1, reason_after="Every check passed.",
             stats=RunStats(http_requests=3, tenders_seen=2))
    sha = hashlib.sha256(b"lv").hexdigest()
    lv = FileRecord(file_id=sha[:16], sha256=sha, size_bytes=2, content_type="application/pdf",
                    storage_path=f"files/{sha[:2]}/{sha}", source_url="https://tenderned.example/f/1", downloaded_at=ago(80))
    db.publish_tenders("tn", [TenderRecord(portal_id="tn", tender_id="450411", url="https://tenderned.example/t/450411",
                                           title="Schoonmaak", buyer_name="Gemeente Utrecht",
                                           publication_date=(now - timedelta(days=3)).date(),
                                           submission_deadline=now + timedelta(days=20), first_seen_at=ago(80),
                                           last_seen_at=ago(2), last_changed_at=ago(80), content_hash="a",
                                           docs_status=DocsStatus.complete)])
    db.set_documents("tn", "450411", [lv], [TenderFile(portal_id="tn", tender_id="450411", file_id=lv.file_id,
                                                       file_name="Leidraad.pdf")])

    # Healing: the layout changed, a repair is running and has written recipe 2.
    _portal(db, "mock", "mock.watchtower.test", PortalState.healing,
            "The list reads 9 tenders but the portal prints 23, also on a second read. Repairing.",
            created_at=ago(60), cause=Cause.breakage, last_success_at=ago(15))
    db.add_recipe(Recipe(portal_id="mock", version=1, body=body, created_at=ago(55), rationale="A table."))
    db.activate_recipe("mock", 1, at=ago(55))
    _run(db, "mock", "mock-1", ago(30), recipe_version=1)
    _run(db, "mock", "mock-2", ago(6), result=RunResult.failed, recipe_version=1,
         reason_after="The list reads 9 tenders but the portal prints 23.")
    db.add_checks([CheckResult(run_id="mock-2", name="printed_total", passed=False, severity=Severity.fail,
                               observed=9, expected=23, message="The list reads 9 tenders but the portal prints 23.")])
    changed = {**body, "nodes": [{"id": "list", "kind": "html", "items": "div.card"}, {"id": "detail", "kind": "html"}]}
    db.add_recipe(Recipe(portal_id="mock", version=2, parent_version=1, body=changed, created_at=ago(3),
                         rationale="The rows became cards; the list locator now reads div.card."))
    _run(db, "mock", "mock-3", ago(5), kind=RunKind.repair, trigger=RunTrigger.heal, result=None, recipe_version=2,
         model_calls=3, usage=TokenUsage(input_tokens=90_000, output_tokens=9_000, cost_usd=0.27))
    db.add_step(AgentStep(run_id="mock-3", seq=1, at=ago(4), kind=StepKind.decision, name="patch",
                          summary="Patching the list node: rows are now cards."))

    # Failed at a login.
    _portal(db, "mercell", "my.mercell.example", PortalState.failed,
            "Login required: the tender list redirects to /login and shows a password field. We do not log in.",
            created_at=ago(50), cause=Cause.block)
    _run(db, "mercell", "mercell-1", ago(48), trigger=RunTrigger.attach, result=RunResult.failed,
         reason_after="Login required.")
    db.add_checks([CheckResult(run_id="mercell-1", name="login", passed=False, severity=Severity.block,
                               message="Login required: the tender list redirects to /login.")])

    # Failed after an outage of more than an hour.
    _portal(db, "place", "marches-publics.example", PortalState.failed,
            "The portal has been unreachable for 3 hours (HTTP 503). This is not a login block.",
            created_at=ago(240), cause=Cause.outage)
    _run(db, "place", "place-1", ago(200), trigger=RunTrigger.attach, result=RunResult.failed,
         reason_after="HTTP 503, three tries.")
    db.add_checks([CheckResult(run_id="place-1", name="outage", passed=False, severity=Severity.outage,
                               message="The portal did not answer (HTTP 503, 3 tries).")])

    # Integrating: the first read is running.
    _portal(db, "es", "contrataciondelestado.example", PortalState.integrating, "Reading tender 120 of 430.",
            created_at=ago(10))
    _run(db, "es", "es-1", ago(9), trigger=RunTrigger.attach, result=None)


NOW = datetime(2026, 11, 20, 21, 0, tzinfo=UTC)


@pytest.fixture
def seeded(tmp_path):
    db = Database(tmp_path / "watchtower.db")
    seed(db, datetime.now(UTC))
    live = LiveSettings(Settings(attachTimeLimitMinutes=20, ignoreRobotsTxt=False), tmp_path / "settings.json")
    with TestClient(create_app(db, DatabaseIdleWorker(db), live_settings=live)) as client:
        yield client, db, tmp_path
    db.close()


def test_the_snapshot_holds_every_portal_as_the_store_has_it(seeded):
    client, _, _ = seeded
    answer = client.get("/api/dashboard")
    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
    snap = answer.json()
    assert snap["eurPerUsd"] == 0.9 and snap["settings"] == {"attachTimeLimitMinutes": 20, "ignoreRobotsTxt": False}
    rows = {p["id"]: p for p in snap["portals"]}
    assert set(rows) == {"tn", "mock", "mercell", "place", "es"}

    tn = rows["tn"]
    assert (tn["state"], tn["tenderCount"], tn["fingerprint"], tn["recipeVersion"]) == ("serving", 1, "tenderned", 1)
    assert tn["recentReads"] == ["ok", "ok", "ok", "ok"] and tn["readsLastHour"] == 3
    assert tn["lastRun"] == {"id": "tn-4", "kind": "read", "result": "ok"}
    assert tn["usage"]["costUsd"] == pytest.approx(1.12) and tn["usage"]["costEur"] == pytest.approx(1.008)
    assert tn["usage"]["inputTokens"] == 300_000 and tn["deliveryTrend"] == []

    mock = rows["mock"]
    assert (mock["state"], mock["cause"]) == ("healing", "breakage")
    assert mock["lastRun"] == {"id": "mock-3", "kind": "repair", "result": None}
    assert mock["recentReads"] == ["ok", "failed"]  # reads only; the repair is in lastRun
    assert (rows["mercell"]["cause"], rows["place"]["cause"], rows["es"]["cause"]) == ("block", "outage", None)
    assert rows["es"]["recentReads"] == [None] and rows["es"]["tenderCount"] == 0


def test_a_timeline_has_each_runs_checks_steps_usage_and_recipe_change(seeded):
    client, _, _ = seeded
    tn = client.get("/api/portals/tn/timeline").json()
    assert [r["id"] for r in tn] == ["tn-1", "tn-2", "tn-3", "tn-4"]
    attach = tn[0]
    assert (attach["trigger"], attach["modelCalls"], attach["recipeVersion"]) == ("attach", 12, 1)
    assert attach["summary"] == "Learned the list API and the documents."
    assert attach["stats"]["httpRequests"] == 40 and attach["usage"]["reasoningTokens"] == 25_000
    assert [c["name"] for c in attach["checks"]] == ["paging_complete", "spot_check"]
    assert [s["kind"] for s in attach["steps"]] == ["tool", "llm"]
    assert attach["steps"][1]["usage"]["costEur"] == pytest.approx(0.09) and "usage" not in attach["steps"][0]
    assert "usage" not in tn[1]  # no model call: known zero, left out as the format says

    mock = client.get("/api/portals/mock/timeline").json()
    repair = mock[-1]
    assert (repair["kind"], repair["result"], repair["finishedAt"]) == ("repair", None, None)
    assert repair["summary"] == "Patching the list node: rows are now cards."  # running: the last step
    assert repair["recipeChange"] == {"from": 1, "to": 2, "changedParts": ["node list"],
                                      "rationale": "The rows became cards; the list locator now reads div.card."}
    failed = mock[1]
    assert failed["checks"][0] | {} == {"name": "printed_total", "passed": False, "severity": "fail",
                                        "message": "The list reads 9 tenders but the portal prints 23.",
                                        "observed": 9, "expected": 23}
    place = client.get("/api/portals/place/timeline").json()
    assert place[0]["checks"][0]["severity"] == "outage"


def test_an_unknown_portal_has_no_timeline(seeded):
    client, _, _ = seeded
    assert client.get("/api/portals/nope/timeline").status_code == 404


def test_settings_are_changed_checked_and_kept_across_a_restart(seeded):
    client, _, folder = seeded
    answer = client.post("/api/settings", json={"attachTimeLimitMinutes": 30, "ignoreRobotsTxt": True})
    assert answer.status_code == 200 and answer.json() == {"attachTimeLimitMinutes": 30, "ignoreRobotsTxt": True}
    assert client.get("/api/dashboard").json()["settings"] == {"attachTimeLimitMinutes": 30, "ignoreRobotsTxt": True}
    for bad in ({"attachTimeLimitMinutes": 0, "ignoreRobotsTxt": True},
                {"attachTimeLimitMinutes": "30", "ignoreRobotsTxt": True},
                {"attachTimeLimitMinutes": 2.5, "ignoreRobotsTxt": True},
                {"attachTimeLimitMinutes": 30, "ignoreRobotsTxt": "yes"},
                {"attachTimeLimitMinutes": 30},
                {"attachTimeLimitMinutes": 30, "ignoreRobotsTxt": True, "extra": 1}):
        assert client.post("/api/settings", json=bad).status_code == 422, bad
    restarted = LiveSettings.from_env({"DATA_DIR": str(folder)})
    assert restarted.current() == Settings(attachTimeLimitMinutes=30, ignoreRobotsTxt=True)


def test_settings_start_from_the_environment(tmp_path):
    live = LiveSettings.from_env({"ATTACH_TIME_LIMIT_SECONDS": "600", "IGNORE_ROBOTS_TXT": "true"})
    assert live.current() == Settings(attachTimeLimitMinutes=10, ignoreRobotsTxt=True)
    (tmp_path / "settings.json").write_text("not json", encoding="utf-8")
    assert LiveSettings.from_env({"DATA_DIR": str(tmp_path)}).current().attachTimeLimitMinutes == 20


def test_the_in_memory_store_answers_without_checks_or_steps():
    store = MemoryStore()
    with TestClient(create_app(store, IdleWorker(store))) as client:
        pid = client.post("/portals", json={"url": "https://a.example/list"}).json()["id"]
        (row,) = client.get("/api/dashboard").json()["portals"]
        assert row["id"] == pid and row["recentReads"] == [None]
        (run,) = client.get(f"/api/portals/{pid}/timeline").json()
        assert "checks" not in run and "steps" not in run  # "No checks recorded", never "All passed"


def test_changed_parts_name_the_nodes_and_parts_that_differ():
    old = {"start": "list", "nodes": [{"id": "list", "items": "tr"}, {"id": "detail"}], "edges": [], "identity": {"a": 1}}
    new = {"start": "list", "nodes": [{"id": "list", "items": "div"}, {"id": "files"}], "edges": [], "identity": {"a": 2}}
    assert changed_parts(old, new) == ["node detail", "node files", "node list", "identity"]
