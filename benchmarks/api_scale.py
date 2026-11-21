"""Benchmark: GET /portals/{id}/tenders on portals with many tenders and many files each.

    python benchmarks/api_scale.py                    # the three shapes below, writes benchmarks/results/api-scale.csv
    python benchmarks/api_scale.py 4132x60 500x120    # your own: TENDERSxFILES

It builds a throwaway SQLite database for each shape (no network, no model), then measures what the route did
before (`list_tenders` + `to_api` + JSON, on the one thread every route shares) against what it does now
(`app/tenders_answer.py`: SQLite builds the documents, a second read connection, a cache, gzip), and how long
`/api/dashboard` waits while a tenders answer is being built.

Shapes (tenders x files per tender): tender24 as seen on 20 Nov 2026 (121 x 26), the NFZ-like small portal
(500 x 8) and TenderNed's ZIPs (4,132 x 60).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard_api import DashboardSettings, dashboard_answer
from app.db import Database
from app.main import create_app
from app.memory_store import IdleWorker
from app.models import DocsStatus, FileRecord, Portal, PortalState, TenderFile, TenderRecord, url_key, utcnow
from app.tenders_answer import TendersAnswers

T0 = datetime(2026, 11, 20, tzinfo=timezone.utc)
SHAPES = ["121x26", "500x8", "4132x60"]
OUT = Path(__file__).resolve().parent / "results" / "api-scale.csv"


class Docs:
    def __init__(self, files, links):
        self.files, self.links = files, links


def build(db: Database, tenders: int, per: int) -> int:
    url = "https://bench.example/"
    db.add_portal(Portal(id="p1", url=url, url_key=url_key(url), created_at=T0))
    links = 0
    for start in range(0, tenders, 200):
        records, docs = [], {}
        for n in range(start, min(start + 200, tenders)):
            tid = f"T{n}"
            records.append(TenderRecord(portal_id="p1", tender_id=tid, url=f"https://bench.example/{tid}", title=f"Tender {n}",
                                        buyer_name="Buyer", publication_date=date(2026, 11, 1),
                                        submission_deadline=T0 + timedelta(days=30), first_seen_at=T0, last_seen_at=T0,
                                        last_changed_at=T0, docs_status=DocsStatus.complete))
            files = []
            for k in range(per):
                sha = hashlib.sha256(f"{tid}-{k}".encode()).hexdigest()
                files.append(FileRecord(file_id=sha[:16], sha256=sha, size_bytes=10_000 + k, content_type="application/pdf",
                                        storage_path=f"files/{sha[:2]}/{sha}", source_url="https://bench.example/f",
                                        downloaded_at=T0))
            docs[tid] = Docs(files, [TenderFile(portal_id="p1", tender_id=tid, file_id=f.file_id,
                                                file_name=f"document-{k:03d}.pdf", position=k) for k, f in enumerate(files)])
            links += per
        db.publish_tenders("p1", records, documents=docs)
    db.update_portal(db.get_portal("p1").model_copy(update={"state": PortalState.serving}))
    return links


def legacy(db: Database) -> bytes:
    """What the route did: every file as an object, every tender through pydantic, on the shared thread."""
    now = utcnow()
    answer = [record.to_api(files, now=now) for record, files in db.list_tenders("p1")]
    return json.dumps(answer, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def timed(fn):
    began = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - began


def dashboard_wait_old(db: Database) -> float:
    """The old route and a dashboard read queue on one thread, as they did in the app (`on_db`)."""
    one_thread = ThreadPoolExecutor(max_workers=1)
    big = one_thread.submit(legacy, db)
    time.sleep(0.05)
    began = time.perf_counter()
    one_thread.submit(lambda: dashboard_answer(db, DashboardSettings(), live={})).result()
    waited = time.perf_counter() - began
    big.result()
    one_thread.shutdown()
    return waited


def dashboard_wait_new(db: Database) -> float:
    """The real app, with a tenders answer being built while /api/dashboard is asked."""
    with TestClient(create_app(db, IdleWorker(db))) as client:
        big = threading.Thread(target=lambda: client.get("/portals/p1/tenders"))
        big.start()
        time.sleep(0.05)
        began = time.perf_counter()
        client.get("/api/dashboard")
        waited = time.perf_counter() - began
        big.join()
    return waited


def run(shape: str) -> dict:
    tenders, per = (int(x) for x in shape.split("x"))
    with tempfile.TemporaryDirectory(prefix="watchtower-api-scale-") as folder:
        db = Database(Path(folder) / "w.db")
        links = build(db, tenders, per)
        old_body, old_seconds = timed(lambda: legacy(db))
        answers = TendersAnswers(db)
        first, first_seconds = timed(lambda: answers.answer("p1"))
        _, cached_seconds = timed(lambda: answers.answer("p1"))
        zipped, gzip_seconds = timed(lambda: gzip.compress(first.body, 3))
        same = json.loads(first.body) == json.loads(old_body)
        row = {
            "shape": shape, "tenders": tenders, "files_per_tender": per, "file_links": links,
            "answer_mb": round(len(first.body) / 1e6, 2), "gzip_mb": round(len(zipped) / 1e6, 2),
            "old_route_s": round(old_seconds, 2), "new_first_call_s": round(first_seconds, 2),
            "new_cached_call_s": round(cached_seconds, 4), "gzip_once_s": round(gzip_seconds, 2),
            "dashboard_wait_old_s": round(dashboard_wait_old(db), 3),
            "dashboard_wait_new_s": round(dashboard_wait_new(db), 3), "same_answer": same,
        }
        db.close()
    return row


def main(argv: list[str]) -> int:
    rows = []
    for shape in argv or SHAPES:
        row = run(shape)
        rows.append(row)
        print(f"{shape:>8}: {row['file_links']:>7,} links, {row['answer_mb']:>5.1f} MB | old {row['old_route_s']:>5.2f}s -> new "
              f"{row['new_first_call_s']:.2f}s, cached {row['new_cached_call_s'] * 1000:.1f} ms | dashboard waits "
              f"{row['dashboard_wait_old_s']:.2f}s -> {row['dashboard_wait_new_s'] * 1000:.0f} ms | same answer: {row['same_answer']}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("wrote", OUT)
    return 0 if all(r["same_answer"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
