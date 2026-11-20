"""`Fetcher`: the fetch interface on httpx, with the rate limiter, robots.txt and record/replay.

Blocking, like `app/docs` and `app/db`: call it from a worker thread, one portal per thread.
Each portal has its own session (cookies stay within the portal) and its own pace.

Redirects are walked here, not by httpx, so that each hop waits for its own slot and is
checked against robots.txt (the audit of Q4: a page behind two redirects otherwise sends
three requests within milliseconds).
"""
from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.checks import DEFAULT_SETTINGS, Answer, CheckSettings, Transport, classify_answer
from app.scheduler import parse_retry_after

from .answer import answer_from_error, answer_from_response
from .interface import BrowsedPage, Fetched, FetchFailed, RobotsForbidden, RobotsUnavailable
from .limiter import PortalLimiter
from .record import RecordingTransport, ReplayTransport, load_browsed
from .robots import RobotsRules, origin_of, robots_url
from .settings import DEFAULT_FETCH_SETTINGS, FetchMode, FetchSettings

REDIRECTS = frozenset({301, 302, 303, 307, 308})
CHUNK_BYTES = 1024 * 1024


class _Shared(httpx.BaseTransport):
    """A transport handed in from outside (tests): used by every session, closed by none."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.inner.handle_request(request)

    def close(self) -> None:
        return None


class _Streamed:
    """One download as `app.docs.Download`: status, headers, final address and the body in chunks."""

    def __init__(self, response: httpx.Response, final_url: str) -> None:
        self._response = response
        self.status = response.status_code
        self.headers = response.headers
        self.final_url = final_url

    def chunks(self) -> Iterator[bytes]:
        return self._response.iter_bytes(CHUNK_BYTES)


@dataclass
class _Last:
    """The last answer of one request after rules T1 and T2."""

    answer: Answer
    final_url: str
    hops: tuple[str, ...]
    headers: httpx.Headers
    body: bytes
    tries: int
    at_slowest: bool = False
    retry_after: float | None = None        # only when too long to wait for in place
    response: httpx.Response | None = None  # still open: a streamed download


class Fetcher:
    """`app.fetch.interface.Fetch` on httpx. One instance for the whole process; thread-safe."""

    def __init__(self, settings: FetchSettings = DEFAULT_FETCH_SETTINGS, checks: CheckSettings = DEFAULT_SETTINGS,
                 *, transport: httpx.BaseTransport | None = None, limiter: PortalLimiter | None = None,
                 clock: Callable[[], float] = time.monotonic, rng: Callable[[], float] = random.random) -> None:
        self.settings = settings
        self.checks = checks
        self.limiter = limiter or PortalLimiter(
            settings.requests_per_second, checks.slowest_request_interval_seconds,
            enabled=settings.mode is not FetchMode.replay)
        self._transport = transport
        self._clock = clock
        self._rng = rng
        self._lock = threading.Lock()
        self._sessions: dict[str, httpx.Client] = {}
        self._robots: dict[tuple[str, str], RobotsRules] = {}

    @classmethod
    def from_env(cls) -> "Fetcher":
        return cls(FetchSettings.from_env())

    # -- sessions --

    def _make_transport(self) -> httpx.BaseTransport:
        if self._transport is not None:
            return _Shared(self._transport)
        if self.settings.mode is FetchMode.replay:
            return ReplayTransport(self.settings.recordings_dir)
        live = httpx.HTTPTransport(verify=True, retries=0)  # never switch verification off (Q10, T4)
        if self.settings.mode is FetchMode.record:
            return RecordingTransport(live, self.settings.recordings_dir)
        return live

    def _session(self, portal_id: str) -> httpx.Client:
        with self._lock:
            client = self._sessions.get(portal_id)
            if client is None:
                timeout = httpx.Timeout(self.settings.read_timeout_seconds,
                                        connect=self.settings.connect_timeout_seconds)
                client = httpx.Client(transport=self._make_transport(), follow_redirects=False, timeout=timeout,
                                      headers={"User-Agent": self.settings.user_agent})
                self._sessions[portal_id] = client
            return client

    def forget(self, portal_id: str) -> None:
        with self._lock:
            client = self._sessions.pop(portal_id, None)
            for key in [k for k in self._robots if k[0] == portal_id]:
                del self._robots[key]
        if client is not None:
            client.close()
        self.limiter.forget(portal_id)

    def close(self) -> None:
        with self._lock:
            sessions, self._sessions = list(self._sessions.values()), {}
        for client in sessions:
            client.close()

    def limit(self, portal_id: str, requests_per_second: float) -> None:
        self.limiter.limit(portal_id, requests_per_second)

    # -- one request: redirects hop by hop, then rules T1 and T2 --

    def _walk(self, portal_id: str, method: str, url: str, *, params: dict[str, Any] | None,
              data: dict[str, Any] | None, json_body: Any, headers: dict[str, str] | None, obey_robots: bool
              ) -> tuple[httpx.Response | None, BaseException | None, str, tuple[str, ...]]:
        """Send the request and follow its redirects: (open response or None, error, final address, hops)."""
        client = self._session(portal_id)
        current = httpx.URL(url, params=params) if params else httpx.URL(url)
        body: dict[str, Any] = {}
        if data is not None:
            body["data"] = data
        elif json_body is not None:
            body["json"] = json_body
        hops: list[str] = []
        while True:
            if obey_robots:
                self._robots_gate(portal_id, str(current))
            request = client.build_request(method, current, headers=headers, **body)
            self.limiter.acquire(portal_id)
            try:
                response = client.send(request, stream=True)
            except httpx.HTTPError as exc:
                return None, exc, str(current), tuple(hops)
            location = response.headers.get("location")
            if response.status_code in REDIRECTS and location and len(hops) < self.settings.max_redirects:
                response.close()
                hops.append(str(current))
                current = current.join(location)
                if response.status_code == 303 or (response.status_code in (301, 302)
                                                   and method not in ("GET", "HEAD")):
                    method, body = "GET", {}
                continue
            return response, None, str(current), tuple(hops)

    def _pause(self, tries: int) -> float:
        """Rule T1: a randomised, growing pause before the next try (ours: half fixed, half random)."""
        grown = min(self.checks.retry_pause_cap_seconds, self.checks.retry_pause_base_seconds * 2 ** (tries - 1))
        return grown * (0.5 + 0.5 * self._rng())

    def _request(self, portal_id: str, method: str, url: str, *, page_load: bool, stream: bool,
                 obey_robots: bool, params: dict[str, Any] | None = None, data: dict[str, Any] | None = None,
                 json_body: Any = None, headers: dict[str, str] | None = None) -> _Last:
        tries = 0
        while True:
            response, error, final_url, hops = self._walk(portal_id, method, url, params=params, data=data,
                                                          json_body=json_body, headers=headers,
                                                          obey_robots=obey_robots)
            body = b""
            keep_open = False
            if response is None:
                answer, resp_headers = answer_from_error(error, page_load=page_load), httpx.Headers()
            else:
                resp_headers = response.headers
                keep_open = stream and 200 <= response.status_code < 300
                if not keep_open:  # a page, or an error page in place of a file: read it to look at it
                    try:
                        body = response.read()
                    finally:
                        response.close()
                answer = answer_from_response(response.status_code, resp_headers, body[: self.settings.sniff_bytes],
                                              final_url=final_url, redirects=hops, page_load=page_load)
            kind = classify_answer(answer)
            wait = parse_retry_after(resp_headers.get("retry-after"), datetime.now(timezone.utc))
            retry_after = wait.total_seconds() if wait is not None else None
            too_long = retry_after is not None and retry_after > self.checks.retry_after_inline_max_seconds
            open_response = response if keep_open else None  # a 2xx download, its body not read yet

            if kind is Transport.rate_limited:  # T2: halve the portal's rate, then go on
                at_slowest = self.limiter.slow_down(portal_id)
                if at_slowest or too_long:
                    return _Last(answer, final_url, hops, resp_headers, body, max(tries, 1), at_slowest,
                                 retry_after if too_long else None, open_response)
                self._close(open_response)
                self.limiter.hold(portal_id, retry_after or 0.0)
                continue  # waiting out a rate limit is not a T1 try
            tries += 1
            if kind is Transport.outage and tries < self.checks.request_tries and not too_long:  # T1
                self._close(open_response)
                self.limiter.hold(portal_id, max(self._pause(tries), retry_after or 0.0))
                continue
            return _Last(answer, final_url, hops, resp_headers, body, tries, False,
                         retry_after if too_long else None, open_response)

    @staticmethod
    def _close(response: httpx.Response | None) -> None:
        if response is not None:
            response.close()

    # -- robots.txt --

    def _rules(self, portal_id: str, url: str) -> RobotsRules:
        origin = origin_of(url)
        key = (portal_id, origin)
        with self._lock:
            rules = self._robots.get(key)
        if rules is not None and self._clock() - rules.fetched_at < self.settings.robots_cache_seconds:
            return rules
        last = self._request(portal_id, "GET", robots_url(url), page_load=False, stream=False, obey_robots=False)
        now = self._clock()
        status = last.answer.status
        if status is not None and 200 <= status < 300:
            rules = RobotsRules.parse(origin, last.body, now)
        elif status is not None and 300 <= status < 500 and status != 429:
            rules = RobotsRules.allow_all(origin, now)  # "unavailable": no rules (also a redirect loop)
        else:
            raise RobotsUnavailable(self._fetched(robots_url(url), last))
        with self._lock:
            self._robots[key] = rules
        return rules

    def _robots_gate(self, portal_id: str, url: str) -> None:
        if self.settings.ignore_robots_txt:
            return
        if not self._rules(portal_id, url).allowed(url, self.settings.user_agent):
            raise RobotsForbidden(url)

    def robots_forbids_every_path(self, portal_id: str, url: str) -> bool:
        return self._rules(portal_id, url).forbids_every_path(self.settings.user_agent)

    # -- the interface --

    @staticmethod
    def _fetched(url: str, last: _Last) -> Fetched:
        return Fetched(url=url, final_url=last.final_url, status=last.answer.status, headers=last.headers,
                       body=last.body, answer=last.answer, redirects=last.hops, tries=last.tries,
                       at_slowest_rate=last.at_slowest, retry_after_seconds=last.retry_after)

    def fetch(self, portal_id: str, url: str, *, method: str = "GET", params: dict[str, Any] | None = None,
              data: dict[str, Any] | None = None, json: Any = None, headers: dict[str, str] | None = None,
              page_load: bool = True) -> Fetched:
        last = self._request(portal_id, method, url, page_load=page_load, stream=False, obey_robots=True,
                             params=params, data=data, json_body=json, headers=headers)
        return self._fetched(url, last)

    @contextmanager
    def download(self, portal_id: str, url: str, *, headers: dict[str, str] | None = None) -> Iterator[_Streamed]:
        last = self._request(portal_id, "GET", url, page_load=False, stream=True, obey_robots=True, headers=headers)
        if last.answer.status is None:
            raise FetchFailed(url, last.answer, last.tries, last.at_slowest)
        if last.response is not None:
            try:
                yield _Streamed(last.response, last.final_url)
            finally:
                last.response.close()
            return
        # Not a 2xx: the error page was read; hand it over so app/docs judges it (login page, 404).
        # Its body is already decoded, so the encoding headers go.
        plain = [(k, v) for k, v in last.headers.multi_items()
                 if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
        yield _Streamed(httpx.Response(last.answer.status, headers=plain, content=last.body), last.final_url)

    def browse(self, portal_id: str, url: str) -> BrowsedPage:
        """A page in the headless browser. Replay serves recorded pages; the live browser comes next."""
        if self.settings.mode is not FetchMode.replay:
            raise NotImplementedError("The live browser (Playwright) is not built yet: docs/BUILD-PLAN.md, stream C.")
        self._robots_gate(portal_id, url)
        recorded = load_browsed(self.settings.recordings_dir, url)
        html = recorded.html.encode("utf-8")
        answer = answer_from_response(recorded.status or 0, httpx.Headers(recorded.headers), html[: self.settings.sniff_bytes],
                                      final_url=recorded.final_url,
                                      redirects=(url,) if recorded.final_url != url else (), via="browser")
        return BrowsedPage(url=url, final_url=recorded.final_url, status=recorded.status, html=recorded.html,
                           answer=answer, network=recorded.network)
