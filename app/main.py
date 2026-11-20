"""Watchtower web app: the API of the track description, the dashboard page, and document bytes.

Every route answers exactly as the appendix of the brief says (summarised in DESIGN.md,
"API contract" and "Where the brief is silent"). The routes talk to the rest of the system
through `app/interfaces.py` only.

Threads (Q15): the routes are `async def` and every call to the store runs on one thread of
its own, the database thread. Several threads reading SQLite in one process took 130 ms a
query against 2.3 ms for one, so the store is never called from a pool. Building the answer
of a long tender list also happens on that thread, off the event loop. The worker is called
on the event loop and returns at once.

Store: with DATA_DIR set, as the Dockerfile does, the records live in SQLite under it
(`app/db.py`) and survive a restart; without it, as in the unit tests, they live in memory.

Run: uvicorn app.main:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, TypeVar
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.db import Database
from app.docs import DocsSettings, FileStore
from app.interfaces import Store, Worker
from app.memory_store import IdleWorker, MemoryStore
from app.standin_worker import DatabaseIdleWorker
from app.models import CreatedId, Portal, PortalCreate, RunAccepted, url_key, utcnow

T = TypeVar("T")

PORTAL_ID_LENGTH = 12
# A time of day, a space, and an offset at the end: the space was a "+" before URL decoding.
_LOST_PLUS = re.compile(r"(\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?) (\d{2}:?\d{2})$")

PLACEHOLDER_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Watchtower</title></head>
<body>
<h1>Watchtower is running</h1>
<p>The dashboard is not built yet. The API answers on this port: try <a href="/portals">/portals</a>.</p>
</body>
</html>
"""


def portal_id_for(url: str) -> str:
    """The id of a portal: derived from its normalised address, so the same address always gives the same id."""
    return hashlib.sha256(url_key(url).encode("utf-8")).hexdigest()[:PORTAL_ID_LENGTH]


def usable_address(url: str) -> bool:
    """True for an http or https address with a host; anything else cannot be a portal."""
    try:
        parts = urlsplit(url.strip())
        return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
    except ValueError:
        return False


def parse_changed_since(raw: str) -> datetime:
    """The `changedSince` value as an aware time. Raises ValueError when it cannot be read.

    A `+` in the offset arrives as a space when the caller did not percent-encode it; both
    are accepted. A value without an offset is read as UTC.
    """
    text = _LOST_PLUS.sub(r"\1+\2", raw.strip())  # "10:00:00 01:00" was "10:00:00+01:00"
    when = datetime.fromisoformat(text)
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def default_store() -> tuple[Store, Worker]:
    """The SQLite store under DATA_DIR when it is set (the container sets it); memory otherwise.

    The worker is a stand-in that records runs and reads nothing, until the read loop exists.
    """
    if os.environ.get("DATA_DIR"):
        database = Database.from_env()
        return database, DatabaseIdleWorker(database)
    memory = MemoryStore()
    return memory, IdleWorker(memory)


