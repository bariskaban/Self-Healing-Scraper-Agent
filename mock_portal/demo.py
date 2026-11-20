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
"""
from __future__ import annotations

import argparse
import os
import tempfile
from collections.abc import Sequence

import httpx
from fastapi import FastAPI

from app.checks import CheckSettings
from app.fetch import Fetcher, FetchSettings, PortalLimiter
from app.main import create_app
from mock_portal.portal import MockPortal

DEMO_URL = "https://mock.example"  # the address to add: the mock portal's own name
# The mock portal is ours and in this process, so the demo need not wait a second between two
# requests as it must for a real portal. At 25 a second the attach takes a few seconds.
DEFAULT_REQUESTS_PER_SECOND = 25.0


def build_app(mock: MockPortal | None = None, *,
              requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND) -> FastAPI:
    """The app on DATA_DIR, with a network layer that reaches the mock portal and nothing else."""
    mock = mock or MockPortal(base_url=DEMO_URL)
    settings, checks = FetchSettings.from_env(), CheckSettings.from_env()
    # The limiter is given here because the default one does not wait in replay mode.
    limiter = PortalLimiter(requests_per_second, checks.slowest_request_interval_seconds)
    fetcher = Fetcher(settings, checks, transport=httpx.MockTransport(mock.handle), limiter=limiter)
    return create_app(fetch=fetcher, mock=mock)


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
    print(f"Records in {os.environ['DATA_DIR']}. Add the portal {DEMO_URL} on http://{args.host}:{args.port}/")
    uvicorn.run(build_app(requests_per_second=args.requests_per_second), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
