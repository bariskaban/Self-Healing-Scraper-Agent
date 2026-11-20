"""Watchtower web app: the API of the track description, the dashboard page, and document bytes.

Every route answers exactly as the appendix of the brief says (summarised in DESIGN.md,
"API contract" and "Where the brief is silent"). The routes are plain functions, which FastAPI
runs in worker threads, so a slow store never stalls the event loop. They talk to the rest of
the system through `app/interfaces.py` only.

Run: uvicorn app.main:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.docs import DocsSettings, FileStore
from app.interfaces import Store, Worker
from app.memory_store import IdleWorker, MemoryStore
from app.models import CreatedId, Portal, PortalCreate, RunAccepted, url_key, utcnow

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


def create_app(store: Store | None = None, worker: Worker | None = None,
               files: Callable[[], FileStore] | None = None) -> FastAPI:
    """The app on a given store and worker. Without them it runs on the in-memory stand-ins."""
    if store is None:
        memory = MemoryStore()
        store, worker = memory, worker or IdleWorker(memory)
    if worker is None:
        raise ValueError("a store was given without a worker")
    file_store: list[FileStore] = []

    def documents() -> FileStore:
        # Opened on first use: creating it makes directories under DATA_DIR.
        if not file_store:
            file_store.append(files() if files is not None else FileStore(DocsSettings.from_env()))
        return file_store[0]

    app = FastAPI(title="Watchtower", docs_url="/api-docs", redoc_url=None)
    # The dashboard may be developed on another port; the API holds nothing private.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def known(portal_id: str) -> Portal:
        portal = store.get_portal(portal_id)
        if portal is None:
            raise HTTPException(status_code=404, detail="No portal has this id.")
        return portal

    def portal_answer(portal: Portal) -> dict:
        return portal.to_api(store.count_tenders(portal.id)).model_dump(mode="json")

    @app.post("/portals", status_code=201)
    def add_portal(body: PortalCreate) -> JSONResponse:
        """Add a portal by its address. Answers at once; the attach runs in the background."""
        if not usable_address(body.url):
            raise HTTPException(status_code=400, detail="url must be an http or https address.")
        url = body.url.strip()
        portal, created = store.add_portal(Portal(id=portal_id_for(url), url=url, url_key=url_key(url)))
        if created:
            worker.attach(portal)
        return JSONResponse(CreatedId(id=portal.id).model_dump(), status_code=201)

    @app.get("/portals")
    def list_portals() -> JSONResponse:
        """The state of every portal."""
        return JSONResponse([portal_answer(portal) for portal in store.list_portals()])

    @app.get("/portals/{portal_id}")
    def get_portal(portal_id: str) -> JSONResponse:
        """The state of one portal."""
        return JSONResponse(portal_answer(known(portal_id)))

    @app.delete("/portals/{portal_id}", status_code=204)
    def delete_portal(portal_id: str) -> Response:
        """Remove a portal. Its tasks are cancelled at once and its records removed."""
        known(portal_id)
        worker.forget(portal_id)
        store.delete_portal(portal_id)
        return Response(status_code=204)

    @app.post("/portals/{portal_id}/refresh", status_code=202)
    def refresh_portal(portal_id: str) -> JSONResponse:
        """Read the portal again now. Answers with the id of the run that is running or was started."""
        run_id = worker.refresh(known(portal_id))
        return JSONResponse(RunAccepted(runId=run_id).model_dump(), status_code=202)

    @app.get("/portals/{portal_id}/tenders")
    def list_tenders(portal_id: str, changedSince: str | None = Query(None)) -> JSONResponse:  # noqa: N803
        """The tenders held for the portal; with `changedSince`, only those that changed later."""
        known(portal_id)
        since = None
        if changedSince is not None:
            try:
                since = parse_changed_since(changedSince)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="changedSince must be a date and time with offset, such as 2026-12-09T10:00:00+01:00.",
                ) from None
        now = utcnow()
        out = []
        for record, tender_files in store.list_tenders(portal_id):
            if since is not None and record.effective_last_changed(now) <= since:
                continue
            out.append(record.to_api(tender_files, now=now))
        return JSONResponse(out)

    @app.get("/portals/{portal_id}/runs")
    def list_runs(portal_id: str) -> JSONResponse:
        """Every read and repair of the portal, oldest first."""
        known(portal_id)
        return JSONResponse([run.to_api().model_dump(mode="json") for run in store.list_runs(portal_id)])

    @app.get("/files/{file_id}")
    def get_file(file_id: str) -> FileResponse:
        """The bytes of one document. Each document's `path` points here."""
        record = store.get_file(file_id)
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
    def index() -> str:
        """Placeholder until the dashboard (`app/dashboard/`) replaces it."""
        return PLACEHOLDER_PAGE

    return app


app = create_app()
