"""The fetch interface (docs/BUILD-PLAN.md: stream C hands it to A and B).

Three kinds of request reach a portal, and only through here (CONVENTIONS.md, rule 1):

  * `fetch`: one HTTP request (a page, an API call, a form post), redirects walked one
    hop at a time, each hop through the rate limiter;
  * `browse`: one page in the headless browser, with the network calls it made, for
    portals that need JavaScript and to find the JSON API behind a page (Q3, Q4);
  * `download`: one document, streamed as the `Download` that `app.docs.store_document` takes.

Every answer carries `Answer`, the facts `app/checks` classifies (Q10, step 1), and how many
tries it took, so the reader can call `transport_check(run_id, f.answer, tries=f.tries,
at_slowest_rate=f.at_slowest_rate)` without knowing anything about HTTP.

Rules T1 and T2 are applied inside: answers that mean "not now" are retried with growing
pauses, and a rate limit halves the portal's rate. What comes back is the last answer.
robots.txt is obeyed before every request unless the test switch is on.

Where answers come from is set by FETCH_MODE (`FetchSettings.mode`): live, record or replay.
"""
from __future__ import annotations

import json as jsonlib
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.checks import Answer, Transport, classify_answer
from app.docs import Download
from app.models import NetworkEntry

_CHARSET = re.compile(r"charset=([\w.-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class Fetched:
    """The last answer to one HTTP request, after redirects and retries."""

    url: str                          # what was asked
    final_url: str                    # where the redirects ended
    status: int | None                # None when no HTTP answer came at all (see answer.error)
    headers: httpx.Headers
    body: bytes                       # the whole body, decoded from gzip and the like
    answer: Answer                    # the facts for app/checks
    redirects: tuple[str, ...] = ()   # every address before final_url, in order
    tries: int = 1                    # tries under rule T1
    at_slowest_rate: bool = False     # rule T2: still rate limited at our slowest pace
    retry_after_seconds: float | None = None  # a Retry-After too long to wait for in place

    @property
    def ok(self) -> bool:
        """A 2xx answer."""
        return self.status is not None and 200 <= self.status < 300

    @property
    def transport(self) -> Transport:
        """answered, outage, rate_limited or certificate (Q10, rules T1, T2, T4)."""
        return classify_answer(self.answer)

    @property
    def content_type(self) -> str | None:
        value = self.headers.get("content-type")
        return value.split(";")[0].strip().lower() if value else None

    @property
    def text(self) -> str:
        """The body as text, in the charset the answer names (UTF-8 otherwise)."""
        match = _CHARSET.search(self.headers.get("content-type", ""))
        encoding = match.group(1) if match else "utf-8"
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return jsonlib.loads(self.body)


@dataclass(frozen=True)
class BrowsedPage:
    """One page as the headless browser left it, with the network calls it made (Q4)."""

    url: str
    final_url: str
    status: int | None
    html: str                          # the DOM after load, as HTML
    answer: Answer                     # facts of the page's own document request
    network: list[NetworkEntry] = field(default_factory=list)  # same-origin calls, JSON ones marked
    tries: int = 1
    at_slowest_rate: bool = False


class FetchFailed(Exception):
    """A download got no HTTP answer at all, after the tries rule T1 allows."""

    def __init__(self, url: str, answer: Answer, tries: int, at_slowest_rate: bool = False) -> None:
        super().__init__(f"No answer for {url} ({answer.error or 'rate limited'}, {tries} tries)")
        self.url = url
        self.answer = answer
        self.tries = tries
        self.at_slowest_rate = at_slowest_rate


class RobotsForbidden(Exception):
    """The portal's robots.txt disallows this address for us. We obey it (the mentor's answer)."""

    def __init__(self, url: str) -> None:
        super().__init__(f"robots.txt disallows {url}")
        self.url = url


class RobotsUnavailable(Exception):
    """The portal's robots.txt could not be read (server error or no answer).

    RFC 9309: an unreachable robots.txt means nothing may be fetched. The checks treat it as
    an outage: `transport_check(run_id, e.fetched.answer, tries=e.fetched.tries)`.
    """

    def __init__(self, fetched: Fetched) -> None:
        super().__init__(f"robots.txt of {fetched.url} could not be read ({fetched.status or fetched.answer.error})")
        self.fetched = fetched


class Fetch(Protocol):
    """What the read loop (stream A) and the agent's tools (stream B) call. `Fetcher` provides it."""

    def fetch(self, portal_id: str, url: str, *, method: str = "GET", params: dict[str, Any] | None = None,
              data: dict[str, Any] | None = None, json: Any = None, headers: dict[str, str] | None = None,
              page_load: bool = True) -> Fetched:
        """One HTTP request. Raises RobotsForbidden or RobotsUnavailable; never raises for an HTTP status."""
        ...

    def browse(self, portal_id: str, url: str) -> BrowsedPage:
        """One page in the headless browser, with the network calls it made."""
        ...

    def download(self, portal_id: str, url: str, *, headers: dict[str, str] | None = None
                 ) -> AbstractContextManager[Download]:
        """One document, streamed. Any HTTP answer is handed over, for app/docs to judge;
        raises FetchFailed when no answer came at all."""
        ...

    def robots_forbids_every_path(self, portal_id: str, url: str) -> bool:
        """For `app.checks.robots_check`: does the portal's robots.txt forbid every path to us?"""
        ...

    def limit(self, portal_id: str, requests_per_second: float) -> None:
        """A portal that states a lower limit than ours keeps to it."""
        ...

    def forget(self, portal_id: str) -> None:
        """Drop a deleted portal's session, robots.txt and pace. No request goes to it after this."""
        ...
