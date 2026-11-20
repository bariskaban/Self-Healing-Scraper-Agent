"""See the product on your own machine, with no network: the app reading its mock portal.

    python -m mock_portal.demo            then open http://127.0.0.1:8791/

and add the portal the page asks for, or from a second terminal:

    curl -X POST http://127.0.0.1:8791/portals -H 'content-type: application/json' \\
         -d '{"url": "https://mock.example"}'

This is the app of `app/main.py` with one difference: its network layer is handed a transport
that answers every request from the mock portal inside this process, the way the tests do
(`tests/test_loop.py`). So `FETCH_MODE` is not set and need not be (CLAUDE.md: only the
Dockerfile sets it to live), and no request can leave the machine whatever address is added:
`https://mock.example` is read by the mock portal's hand-written recipe, and any other address
ends `failed` with "No recipe could be learned", without a request.

The same mock portal is mounted at /mock, so you can look at the pages that are being read.
Records go to DATA_DIR when it is set, and to a temporary folder otherwise.

For showing a break and a block there are two mock portals and three routes that exist only here:

    https://mock.example          the portal whose layout changes
    https://login.mock.example    a second portal, for the login wall

    POST /demo/layout             the first portal changes its layout (a breakage: repaired by the model)
    POST /demo/login-wall         the second portal puts every page behind a login (a block: failed)
    POST /demo/reset              both portals work again
    GET  /demo/runs/{portal_id}   the portal's runs with their model calls, cost and recipe version

The routes change the mock portals only. The app notices on its next scheduled read
(READ_INTERVAL_SECONDS) or on `POST /portals/{id}/refresh`. A repair needs OPENAI_API_KEY.
"""
from __future__ import annotations

import argparse
import os
import tempfile
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI

from app.checks import CheckSettings
from app.db import Database
from app.fetch import Fetcher, FetchSettings, PortalLimiter
from app.main import create_app
from mock_portal.portal import MockPortal

DEMO_URL = "https://mock.example"  # the address to add: the mock portal's own name
LOGIN_URL = "https://login.mock.example"  # the second mock portal, for the login wall
# The mock portal is ours and in this process, so the demo need not wait a second between two
# requests as it must for a real portal. At 25 a second the attach takes a few seconds.
DEFAULT_REQUESTS_PER_SECOND = 25.0


def build_app(mock: MockPortal | None = None, *, requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
              second: MockPortal | None = None) -> FastAPI:
    """The app on DATA_DIR, with a network layer that reaches the two mock portals and nothing else."""
    mock = mock or MockPortal(base_url=DEMO_URL)
    second = second or MockPortal(tenders=12, base_url=LOGIN_URL)
    login_host = urlsplit(LOGIN_URL).hostname

    def handle(request: httpx.Request) -> httpx.Response:
        return (second if request.url.host == login_host else mock).handle(request)

    settings, checks = FetchSettings.from_env(), CheckSettings.from_env()
    # The limiter is given here because the default one does not wait in replay mode.
    limiter = PortalLimiter(requests_per_second, checks.slowest_request_interval_seconds)
    fetcher = Fetcher(settings, checks, transport=httpx.MockTransport(handle), limiter=limiter)
    app = create_app(fetch=fetcher, mock=mock)
    add_demo_routes(app, mock, second)
    return app


def add_demo_routes(app: FastAPI, mock: MockPortal, second: MockPortal) -> None:
    """The switches of the two mock portals, and a look at a portal's runs. Only the demo has these."""

    def switches() -> dict[str, Any]:
        return {DEMO_URL: {"layout_changed": mock.layout_changed}, LOGIN_URL: {"login_wall": second.login_wall}}

    @app.post("/demo/layout")
    def change_layout() -> dict[str, Any]:
        """The first mock portal shows its list as cards and its tender page as a table: a breakage."""
        mock.layout_changed = True
        return switches()

    @app.post("/demo/login-wall")
    def put_up_login_wall() -> dict[str, Any]:
        """Every page of the second mock portal redirects to a login page: a block."""
        second.login_wall = "all"
        return switches()

    @app.post("/demo/reset")
    def reset() -> dict[str, Any]:
        """Both mock portals work again as at the start."""
        mock.reset()
        second.reset()
        return switches()

    @app.get("/demo/runs/{portal_id}")
    def runs(portal_id: str) -> list[dict[str, Any]]:
        """Each run of the portal, oldest first: a run that called the model is a learn or a repair."""
        database = Database.from_env()
        try:
            return [{"runId": run.id, "trigger": run.trigger.value, "startedAt": run.started_at.isoformat(),
                     "result": run.result.value if run.result else None,
                     "stateAfter": run.state_after.value if run.state_after else None,
                     "modelCalls": run.model_calls, "costUsd": round(run.usage.cost_usd, 4),
                     "recipeVersion": run.recipe_version, "reason": run.reason_after}
                    for run in database.list_runs(portal_id)]
        finally:
            database.close()


def main(argv: Sequence[str] | None = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Serve Watchtower reading its own mock portal, with no network.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--requests-per-second", type=float, default=DEFAULT_REQUESTS_PER_SECOND,
                        help="how fast the mock portal is read (a real portal gets 1)")
    args = parser.parse_args(argv)
    if not os.environ.get("DATA_DIR"):
        os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="watchtower-demo-")
    print(f"Records in {os.environ['DATA_DIR']}. Add the portals {DEMO_URL} and {LOGIN_URL} "
          f"on http://{args.host}:{args.port}/")
    uvicorn.run(build_app(requests_per_second=args.requests_per_second), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
