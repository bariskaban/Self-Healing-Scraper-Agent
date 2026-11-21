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
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.dashboard_api import add_dashboard_routes
from app.checks import CheckSettings
from app.db import Database
from app.docs import DocsSettings, FileStore
from app.interfaces import Store, Worker
from app.memory_store import IdleWorker, MemoryStore
from app.fetch import Fetcher
from app.loop import ReadLoop
from app.reader import Learned, Learner, NotLearned, Reader, Repairer, SpotChecked, SpotChecker
from app.recipe.settings import RecipeSettings
from app.scheduler import SchedulerSettings
from app.tenders_answer import TendersAnswers
from app.models import CreatedId, Portal, PortalCreate, RunAccepted, url_key, utcnow

T = TypeVar("T")

PORTAL_ID_LENGTH = 12
# A time of day, a space, and an offset at the end: the space was a "+" before URL decoding.
_LOST_PLUS = re.compile(r"(\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?) (\d{2}:?\d{2})$")

# The dashboard is a static page built from dashboard/ (see docs/DASHBOARD_API.md for what it reads).
DASHBOARD_DIR = Path(__file__).parent / "dashboard" / "static"
DASHBOARD_PAGE = DASHBOARD_DIR / "index.html"
DASHBOARD_ROOT_FILES = ("favicon.ico", "robots.txt")

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


MOCK_PATH = "/mock"  # where the mock portal is mounted, for demos and end-to-end tests


def builtin_learner(portal: Portal, run_id: str) -> Learned | None:
    """The recipes this build knows without a model: the mock portal's, written by hand.

    The learning agent (app/agent, stream B) takes this place for every other portal.
    """
    from urllib.parse import urlsplit

    import mock_portal

    path = urlsplit(portal.url).path.rstrip("/")
    host = urlsplit(portal.url).hostname or ""
    # `mock.example` is the mock portal's own name; the demo serves further ones under it.
    if path.endswith(MOCK_PATH) or host == "mock.example" or host.endswith(".mock.example"):
        root = path if path.endswith(MOCK_PATH) else ""
        return Learned(recipe=mock_portal.recipe(root), timezone=mock_portal.TIMEZONE, country_code="NL")
    return None


def agent_hooks(agents: Any, *, mock_by_model: bool = False
                ) -> tuple[Learner, Repairer | None, SpotChecker | None]:
    """What the reader calls to learn, repair and spot-check, on the agents of `app/agent`.

    Without agents (no OPENAI_API_KEY) the build knows only the mock portal's hand-written recipe,
    repairs nothing and checks nothing with a model. With them the hand-written recipe still
    serves the mock portal, so the demo costs nothing, unless `mock_by_model` (MOCK_LEARNED_BY_MODEL)
    says the model shall learn it too; and it stays the fallback when the model finds no recipe.
    """
    if agents is None:
        return builtin_learner, None, None

    def result(found: Any) -> Learned | NotLearned:
        if found.recipe is None:
            return NotLearned(reason=found.reason, model_calls=found.model_calls, usage=found.usage)
        return Learned(recipe=found.recipe, timezone=found.timezone, country_code=found.country_code,
                       model_calls=found.model_calls, usage=found.usage)

    def learn(portal: Portal, run_id: str) -> Learned | NotLearned | None:
        known = builtin_learner(portal, run_id)
        if known is not None and not mock_by_model:
            return known
        learned = result(agents.learn(portal, run_id))
        if isinstance(learned, NotLearned) and known is not None:
            return Learned(recipe=known.recipe, timezone=known.timezone, country_code=known.country_code,
                           model_calls=learned.model_calls, usage=learned.usage)
        return learned

    def repair(portal: Portal, recipe: Any, failed: Any, run_id: str) -> Learned | NotLearned | None:
        return result(agents.repair(portal, recipe, failed, run_id))

    def spot_check(portal: Portal, records: Any, finding: str, run_id: str) -> SpotChecked | None:
        found = agents.spot_check(portal, records, finding, run_id)
        if found is None:
            return None
        return SpotChecked(passed=found.passed, message=found.message, model_calls=found.model_calls,
                           usage=found.usage)

    return learn, repair, spot_check


def default_store() -> tuple[Store, Worker | None]:
    """The SQLite store under DATA_DIR when it is set (the container sets it); memory otherwise.

    On the database the worker is the read loop, which `create_app` builds; in memory it is a
    stand-in that reads nothing.
    """
    if os.environ.get("DATA_DIR"):
        database = Database.from_env()
        return database, None  # create_app builds the read loop on it
    memory = MemoryStore()
    return memory, IdleWorker(memory)


