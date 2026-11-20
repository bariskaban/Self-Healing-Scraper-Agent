"""The app on the SQLite store: chosen by DATA_DIR, and what it holds survives a restart.

Run: pytest tests/test_app_on_database.py
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app, default_store
from app.memory_store import MemoryStore
from app.models import Portal, PortalState, RunResult, url_key
from app.standin_worker import DatabaseIdleWorker

URL = "https://vergabe.example/tenders"


def test_without_data_dir_the_app_keeps_its_records_in_memory(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    store, worker = default_store()
    assert isinstance(store, MemoryStore)


def test_with_data_dir_the_records_live_in_sqlite_and_survive_a_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as client:
        pid = client.post("/portals", json={"url": URL}).json()["id"]
        (attach,) = client.get(f"/portals/{pid}/runs").json()
        assert attach["kind"] == "read" and attach["result"] is None
        assert client.post(f"/portals/{pid}/refresh").json() == {"runId": attach["id"]}
    assert (tmp_path / "watchtower.db").is_file()

    with TestClient(create_app()) as client:  # a new process on the same DATA_DIR
        (portal,) = client.get("/portals").json()
        assert portal["id"] == pid and portal["state"] == "integrating"
        assert portal["reason"] == DatabaseIdleWorker.REASON
        assert client.post("/portals", json={"url": URL + "/"}).json() == {"id": pid}
        assert [run["id"] for run in client.get(f"/portals/{pid}/runs").json()] == [attach["id"]]
        assert client.delete(f"/portals/{pid}").status_code == 204
        assert client.get("/portals").json() == []


def test_the_stand_in_worker_keeps_one_run_per_portal(tmp_path):
    db = Database(tmp_path / "watchtower.db")
    try:
        portal, _ = db.add_portal(Portal(id="p1", url=URL, url_key=url_key(URL)))
        worker = DatabaseIdleWorker(db)
        worker.attach(portal)
        (attach,) = db.list_runs("p1")
        assert db.get_portal("p1").reason == DatabaseIdleWorker.REASON
        assert worker.refresh(portal) == attach.id

        db.save_run(attach.model_copy(update={"finished_at": attach.started_at + timedelta(seconds=5),
                                              "result": RunResult.ok, "state_after": PortalState.serving}))
        fresh = worker.refresh(portal)
        assert fresh != attach.id and db.active_run("p1").id == fresh
        worker.forget("p1")
    finally:
        db.close()


def test_a_store_given_without_a_worker_is_refused(tmp_path):
    db = Database(tmp_path / "watchtower.db")
    try:
        with pytest.raises(ValueError):
            create_app(db)
    finally:
        db.close()
