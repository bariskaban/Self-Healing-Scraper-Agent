"""The dashboard's paged tender list (GET /api/portals/{id}/tenders) and its one-tender route.

The page scrolls through 50 tenders at a time and opens one tender's files when its row is opened, so it never
asks for the whole list (the public route answers 40 MB on a big portal and cannot be paged).
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.memory_store import IdleWorker, MemoryStore
from app.models import (
    DocsStatus, FileRecord, Portal, PortalState, SkipReason, TenderFile, TenderRecord, url_key,
)

UTC = timezone.utc
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


class Docs:
    def __init__(self, files, links):
        self.files, self.links = files, links


def blob(n: int, **kw) -> FileRecord:
    sha = hashlib.sha256(str(n).encode()).hexdigest()
    base = dict(file_id=sha[:16], sha256=sha, size_bytes=100 + n, content_type="application/pdf",
                storage_path=f"files/{sha[:2]}/{sha}", source_url=f"https://x.example/f/{n}", downloaded_at=T0)
    base.update(kw)
    return FileRecord(**base)


def link(tid: str, f: FileRecord, name: str, pos: int) -> TenderFile:
    return TenderFile(portal_id="p1", tender_id=tid, file_id=f.file_id, file_name=name, position=pos)


def tender(tid: str, deadline_days: int | None, **kw) -> TenderRecord:
    base = dict(portal_id="p1", tender_id=tid, url=f"https://x.example/t/{tid}", title=f"Tender {tid}",
                buyer_name="City", publication_date=date(2026, 11, 2),
                submission_deadline=None if deadline_days is None else T0 + timedelta(days=deadline_days),
                first_seen_at=T0, last_seen_at=T0, last_changed_at=T0, content_hash=f"h{tid}",
                docs_status=DocsStatus.complete)
    base.update(kw)
    return TenderRecord(**base)


def seed(store) -> None:
    ok1, ok2 = blob(1), blob(2)
    loading = FileRecord(file_id="p" + "0" * 15, size_bytes=5000, source_url="https://x.example/f/p")
    huge = FileRecord(file_id="s" + "0" * 15, size_bytes=300_000_000, source_url="https://x.example/f/h",
                      skipped=SkipReason.too_large)
    records = [tender("E", 5), tender("A", 30), tender("D", None), tender("C", 10, docs_status=DocsStatus.pending),
               tender("B", 10), tender("F", 1)]
    docs = {"E": Docs([ok1, ok2], [link("E", ok1, "a.pdf", 0), link("E", ok2, "b.pdf", 1)]),
            "A": Docs([ok1, loading, huge], [link("A", ok1, "x.pdf", 0), link("A", loading, "y.pdf", 1),
                                              link("A", huge, "z.zip", 2)])}
    store.publish_tenders("p1", records, documents=docs)
    store.update_portal(store.get_portal("p1").model_copy(update={"state": PortalState.serving}))


@pytest.fixture
def client(tmp_path):
    store = Database(tmp_path / "w.db")
    store.add_portal(Portal(id="p1", url="https://x.example/", url_key=url_key("https://x.example/"), created_at=T0))
    seed(store)
    with TestClient(create_app(store, IdleWorker(store))) as c:
        yield c
    store.close()


def test_the_in_memory_store_answers_an_empty_page():
    store = MemoryStore()
    with TestClient(create_app(store, IdleWorker(store))) as c:
        pid = c.post("/portals", json={"url": "https://a.example/list"}).json()["id"]
        assert c.get(f"/api/portals/{pid}/tenders").json() == {"total": 0, "offset": 0, "limit": 50, "next": None,
                                                               "items": []}
        assert c.get(f"/api/portals/{pid}/tenders/X").status_code == 404


def test_a_page_has_the_total_the_next_offset_and_no_file_lists(client):
    page = client.get("/api/portals/p1/tenders?limit=4&offset=0").json()
    assert (page["total"], page["offset"], page["limit"], page["next"]) == (6, 0, 4, 4)
    assert len(page["items"]) == 4 and all("documents" not in item for item in page["items"])
    assert {"id", "title", "status", "submissionDeadline", "lastChangedAt", "documentCount"} <= set(page["items"][0])
    last = client.get("/api/portals/p1/tenders?limit=4&offset=4").json()
    assert (last["total"], last["next"], len(last["items"])) == (6, None, 2)


def test_the_soonest_deadline_comes_first_and_no_deadline_comes_last(client):
    ids = []
    offset = 0
    while offset is not None:
        page = client.get(f"/api/portals/p1/tenders?limit=2&offset={offset}").json()
        ids += [item["id"] for item in page["items"]]
        offset = page["next"]
    assert ids == ["F", "E", "B", "C", "A", "D"]      # 1, 5, 10, 10 (ties by id), 30 days, none


def test_each_row_says_how_many_documents_it_shows(client):
    items = {i["id"]: i for i in client.get("/api/portals/p1/tenders?limit=50").json()["items"]}
    assert items["E"]["documentCount"] == 2
    assert items["A"]["documentCount"] == 2        # one done, one still loading; the skipped one is not listed
    assert items["C"]["documentCount"] is None     # no link and docs pending: not even the list is known
    assert items["B"]["documentCount"] == 0        # no link, complete: none


def test_one_tender_is_exactly_what_the_public_route_gives_for_it(client):
    public = {t["id"]: t for t in client.get("/portals/p1/tenders").json()}
    for tid in ("E", "A", "B", "C", "D"):
        one = client.get(f"/api/portals/p1/tenders/{tid}")
        assert one.status_code == 200 and one.json() == public[tid]
    assert [d["fileName"] for d in client.get("/api/portals/p1/tenders/E").json()["documents"]] == ["a.pdf", "b.pdf"]


def test_unknown_things_and_bad_limits(client):
    assert client.get("/api/portals/nope/tenders").status_code == 404
    assert client.get("/api/portals/p1/tenders/ZZZ").status_code == 404
    for bad in ("limit=0", "limit=201", "offset=-1", "limit=x"):
        assert client.get(f"/api/portals/p1/tenders?{bad}").status_code == 422
    assert client.get("/api/portals/p1/tenders?limit=200&offset=900").json() == {
        "total": 6, "offset": 900, "limit": 200, "next": None, "items": []}
    assert client.get("/api/portals/p1/tenders").headers["cache-control"] == "no-store"


def test_nothing_is_delivered_while_the_portal_is_integrating(tmp_path):
    db = Database(tmp_path / "w.db")
    db.add_portal(Portal(id="p1", url="https://x.example/", url_key=url_key("https://x.example/"), created_at=T0))
    seed(db)
    db.update_portal(db.get_portal("p1").model_copy(update={"state": PortalState.integrating}))
    with TestClient(create_app(db, IdleWorker(db))) as c:
        assert c.get("/api/portals/p1/tenders").json()["total"] == 0
        assert c.get("/api/portals/p1/tenders/E").status_code == 404
    db.close()
