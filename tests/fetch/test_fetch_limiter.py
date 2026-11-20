"""The rate limiter: one request start per interval per portal (Q4; Q10, rule T2)."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.fetch import PortalLimiter
from tests.fetch.conftest import Clock


def limiter(clock: Clock, rps: float = 1.0) -> PortalLimiter:
    return PortalLimiter(rps, 10.0, clock=clock, sleep=clock.sleep)


def test_one_request_start_per_second_per_portal():
    clock = Clock()
    lim = limiter(clock)
    starts = []
    for _ in range(4):
        lim.acquire("de")
        starts.append(clock.now)
    assert starts == [0.0, 1.0, 2.0, 3.0]
    lim.acquire("nl")  # another portal keeps its own pace
    assert clock.now == 3.0


def test_rate_limit_halves_down_to_the_slowest_and_then_says_so():
    lim = limiter(Clock())
    seen = []
    for _ in range(6):
        seen.append((lim.slow_down("pl"), lim.interval("pl")))
    assert seen == [(False, 2.0), (False, 4.0), (False, 8.0), (False, 10.0), (True, 10.0), (True, 10.0)]
    assert lim.at_slowest("pl") and lim.interval("de") == 1.0


def test_a_retry_after_holds_the_portal():
    clock = Clock()
    lim = limiter(clock)
    lim.acquire("de")
    lim.hold("de", 30)
    lim.acquire("de")
    assert clock.now == 30.0


def test_a_portal_that_states_a_lower_limit_keeps_to_it():
    clock = Clock()
    lim = limiter(clock)
    lim.limit("pl", 0.5)  # 30 requests a minute, as Poland's notice API states
    lim.acquire("pl")
    lim.acquire("pl")
    assert clock.now == 2.0
    lim.slow_down("de")
    lim.limit("de", 5)  # a stated limit never speeds a portal up
    assert lim.interval("de") == 2.0
    with pytest.raises(ValueError):
        lim.limit("de", 0)


def test_replay_needs_no_pace():
    clock = Clock()
    lim = PortalLimiter(1.0, 10.0, enabled=False, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        lim.acquire("de")
    assert clock.now == 0.0 and clock.sleeps == []


def test_threads_get_one_slot_each():
    clock = Clock()  # frozen: every wait is how far ahead the slot is
    lim = limiter(clock)
    waits: list[float] = []
    barrier = threading.Barrier(20)

    def take() -> None:
        barrier.wait()
        waits.append(lim.reserve("de"))

    threads = [threading.Thread(target=take) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(waits) == [float(i) for i in range(20)]


def test_the_event_loop_waits_too():
    lim = PortalLimiter(50.0, 10.0)  # real clock, 20 ms apart

    async def three() -> list[float]:
        out = []
        for _ in range(3):
            await lim.acquire_async("de")
            out.append(time.monotonic())
        return out

    starts = asyncio.run(three())
    assert all(b - a >= 0.019 for a, b in zip(starts, starts[1:]))


def test_forget_resets_a_portal():
    lim = limiter(Clock())
    lim.slow_down("de")
    lim.forget("de")
    assert lim.interval("de") == 1.0
