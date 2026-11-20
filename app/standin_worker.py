"""The worker on the database until the read loop exists (docs/BUILD-PLAN.md, stream A).

`app.interfaces.Worker` on `app.db.Database`: it records the attach as a running read and
reads nothing. It keeps the contract honest while no portal is read: the first run of a
portal is a read, a refresh answers with the run that is going on, and the reason says why
nothing arrives. The read loop replaces it in `app/main.py`.

Its calls to the database are quick (one or two rows) and the store locks its connections,
so calling it on the event loop, as the API does with a worker, is safe.
"""
from __future__ import annotations

import uuid

from app.db import Database
from app.models import Portal, PortalState, Run, RunKind, RunTrigger


class DatabaseIdleWorker:
    """Records runs in the database; reads no portal."""

    REASON = "Attaching: nothing delivered yet. This build has no reader, so the attach does not finish."

    def __init__(self, database: Database) -> None:
        self._db = database

    def attach(self, portal: Portal) -> None:
        stored = self._db.get_portal(portal.id) or portal
        self._db.update_portal(stored.model_copy(update={"reason": self.REASON}))
        self._db.start_run(Run(id=uuid.uuid4().hex, portal_id=portal.id, kind=RunKind.read,
                               trigger=RunTrigger.attach, state_before=PortalState.integrating))

    def refresh(self, portal: Portal) -> str:
        # start_run returns the run going on (read or repair) when there is one: one run per portal.
        return self._db.start_run(Run(id=uuid.uuid4().hex, portal_id=portal.id, kind=RunKind.read,
                                      trigger=RunTrigger.refresh, state_before=portal.state)).id

    def forget(self, portal_id: str) -> None:
        return None
