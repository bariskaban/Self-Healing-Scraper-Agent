"""GET /portals/{id}/tenders for big portals: built fast, built once, and never on the dashboard's thread.

Why this exists. A portal with thousands of tenders and dozens of files each (TenderNed: about 60 files a
tender) made the old route build a quarter of a million Python objects and a 40 MB answer in 6 seconds, on the
one thread every route shares: for those 6 seconds the dashboard waited too (`/api/dashboard` took 5.7 s
instead of 5 ms). Now:

  * the documents of each tender are built by SQLite as JSON text (0.7 s for 248,000 files, without Python's
    lock) on a second read connection (`Database.tenders_for_answer`), and spliced into the tender's JSON;
  * the finished answer is kept per portal until something that shows in it changes (`Database.tenders_version`)
    or a short time passes (a tender whose deadline passes reads as closed): repeat calls cost milliseconds;
  * a client that accepts gzip gets the compressed answer, compressed once per build;
  * an `ETag` lets a client that polls say "unchanged" and receive no body (304).

The answer is exactly what `TenderRecord.to_api` gives for each tender (`tests/test_tenders_answer.py` compares
the two on every kind of document). A store without these methods (the in-memory stand-in) keeps the old route.
"""
from __future__ import annotations

import gzip
import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime

from app.models import DocsStatus, TenderRecord, utcnow

log = logging.getLogger("watchtower.tenders")

CACHE_PORTALS = 4          # finished answers kept; the oldest goes first
FRESH_SECONDS = 15         # a tender's status moves with the clock (its deadline passes): at most this stale
GZIP_LEVEL = 3             # about 0.5 s for 40 MB; the answer is repetitive hex and names


@dataclass
class Answer:
    body: bytes                 # the JSON array, UTF-8
    etag: str
    compressed: bytes | None = None

    def encoded(self, gzip_ok: bool) -> tuple[bytes, bool]:
        """The body to send and whether it is gzip: compressed once, on the first call that accepts it."""
        if not gzip_ok:
            return self.body, False
        if self.compressed is None:
            self.compressed = gzip.compress(self.body, GZIP_LEVEL)
        return self.compressed, True


def etag_for(portal_id: str, version: tuple[int, int], now: datetime) -> str:
    return f'"{portal_id}-{version[0]}-{version[1]}-{int(now.timestamp() // FRESH_SECONDS)}"'


class TendersAnswers:
    """Builds and keeps the tenders answers of a `Database`."""

    def __init__(self, database) -> None:
        self.db = database
        self._cache: OrderedDict[str, tuple[str, Answer]] = OrderedDict()   # portal id -> (etag, answer)
        self._lock = threading.Lock()
        self._building: dict[str, threading.Lock] = {}

    def etag(self, portal_id: str, now: datetime | None = None) -> str:
        return etag_for(portal_id, self.db.tenders_version(portal_id), now or utcnow())

    def answer(self, portal_id: str, since: datetime | None = None, now: datetime | None = None) -> Answer:
        """The answer for a portal, from the cache when nothing has changed. Blocks while it is built: call it from
        a worker thread. With `since`, only the tenders that changed later, and never cached."""
        now = now or utcnow()
        if since is not None:
            return self._build(portal_id, since, now, etag_for(portal_id, self.db.tenders_version(portal_id), now))
        tag = self.etag(portal_id, now)
        cached = self._get(portal_id, tag)
        if cached is not None:
            return cached
        with self._building.setdefault(portal_id, threading.Lock()):   # one build at a time per portal
            tag = self.etag(portal_id, now)
            cached = self._get(portal_id, tag)
            if cached is not None:
                return cached
            made = self._build(portal_id, None, now, tag)
            with self._lock:
                self._cache[portal_id] = (tag, made)
                self._cache.move_to_end(portal_id)
                while len(self._cache) > CACHE_PORTALS:
                    self._cache.popitem(last=False)
            return made

    def _get(self, portal_id: str, tag: str) -> Answer | None:
        with self._lock:
            held = self._cache.get(portal_id)
            return held[1] if held is not None and held[0] == tag else None

    def _build(self, portal_id: str, since: datetime | None, now: datetime, tag: str) -> Answer:
        began = time.monotonic()
        records, documents = self.db.tenders_for_answer(portal_id)
        read = time.monotonic() - began
        placeholder = f"@@{uuid.uuid4().hex}@@"       # stands where a tender's documents go until they are spliced in
        quoted = f'"{placeholder}"'
        parts: list[str] = []
        for record in records:
            if since is not None and record.effective_last_changed(now) <= since:
                continue
            fields = record.to_api([], now)
            fields["documents"] = placeholder
            text = json.dumps(fields, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            parts.append(text.replace(quoted, _documents(record, documents.get(record.tender_id))))
        body = ("[" + ",".join(parts) + "]").encode("utf-8")
        log.debug("portal %s: tenders answer built: %d of %d tender(s), %.1f MB, SQLite %.2fs, total %.2fs%s", portal_id,
                  len(parts), len(records), len(body) / 1e6, read, time.monotonic() - began,
                  f", since {since.isoformat()}" if since is not None else "")
        return Answer(body=body, etag=tag)


def _documents(record: TenderRecord, text: str | None) -> str:
    """A tender's documents as JSON text: what SQLite built, or `null` / `[]` when it has no link at all. A tender with
    no link is `null` while its documents are still pending (not even the list is known) and `[]` otherwise
    (`TenderRecord.to_api`)."""
    if text is not None:
        return text
    return "null" if record.docs_status == DocsStatus.pending else "[]"
