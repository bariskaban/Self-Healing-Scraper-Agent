"""Helpers for app/fetch tests: a fake clock, and a Fetcher on an in-process transport.

Nothing here opens a connection to anything but this process (CLAUDE.md, "no live portals").
"""
from __future__ import annotations

from collections.abc import Callable

import httpx

from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter

BASE = "https://portal.example"


class Clock:
    """Monotonic time that moves only when something sleeps."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Server:
    """A MockTransport handler that records when each request arrived, by the fake clock."""

    def __init__(self, clock: Clock, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.clock = clock
        self.handler = handler
        self.seen: list[tuple[float, str, str]] = []  # (time, method, url)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append((self.clock.now, request.method, str(request.url)))
        self.requests.append(request)
        return self.handler(request)

    def times(self, path: str | None = None) -> list[float]:
        return [t for t, _, url in self.seen if path is None or httpx.URL(url).path == path]

    def paths(self) -> list[str]:
        return [httpx.URL(url).path for _, _, url in self.seen]


def make_fetcher(handler: Callable[[httpx.Request], httpx.Response], *, robots: bool = False,
                 rng: float = 0.0, **settings) -> tuple[Fetcher, Server, Clock]:
    """A Fetcher in live mode on an in-process transport, its limiter on a fake clock."""
    clock = Clock()
    server = Server(clock, handler)
    limiter = PortalLimiter(1.0, 10.0, clock=clock, sleep=clock.sleep)
    settings.setdefault("ignore_robots_txt", not robots)
    fetch_settings = FetchSettings(mode=FetchMode.live, **settings)
    fetcher = Fetcher(fetch_settings, transport=httpx.MockTransport(server), limiter=limiter, clock=clock,
                      rng=lambda: rng)
    return fetcher, server, clock


def html(body: str, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8", **(headers or {})},
                          text=f"<!doctype html><html><body>{body}</body></html>")
