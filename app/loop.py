"""The read loop: `Worker` of `app/interfaces.py` on asyncio, one task per portal.

It holds no rule of its own. `app/reader.py` does one read; the scheduler's functions say
when the next one is due (`read_plan` and `next_read` while serving, `next_outage_retry`
during an outage, `next_failed_check` and `may_check_on_refresh` for a failed portal).

The API calls `attach`, `refresh` and `forget` on the event loop, and each returns at once: a
read runs in a worker thread, because the network layer, the documents module and the
database all block. One run per portal at a time: a refresh during a read answers with the
run that is going on. After a restart, `start` closes the runs the old process left open and
queues every portal again.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from app.checks.result import Cause
from app.db import Database, UnknownPortal
from app.fetch.interface import Fetch
from app.models import Portal, PortalState, Run, RunResult, RunTrigger, utcnow
from app.reader import Incident, ReadOutcome, Reader, new_run
from app.scheduler import (
    DEFAULT_SETTINGS, SchedulerSettings, may_check_on_refresh, next_failed_check, next_outage_retry, next_read,
    read_plan,
)

log = logging.getLogger("watchtower.loop")


def _own_trigger(portal: Portal) -> RunTrigger:
    """The trigger of a read the loop starts by itself, with no call to the API behind it.

    A portal that was never read through is still being attached: its first read was cut short
    by a restart, or did not pass, and the read that tries again is the attach, not a periodic read.
    """
    if portal.state is PortalState.failed:
        return RunTrigger.recheck
    if portal.state is PortalState.integrating and portal.recipe_version is None:
        return RunTrigger.attach
    return RunTrigger.schedule


class ReadLoop:
    """Reads every portal on its schedule. Start it inside a running event loop."""

    def __init__(self, database: Database, reader: Reader, fetch: Fetch, *,
                 schedule: SchedulerSettings = DEFAULT_SETTINGS, now: Callable[[], datetime] = utcnow,
                 rng: Callable[[], float] = random.random) -> None:
        self.db, self.reader, self.fetch = database, reader, fetch
        self.schedule, self.now, self.rng = schedule, now, rng
        self._tasks: dict[str, asyncio.Task] = {}
        self._wake: dict[str, asyncio.Event] = {}
        self._queued: dict[str, Run] = {}       # a run a refresh started, for the task to pick up
        self._incidents: dict[str, Incident] = {}
        self._due: dict[str, datetime] = {}
        self._first_page: dict[str, bool] = {}
        self._last_run: dict[str, str] = {}
        self._cancel: dict[str, threading.Event] = {}

    # == Worker ==

    def attach(self, portal: Portal) -> None:
        """Start the first read of a newly added portal."""
        run = self.db.start_run(new_run(portal, RunTrigger.attach))
        self._queued[portal.id] = run
        self._last_run[portal.id] = run.id
        self._spawn(portal.id)

    def refresh(self, portal: Portal) -> str:
        """Start a read now and return its run id; the run going on, when there is one."""
        active = self.db.active_run(portal.id)
        if active is not None:
            return active.id
        incident = self._incidents.setdefault(portal.id, Incident())
        last = self._last_run.get(portal.id)
        if portal.state is PortalState.failed and last is not None and not may_check_on_refresh(
                incident.last_check_at, self.now(), self.schedule):
            return last  # a failed portal is checked at most once a minute (Q14)
        mine = new_run(portal, RunTrigger.refresh)
        run = self.db.start_run(mine)
        if run.id != mine.id:
            # A read began between the look above and this start (the portal's task starts its
            # runs in a worker thread). That read is the run going on, and its task reads it:
            # queueing it here too would have it read a second time, after it has ended.
            return run.id
        self._queued[portal.id] = run
        self._last_run[portal.id] = run.id
        self._spawn(portal.id)
        self._wake[portal.id].set()
        return run.id

    def forget(self, portal_id: str) -> None:
        """Cancel everything running for a deleted portal. No request goes to it after this."""
        task = self._tasks.pop(portal_id, None)
        if task is not None:
            task.cancel()
        cancel = self._cancel.pop(portal_id, None)
        if cancel is not None:
            cancel.set()  # the read runs in a thread: it stops before its next request
        for table in (self._wake, self._queued, self._incidents, self._due, self._first_page, self._last_run):
            table.pop(portal_id, None)
        self.fetch.forget(portal_id)

    # == What the dashboard reads and sets (docs/DASHBOARD_API.md) ==

    def next_reads(self) -> dict[str, datetime]:
        """When each portal is read next, as planned after its last read. Kept in memory only."""
        return dict(self._due)

    @property
    def attach_time_limit_seconds(self) -> float:
        """The attach time limit the next attach is judged by."""
        return self.reader.schedule.attach_time_limit_seconds

    @property
    def ignore_robots_txt(self) -> bool:
        """True when requests are sent without asking robots.txt (the mentor's switch for tests)."""
        return bool(getattr(getattr(self.fetch, "settings", None), "ignore_robots_txt", False))

    def apply_settings(self, *, attach_time_limit_seconds: float, ignore_robots_txt: bool) -> None:
        """Change the two settings of the dashboard, from the next decision and the next request on.

        Nothing is written down: after a restart both are what the environment says again. The
        robots.txt switch needs a network layer that carries `settings` (`Fetcher` does); on any
        other it stays as it is, and `ignore_robots_txt` goes on saying so.
        """
        self.schedule = replace(self.schedule, attach_time_limit_seconds=attach_time_limit_seconds)
        self.reader.schedule = replace(self.reader.schedule, attach_time_limit_seconds=attach_time_limit_seconds)
        settings = getattr(self.fetch, "settings", None)
        if hasattr(settings, "ignore_robots_txt"):
            self.fetch.settings = replace(settings, ignore_robots_txt=ignore_robots_txt)  # type: ignore[attr-defined]
        self.reader.ignore_robots = self.ignore_robots_txt  # the robots check reports what the gate does

    # == Life cycle ==

    async def start(self) -> None:
        """After a start: close the runs a stopped process left open, and queue every portal."""
        cut = await asyncio.to_thread(self.db.fail_open_runs)
        portals = await asyncio.to_thread(self.db.list_portals)
        if cut:
            log.info("closed %d run(s) left open by a restart", len(cut))
        for portal in portals:
            self._spawn(portal.id)
            self._wake[portal.id].set()  # read at once: we do not know how long we were away

    async def stop(self) -> None:
        tasks, self._tasks = list(self._tasks.values()), {}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _spawn(self, portal_id: str) -> None:
        self._wake.setdefault(portal_id, asyncio.Event())
        self._incidents.setdefault(portal_id, Incident())
        self._cancel.setdefault(portal_id, threading.Event())
        task = self._tasks.get(portal_id)
        if task is None or task.done():
            self._tasks[portal_id] = asyncio.get_running_loop().create_task(self._portal(portal_id))

    # == One portal ==

    async def _portal(self, portal_id: str) -> None:
        wake = self._wake[portal_id]
        incident = self._incidents[portal_id]
        while True:
            run = self._queued.pop(portal_id, None)
            if run is None:
                due = self._due.get(portal_id)
                wait = None if due is None else max(0.0, (due - self.now()).total_seconds())
                woken = wake.is_set()
                if not woken and wait != 0.0:
                    try:
                        await asyncio.wait_for(wake.wait(), timeout=wait)
                        woken = True
                    except asyncio.TimeoutError:
                        woken = False
                wake.clear()
                run = self._queued.pop(portal_id, None)
            first_page_only = False
            if run is None:
                portal = await asyncio.to_thread(self.db.get_portal, portal_id)
                if portal is None:
                    return
                try:
                    run = await asyncio.to_thread(self.db.start_run, new_run(portal, _own_trigger(portal)))
                except UnknownPortal:
                    return
                # A refresh may have started its run while this one was on its way to the
                # database: then `start_run` answered with the refresh's run, and that is the
                # one read now. It leaves the queue here, so that it is read once only.
                queued = self._queued.get(portal_id)
                if queued is not None and queued.id == run.id:
                    del self._queued[portal_id]
                # Only a read the schedule asked for may stop at the first page.
                first_page_only = (run.trigger is RunTrigger.schedule and portal.state is PortalState.serving
                                   and self._first_page.get(portal_id, False))
                self._last_run[portal_id] = run.id
            wake.clear()
            try:
                outcome = await asyncio.to_thread(self.reader.read, portal_id, run, incident,
                                                  first_page_only=first_page_only,
                                                  cancel=self._cancel.get(portal_id))
            except asyncio.CancelledError:
                raise
            except Exception as error:  # a bug of ours must not stop the portal's schedule
                log.exception("read of portal %s failed", portal_id)
                outcome = await asyncio.to_thread(self._crashed, portal_id, run, error)
            if outcome.gone:
                return
            self._plan_next(portal_id, incident, outcome, scheduled=run.trigger in (
                RunTrigger.schedule, RunTrigger.recheck))

    def _crashed(self, portal_id: str, run: Run, error: Exception) -> ReadOutcome:
        portal = self.db.get_portal(portal_id)
        if portal is None:
            return ReadOutcome(None, PortalState.failed, False, gone=True)
        # The row as the read last saved it, not the copy this task started with: the read saves its calls,
        # tokens and cost as it goes, and the copy would write them back as zero.
        saved = self.db.get_run(run.id) or run
        self.db.save_run(saved.model_copy(update={"finished_at": self.now(), "result": RunResult.failed,
                                                  "state_after": portal.state, "reason_after": portal.reason,
                                                  "error": f"{type(error).__name__}: {error}"[:300]}))
        return ReadOutcome(None, portal.state, False)

    def _plan_next(self, portal_id: str, incident: Incident, outcome: ReadOutcome, *, scheduled: bool) -> None:
        """When this portal is read next, by the scheduler's rules."""
        now = self.now()
        incident.last_check_at = now
        cause = outcome.decision.cause if outcome.decision is not None else None
        first_page = False
        if outcome.state is PortalState.serving:
            plan = read_plan(incident.list_seconds, incident.list_pages, incident.newest_first, self.schedule)
            nxt = next_read(plan, incident.last_full_started_at or now, now if self._first_page.get(portal_id) else None)
            due, first_page = nxt.at, nxt.first_page_only
        elif cause is Cause.outage and (due := next_outage_retry(now, incident.outage_retries, self.schedule)) is not None:
            # An outage is `failed`, but it is tried again on the outage ladder (1, 2, 4, 8, 15, 30 minutes),
            # not on the failed schedule, which is for portals a person has to look at.
            incident.outage_retries += 1
        elif outcome.state is PortalState.failed:
            if incident.failed_at is None or (cause is Cause.outage and incident.failed_checks == 0):
                incident.failed_at = now  # for an outage: the ladder is used up, the failed schedule starts here
            due = next_failed_check(incident.failed_at, incident.failed_checks, self.schedule,
                                    blocked=cause is Cause.block, rng=self.rng, last_check_at=now)
            if scheduled:
                incident.failed_checks += 1
        else:  # healing after a breakage, or an attach that is not through: try again after the read interval
            plan = read_plan(incident.list_seconds, incident.list_pages, incident.newest_first, self.schedule)
            due = now + plan.interval
        incident.next_try_at = due if outcome.state is not PortalState.serving else None
        self._due[portal_id] = due
        self._first_page[portal_id] = first_page
