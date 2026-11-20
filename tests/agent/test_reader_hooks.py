"""What the reader does with a learner, a repairer and a spot checker that spend model calls.

The hooks here are plain functions: no model, no network. Run: pytest tests/agent/test_reader_hooks.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.checks.result import effect_of, wants_spot_check
from app.db import Database
from app.models import AgentStep, Portal, PortalState, RunTrigger, StepKind, TenderRecord, TokenUsage, url_key
from app.reader import Incident, NotLearned, Reader, SpotChecked, _Read, new_run

URL = "https://vergabe.example"
SPENT = TokenUsage(input_tokens=1000, output_tokens=100, cost_usd=0.25)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "watchtower.db")
    database.add_portal(Portal(id="p1", url=URL, url_key=url_key(URL)))
    yield database
    database.close()


def start(db: Database):
    return db.start_run(new_run(db.get_portal("p1"), RunTrigger.refresh))


def test_paid_learns_are_capped_per_day_and_start_again_the_next_day(db):
    now = [datetime(2026, 11, 20, 12, tzinfo=timezone.utc)]
    calls = []

    def learner(portal, run_id):
        calls.append(run_id)
        db.add_step(AgentStep(run_id=run_id, seq=1, kind=StepKind.llm, name="gpt", summary="Asked the model."))
        return NotLearned(reason="No list found.", model_calls=2, usage=SPENT)

    reader = Reader(db, None, lambda: None, learn=learner, now=lambda: now[0])
    incident = Incident()
    for _ in range(5):
        run = start(db)
        outcome = reader.read("p1", run, incident)
        assert outcome.state is PortalState.failed and not outcome.passed
    assert len(calls) == reader.checks.repairs_per_day == 3
    runs = db.list_runs("p1")
    assert [run.model_calls for run in runs] == [2, 2, 2, 0, 0]
    assert runs[0].usage.cost_usd == 0.25 and runs[-1].usage.cost_usd == 0
    portal = db.get_portal("p1")
    assert "already tried 3 time(s) today" in portal.reason
    assert "No list found" in runs[0].reason_after
    # The reader's own step follows the learner's: no two steps of a run share a number.
    assert [step.seq for step in db.list_steps(runs[0].id)] == [1, 2]

    now[0] += timedelta(days=1)
    reader.read("p1", start(db), incident)
    assert len(calls) == 4


def test_a_learner_that_spends_nothing_is_not_capped(db):
    calls = []
    reader = Reader(db, None, lambda: None, learn=lambda portal, run_id: calls.append(run_id))
    incident = Incident()
    for _ in range(5):
        reader.read("p1", start(db), incident)
    assert len(calls) == 5


def reading(db: Database, spot_check) -> _Read:
    reader = Reader(db, None, lambda: None, spot_check=spot_check)
    read = _Read(reader, "p1", start(db), Incident(), False)
    read.portal = db.get_portal("p1")
    return read


RECORDS = {"t1": TenderRecord(portal_id="p1", tender_id="t1", title="One", url=f"{URL}/t1"),
           "t2": TenderRecord(portal_id="p1", tender_id="t2", title="Two", url=f"{URL}/t2")}


def asked(read: _Read):
    return wants_spot_check(read.run.id, "structure", "The list page's structure changed.")


def test_a_spot_check_that_confirms_the_values_passes_and_its_cost_is_counted(db):
    seen = []

    def checker(portal, records, finding, run_id):
        seen.append(([record.tender_id for record in records], finding))
        return SpotChecked(passed=True, message="The spot check confirmed all 4 value(s).", model_calls=1, usage=SPENT)

    read = reading(db, checker)
    row = read._spot_check(asked(read), RECORDS, {"t2": object()})
    # What the model cost is on the run row at once, while the read is still going on.
    stored = db.get_run(read.run.id)
    assert stored.finished_at is None and stored.model_calls == 1 and stored.usage.cost_usd == 0.25
    assert row.passed and row.name == "spot_check" and row.message.startswith("The spot check confirmed")
    assert seen == [(["t2", "t1"], "The list page's structure changed.")]  # the pages read now come first
    assert read.model_calls == 1 and read.usage.cost_usd == 0.25
    (step,) = db.list_steps(read.run.id)
    assert step.name == "spot_check" and step.error is None


def test_a_spot_check_that_does_not_confirm_is_a_breakage(db):
    read = reading(db, lambda *a: SpotChecked(passed=False, message="1 of 4 value(s) not confirmed.", model_calls=1))
    row = read._spot_check(asked(read), RECORDS, {})
    assert not row.passed and effect_of(row).value == "breakage" and "not confirmed" in row.message


@pytest.mark.parametrize("checker", [None, lambda *a: None])
def test_without_a_model_or_an_answer_the_finding_counts_as_a_breakage(db, checker):
    read = reading(db, checker)
    row = read._spot_check(asked(read), RECORDS, {})
    assert not row.passed and effect_of(row).value == "breakage"
    assert "could not be checked against the page" in row.message and read.model_calls == 0
