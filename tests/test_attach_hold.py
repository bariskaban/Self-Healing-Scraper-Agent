"""What an attach shows at each moment: its tenders are delivered only when the portal leaves `integrating`.

The reader is called directly on the mock portal (no loop, no threads). Every request for a
document goes through a hook, which notes what the store and the timeline say at that moment.
Run: pytest tests/test_attach_hold.py
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.dashboard_api import DashboardSettings, dashboard_answer, timeline_answer
from app.db import Database
from app.docs import DocsSettings, FileStore
from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter
from app.main import builtin_learner
from app.models import Portal, PortalState, RunTrigger, url_key
from app.reader import HOLD_STEP, PUBLISH_STEP, Incident, Reader, new_run
from app.scheduler import SchedulerSettings
from mock_portal import MockPortal

URL = "https://mock.example"
PID = "p1"
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
SETTINGS = DashboardSettings()


class Attach:
    """One attach of the mock portal, with a note taken at every document request."""

    def __init__(self, tmp_path, schedule: SchedulerSettings, seconds_per_document: float = 0.0) -> None:
        self.mock = MockPortal()
        self.clock = [T0]
        self.moments: list[dict] = []
        self.db = Database(tmp_path / "watchtower.db")
        self.portal, _ = self.db.add_portal(Portal(id=PID, url=URL, url_key=url_key(URL)))
        self.seconds_per_document = seconds_per_document
        ticks = [0.0]
        limiter = PortalLimiter(1.0, 10.0, clock=lambda: ticks[0], sleep=lambda s: ticks.__setitem__(0, ticks[0] + s))
        fetcher = Fetcher(FetchSettings(mode=FetchMode.live), transport=httpx.MockTransport(self.handle),
                          limiter=limiter, clock=lambda: ticks[0], rng=lambda: 0.0)
        store = FileStore(DocsSettings(data_dir=tmp_path))
        self.reader = Reader(self.db, fetcher, lambda: store, learn=builtin_learner, schedule=schedule,
                             now=lambda: self.clock[0])

    def handle(self, request: httpx.Request) -> httpx.Response:
        if "/files/" in request.url.path:
            self.moments.append(self.look())
            self.clock[0] += timedelta(seconds=self.seconds_per_document)
        return self.mock.handle(request)

    def look(self) -> dict:
        """What a caller of the API and the dashboard would see right now."""
        portal = self.db.get_portal(PID)
        (run,) = timeline_answer(self.db, PID, SETTINGS)
        (row,) = dashboard_answer(self.db, SETTINGS, live={})["portals"]
        return {"state": portal.state, "reason": portal.reason, "count": self.db.count_tenders(PID),
                "listed": len(self.db.list_tenders(PID)), "steps": [step["name"] for step in run["steps"]],
                "summaries": [step["summary"] for step in run["steps"]],
                "publishedCount": run.get("publishedCount"), "trend": row["deliveryTrend"],
                "rowCount": row["tenderCount"]}

    def run(self) -> list[dict]:
        run = self.db.start_run(new_run(self.portal, RunTrigger.attach))
        outcome = self.reader.read(PID, run, Incident())
        assert outcome.passed and outcome.state is PortalState.serving
        return self.moments


@pytest.fixture
def attach(tmp_path):
    made: list[Attach] = []

    def make(schedule: SchedulerSettings = SchedulerSettings(), seconds_per_document: float = 0.0) -> Attach:
        made.append(Attach(tmp_path, schedule, seconds_per_document))
        return made[-1]

    yield make
    for one in made:
        one.db.close()


def test_documents_within_the_ten_minute_rule_keep_the_tenders_back_until_they_are_in(attach):
    site = attach()
    moments = site.run()
    assert len(moments) > 45  # the mock portal has more than one file for a tender

    # While the documents are fetched: integrating, nothing delivered, and nothing says "published".
    for moment in moments:
        assert moment["state"] is PortalState.integrating
        assert (moment["count"], moment["listed"], moment["rowCount"]) == (0, 0, 0)
        assert HOLD_STEP in moment["steps"] and PUBLISH_STEP not in moment["steps"]
        assert moment["publishedCount"] is None and moment["trend"] == []
        assert not any("Published" in summary for summary in moment["summaries"])
        assert re.fullmatch(r"All 45 tenders read\. Fetching documents: \d+ of 45\.", moment["reason"])
    held = moments[0]["summaries"][moments[0]["steps"].index(HOLD_STEP)]
    assert "Read and checked 45 tender(s)" in held and "held back" in held and "integrating" in held

    # The reason is the scheduler's at each moment: it counts the tenders whose documents are in.
    done = [int(re.search(r"documents: (\d+) of", moment["reason"]).group(1)) for moment in moments]
    assert done[0] == 0 and done == sorted(done) and done[-1] == 44

    # At the end: serving, all 45 delivered, and the publication is recorded after the documents.
    end = site.look()
    assert (end["state"], end["count"], end["listed"], end["rowCount"]) == (PortalState.serving, 45, 45, 45)
    assert end["steps"][-3:] == [HOLD_STEP, "documents", PUBLISH_STEP]
    assert (end["publishedCount"], end["trend"]) == (45, [45])
    assert end["summaries"][-1].startswith("Published 45 tender(s)") and "documents are in" in end["summaries"][-1]


def test_documents_that_do_not_fit_are_fetched_while_serving_and_the_tenders_are_published_first(attach):
    site = attach(SchedulerSettings(documents_before_serving_seconds=10.0))
    moments = site.run()
    for moment in moments:
        assert (moment["state"], moment["count"], moment["listed"]) == (PortalState.serving, 45, 45)
        assert PUBLISH_STEP in moment["steps"] and HOLD_STEP not in moment["steps"]
        assert (moment["publishedCount"], moment["trend"]) == (45, [45])
        assert re.match(r"All 45 open tenders are delivered\. Documents are in for \d+ of them", moment["reason"])
    done = [int(re.search(r"in for (\d+) of them", moment["reason"]).group(1)) for moment in moments]
    assert done[0] == 0 and done[-1] == 44
    end = site.look()
    assert end["steps"][-2:] == [PUBLISH_STEP, "documents"] and end["state"] is PortalState.serving
    assert end["steps"].count(PUBLISH_STEP) == 1


def test_the_time_limit_passing_during_the_documents_delivers_the_tenders_at_that_moment(attach):
    # Each document takes 30 seconds on this clock, and the attach may take 5 minutes.
    site = attach(SchedulerSettings(attach_time_limit_seconds=300.0, documents_before_serving_seconds=1e9),
                  seconds_per_document=30.0)
    moments = site.run()
    states = [moment["state"] for moment in moments]
    turn = states.index(PortalState.serving)
    assert 0 < turn < len(moments) - 1
    assert set(states[:turn]) == {PortalState.integrating} and set(states[turn:]) == {PortalState.serving}
    for moment in moments[:turn]:
        assert (moment["count"], moment["publishedCount"], moment["trend"]) == (0, None, [])
        assert PUBLISH_STEP not in moment["steps"]
    for moment in moments[turn:]:
        assert (moment["count"], moment["listed"], moment["publishedCount"], moment["trend"]) == (45, 45, 45, [45])
        assert moment["steps"][-2:] == [HOLD_STEP, PUBLISH_STEP]
        assert "time limit passed" in moment["summaries"][-1]
        assert moment["reason"].startswith("All 45 open tenders are delivered.")
    end = site.look()
    assert end["steps"].count(PUBLISH_STEP) == 1 and end["steps"][-1] == "documents"
