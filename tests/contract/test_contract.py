"""Every call of the track description's appendix, with the exact answer it asks for."""
from __future__ import annotations

import time
import uuid

import pytest

from tests.contract.schema import check_portal, check_run, check_tender

UNKNOWN = "no-such-id-0000"


def is_json(answer) -> bool:
    return answer.headers.get("content-type", "").split(";")[0].strip() == "application/json"


def runs_of(api, portal_id, wait_seconds: float = 5.0) -> list:
    """The portal's runs; waits briefly for the first one, which the attach creates in the background."""
    deadline = time.monotonic() + wait_seconds
    while True:
        answer = api.get(f"/portals/{portal_id}/runs")
        assert answer.status_code == 200 and is_json(answer), answer.text
        runs = answer.json()
        if runs or time.monotonic() >= deadline:
            return runs
        time.sleep(0.2)


# -- POST /portals -------------------------------------------------------------

def test_adding_a_portal_answers_201_with_its_id(api, address):
    answer = api.post("/portals", json={"url": address})
    try:
        assert answer.status_code == 201 and is_json(answer)
        body = answer.json()
        assert set(body) == {"id"} and isinstance(body["id"], str) and body["id"]
    finally:
        api.delete(f"/portals/{answer.json()['id']}")


def test_the_same_address_twice_returns_the_same_id(api, address, portal_id):
    again = api.post("/portals", json={"url": address})
    assert again.status_code == 201 and again.json() == {"id": portal_id}
    listed = [p["id"] for p in api.get("/portals").json()]
    assert listed.count(portal_id) == 1


def test_the_same_address_written_differently_is_the_same_portal(api, address, portal_id):
    host, path = address.removeprefix("https://").split("/", 1)
    for variant in (f"https://{host.upper()}/{path}", f"{address}/", f"{address}#top", f"https://{host}:443/{path}"):
        assert api.post("/portals", json={"url": variant}).json() == {"id": portal_id}, variant


@pytest.mark.parametrize("body", [{}, {"url": ""}, {"url": "not an address"}, {"url": "ftp://x.example/"},
                                  {"address": "https://x.example"}])
def test_a_body_without_a_usable_address_is_refused(api, body):
    before = len(api.get("/portals").json())
    answer = api.post("/portals", json=body)
    assert 400 <= answer.status_code < 500, answer.text
    assert len(api.get("/portals").json()) == before


# -- GET /portals, GET /portals/{id} ------------------------------------------

def test_a_portal_has_every_field_of_the_contract(api, address, portal_id):
    answer = api.get(f"/portals/{portal_id}")
    assert answer.status_code == 200 and is_json(answer)
    portal = answer.json()
    check_portal(portal)
    assert portal["id"] == portal_id and portal["url"] == address


def test_portals_is_a_bare_list_that_holds_the_portal(api, portal_id):
    answer = api.get("/portals")
    assert answer.status_code == 200 and is_json(answer)
    portals = answer.json()
    assert isinstance(portals, list)
    for portal in portals:
        check_portal(portal)
    assert portal_id in [p["id"] for p in portals]
    assert next(p for p in portals if p["id"] == portal_id) == api.get(f"/portals/{portal_id}").json()


# -- GET /portals/{id}/tenders ------------------------------------------------

def test_tenders_is_a_bare_list_of_tenders(api, portal_id):
    answer = api.get(f"/portals/{portal_id}/tenders")
    assert answer.status_code == 200 and is_json(answer)
    tenders = answer.json()
    assert isinstance(tenders, list)
    for tender in tenders:
        check_tender(tender)
    portal = api.get(f"/portals/{portal_id}").json()
    if portal["state"] == "integrating":
        assert tenders == [], "nothing is delivered while a portal is integrating"


@pytest.mark.parametrize("value", [
    "2026-12-09T10:00:00+01:00",   # as the brief writes it; the client percent-encodes the plus
    "2026-12-09T10:00:00Z",
    "2026-12-09T10:00:00.250-05:00",
])
def test_changed_since_takes_a_time_with_offset(api, portal_id, value):
    answer = api.get(f"/portals/{portal_id}/tenders", params={"changedSince": value})
    assert answer.status_code == 200 and isinstance(answer.json(), list), answer.text


def test_changed_since_with_a_plus_that_was_not_encoded(api, portal_id):
    # Written straight into the address, "+" reaches the server as a space.
    answer = api.get(f"/portals/{portal_id}/tenders?changedSince=2026-12-09T10:00:00+01:00")
    assert answer.status_code == 200 and isinstance(answer.json(), list), answer.text


def test_changed_since_far_in_the_future_leaves_nothing(api, portal_id):
    answer = api.get(f"/portals/{portal_id}/tenders", params={"changedSince": "2999-01-01T00:00:00+00:00"})
    assert answer.status_code == 200 and answer.json() == []


