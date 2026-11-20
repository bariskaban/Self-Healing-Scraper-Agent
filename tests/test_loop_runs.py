"""The runs of the read loop: each is read once, under the trigger that asked for it, one at a time.

Three parts: a refresh that meets a scheduled read at the very moment it starts (both orders,
made to happen with a database that waits where the race is); refreshes sent without pause
while the app reads the mock portal on a short interval; and a start on a database whose run
was cut short by a restart. Run: pytest tests/test_loop_runs.py
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import Counter
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient

from app.db import Database
from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter
from app.loop import ReadLoop
from app.main import create_app, portal_id_for
from app.models import Portal, PortalState, Run, RunResult, RunTrigger, url_key, utcnow
from app.reader import ReadOutcome, new_run
from app.scheduler import SchedulerSettings
from mock_portal import MockPortal

URL = "https://mock.example"
PID = "p1"


class RacingDatabase(Database):
    """A database that stops a scheduled read where it starts its run, until the test lets it go."""

    def __init__(self, path, wait: str) -> None:
        super().__init__(path)
        self.wait = wait  # "before": the run is not stored yet; "after": it is
        self.reached, self.go = threading.Event(), threading.Event()

    def start_run(self, run: Run) -> Run:
        if run.trigger is not RunTrigger.schedule or self.reached.is_set():
            return super().start_run(run)
        if self.wait == "before":
            self.reached.set()
            self.go.wait(5)
            return super().start_run(run)
        stored = super().start_run(run)
        self.reached.set()
        self.go.wait(5)
        return stored


class NotingReader:
    """Stands in for the reader: notes each read it is asked for, and ends the run as passed."""

    schedule = SchedulerSettings()

    def __init__(self, database: Database) -> None:
        self.db = database
        self.reads: list[tuple[str, RunTrigger, bool, bool]] = []

    def read(self, portal_id, run, incident, *, first_page_only=False, cancel=None) -> ReadOutcome:
        still_open = self.db.get_run(run.id).finished_at is None
        self.reads.append((run.id, run.trigger, first_page_only, still_open))
        self.db.save_run(run.model_copy(update={"finished_at": utcnow(), "result": RunResult.ok,
                                                "state_after": PortalState.serving}))
        return ReadOutcome(None, PortalState.serving, True)


class NoNetwork:
    def forget(self, portal_id: str) -> None:
        return None


def collide(tmp_path, wait: str) -> tuple[str, list, list[Run], dict]:
    """A refresh arrives while the loop's own scheduled read is starting its run."""
    db = RacingDatabase(tmp_path / "watchtower.db", wait)
    portal, _ = db.add_portal(Portal(id=PID, url=URL, url_key=url_key(URL)))
    portal = portal.model_copy(update={"state": PortalState.serving, "recipe_version": 1})
    db.update_portal(portal)
    reader = NotingReader(db)

    async def scenario() -> tuple[str, dict]:
        loop = ReadLoop(db, reader, NoNetwork())
        loop._due[PID] = utcnow() - timedelta(seconds=1)  # a scheduled read is due
        loop._first_page[PID] = True                      # and it would be a first-page read
        loop._spawn(PID)
        assert await asyncio.to_thread(db.reached.wait, 5)
        if wait == "after":
            # The refresh looked for a run going on just before the scheduled one was stored.
            db.active_run = lambda portal_id: None  # type: ignore[method-assign]
        answer = loop.refresh(portal)
        db.__dict__.pop("active_run", None)
        db.go.set()
        until = time.monotonic() + 5
        while not reader.reads and time.monotonic() < until:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)  # time for a second read of the same run, if the loop made one
        queued = dict(loop._queued)
        await loop.stop()
        return answer, queued

    try:
        answer, queued = asyncio.run(scenario())
        return answer, reader.reads, db.list_runs(PID), queued
    finally:
        db.close()


def test_a_refresh_that_starts_its_run_just_before_a_scheduled_read_is_read_once_as_a_refresh(tmp_path):
    answer, reads, runs, queued = collide(tmp_path, "before")
    # The loop's own read found the refresh's run open and read that one: in full, and once.
    assert reads == [(answer, RunTrigger.refresh, False, True)]
    assert [(run.id, run.trigger, run.result) for run in runs] == [(answer, RunTrigger.refresh, RunResult.ok)]
    assert queued == {}


