"""One request start per interval, per portal (the brief; Q4 and its audit; Q10, rule T2).

Per portal, not per host: a portal's files often sit on a second host, and the brief says
"per portal". The mentor: the limit counts request starts, so a long download may still be
running when the next request starts.

Every request that reaches a portal takes a slot first: each redirect hop, robots.txt, and
every retry. `reserve` books the next free slot under a lock and says how long to wait for
it, so the limiter serves threads (`acquire`) and the event loop (`acquire_async`) alike.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable


class PortalLimiter:
    """Books request slots per portal. Thread-safe."""

    def __init__(self, requests_per_second: float = 1.0, slowest_interval_seconds: float = 10.0, *,
                 enabled: bool = True, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not requests_per_second > 0 or not slowest_interval_seconds > 0:
            raise ValueError("rates must be positive")
        self.base_interval = 1.0 / requests_per_second
        self.slowest_interval = max(slowest_interval_seconds, self.base_interval)
        self.enabled = enabled  # off in replay mode: no portal is reached, so there is nothing to protect
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_free: dict[str, float] = {}
        self._interval: dict[str, float] = {}

    def interval(self, portal_id: str) -> float:
        """Seconds between two request starts for this portal right now."""
        with self._lock:
            return self._interval.get(portal_id, self.base_interval)

    def reserve(self, portal_id: str) -> float:
        """Book the next free slot; return how many seconds to wait before starting the request."""
        if not self.enabled:
            return 0.0
        with self._lock:
            now = self._clock()
            start = max(now, self._next_free.get(portal_id, now))
            self._next_free[portal_id] = start + self._interval.get(portal_id, self.base_interval)
            return start - now

    def acquire(self, portal_id: str) -> None:
        """Wait, blocking this thread, until the portal may receive the next request."""
        wait = self.reserve(portal_id)
        if wait > 0:
            self._sleep(wait)

    async def acquire_async(self, portal_id: str) -> None:
        """Wait, on the event loop, until the portal may receive the next request."""
        wait = self.reserve(portal_id)
        if wait > 0:
            await asyncio.sleep(wait)

    def slow_down(self, portal_id: str) -> bool:
        """Rule T2: halve this portal's rate, down to the slowest. The slower rate is kept.

        Returns True when the portal was already at the slowest rate: then the rate limit
        persists at the slowest pace, which the checks count as an outage.
        """
        with self._lock:
            current = self._interval.get(portal_id, self.base_interval)
            if current >= self.slowest_interval:
                return True
            self._interval[portal_id] = min(current * 2, self.slowest_interval)
            return False

    def at_slowest(self, portal_id: str) -> bool:
        with self._lock:
            return self._interval.get(portal_id, self.base_interval) >= self.slowest_interval

    def limit(self, portal_id: str, requests_per_second: float) -> None:
        """A portal that states a lower limit keeps to it (Poland's portal: 30 requests a minute)."""
        if not requests_per_second > 0:
            raise ValueError("requests_per_second must be positive")
        with self._lock:
            current = self._interval.get(portal_id, self.base_interval)
            self._interval[portal_id] = max(current, 1.0 / requests_per_second)

    def hold(self, portal_id: str, seconds: float) -> None:
        """No request to this portal for `seconds` from now (a Retry-After)."""
        if seconds <= 0:
            return
        with self._lock:
            until = self._clock() + seconds
            self._next_free[portal_id] = max(self._next_free.get(portal_id, until), until)

    def forget(self, portal_id: str) -> None:
        """Drop what is known of a deleted portal."""
        with self._lock:
            self._next_free.pop(portal_id, None)
            self._interval.pop(portal_id, None)
