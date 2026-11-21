"""The fast tenders answer (app/tenders_answer.py) is the old answer, faster and cached.

The reference is `TenderRecord.to_api` on `Database.list_tenders`, which is what the route used to return: for
every kind of document and tender the two must give the same JSON.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.memory_store import IdleWorker
from app.models import (
    DocsStatus, FileRecord, PlaceOfPerformance, Portal, PortalState, SkipReason, TenderFile, TenderRecord, url_key,
)
from app.tenders_answer import TendersAnswers

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


def link(tender_id: str, f: FileRecord, name: str, position: int) -> TenderFile:
    return TenderFile(portal_id="p1", tender_id=tender_id, file_id=f.file_id, file_name=name, position=position)


def tender(tender_id: str, **kw) -> TenderRecord:
    base = dict(portal_id="p1", tender_id=tender_id, url=f"https://x.example/t/{tender_id}", title=f"Tender {tender_id}",
                buyer_name="City of Example", publication_date=date(2026, 11, 2),
                submission_deadline=datetime(2026, 12, 15, 10, 0, tzinfo=UTC), first_seen_at=T0, last_seen_at=T0,
                last_changed_at=T0, content_hash=f"h-{tender_id}", docs_status=DocsStatus.complete)
    base.update(kw)
    return TenderRecord(**base)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "w.db")
    database.add_portal(Portal(id="p1", url="https://x.example/", url_key=url_key("https://x.example/"), created_at=T0))
    yield database
    database.close()


def go_live(db: Database) -> None:
    db.update_portal(db.get_portal("p1").model_copy(update={"state": PortalState.serving}))


def seed_every_kind(db: Database) -> None:
    """One tender for each way documents can be, and some odd text."""
    ok1, ok2, ok3 = blob(1), blob(2), blob(3)
    loading = FileRecord(file_id="p" + "0" * 15, size_bytes=5000, source_url="https://x.example/f/p")
    loading_unknown_size = FileRecord(file_id="p" + "1" * 15, source_url="https://x.example/f/q")
    too_big = FileRecord(file_id="s" + "0" * 15, size_bytes=300_000_000, source_url="https://x.example/f/big",
                         skipped=SkipReason.too_large)
    archive = blob(9, is_archive=True, storage_path=None)
    odd = blob(4)
    docs = {
        "A": Docs([ok2, ok1, ok3], [link("A", ok1, "first.pdf", 0), link("A", ok2, "second.pdf", 1),
                                    link("A", ok3, "third.pdf", 2)]),                                   # in order
        "B": Docs([ok1, loading, loading_unknown_size],
                  [link("B", ok1, "done.pdf", 0), link("B", loading, "loading.pdf", 1),
                   link("B", loading_unknown_size, "unknown size.pdf", 2)]),                            # pending ones
        "C": Docs([ok1, too_big, archive], [link("C", ok1, "kept.pdf", 0), link("C", too_big, "huge.zip", 1),
                                            link("C", archive, "bundle.zip", 2)]),                      # skipped, archive
        "D": Docs([too_big], [link("D", too_big, "only-huge.zip", 0)]),                                 # none shown: []
        "E": Docs([odd], [link("E", odd, 'Zażółć "quoted" \\ back/slash & <tag> 日本語.pdf', 0)]),         # escaping
    }
    records = [
        tender("A"), tender("B"), tender("C"), tender("D"), tender("E", title='Roads "and" bridges, \\ Zürich 日本'),
        tender("F", docs_status=DocsStatus.pending),                  # no link, pending: documents null
        tender("G", docs_status=DocsStatus.complete),                 # no link, complete: []
        tender("H", place=PlaceOfPerformance(postalCode="1011", city="Amsterdam", countryCode="NL"),
               reference_number="REF-1", description="What is bought", cpv_codes=["45000000"]),
        tender("I", submission_deadline=datetime(2026, 11, 1, tzinfo=UTC)),   # deadline passed: closed
    ]
    db.publish_tenders("p1", records, documents=docs)
    go_live(db)


def reference(db: Database, now: datetime, since: datetime | None = None) -> list[dict]:
    return [r.to_api(files, now=now) for r, files in db.list_tenders("p1")
            if since is None or r.effective_last_changed(now) > since]


def test_the_fast_answer_is_the_old_answer_for_every_kind_of_document(db):
    seed_every_kind(db)
    now = T0 + timedelta(hours=1)
    got = json.loads(TendersAnswers(db).answer("p1", now=now).body)
    assert got == reference(db, now)
    by_id = {t["id"]: t for t in got}
    assert by_id["F"]["documents"] is None and by_id["G"]["documents"] == [] and by_id["D"]["documents"] == []
    assert [d["fileName"] for d in by_id["A"]["documents"]] == ["first.pdf", "second.pdf", "third.pdf"]
    assert {d["fileName"] for d in by_id["C"]["documents"]} == {"kept.pdf"}          # skipped and archive are left out
    assert by_id["B"]["documents"][1] == {"fileName": "loading.pdf", "sizeBytes": 5000, "sha256": None, "path": None}
    assert by_id["B"]["documents"][2]["sizeBytes"] is None
    assert by_id["I"]["status"] == "closed"


def test_the_body_is_what_the_route_used_to_send_byte_for_byte(db):
    seed_every_kind(db)
    now = T0 + timedelta(hours=1)
    old = json.dumps(reference(db, now), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    assert TendersAnswers(db).answer("p1", now=now).body == old


def test_changed_since_returns_the_same_tenders_as_before(db):
    seed_every_kind(db)
    now = T0 + timedelta(hours=1)
    later = T0 + timedelta(minutes=30)
    db.set_documents("p1", "A", [blob(1)], [link("A", blob(1), "only.pdf", 0)], last_changed_at=later)
    since = T0 + timedelta(minutes=10)
    got = json.loads(TendersAnswers(db).answer("p1", since, now).body)
    assert [t["id"] for t in got] == ["A"] and got == reference(db, now, since)


def test_nothing_is_delivered_while_the_portal_is_integrating(db):
    seed_every_kind(db)
    db.update_portal(db.get_portal("p1").model_copy(update={"state": PortalState.integrating}))
    assert json.loads(TendersAnswers(db).answer("p1").body) == [] == reference(db, T0)


def test_a_repeat_call_is_served_from_the_cache_until_something_changes(db, monkeypatch):
    seed_every_kind(db)
    answers, calls = TendersAnswers(db), []
    real = db.tenders_for_answer
    monkeypatch.setattr(db, "tenders_for_answer", lambda pid: calls.append(pid) or real(pid))
    now = T0 + timedelta(hours=1)
    first = answers.answer("p1", now=now)
    assert answers.answer("p1", now=now) is first and len(calls) == 1               # cached
    db.set_documents("p1", "G", [blob(7)], [link("G", blob(7), "new.pdf", 0)])       # a document arrives
    second = answers.answer("p1", now=now)
    assert second is not first and len(calls) == 2
    assert [t["documents"] for t in json.loads(second.body) if t["id"] == "G"][0][0]["fileName"] == "new.pdf"
    db.update_portal(db.get_portal("p1").model_copy(update={"state": PortalState.failed}))   # the state moved
    assert answers.answer("p1", now=now) is not second and len(calls) == 3
    later = now + timedelta(minutes=1)                                              # the clock moved on
    assert answers.answer("p1", now=later) is not second


def test_many_requests_at_once_build_the_answer_once(db, monkeypatch):
    seed_every_kind(db)
    answers, calls = TendersAnswers(db), []
    real = db.tenders_for_answer

    def slow(pid):
        calls.append(pid)
        time.sleep(0.2)
        return real(pid)

    monkeypatch.setattr(db, "tenders_for_answer", slow)
    now = T0 + timedelta(hours=1)
    results = []
    threads = [threading.Thread(target=lambda: results.append(answers.answer("p1", now=now))) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1 and len({id(r) for r in results}) == 1


def test_gzip_is_the_same_answer_compressed_once(db):
    seed_every_kind(db)
    made = TendersAnswers(db).answer("p1", now=T0 + timedelta(hours=1))
    plain, zipped = made.encoded(False), made.encoded(True)
    assert plain == (made.body, False) and zipped[1] is True and gzip.decompress(zipped[0]) == made.body
    assert made.encoded(True)[0] is zipped[0]


def test_the_route_sends_gzip_and_etag_and_answers_304_when_nothing_changed(db):
    seed_every_kind(db)
    with TestClient(create_app(db, IdleWorker(db))) as client:
        first = client.get("/portals/p1/tenders", headers={"Accept-Encoding": "identity"})
        assert first.status_code == 200 and first.headers["content-type"] == "application/json"
        assert "content-encoding" not in first.headers and first.headers["etag"]
        zipped = client.get("/portals/p1/tenders", headers={"Accept-Encoding": "gzip"})
        assert zipped.headers["content-encoding"] == "gzip" and zipped.json() == first.json()   # httpx decodes it
        same = client.get("/portals/p1/tenders", headers={"If-None-Match": first.headers["etag"]})
        assert same.status_code == 304 and same.content == b""
        db.set_documents("p1", "G", [blob(7)], [link("G", blob(7), "new.pdf", 0)])
        changed = client.get("/portals/p1/tenders", headers={"If-None-Match": first.headers["etag"]})
        assert changed.status_code == 200 and changed.json() != first.json()
        assert client.get("/portals/nope/tenders").status_code == 404
        assert client.get("/portals/p1/tenders?changedSince=garbage").status_code == 400


def test_a_big_answer_does_not_hold_up_the_dashboards_reads(db, monkeypatch):
    """The reason for all of this: while a tenders answer is being built, /api/dashboard still answers at once."""
    seed_every_kind(db)
    real = db.tenders_for_answer

    def slow(pid):
        time.sleep(1.0)       # stands in for a 6-second build on a big portal
        return real(pid)

    monkeypatch.setattr(db, "tenders_for_answer", slow)
    with TestClient(create_app(db, IdleWorker(db))) as client:
        big = threading.Thread(target=lambda: client.get("/portals/p1/tenders"))
        big.start()
        time.sleep(0.2)
        began = time.monotonic()
        assert client.get("/api/dashboard").status_code == 200 and client.get("/portals").status_code == 200
        took = time.monotonic() - began
        big.join()
    assert took < 0.5, f"the dashboard waited {took:.2f}s behind the tenders answer"
