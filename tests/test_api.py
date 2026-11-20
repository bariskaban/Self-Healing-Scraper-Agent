"""The API on a store that holds tenders, documents and runs. Run: pytest tests/test_api.py

The contract test (tests/contract/) plays the judges against an empty system. These tests put
records in place and check what the routes make of them.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.docs import DocsSettings, FileStore
from app.main import create_app, parse_changed_since, portal_id_for
from app.memory_store import IdleWorker, MemoryStore
from app.models import (
    Cause, DocsStatus, FileRecord, Portal, PortalState, Run, RunKind, RunResult, RunTrigger,
    TenderFile, TenderRecord, url_key,
)
from tests.contract.schema import check_portal, check_run, check_tender

UTC = timezone.utc
CET = timezone(timedelta(hours=1))
URL = "https://vergabe.example/tenders"
PDF = b"%PDF-1.7\n" + b"x" * 300


@pytest.fixture
def system(tmp_path):
    """A client on a store with one serving portal, three tenders, one stored document and two runs."""
    store = MemoryStore()
    files = FileStore(DocsSettings(data_dir=tmp_path / "data"))
    client = TestClient(create_app(store, IdleWorker(store), files=lambda: files))
    portal_id = portal_id_for(URL)
    now = datetime.now(UTC)
    store.put_portal(Portal(id=portal_id, url=URL, url_key=url_key(URL), state=PortalState.serving,
                            reason="Read at 14:02 UTC found 2 open tenders, 0 new and 1 closed. Every check passed.",
                            last_success_at=now - timedelta(minutes=2), created_at=now - timedelta(hours=1)))

    with files.writer() as writer:
        writer.write(PDF)
        blob = writer.commit()
    stored = FileRecord(file_id=blob.file_id, sha256=blob.sha256, size_bytes=blob.size_bytes,
                        content_type="application/pdf", storage_path=blob.storage_path, source_url=f"{URL}/1/lv.pdf")
    loading = FileRecord(file_id="p00000000000001", source_url=f"{URL}/1/plan.pdf", size_bytes=52_000)

    def tender(number: int, **changes) -> TenderRecord:
        base = dict(portal_id=portal_id, tender_id=f"T-{number}", url=f"{URL}/{number}", title=f"Road works {number}",
                    buyer_name="Stadt Beispiel", publication_date=date(2026, 11, 2),
                    submission_deadline=now + timedelta(days=10 + number), docs_status=DocsStatus.complete,
                    last_changed_at=now - timedelta(days=number))
        return TenderRecord(**{**base, **changes})

    store.put_tender(tender(1, reference_number="2026/17", cpv_codes=["45233120-6"]), [
        (TenderFile(portal_id=portal_id, tender_id="T-1", file_id=stored.file_id, file_name="LV.pdf"), stored),
        (TenderFile(portal_id=portal_id, tender_id="T-1", file_id=loading.file_id, file_name="Plan.pdf", position=1),
         loading),
    ])
    store.put_tender(tender(2, buyer_name=None, docs_status=DocsStatus.pending))
    # Changed three days ago; its deadline passed an hour ago, which is a change of its own.
    store.put_tender(tender(3, submission_deadline=now - timedelta(hours=1)))

    store.put_run(Run(id="run-attach", portal_id=portal_id, kind=RunKind.read, trigger=RunTrigger.attach,
                      started_at=now - timedelta(hours=1), finished_at=now - timedelta(minutes=50),
                      result=RunResult.ok, state_before=PortalState.integrating))
    store.put_run(Run(id="run-repair", portal_id=portal_id, kind=RunKind.repair, trigger=RunTrigger.heal,
                      started_at=now - timedelta(minutes=20), finished_at=now - timedelta(minutes=15),
                      result=RunResult.failed, state_before=PortalState.healing))
    return client, store, portal_id, stored, now


def test_a_serving_portal_counts_every_tender_it_delivers(system):
    client, _, portal_id, _, _ = system
    portal = client.get(f"/portals/{portal_id}").json()
    check_portal(portal)
    assert portal["state"] == "serving" and portal["tenderCount"] == 3 and portal["cause"] is None
    assert portal["lastSuccessAt"].endswith("+00:00")


def test_a_portal_that_is_not_serving_says_why(system):
    client, store, portal_id, _, _ = system
    store.put_portal(store.get_portal(portal_id).model_copy(update={
        "state": PortalState.healing, "cause": Cause.outage,
        "reason": "The portal has not answered since 14:07 UTC (HTTP 503, 3 tries)."}))
    portal = client.get(f"/portals/{portal_id}").json()
    check_portal(portal)
    assert portal["state"] == "healing" and portal["cause"] == "outage"
    # While healing, the last correct tenders are still served.
    assert len(client.get(f"/portals/{portal_id}/tenders").json()) == 3


def test_tenders_follow_the_contract(system):
    client, _, portal_id, stored, _ = system
    tenders = {t["id"]: t for t in client.get(f"/portals/{portal_id}/tenders").json()}
    assert sorted(tenders) == ["T-1", "T-2", "T-3"]
    for tender in tenders.values():
        check_tender(tender)

    first = tenders["T-1"]
    assert first["status"] == "open" and first["referenceNumber"] == "2026/17" and first["cpvCodes"] == ["45233120"]
    assert first["documents"] == [
        {"fileName": "LV.pdf", "sizeBytes": len(PDF), "sha256": stored.sha256, "path": f"/files/{stored.file_id}"},
        {"fileName": "Plan.pdf", "sizeBytes": 52_000, "sha256": None, "path": None},  # known, still loading
    ]
    # A required field the portal does not show is null; optional ones are left out.
    assert tenders["T-2"]["buyerName"] is None and "referenceNumber" not in tenders["T-2"]
    assert tenders["T-2"]["documents"] is None   # not even the list of documents is known yet
    assert tenders["T-3"]["documents"] == []     # read to the end: this tender has no documents
    assert tenders["T-3"]["status"] == "closed"  # its deadline has passed


def test_a_documents_path_returns_its_bytes(system):
    client, _, portal_id, stored, _ = system
    document = client.get(f"/portals/{portal_id}/tenders").json()[0]["documents"][0]
    answer = client.get(document["path"])
    assert answer.status_code == 200 and answer.content == PDF
    assert answer.headers["content-type"] == "application/pdf"
    assert int(answer.headers["content-length"]) == document["sizeBytes"]


def test_a_document_without_bytes_is_not_served(system):
    client, store, _, stored, _ = system
    assert client.get("/files/p00000000000001").status_code == 404          # still loading
    store._files["gone"] = stored.model_copy(update={"file_id": "gone", "storage_path": "files/aa/bb/" + "0" * 64})
    assert client.get("/files/gone").status_code == 404                     # record without bytes on disk
    store._files["evil"] = stored.model_copy(update={"file_id": "evil", "storage_path": "../../etc/passwd"})
    assert client.get("/files/evil").status_code == 404                     # never a path outside the store


def test_changed_since_keeps_only_tenders_that_changed_later(system):
    client, _, portal_id, _, now = system

    def ids(since: datetime) -> list[str]:
        answer = client.get(f"/portals/{portal_id}/tenders", params={"changedSince": since.isoformat()})
        assert answer.status_code == 200
        return [t["id"] for t in answer.json()]

    assert ids(now - timedelta(days=30)) == ["T-1", "T-2", "T-3"]
    # T-1 changed a day ago, T-2 two days ago. T-3's deadline passed an hour ago: that counts as a change.
    assert ids(now - timedelta(days=1, hours=12)) == ["T-1", "T-3"]
    assert ids(now - timedelta(minutes=30)) == []
    closed = client.get(f"/portals/{portal_id}/tenders",
                        params={"changedSince": (now - timedelta(hours=2)).isoformat()}).json()
    assert [(t["id"], t["status"]) for t in closed] == [("T-3", "closed")]


@pytest.mark.parametrize("raw, expected", [
    ("2026-12-09T10:00:00+01:00", datetime(2026, 12, 9, 10, 0, tzinfo=CET)),
    ("2026-12-09T10:00:00 01:00", datetime(2026, 12, 9, 10, 0, tzinfo=CET)),   # the plus arrived as a space
    ("2026-12-09T10:00:00Z", datetime(2026, 12, 9, 10, 0, tzinfo=UTC)),
    ("2026-12-09T10:00:00", datetime(2026, 12, 9, 10, 0, tzinfo=UTC)),          # no offset: read as UTC
    ("2026-12-09", datetime(2026, 12, 9, 0, 0, tzinfo=UTC)),
    ("2026-12-09 10:00:00 01:00", datetime(2026, 12, 9, 10, 0, tzinfo=CET)),
])
def test_changed_since_forms(raw, expected):
    assert parse_changed_since(raw) == expected


@pytest.mark.parametrize("raw", ["yesterday", "", "2026-13-40T10:00:00+01:00", "10:00"])
def test_changed_since_that_cannot_be_read(raw):
    with pytest.raises(ValueError):
        parse_changed_since(raw)


def test_runs_are_listed_oldest_first_with_the_attach_as_a_read(system):
    client, _, portal_id, _, _ = system
    runs = client.get(f"/portals/{portal_id}/runs").json()
    for run in runs:
        check_run(run)
    assert [(r["id"], r["kind"], r["result"]) for r in runs] == [
        ("run-attach", "read", "ok"), ("run-repair", "repair", "failed")]


def test_refresh_starts_a_read_and_a_second_refresh_answers_with_the_same_one(system):
    client, _, portal_id, _, _ = system
    first = client.post(f"/portals/{portal_id}/refresh")
    assert first.status_code == 202
    assert client.post(f"/portals/{portal_id}/refresh").json() == first.json()
    newest = client.get(f"/portals/{portal_id}/runs").json()[-1]
    assert newest["id"] == first.json()["runId"] and newest["kind"] == "read" and newest["result"] is None


def test_delete_removes_the_portal_with_its_tenders_and_runs(system):
    client, store, portal_id, _, _ = system
    assert client.delete(f"/portals/{portal_id}").status_code == 204
    assert store.list_tenders(portal_id) == [] and store.list_runs(portal_id) == []
    again = client.post("/portals", json={"url": URL}).json()["id"]
    assert again == portal_id and client.get(f"/portals/{portal_id}/tenders").json() == []


def test_the_worker_is_told_about_a_new_portal_once_and_about_a_delete():
    calls: list[tuple[str, str]] = []

    class Recorder:
        def attach(self, portal):
            calls.append(("attach", portal.id))

        def refresh(self, portal):
            calls.append(("refresh", portal.id))
            return "run-1"

        def forget(self, portal_id):
            calls.append(("forget", portal_id))

    client = TestClient(create_app(MemoryStore(), Recorder()))
    portal_id = client.post("/portals", json={"url": URL}).json()["id"]
    client.post("/portals", json={"url": URL + "/"})          # the same portal: no second attach
    assert client.post(f"/portals/{portal_id}/refresh").json() == {"runId": "run-1"}
    client.delete(f"/portals/{portal_id}")
    assert calls == [("attach", portal_id), ("refresh", portal_id), ("forget", portal_id)]


def test_the_portal_id_comes_from_the_normalised_address():
    assert portal_id_for("https://Vergabe.Example/tenders/") == portal_id_for(URL)
    assert portal_id_for("https://vergabe.example/other") != portal_id_for(URL)
    assert len(portal_id_for(URL)) == 12