def create_app(store: Store | None = None, worker: Worker | None = None,
               files: Callable[[], FileStore] | None = None, *, fetch: Fetcher | None = None,
               mock: Any = None,
               agents: Callable[[Fetcher, Database], Any] | None = None) -> FastAPI:
    """The app on a given store and worker. Without them, on `default_store()`.

    `fetch` replaces the network layer of the read loop and `mock` the mock portal mounted at
    /mock: tests hand in a fetcher that reaches the mock portal in this process. `agents`
    builds the learning and repair agents (`app.agent.Agents`) from the network layer and the
    database: tests hand in one on a scripted model. Without it the agents are built on OpenAI
    when OPENAI_API_KEY is set, and else there are none.
    """
    opened: Database | None = None  # a database this app opened itself, and closes on shutdown
    if store is None:
        store, default_worker = default_store()
        worker = worker or default_worker
        opened = store if isinstance(store, Database) else None
    if worker is None and opened is None:
        raise ValueError("a store was given without a worker")
    file_store: list[FileStore] = []

    def documents() -> FileStore:
        # Opened on first use: creating it makes directories under DATA_DIR.
        if not file_store:
            file_store.append(files() if files is not None else FileStore(DocsSettings.from_env()))
        return file_store[0]

    fetcher: Fetcher | None = None
    if worker is None:  # our own database and no worker given: the read loop
        fetcher = fetch or Fetcher.from_env()
        # Every number of ours comes from the environment (CLAUDE.md): READ_INTERVAL_SECONDS,
        # ATTACH_TIME_LIMIT_SECONDS, the check thresholds, the executor's ceilings.
        schedule = SchedulerSettings.from_env()
        recipes = RecipeSettings.from_env()
        if agents is None:
            from app.agent import Agents

            built = Agents.from_env(fetcher, opened, recipes=recipes)
        else:
            built = agents(fetcher, opened)
        mock_by_model = os.environ.get("MOCK_LEARNED_BY_MODEL", "").strip().lower() in ("1", "true", "yes", "on")
        learn, repair, spot_check = agent_hooks(built, mock_by_model=mock_by_model)
        reader = Reader(opened, fetcher, documents, learn=learn, repair=repair, spot_check=spot_check,
                        checks=CheckSettings.from_env(), schedule=schedule, recipes=recipes,
                        ignore_robots=fetcher.settings.ignore_robots_txt)
        worker = ReadLoop(opened, reader, fetcher, schedule=schedule)

    database = ThreadPoolExecutor(max_workers=1, thread_name_prefix="watchtower-db")
    # The tenders of a big portal are built here, on a read connection of their own (app/tenders_answer.py), so
    # that building them never holds up the dashboard's small reads on `database`. Only a Database has it.
    heavy = ThreadPoolExecutor(max_workers=2, thread_name_prefix="watchtower-tenders")
    answers = TendersAnswers(store) if isinstance(store, Database) else None

    async def on_db(call: Callable[..., T], *args: Any) -> T:
        """Run one call to the store on the database thread."""
        return await asyncio.get_running_loop().run_in_executor(database, call, *args)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if isinstance(worker, ReadLoop):
            await worker.start()
        yield
        if isinstance(worker, ReadLoop):
            await worker.stop()
        if fetcher is not None:
            fetcher.close()
        database.shutdown(wait=False, cancel_futures=True)
        heavy.shutdown(wait=False, cancel_futures=True)
        if opened is not None:
            opened.close()

    app = FastAPI(title="Watchtower", docs_url="/api-docs", redoc_url=None, lifespan=lifespan)
    # The dashboard may be developed on another port; the API holds nothing private.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    if os.environ.get("MOCK_PORTAL", "1").strip().lower() not in ("0", "false", "no", "off"):
        from mock_portal import MockPortal

        app.state.mock_portal = mock or MockPortal()  # the portal we break on purpose (DESIGN.md, "Mock portal")
        app.mount(MOCK_PATH, app.state.mock_portal.asgi())

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
    async def list_tenders(request: Request, portal_id: str,
                           changedSince: str | None = Query(None)) -> Response:  # noqa: N803
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
        if answers is None:  # the in-memory stand-in: small, and built on the database thread as before
            return JSONResponse(await on_db(tender_answers, portal_id, since))
        now = utcnow()
        tag = answers.etag(portal_id, now)
        if since is None and request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"ETag": tag, "Cache-Control": "no-cache"})
        loop = asyncio.get_running_loop()
        made = await loop.run_in_executor(heavy, answers.answer, portal_id, since, now)
        body, zipped = made.encoded("gzip" in request.headers.get("accept-encoding", "").lower())
        headers = {"Vary": "Accept-Encoding", "Cache-Control": "no-cache"}
        if zipped:
            headers["Content-Encoding"] = "gzip"
        if since is None:
            headers["ETag"] = made.etag
        return Response(content=body, media_type="application/json", headers=headers)

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

    add_dashboard_routes(app, store, on_db, worker)  # /api/...: what the page reads (docs/DASHBOARD_API.md)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> Response:
        """The dashboard page (built from the dashboard source into app/dashboard/static/), or a placeholder."""
        if DASHBOARD_PAGE.is_file():
            return FileResponse(DASHBOARD_PAGE, media_type="text/html", headers={"Cache-Control": "no-cache"})
        return HTMLResponse(PLACEHOLDER_PAGE)

    for name in DASHBOARD_ROOT_FILES:
        if (DASHBOARD_DIR / name).is_file():
            app.add_api_route(f"/{name}", _static_file(DASHBOARD_DIR / name), include_in_schema=False)
    if (DASHBOARD_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=DASHBOARD_DIR / "assets"), name="dashboard-assets")

    return app


def _static_file(path: Path) -> Callable[[], FileResponse]:
    def serve() -> FileResponse:
        return FileResponse(path)
    return serve


app = create_app()
