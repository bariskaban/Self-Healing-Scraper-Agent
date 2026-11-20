"""The contract test plays the judges: it calls the API the way the track description says.

By default it runs against the app in this process. With CONTRACT_BASE_URL set (for example
http://localhost:8080) it runs against a running container instead, which is what CI does.

It only ever adds addresses under the reserved name `.example`, which never resolves, so
no request can reach a real portal (CLAUDE.md, "no live portals").
"""
from __future__ import annotations

import os
import uuid

import pytest


@pytest.fixture(scope="session")
def api():
    """An HTTP client for the API under test."""
    base_url = os.environ.get("CONTRACT_BASE_URL")
    if base_url:
        import httpx

        with httpx.Client(base_url=base_url, timeout=15.0) as client:
            yield client
        return
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def address() -> str:
    """A portal address no other test uses, on a name that cannot resolve."""
    return f"https://contract-{uuid.uuid4().hex[:12]}.example/tenders"


@pytest.fixture
def portal_id(api, address):
    """A freshly added portal, removed again after the test."""
    answer = api.post("/portals", json={"url": address})
    assert answer.status_code == 201, answer.text
    portal = answer.json()["id"]
    yield portal
    api.delete(f"/portals/{portal}")
