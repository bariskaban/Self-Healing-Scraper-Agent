"""What the reader writes down with a recipe it stores: the software it is for, and the version it replaces.

The reader is called directly on the mock portal, with learners and a repairer written here.
No model is called. Run: pytest tests/test_reader_recipes.py
"""
from __future__ import annotations

import httpx
import pytest

import mock_portal
from app.dashboard_api import DashboardSettings, timeline_answer
from app.db import Database
from app.docs import DocsSettings, FileStore
from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter
from app.models import Portal, PortalState, Recipe, RecipeStatus, RunTrigger, url_key
from app.reader import Incident, Learned, Reader, new_run
from app.recipe.schema import RecipeBody
from mock_portal import MockPortal

URL = "https://mock.example"
PID = "p1"


def recipe(family: str | None = None):
    return mock_portal.recipe().model_copy(update={"family": family})


@pytest.fixture
def site(tmp_path):
    mock = MockPortal()
    ticks = [0.0]
    limiter = PortalLimiter(1.0, 10.0, clock=lambda: ticks[0], sleep=lambda s: ticks.__setitem__(0, ticks[0] + s))
    fetcher = Fetcher(FetchSettings(mode=FetchMode.live), transport=httpx.MockTransport(mock.handle),
                      limiter=limiter, clock=lambda: ticks[0], rng=lambda: 0.0)
    db = Database(tmp_path / "watchtower.db")
    db.add_portal(Portal(id=PID, url=URL, url_key=url_key(URL)))
    store = FileStore(DocsSettings(data_dir=tmp_path))

    def read(trigger: RunTrigger, incident: Incident, **functions):
        reader = Reader(db, fetcher, lambda: store, **functions)
        run = db.start_run(new_run(db.get_portal(PID), trigger))
        return reader.read(PID, run, incident), run

    read.mock = mock
    yield db, read
    db.close()


@pytest.mark.parametrize("family, detected, software", [
    ("cosinex-vmp", None, "cosinex-vmp"),       # the recipe names the software
    ("cosinex-vmp", "cosinex", "cosinex-vmp"),  # both do: the recipe's word is the one stored everywhere
    (None, "cosinex", "cosinex"),               # only the learner detected it
    (None, None, None),
])
def test_a_stored_recipe_and_its_portal_name_the_same_software(site, family, detected, software):
    db, read = site
    learned = Learned(recipe=recipe(family), timezone=mock_portal.TIMEZONE, fingerprint=detected)
    outcome, _ = read(RunTrigger.attach, Incident(), learn=lambda portal, run_id: learned)
    assert outcome.passed
    stored = db.active_recipe(PID)
    assert (stored.fingerprint, db.get_portal(PID).fingerprint) == (software, software)
    assert stored.body["family"] == family and stored.parent_version is None
    if family is not None:
        assert stored.fingerprint == stored.body["family"]
    # A recipe is found again by the software it names (Q11).
    found = db.recipes_for_fingerprint(software, exclude_portal_id="another") if software else []
    assert [(r.portal_id, r.version) for r in found] == ([(PID, 1)] if software else [])


