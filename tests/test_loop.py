"""The read loop end to end on the mock portal: attach, serving, a break, healing, and back.

The app runs in this process on a temporary database; its network layer reaches the mock
portal through an in-process transport on a clock that does not wait. No model is called.
"""
from __future__ import annotations

import hashlib
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter
from app.main import create_app
from mock_portal import MockPortal

URL = "https://mock.example"


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


def test_attach_serving_break_healing_and_back(site):
    mock, client = site
    pid = client.post("/portals", json={"url": URL}).json()["id"]
    assert client.get(f"/portals/{pid}/tenders").json() == []  # nothing is delivered while integrating

    portal = settled(client, pid)
    assert (portal["state"], portal["tenderCount"], portal["cause"]) == ("serving", 45, None)
    assert portal["lastSuccessAt"] is not None

    tenders = {tender["id"]: tender for tender in client.get(f"/portals/{pid}/tenders").json()}
    truth = {tender["id"]: tender for tender in mock.truth()}
    assert set(tenders) == set(truth)
    for tender_id, want in truth.items():
        got = tenders[tender_id]
        assert got["title"] == want["title"] and got["buyerName"] == want["buyer_name"]
        assert got["url"] == want["url"] and got["status"] == "open"
        assert got["publicationDate"] == want["publication_date"].isoformat()
        assert got["submissionDeadline"] == want["submission_deadline"].isoformat(timespec="seconds")
        assert got["cpvCodes"] == want["cpv_codes"]
        # Every file is delivered under its hash; a ZIP is unpacked into the files it holds.
        shas = {document["sha256"] for document in got["documents"]}
        plain = {sha for name, _, sha in want["documents"] if not name.endswith(".zip")}
        assert plain <= shas and None not in shas
    first = next(iter(tenders.values()))["documents"][0]
    body = client.get(first["path"]).content
    assert hashlib.sha256(body).hexdigest() == first["sha256"] and len(body) == first["sizeBytes"]

    runs = client.get(f"/portals/{pid}/runs").json()
    assert [(run["kind"], run["result"]) for run in runs] == [("read", "ok")]

    # The portal stops answering: healing, the last good tenders stay, and no repair starts.
    mock.outage = True
    portal = refresh(client, pid)
    assert (portal["state"], portal["cause"], portal["tenderCount"]) == ("healing", "outage", 45)
    assert "not answered" in portal["reason"] and "recipe is unchanged" in portal["reason"]
    assert len(client.get(f"/portals/{pid}/tenders").json()) == 45

    mock.reset()
    portal = refresh(client, pid)
    assert (portal["state"], portal["cause"]) == ("serving", None)
    assert "served again" in portal["reason"]

    # The layout changes: the list no longer reads, a second look confirms it, healing.
    mock.layout_changed = True
    portal = refresh(client, pid)
    assert (portal["state"], portal["cause"], portal["tenderCount"]) == ("healing", "breakage", 45)
    assert "second look" in portal["reason"]

    mock.reset()
    assert refresh(client, pid)["state"] == "serving"


def test_a_withdrawn_tender_a_removed_one_and_an_emptied_list(site):
    mock, client = site
    pid = client.post("/portals", json={"url": URL}).json()["id"]
    assert settled(client, pid)["state"] == "serving"
    cancelled, removed = mock.ids[0], mock.ids[1]

    mock.withdrawn = {cancelled}
    mock.removed = {removed}
    assert refresh(client, pid)["state"] == "serving"
    status = {tender["id"]: tender["status"] for tender in client.get(f"/portals/{pid}/tenders").json()}
    assert status[cancelled] == "withdrawn" and status[removed] == "closed"
    assert sum(1 for value in status.values() if value == "open") == 43

    # The list is empty and the portal says so itself: still serving, and every tender is closed.
    mock.list_emptied = "with_notice"
    mock.removed = set(mock.ids) | {removed}
    portal = refresh(client, pid)
    assert portal["state"] == "serving" and "lists no open tenders" in portal["reason"]
    status = {tender["id"]: tender["status"] for tender in client.get(f"/portals/{pid}/tenders").json()}
    assert "open" not in status.values() and len(status) == 45


def test_an_emptied_list_without_the_notice_does_not_pass(site):
    mock, client = site
    pid = client.post("/portals", json={"url": URL}).json()["id"]
    assert settled(client, pid)["state"] == "serving"
    mock.list_emptied = "without_notice"
    portal = refresh(client, pid)
    assert (portal["state"], portal["cause"], portal["tenderCount"]) == ("healing", "breakage", 45)


def test_a_login_wall_is_a_block_and_no_read_calls_a_model(site):
    mock, client = site
    pid = client.post("/portals", json={"url": URL}).json()["id"]
    assert settled(client, pid)["state"] == "serving"
    mock.login_wall = "all"
    portal = refresh(client, pid)
    assert (portal["state"], portal["cause"]) == ("failed", "block")
    assert "Login required" in portal["reason"]
    runs = client.get(f"/portals/{pid}/runs").json()
    assert runs[-1]["result"] == "failed"


def test_a_refresh_during_a_read_answers_with_the_run_going_on_and_delete_stops_it(site):
    mock, client = site
    pid = client.post("/portals", json={"url": URL}).json()["id"]
    (attach,) = client.get(f"/portals/{pid}/runs").json()
    if client.get(f"/portals/{pid}/runs").json()[0]["finishedAt"] is None:
        answer = client.post(f"/portals/{pid}/refresh").json()
        still = client.get(f"/portals/{pid}/runs").json()
        assert answer == {"runId": attach["id"]} or still[0]["finishedAt"] is not None
    assert client.delete(f"/portals/{pid}").status_code == 204
    assert client.get("/portals").json() == []
    asked = len(mock.requests)
    time.sleep(0.3)
    assert len(mock.requests) - asked <= 2  # a request already under way may land; nothing after it


def test_a_crashed_read_keeps_the_usage_it_had_saved(tmp_path):
    """The read saves its model calls and cost as it goes. When it crashes, the run row is closed from what is
    stored, not from the copy the loop started with: that one would write the cost back as zero."""
    from datetime import datetime, timezone

    from app.db import Database
    from app.loop import ReadLoop, new_run
    from app.models import Portal, RunResult, RunTrigger, TokenUsage, url_key

    db = Database(tmp_path / "w.db")
    portal = Portal(id="p1", url="https://a.example/", url_key=url_key("https://a.example/"),
                    created_at=datetime(2026, 11, 20, tzinfo=timezone.utc))
    db.add_portal(portal)
    started = db.start_run(new_run(portal, RunTrigger.attach))
    db.save_run(started.model_copy(update={"model_calls": 21, "usage": TokenUsage(input_tokens=954_581, cost_usd=0.41)}))

    loop = ReadLoop(db, None, None)
    loop._crashed("p1", started, ValueError("boom"))     # `started` is the stale copy, as in the loop
    saved = db.get_run(started.id)
    assert saved.result is RunResult.failed and "ValueError: boom" in saved.error
    assert (saved.model_calls, saved.usage.input_tokens, saved.usage.cost_usd) == (21, 954_581, 0.41)
    db.close()