def test_changed_since_that_is_no_time_answers_400(api, portal_id):
    answer = api.get(f"/portals/{portal_id}/tenders", params={"changedSince": "yesterday"})
    assert answer.status_code == 400 and is_json(answer)


# -- GET /portals/{id}/runs ---------------------------------------------------

def test_runs_is_a_list_and_the_first_attach_is_a_read(api, portal_id):
    runs = runs_of(api, portal_id)
    assert isinstance(runs, list) and runs, "the attach is recorded as a run"
    for run in runs:
        check_run(run)
    assert runs[0]["kind"] == "read"
    assert [r["startedAt"] for r in runs] == sorted(r["startedAt"] for r in runs), "oldest first"


# -- POST /portals/{id}/refresh -----------------------------------------------

def test_refresh_answers_202_with_a_run_id(api, portal_id):
    answer = api.post(f"/portals/{portal_id}/refresh")
    assert answer.status_code == 202 and is_json(answer)
    body = answer.json()
    assert set(body) == {"runId"} and isinstance(body["runId"], str) and body["runId"]
    assert body["runId"] in [r["id"] for r in runs_of(api, portal_id)]


def test_refresh_while_a_read_is_running_answers_with_that_read(api, portal_id):
    running = [r for r in runs_of(api, portal_id) if r["finishedAt"] is None]
    if not running:
        pytest.skip("the attach finished before the test could refresh")
    first = api.post(f"/portals/{portal_id}/refresh").json()["runId"]
    still_running = [r["id"] for r in runs_of(api, portal_id) if r["finishedAt"] is None]
    if first in still_running:
        assert api.post(f"/portals/{portal_id}/refresh").json()["runId"] == first


# -- DELETE /portals/{id} -----------------------------------------------------

def test_delete_answers_204_and_the_id_is_unknown_afterwards(api, address):
    portal_id = api.post("/portals", json={"url": address}).json()["id"]
    answer = api.delete(f"/portals/{portal_id}")
    assert answer.status_code == 204 and answer.content == b""
    assert api.get(f"/portals/{portal_id}").status_code == 404
    assert api.get(f"/portals/{portal_id}/tenders").status_code == 404
    assert api.get(f"/portals/{portal_id}/runs").status_code == 404
    assert api.post(f"/portals/{portal_id}/refresh").status_code == 404
    assert api.delete(f"/portals/{portal_id}").status_code == 404
    assert portal_id not in [p["id"] for p in api.get("/portals").json()]


def test_an_address_added_again_after_a_delete_gets_the_same_id_and_a_fresh_attach(api, address):
    first = api.post("/portals", json={"url": address}).json()["id"]
    api.delete(f"/portals/{first}")
    again = api.post("/portals", json={"url": address})
    try:
        assert again.status_code == 201 and again.json() == {"id": first}
        portal = api.get(f"/portals/{first}").json()
        check_portal(portal)
        assert portal["tenderCount"] == 0 and portal["lastSuccessAt"] is None
    finally:
        api.delete(f"/portals/{first}")


# -- unknown ids, the dashboard, documents ------------------------------------

@pytest.mark.parametrize("method, path", [
    ("GET", f"/portals/{UNKNOWN}"), ("DELETE", f"/portals/{UNKNOWN}"), ("POST", f"/portals/{UNKNOWN}/refresh"),
    ("GET", f"/portals/{UNKNOWN}/tenders"), ("GET", f"/portals/{UNKNOWN}/runs"), ("GET", f"/files/{UNKNOWN}"),
])
def test_an_unknown_id_answers_404(api, method, path):
    answer = api.request(method, path)
    assert answer.status_code == 404 and is_json(answer), answer.text


def test_the_dashboard_is_a_page_at_the_root(api):
    answer = api.get("/")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/html")


def test_no_route_asks_for_authentication(api, portal_id):
    for path in ("/portals", f"/portals/{portal_id}", f"/portals/{portal_id}/tenders", f"/portals/{portal_id}/runs"):
        answer = api.get(path)
        assert answer.status_code == 200 and "www-authenticate" not in answer.headers


def test_many_portals_added_at_once_all_answer(api):
    addresses = [f"https://contract-{uuid.uuid4().hex[:12]}.example/" for _ in range(20)]
    ids = [api.post("/portals", json={"url": a}).json()["id"] for a in addresses]
    try:
        assert len(set(ids)) == 20
        for portal in api.get("/portals").json():
            check_portal(portal)
        assert set(ids) <= {p["id"] for p in api.get("/portals").json()}
    finally:
        for portal_id in ids:
            api.delete(f"/portals/{portal_id}")
