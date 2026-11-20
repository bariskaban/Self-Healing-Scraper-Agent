"""A store and a worker in memory, standing in until `app/db.py` and the scheduler's loop exist.

Nothing here survives a restart and nothing reads a portal. It exists so that the API can be
built, tested and called by the dashboard today. Tests also use it to put records in place.
"""
from __future__ import annotations

import threading
import uuid

from app.interfaces import PublishedTender
from app.models import FileRecord, Portal, PortalState, Run, RunKind, RunTrigger, TenderFile, TenderRecord


class MemoryStore:
    """`app.interfaces.Store` on dictionaries, guarded by one lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._portals: dict[str, Portal] = {}
        self._tenders: dict[str, dict[str, TenderRecord]] = {}
        self._links: dict[tuple[str, str], list[TenderFile]] = {}
        self._runs: dict[str, list[Run]] = {}
        self._files: dict[str, FileRecord] = {}

    # -- what the API calls (app.interfaces.Store) --

    def add_portal(self, portal: Portal) -> tuple[Portal, bool]:
        with self._lock:
            for known in self._portals.values():
                if known.url_key == portal.url_key:
                    return known, False
            self._portals[portal.id] = portal
            return portal, True

    def get_portal(self, portal_id: str) -> Portal | None:
        with self._lock:
            return self._portals.get(portal_id)

    def list_portals(self) -> list[Portal]:
        with self._lock:
            return sorted(self._portals.values(), key=lambda p: (p.created_at, p.id))

    def delete_portal(self, portal_id: str) -> bool:
        with self._lock:
            if self._portals.pop(portal_id, None) is None:
                return False
            for tender_id in self._tenders.pop(portal_id, {}):
                self._links.pop((portal_id, tender_id), None)
            self._runs.pop(portal_id, None)
            return True

    def count_tenders(self, portal_id: str) -> int:
        with self._lock:
            return len(self._tenders.get(portal_id, {}))

    def list_tenders(self, portal_id: str) -> list[PublishedTender]:
        with self._lock:
            out: list[PublishedTender] = []
            for tender_id, record in sorted(self._tenders.get(portal_id, {}).items()):
                links = self._links.get((portal_id, tender_id), [])
                out.append((record, [(link, self._files[link.file_id]) for link in links
                                     if link.file_id in self._files]))
            return out

    def list_runs(self, portal_id: str) -> list[Run]:
        with self._lock:
            return sorted(self._runs.get(portal_id, []), key=lambda r: (r.started_at, r.id))

    def get_file(self, file_id: str) -> FileRecord | None:
        with self._lock:
            return self._files.get(file_id)

    # -- writes, for the stand-in worker and for tests --

    def put_portal(self, portal: Portal) -> None:
        """Store or replace a portal."""
        with self._lock:
            self._portals[portal.id] = portal

    def put_tender(self, record: TenderRecord,
                   files: list[tuple[TenderFile, FileRecord]] | None = None) -> None:
        """Publish one tender with its documents."""
        with self._lock:
            self._tenders.setdefault(record.portal_id, {})[record.tender_id] = record
            self._links[(record.portal_id, record.tender_id)] = [link for link, _ in files or []]
            for _, file in files or []:
                self._files[file.file_id] = file

    def put_run(self, run: Run) -> None:
        """Store or replace a run."""
        with self._lock:
            runs = self._runs.setdefault(run.portal_id, [])
            runs[:] = [r for r in runs if r.id != run.id] + [run]


class IdleWorker:
    """`app.interfaces.Worker` that records the attach as a running read and reads nothing.

    It keeps the contract honest while there is no reader: the first run is a read, refresh
    answers with the id of the read that is running, and the reason says why nothing arrives.
    """

    REASON = "Attaching: nothing delivered yet. This build has no reader, so the attach does not finish."

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def attach(self, portal: Portal) -> None:
        self._store.put_portal(portal.model_copy(update={"reason": self.REASON}))
        self._store.put_run(Run(id=uuid.uuid4().hex, portal_id=portal.id, kind=RunKind.read,
                                trigger=RunTrigger.attach, state_before=PortalState.integrating))

    def refresh(self, portal: Portal) -> str:
        running = [run for run in self._store.list_runs(portal.id) if run.finished_at is None]
        if running:
            return running[-1].id
        run = Run(id=uuid.uuid4().hex, portal_id=portal.id, kind=RunKind.read,
                  trigger=RunTrigger.refresh, state_before=portal.state)
        self._store.put_run(run)
        return run.id

    def forget(self, portal_id: str) -> None:
        return None
