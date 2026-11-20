"""The network layer (Q4, Q10; docs/BUILD-PLAN.md, stream C): the only place a request to a portal starts.

`Fetch` in `interface.py` is what the read loop and the agent's tools call; `Fetcher` provides
it on httpx. One request start per second per portal, redirects walked hop by hop, rules T1
and T2 applied, robots.txt obeyed unless IGNORE_ROBOTS_TXT is set, and every exchange
recorded or replayed by FETCH_MODE. The live browser comes in the next step; `browse`
already replays recorded browser pages.

Blocking: call it from a worker thread, like `app/docs` and `app/db`.
"""
from app.fetch.answer import answer_from_error, answer_from_response, error_kind
from app.fetch.client import Fetcher
from app.fetch.interface import BrowsedPage, Fetch, Fetched, FetchFailed, RobotsForbidden, RobotsUnavailable
from app.fetch.limiter import PortalLimiter
from app.fetch.record import RecordedPage, RecordingTransport, ReplayMiss, ReplayTransport, load_browsed, save_browsed
from app.fetch.robots import RobotsRules
from app.fetch.settings import DEFAULT_FETCH_SETTINGS, FetchMode, FetchSettings

__all__ = [
    "DEFAULT_FETCH_SETTINGS", "BrowsedPage", "Fetch", "FetchFailed", "FetchMode", "FetchSettings", "Fetched",
    "Fetcher", "PortalLimiter", "RecordedPage", "RecordingTransport", "ReplayMiss", "ReplayTransport",
    "RobotsForbidden", "RobotsRules", "RobotsUnavailable", "answer_from_error", "answer_from_response",
    "error_kind", "load_browsed", "save_browsed",
]
