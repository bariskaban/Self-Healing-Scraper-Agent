"""What the API needs from the rest of the system: a store and a worker.

`app/main.py` is written against these two interfaces only. `app/db.py` provides the
store on SQLite and `app/loop.py` the worker. Without DATA_DIR, as in the unit tests,
`app/memory_store.py` stands in for both: it keeps records in memory and reads no portal.

Threads (Q15, `research/q15-storage.md`): the API calls every `Store` method on one thread
of its own, the database thread, and never on the event loop or from a pool. So a store that
keeps one connection for the API needs no locking for these calls. The `Worker` methods are
called on the event loop; they must return at once and start their work in the background.
"""
from __future__ import annotations

from typing import Protocol

from app.models import FileRecord, Portal, Run, TenderFile, TenderRecord

# One published tender with its documents in order: the shape `TenderRecord.to_api` takes.
PublishedTender = tuple[TenderRecord, list[tuple[TenderFile, FileRecord]]]


class Store(Protocol):
    """The records the API reads, and the two writes it makes (add and delete a portal)."""

    def add_portal(self, portal: Portal) -> tuple[Portal, bool]:
        """Store a new portal. If one with the same `url_key` exists, change nothing.

        Returns the stored portal and whether it was created by this call. Must be atomic:
        the same address posted twice at the same moment creates one portal.
        """
        ...

    def get_portal(self, portal_id: str) -> Portal | None:
        """One portal, or None when the id is unknown."""
        ...

    def list_portals(self) -> list[Portal]:
        """Every portal, oldest first."""
        ...

    def delete_portal(self, portal_id: str) -> bool:
        """Remove a portal with its tenders, runs and links to files. False when the id is unknown."""
        ...

    def count_tenders(self, portal_id: str) -> int:
        """How many tenders `list_tenders` returns: closed and withdrawn ones included."""
        ...

    def list_tenders(self, portal_id: str) -> list[PublishedTender]:
        """The tenders delivered for a portal right now, in a stable order.

        Only what is published: nothing while the portal is `integrating`, and the tenders of
        the last good read while it is `healing`. A read that has not passed its checks is
        never visible here.
        """
        ...

    def list_runs(self, portal_id: str) -> list[Run]:
        """Every read and repair of a portal, oldest first. The first attach is a read."""
        ...

    def get_file(self, file_id: str) -> FileRecord | None:
        """The record of one document, or None when the id is unknown."""
        ...


class Worker(Protocol):
    """The part that reads portals. Each method returns at once; the work happens in the background."""

    def attach(self, portal: Portal) -> None:
        """Start the first read of a newly added portal."""
        ...

    def refresh(self, portal: Portal) -> str:
        """Start a read now and return its run id.

        If a read or a repair is already running, return that run's id. On a `failed` portal
        this is the check of Q14, at most once a minute; within that minute return the last
        check's run id.
        """
        ...

    def forget(self, portal_id: str) -> None:
        """Cancel everything running for a deleted portal. No request goes to it after this."""
        ...