def test_a_refresh_just_after_a_scheduled_read_started_answers_with_that_run_and_queues_nothing(tmp_path):
    answer, reads, runs, queued = collide(tmp_path, "after")
    # One run only, the scheduled one, read once; the refresh was answered with it (the run going on).
    assert reads == [(answer, RunTrigger.schedule, True, True)]
    assert [(run.id, run.trigger, run.result) for run in runs] == [(answer, RunTrigger.schedule, RunResult.ok)]
    assert queued == {}


def mock_app(mock: MockPortal):
    clock = [0.0]
    limiter = PortalLimiter(1.0, 10.0, clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    fetcher = Fetcher(FetchSettings(mode=FetchMode.live), transport=httpx.MockTransport(mock.handle),
                      limiter=limiter, clock=lambda: clock[0], rng=lambda: 0.0)
    return create_app(fetch=fetcher, mock=mock)


def test_refreshes_without_pause_during_and_between_reads(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("READ_INTERVAL_SECONDS", "0.05")  # scheduled reads start all the time
    answered: list[str] = []
    with TestClient(mock_app(MockPortal())) as client:
        pid = client.post("/portals", json={"url": URL}).json()["id"]
        until = time.monotonic() + 2.5
        while time.monotonic() < until:
            answered.append(client.post(f"/portals/{pid}/refresh").json()["runId"])
        # Every run a refresh was answered with ends: none is left for no read to finish.
        until = time.monotonic() + 20
        while time.monotonic() < until:
            runs = {run["id"]: run for run in client.get(f"/api/portals/{pid}/timeline").json()}
            if all(runs[run_id]["finishedAt"] is not None for run_id in set(answered)):
                break
            time.sleep(0.02)
        assert client.delete(f"/portals/{pid}").status_code == 204  # stops the scheduled reads
        time.sleep(0.2)

    assert set(answered) <= set(runs)
    by_trigger = Counter(runs[run_id]["trigger"] for run_id in answered)
    assert by_trigger["refresh"] > 0 and set(by_trigger) <= {"attach", "schedule", "refresh"}
    ended = [run for run in runs.values() if run["finishedAt"] is not None]
    assert all(runs[run_id] in ended for run_id in answered)
    assert len(runs) - len(ended) <= 1  # at most the read that was going on when we looked
    # No run was read twice (a second read of an ended run cannot store its steps, and fails it).
    assert [run["id"] for run in ended if run["result"] != "ok"] == []
    assert all([step["name"] for step in run["steps"]].count("read_list") == 1 for run in ended)
    # A run under the trigger `refresh` is one a refresh call started, and was answered with.
    assert {run["id"] for run in runs.values() if run["trigger"] == "refresh"} <= set(answered)
    assert [run["trigger"] for run in runs.values()].count("attach") == 1
    # One run at a time: each begins after the one before it ended.
    spans = sorted((run["startedAt"], run["finishedAt"]) for run in ended)
    assert all(later[0] >= earlier[1] for earlier, later in zip(spans, spans[1:]))


def test_after_a_restart_the_cut_run_is_closed_as_failed_and_the_portal_is_read_again(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    pid = portal_id_for(URL)
    db = Database(tmp_path / "watchtower.db")  # what a process that stopped during an attach left behind
    portal, _ = db.add_portal(Portal(id=pid, url=URL, url_key=url_key(URL)))
    cut = db.start_run(new_run(portal, RunTrigger.attach))
    db.close()

    with TestClient(mock_app(MockPortal())) as client:
        until = time.monotonic() + 30
        while time.monotonic() < until:
            runs = client.get(f"/api/portals/{pid}/timeline").json()
            if len(runs) == 2 and all(run["finishedAt"] is not None for run in runs):
                break
            time.sleep(0.02)
        first, again = runs
        assert (first["id"], first["trigger"], first["result"]) == (cut.id, "attach", "failed")
        assert "cut short by a restart" in first["summary"]
        # Nobody called the API: the loop read the portal again by itself, and it is still the attach.
        assert (again["trigger"], again["result"]) == ("attach", "ok")
        portal = client.get(f"/portals/{pid}").json()
        assert (portal["state"], portal["tenderCount"]) == ("serving", 45)