def test_a_recipe_stored_after_a_repair_names_the_version_it_replaces_and_the_software(site):
    db, read = site
    first = Learned(recipe=recipe(), timezone=mock_portal.TIMEZONE)
    incident = Incident()
    outcome, _ = read(RunTrigger.attach, incident, learn=lambda portal, run_id: first)
    assert outcome.passed and db.get_portal(PID).fingerprint is None

    # The active recipe stops reading the list (as after a change of the portal's layout).
    broken = RecipeBody.model_validate(db.active_recipe(PID).body)
    broken.nodes[0].items.expr = "table#nothing tr"
    db.add_recipe(Recipe(portal_id=PID, version=2, parent_version=1, body=broken.model_dump(mode="json")))
    db.activate_recipe(PID, 2)

    repaired = Learned(recipe=recipe("mock-software"), model_calls=3)
    asked: list[int] = []

    def repair(portal, body, failed, run_id):
        asked.append(portal.recipe_version)
        return repaired

    outcome, run = read(RunTrigger.refresh, incident, learn=lambda portal, run_id: first, repair=repair)
    assert asked == [2] and outcome.passed and outcome.state is PortalState.serving

    stored = db.active_recipe(PID)
    assert (stored.version, stored.parent_version, stored.created_by_run_id) == (3, 2, run.id)
    assert db.get_recipe(PID, 2).status is RecipeStatus.retired
    portal = db.get_portal(PID)
    assert (portal.recipe_version, portal.fingerprint, stored.fingerprint) == (3, "mock-software", "mock-software")
    assert stored.body["family"] == "mock-software"

    # The dashboard shows the change, which it can only do when the record names its parent.
    shown = timeline_answer(db, PID, DashboardSettings())[-1]
    assert shown["id"] == run.id and shown["modelCalls"] == 3
    assert (shown["recipeChange"]["from"], shown["recipeChange"]["to"]) == (2, 3)
    assert "nodes.list" in shown["recipeChange"]["changedParts"]
    # GET /portals/{id}/runs answers that run, and only that one, as a repair (the contract: every read and every repair).
    assert db.repair_run_ids(PID) == {run.id}
    # A repair that found nothing leaves its steps: that run is a repair too.
    from app.models import AgentStep, StepKind
    _, later = read(RunTrigger.refresh, incident, learn=lambda portal, run_id: first)
    assert db.repair_run_ids(PID) == {run.id}
    db.add_step(AgentStep(run_id=later.id, seq=99, kind=StepKind.decision, name="repair_failed", summary="No recipe."))
    assert db.repair_run_ids(PID) == {run.id, later.id} and db.repair_run_ids("another") == set()


def test_a_limit_per_portal_keeps_the_first_tenders_and_closes_none_on_a_later_read(site):
    from app.recipe.settings import RecipeSettings
    db, read = site
    learned = Learned(recipe=recipe(), timezone=mock_portal.TIMEZONE)
    limit = RecipeSettings(max_tenders_per_portal=10)
    outcome, run = read(RunTrigger.attach, Incident(), learn=lambda portal, run_id: learned, recipes=limit)
    assert outcome.passed
    assert db.count_tenders(PID) == 10                       # the mock portal lists more than that
    # A later full read with the same limit sees the same ten and closes nothing.
    again, _ = read(RunTrigger.schedule, Incident(), recipes=limit)
    assert again.passed and db.count_tenders(PID) == 10


def test_a_recipe_whose_first_read_met_an_outage_is_kept_and_not_learned_again(site):
    db, read = site
    asked = []

    def learner(portal, run_id):
        asked.append(run_id)
        return Learned(recipe=recipe(), timezone=mock_portal.TIMEZONE, model_calls=4)

    incident = Incident()
    read.mock.outage = True
    outcome, _ = read(RunTrigger.attach, incident, learn=learner)
    assert not outcome.passed and db.active_recipe(PID) is None and incident.learned_unread is not None
    outcome, run = read(RunTrigger.recheck, incident, learn=learner)       # still out: still kept, still not asked
    assert not outcome.passed and len(asked) == 1 and db.get_run(run.id).model_calls == 0

    read.mock.outage = False
    outcome, run = read(RunTrigger.recheck, incident, learn=learner)
    assert outcome.passed and len(asked) == 1                              # the learner was asked once in all
    assert db.active_recipe(PID).version == 1 and incident.learned_unread is None
    assert db.get_run(run.id).model_calls == 0 and db.get_portal(PID).state is PortalState.serving


def test_a_read_that_passes_long_after_the_last_one_stays_serving(site, monkeypatch):
    """A long document phase or a restart: the last passing read is old, and this one passes. It is no outage."""
    from datetime import datetime, timedelta, timezone
    db, read = site
    learned = Learned(recipe=recipe(), timezone=mock_portal.TIMEZONE)
    incident = Incident()
    outcome, _ = read(RunTrigger.attach, incident, learn=lambda portal, run_id: learned)
    assert outcome.passed and db.get_portal(PID).state is PortalState.serving
    later = datetime.now(timezone.utc) + timedelta(hours=3)
    outcome, run = read(RunTrigger.schedule, incident, now=lambda: later)
    assert outcome.passed and db.get_portal(PID).state is PortalState.serving and db.get_run(run.id).result.value == "ok"
    # When the portal does not answer, the age is still reported with the outage.
    read.mock.outage = True
    outcome, _ = read(RunTrigger.schedule, incident, now=lambda: later + timedelta(hours=3))
    assert not outcome.passed and db.get_portal(PID).state is PortalState.failed
