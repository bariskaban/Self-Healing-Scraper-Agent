"""The local demo (`python -m mock_portal.demo`): the product on the mock portal without FETCH_MODE.

Run: pytest tests/mock_portal/test_demo.py
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from mock_portal import MockPortal
from mock_portal.demo import DEMO_URL, build_app


def settled(client: TestClient, pid: str, seconds: float = 30.0) -> dict:
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        runs = client.get(f"/portals/{pid}/runs").json()
        if runs and all(run["finishedAt"] is not None for run in runs):
            return client.get(f"/portals/{pid}").json()
        time.sleep(0.02)
    raise AssertionError("the read did not end in time")


def test_the_demo_app_reads_its_mock_portal_with_no_fetch_mode_and_no_network(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FETCH_MODE", raising=False)  # the default, replay: the demo must not need more
    mock = MockPortal(base_url=DEMO_URL)
    with TestClient(build_app(mock, requests_per_second=2000.0)) as client:
        pid = client.post("/portals", json={"url": DEMO_URL}).json()["id"]
        portal = settled(client, pid)
        assert (portal["state"], portal["tenderCount"]) == ("serving", 45)
        tender = client.get(f"/portals/{pid}/tenders").json()[0]
        assert tender["url"].startswith(DEMO_URL) and tender["documents"]
        assert client.get("/mock/").status_code == 200  # the pages being read can be looked at
        assert client.get("/api/dashboard").json()["portals"][0]["deliveryTrend"] == [45]

        # Any other address is not fetched at all: nothing here can learn it.
        asked = len(mock.requests)
        other = client.post("/portals", json={"url": "https://tenders.example.org/list"}).json()["id"]
        portal = settled(client, other)
        assert portal["state"] == "failed" and "No recipe could be learned" in portal["reason"]
        assert len(mock.requests) == asked


def test_the_demo_has_a_second_portal_and_switches_that_change_the_mock_portals_only(monkeypatch, tmp_path):
    from mock_portal.demo import LOGIN_URL

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    mock, second = MockPortal(base_url=DEMO_URL), MockPortal(tenders=12, base_url=LOGIN_URL)
    with TestClient(build_app(mock, requests_per_second=2000.0, second=second)) as client:
        first = client.post("/portals", json={"url": DEMO_URL}).json()["id"]
        walled = client.post("/portals", json={"url": LOGIN_URL}).json()["id"]
        assert (settled(client, first)["tenderCount"], settled(client, walled)["tenderCount"]) == (45, 12)
        assert client.get(f"/portals/{walled}/tenders").json()[0]["url"].startswith(LOGIN_URL)

        # The login wall blocks the second portal and leaves the first one serving.
        assert client.post("/demo/login-wall").json()[LOGIN_URL] == {"login_wall": "all"}
        assert client.get(f"/portals/{walled}").json()["state"] == "serving"  # a switch reads nothing itself
        client.post(f"/portals/{walled}/refresh")
        portal = settled(client, walled)
        assert portal["state"] == "failed" and "Login required" in portal["reason"] and portal["tenderCount"] == 12
        client.post(f"/portals/{first}/refresh")
        assert settled(client, first)["state"] == "serving"

        # The layout switch breaks the first portal; with no key there is no repairer, so it stays broken.
        assert client.post("/demo/layout").json()[DEMO_URL] == {"layout_changed": True}
        client.post(f"/portals/{first}/refresh")
        portal = settled(client, first)
        assert portal["state"] == "healing" and portal["tenderCount"] == 45
        runs = client.get(f"/demo/runs/{first}").json()
        assert [run["result"] for run in runs] == ["ok", "ok", "failed"] and runs[-1]["modelCalls"] == 0
        assert runs[-1]["stateAfter"] == "healing" and runs[0]["recipeVersion"] == 1

        assert client.post("/demo/reset").json() == {DEMO_URL: {"layout_changed": False},
                                                     LOGIN_URL: {"login_wall": "none"}}
        client.post(f"/portals/{first}/refresh")
        assert settled(client, first)["state"] == "serving"
