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
