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

from app import logs
from app.checks import DEFAULT_SETTINGS, Answer, CheckSettings, Transport, classify_answer
from app.scheduler import parse_retry_after

from .answer import answer_from_error, answer_from_response
from .interface import BrowsedPage, Fetched, FetchFailed, RobotsForbidden, RobotsUnavailable
from .limiter import PortalLimiter
from .record import RecordingTransport, ReplayTransport, load_browsed
from .robots import RobotsRules, origin_of, robots_url
from .settings import DEFAULT_FETCH_SETTINGS, FetchMode, FetchSettings

log = logs.get("fetch")

REDIRECTS = frozenset({301, 302, 303, 307, 308})
CHUNK_BYTES = 1024 * 1024
# Headers a caller sets for one host, which a redirect to another host must not receive.
CREDENTIAL_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


_ANSWER = "watchtower.answer"


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return url.scheme, url.host, url.port


def _remember_answer(response: httpx.Response) -> None:
    """Keep each answer with its request, so `_walk` still has it if httpx refuses its Location."""
    response.request.extensions[_ANSWER] = response


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

    def __init__(self, response: httpx.Response, final_url: str, tries: int = 1) -> None:
        self._response = response
        self._tries = tries
        self.status = response.status_code
        self.headers = response.headers
        self.final_url = final_url

    def chunks(self) -> Iterator[bytes]:
        # The body can still break off after the headers (timeout, reset, bad encoding).
        # The caller must not need httpx to catch that, so it becomes FetchFailed.
        try:
            yield from self._response.iter_bytes(CHUNK_BYTES)
        except httpx.HTTPError as exc:
            raise FetchFailed(self.final_url, answer_from_error(exc, page_load=False), self._tries) from exc


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
        log.debug("fetcher ready: mode=%s rate=%s/s ignore_robots=%s recordings=%s", settings.mode.value,
                  settings.requests_per_second, settings.ignore_robots_txt, settings.recordings_dir)

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
                                      headers={"User-Agent": self.settings.user_agent},
                                      event_hooks={"response": [_remember_answer]})
                self._sessions[portal_id] = client
                log.debug("portal %s: new session (%s transport)", portal_id, self.settings.mode.value)
            return client

    def forget(self, portal_id: str) -> None:
        with self._lock:
            client = self._sessions.pop(portal_id, None)
            for key in [k for k in self._robots if k[0] == portal_id]:
                del self._robots[key]
        if client is not None:
            client.close()
        self.limiter.forget(portal_id)
        log.debug("portal %s: session, robots rules and rate state dropped", portal_id)

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
        # Merged, not replaced: a query already in the address (a filter) stays beside `params`.
        current = httpx.URL(url).copy_merge_params(params) if params else httpx.URL(url)
        headers = dict(headers) if headers else None
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
            log.debug("portal %s: -> %s %s%s", portal_id, method, logs.safe_url(str(current)),
                      f" hop {len(hops)}" if hops else "")
            started = self._clock()
            try:
                response = client.send(request, stream=True)
            except httpx.HTTPError as exc:
                log.debug("portal %s: <- %s %s failed after %.2fs: %s: %s", portal_id, method,
                          logs.safe_url(str(current)), self._clock() - started, type(exc).__name__, logs.clip(exc))
                return None, exc, str(current), tuple(hops)
            except httpx.InvalidURL:
                # httpx reads the Location of every redirect, even one it does not follow, and
                # refuses one that is no address (mailto:, javascript:). The redirect is the answer.
                refused = request.extensions.get(_ANSWER)
                if refused is None:
                    raise
                plain = [(k, v) for k, v in refused.headers.multi_items()
                         if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
                response = httpx.Response(refused.status_code, headers=plain, request=request)  # httpx closed it unread
                return response, None, str(current), tuple(hops)
            location = response.headers.get("location")
            log.debug("portal %s: <- %s %s %s in %.2fs, type=%s length=%s%s", portal_id, response.status_code, method,
                      logs.safe_url(str(current)), self._clock() - started, response.headers.get("content-type"),
                      response.headers.get("content-length", "?"),
                      f", location={logs.safe_url(location)}" if location else "")
            target = None
            if response.status_code in REDIRECTS and location and len(hops) < self.settings.max_redirects:
                target = self._redirect_target(current, location)
            if target is None:  # the answer itself, or a redirect we do not follow: the walk ends here
                return response, None, str(current), tuple(hops)
            response.close()
            hops.append(str(current))
            if headers and _origin(target) != _origin(current):  # credentials stay with the host they were for
                headers = {k: v for k, v in headers.items() if k.lower() not in CREDENTIAL_HEADERS}
            current = target
            if response.status_code == 303 or (response.status_code in (301, 302)
                                               and method not in ("GET", "HEAD")):
                method, body = "GET", {}
                if headers:  # no body goes with a GET, so nothing names its type
                    headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}

    @staticmethod
    def _redirect_target(current: httpx.URL, location: str) -> httpx.URL | None:
        """Where a Location header leads, or None when it is not an http(s) address (mailto:, javascript:)."""
        try:
            target = current.join(location)
        except httpx.InvalidURL:
            return None
        return target if target.scheme in ("http", "https") and target.host else None

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
            if response is not None:
                keep_open = stream and 200 <= response.status_code < 300
                if not keep_open:  # a page, or an error page in place of a file: read it to look at it
                    try:
                        body = response.read()
                    except httpx.HTTPError as exc:  # it broke off after its headers: no answer, as rule T1 counts it
                        body, error = b"", exc
                    finally:
                        response.close()
            if response is None or error is not None:
                answer, resp_headers = answer_from_error(error, page_load=page_load), httpx.Headers()
            else:
                resp_headers = response.headers
                answer = answer_from_response(response.status_code, resp_headers, body[: self.settings.sniff_bytes],
                                              final_url=final_url, redirects=hops, page_load=page_load)
            kind = classify_answer(answer)
            wait = parse_retry_after(resp_headers.get("retry-after"), datetime.now(timezone.utc))
            retry_after = wait.total_seconds() if wait is not None else None
            too_long = retry_after is not None and retry_after > self.checks.retry_after_inline_max_seconds
            open_response = response if keep_open else None  # a 2xx download, its body not read yet

            log.debug("portal %s: %s %s answered %s: kind=%s tries=%d%s", portal_id, method, logs.safe_url(final_url),
                      answer.status, kind.value, tries + 1, f" retry_after={retry_after}s" if retry_after else "")
            if kind is Transport.rate_limited:  # T2: halve the portal's rate, then go on
                at_slowest = self.limiter.slow_down(portal_id)
                log.info("portal %s: rate limited (HTTP %s), rate halved%s", portal_id, answer.status,
                         ", already at the slowest" if at_slowest else "")
                if at_slowest or too_long:
                    return _Last(answer, final_url, hops, resp_headers, body, max(tries, 1), at_slowest,
                                 retry_after if too_long else None, open_response)
                self._close(open_response)
                self.limiter.hold(portal_id, retry_after or 0.0)
                continue  # waiting out a rate limit is not a T1 try
            tries += 1
            if kind is Transport.outage and tries < self.checks.request_tries and not too_long:  # T1
                self._close(open_response)
                pause = max(self._pause(tries), retry_after or 0.0)
                log.info("portal %s: %s %s did not answer (try %d of %d), pausing %.1fs", portal_id, method,
                         logs.safe_url(final_url), tries, self.checks.request_tries, pause)
                self.limiter.hold(portal_id, pause)
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
        log.debug("portal %s: fetching robots.txt of %s", portal_id, origin)
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
        log.debug("portal %s: robots.txt of %s read (status %s), cached", portal_id, origin, status)
        return rules

    def _robots_gate(self, portal_id: str, url: str) -> None:
        if self.settings.ignore_robots_txt:
            return
        if not self._rules(portal_id, url).allowed(url, self.settings.user_agent):
            log.info("portal %s: robots.txt forbids %s", portal_id, logs.safe_url(url))
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
        log.debug("portal %s: download %s -> status %s", portal_id, logs.safe_url(url), last.answer.status)
        if last.answer.status is None:
            raise FetchFailed(url, last.answer, last.tries, last.at_slowest)
        if last.response is not None:
            try:
                yield _Streamed(last.response, last.final_url, last.tries)
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