def create_app(store: Store | None = None, worker: Worker | None = None,
               files: Callable[[], FileStore] | None = None) -> FastAPI:
    """The app on a given store and worker. Without them, on `default_store()`."""
    opened: Database | None = None  # a database this app opened itself, and closes on shutdown
    if store is None:
        store, default_worker = default_store()
        worker = worker or default_worker
        opened = store if isinstance(store, Database) else None
    if worker is None:
        raise ValueError("a store was given without a worker")
    file_store: list[FileStore] = []

    def documents() -> FileStore:
        # Opened on first use: creating it makes directories under DATA_DIR.
        if not file_store:
            file_store.append(files() if files is not None else FileStore(DocsSettings.from_env()))
        return file_store[0]

    database = ThreadPoolExecutor(max_workers=1, thread_name_prefix="watchtower-db")

    async def on_db(call: Callable[..., T], *args: Any) -> T:
        """Run one call to the store on the database thread."""
        return await asyncio.get_running_loop().run_in_executor(database, call, *args)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        database.shutdown(wait=False, cancel_futures=True)
        if opened is not None:
            opened.close()

    app = FastAPI(title="Watchtower", docs_url="/api-docs", redoc_url=None, lifespan=lifespan)
    # The dashboard may be developed on another port; the API holds nothing private.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    async def known(portal_id: str) -> Portal:
        portal = await on_db(store.get_portal, portal_id)
        if portal is None:
            raise HTTPException(status_code=404, detail="No portal has this id.")
        return portal

    def portal_answer(portal: Portal) -> dict:
        # Runs on the database thread.
        return portal.to_api(store.count_tenders(portal.id)).model_dump(mode="json")

    def tender_answers(portal_id: str, since: datetime | None) -> list[dict]:
        # Runs on the database thread: the query, and building up to thousands of answers.
        now = utcnow()
        return [record.to_api(tender_files, now=now) for record, tender_files in store.list_tenders(portal_id)
                if since is None or record.effective_last_changed(now) > since]

    @app.post("/portals", status_code=201)
    async def add_portal(body: PortalCreate) -> JSONResponse:
        """Add a portal by its address. Answers at once; the attach runs in the background."""
        if not usable_address(body.url):
            raise HTTPException(status_code=400, detail="url must be an http or https address.")
        url = body.url.strip()
        portal, created = await on_db(
            store.add_portal, Portal(id=portal_id_for(url), url=url, url_key=url_key(url)))
        if created:
            worker.attach(portal)
        return JSONResponse(CreatedId(id=portal.id).model_dump(), status_code=201)

    @app.get("/portals")
    async def list_portals() -> JSONResponse:
        """The state of every portal."""
        return JSONResponse(await on_db(lambda: [portal_answer(portal) for portal in store.list_portals()]))

    @app.get("/portals/{portal_id}")
    async def get_portal(portal_id: str) -> JSONResponse:
        """The state of one portal."""
        return JSONResponse(await on_db(portal_answer, await known(portal_id)))

    @app.delete("/portals/{portal_id}", status_code=204)
    async def delete_portal(portal_id: str) -> Response:
        """Remove a portal. Its tasks are cancelled at once and its records removed."""
        await known(portal_id)
        worker.forget(portal_id)
        await on_db(store.delete_portal, portal_id)
        return Response(status_code=204)

    @app.post("/portals/{portal_id}/refresh", status_code=202)
    async def refresh_portal(portal_id: str) -> JSONResponse:
        """Read the portal again now. Answers with the id of the run that is running or was started."""
        run_id = worker.refresh(await known(portal_id))
        return JSONResponse(RunAccepted(runId=run_id).model_dump(), status_code=202)

    @app.get("/portals/{portal_id}/tenders")
    async def list_tenders(portal_id: str, changedSince: str | None = Query(None)) -> JSONResponse:  # noqa: N803
        """The tenders held for the portal; with `changedSince`, only those that changed later."""
        await known(portal_id)
        since = None
        if changedSince is not None:
            try:
                since = parse_changed_since(changedSince)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="changedSince must be a date and time with offset, such as 2026-12-09T10:00:00+01:00.",
                ) from None
        return JSONResponse(await on_db(tender_answers, portal_id, since))

    @app.get("/portals/{portal_id}/runs")
    async def list_runs(portal_id: str) -> JSONResponse:
        """Every read and repair of the portal, oldest first."""
        await known(portal_id)
        runs = await on_db(store.list_runs, portal_id)
        return JSONResponse([run.to_api().model_dump(mode="json") for run in runs])

    @app.get("/files/{file_id}")
    async def get_file(file_id: str) -> FileResponse:
        """The bytes of one document. Each document's `path` points here."""
        record = await on_db(store.get_file, file_id)
        if record is None or not record.deliverable or not record.storage_path:
            raise HTTPException(status_code=404, detail="No document has this id.")
        try:
            path = documents().resolve(record.storage_path)
        except ValueError:
            raise HTTPException(status_code=404, detail="No document has this id.") from None
        if not path.is_file():
            raise HTTPException(status_code=404, detail="The document's bytes are not on disk.")
        return FileResponse(path, media_type=record.content_type or "application/octet-stream")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        """Placeholder until the dashboard (`app/dashboard/`) replaces it."""
        return PLACEHOLDER_PAGE

    return app


app = create_app()
