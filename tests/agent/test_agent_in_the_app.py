"""The agents inside the app: a portal learned on attach, a break repaired, a failed learn, on a
scripted model and the mock portal. The app runs in this process on a temporary database.

No test here calls the OpenAI API or sends a request anywhere. Run: pytest tests/agent/test_agent_in_the_app.py
"""
from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent import Agents
from app.config import ModelSettings
from app.db import Database
from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter
from app.main import create_app
from app.models import StepKind
from app.recipe.build import css, documents, facts, field, follow, get, host, identity, label, node, paging, regex
from app.recipe.schema import AuthoredRecipe, FieldName as F, NodeRole, PagingKind, ValueType as T
from mock_portal import MockPortal, recipe as mock_recipe
from mock_portal.data import DATE_FORMAT, DATETIME_FORMAT, NATURE_WORDS, PROCEDURE_WORDS, STATUS_WORDS
from tests.agent.helpers import ScriptedModel, call

MOCK = "https://mock.example"            # the build knows this one's recipe by hand
FOREIGN = "https://vergabe.example"      # served by the same mock, but nothing knows its recipe
GOOD = mock_recipe().model_dump(mode="json")
PROPOSE = call("propose_recipe", recipe=GOOD, timezone="Europe/Amsterdam", country_code="NL")
LEARN = [[call("open_page", url="/")], [PROPOSE], {"done": True, "summary": "A paged table."}]


def new_layout() -> AuthoredRecipe:
    """The recipe for the mock portal after `layout_changed`: what a repair should arrive at."""
    return AuthoredRecipe(
        start="list",
        nodes=[
            node("list", NodeRole.list, request=get("/tenders"), items=css("section#results div.result-card"),
                 fields=[field(F.id, css("span.badge"), type=T.id),
                         field(F.url, css("h3.card-title a", attr="href"), type=T.url),
                         field(F.title, css("h3.card-title a")),
                         field(F.buyer_name, css("li.org strong")),
                         field(F.publication_date, css("li.opened strong"), type=T.date, formats=[DATE_FORMAT]),
                         field(F.submission_deadline, css("li.closes strong"), type=T.datetime,
                               formats=[DATETIME_FORMAT]),
                         field(F.status, css("span.state"), type=T.status, words=STATUS_WORDS)],
                 paging=paging(PagingKind.next_link, next=css("a.pager-next", attr="href")),
                 facts=facts(total=regex(r"Showing (\d+) notices"), total_counts_closed=True, newest_first=True)),
            node("detail", NodeRole.detail,
                 fields=[field(F.id, label("Notice ID"), type=T.id),
                         field(F.title, css("h1.notice-title")),
                         field(F.reference_number, label("File reference")),
                         field(F.buyer_name, label("Buyer")),
                         field(F.publication_date, label("Publication date"), type=T.date, formats=[DATE_FORMAT]),
                         field(F.submission_deadline, label("Closing date"), type=T.datetime,
                               formats=[DATETIME_FORMAT]),
                         field(F.status, label("State"), type=T.status, words=STATUS_WORDS),
                         field(F.procedure_type, label("Procedure type"), type=T.procedure, words=PROCEDURE_WORDS),
                         field(F.contract_nature, label("Contract category"), type=T.nature, words=NATURE_WORDS),
                         field(F.cpv_codes, label("CPV codes"), type=T.cpv),
                         field(F.description, css("div.summary-text p")),
                         field(F.postal_code, label("Postcode"), type=T.postal_code),
                         field(F.city, label("Town"))],
                 documents=documents(css("table.attachments a.download", attr="href"))),
        ],
        edges=[follow("list", "detail", css("h3.card-title a", attr="href"))],
        identity=identity(r"^MP-\d{4}-\d{4,}$", from_url=r"/tenders/(MP-\d{4}-\d{4,})", must_agree=True),
        family=None, host=host("en"),
        rationale="The list is a set of cards with a link to the next page; each card links to the tender's page.")


class Site:
    def __init__(self, client: TestClient, mock: MockPortal, model: ScriptedModel, data_dir) -> None:
        self.client, self.mock, self.model, self.data_dir = client, mock, model, data_dir

    def settled(self, pid: str, run_id: str | None = None, seconds: float = 30.0) -> dict:
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            runs = self.client.get(f"/portals/{pid}/runs").json()
            mine = [run for run in runs if run_id is None or run["id"] == run_id]
            if mine and all(run["finishedAt"] is not None for run in mine):
                return self.client.get(f"/portals/{pid}").json()
            time.sleep(0.02)
        raise AssertionError("the read did not end in time")

    def attach(self, url: str) -> tuple[str, dict]:
        pid = self.client.post("/portals", json={"url": url}).json()["id"]
        return pid, self.settled(pid)

    def refresh(self, pid: str) -> dict:
        run_id = self.client.post(f"/portals/{pid}/refresh").json()["runId"]
        return self.settled(pid, run_id)

    def records(self, pid: str):
        """The runs and their steps, read from the database file the app writes."""
        db = Database(self.data_dir / "watchtower.db")
        try:
            runs = db.list_runs(pid)
            return runs, {run.id: db.list_steps(run.id) for run in runs}, db.active_recipe(pid)
        finally:
            db.close()


@pytest.fixture
def site(monkeypatch, tmp_path):
    def make(script, env: dict[str, str] | None = None):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        for name, value in (env or {}).items():
            monkeypatch.setenv(name, value)
        mock = MockPortal()
        clock = [0.0]
        limiter = PortalLimiter(1.0, 10.0, clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
        fetcher = Fetcher(FetchSettings(mode=FetchMode.live), transport=httpx.MockTransport(mock.handle),
                          limiter=limiter, clock=lambda: clock[0], rng=lambda: 0.0)
        model = ScriptedModel(script)
        app = create_app(fetch=fetcher, mock=mock,
                         agents=lambda fetch, database: Agents(model, fetch, database, models=ModelSettings()))
        opened.append(TestClient(app))
        return Site(opened[-1].__enter__(), mock, model, tmp_path)

    opened: list[TestClient] = []
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def test_a_portal_nobody_knows_is_learned_on_attach_and_served(site):
    s = site(LEARN)
    pid, portal = s.attach(FOREIGN)
    assert (portal["state"], portal["tenderCount"]) == ("serving", 45), portal["reason"]
    tenders = {t["id"]: t for t in s.client.get(f"/portals/{pid}/tenders").json()}
    truth = {t["id"]: t for t in s.mock.truth()}
    assert set(tenders) == set(truth)
    one = next(iter(truth))
    assert tenders[one]["title"] == truth[one]["title"] and tenders[one]["documents"]
    assert tenders[one]["submissionDeadline"] == truth[one]["submission_deadline"].isoformat(timespec="seconds")

    (run,), steps, recipe = s.records(pid)
    assert run.model_calls == 3 and run.usage.input_tokens == 3000 and run.usage.cost_usd > 0
    mine = steps[run.id]
    assert [step.seq for step in mine] == list(range(1, len(mine) + 1))  # the agent's steps and the reader's, in one line
    kinds = [step.kind for step in mine]
    assert kinds.count(StepKind.llm) == 3 and kinds.count(StepKind.tool) == 2
    names = [step.name for step in mine]
    assert names.index("learn_done") < names.index("learn") < names.index("read_list") < names.index("publish")
    assert all(step.prompt_id == "learn/system@3" and step.usage for step in mine if step.kind is StepKind.llm)
    assert recipe is not None and recipe.version == 1 and recipe.rationale == mock_recipe().rationale
    assert len(s.model.requests) == 3

    # A regular read afterwards calls no model (CONVENTIONS.md, rule 2).
    assert s.refresh(pid)["state"] == "serving"
    runs, _, _ = s.records(pid)
    assert runs[-1].model_calls == 0 and runs[-1].usage.input_tokens == 0 and len(s.model.requests) == 3


def test_a_learn_that_finds_no_recipe_fails_the_portal_with_the_learners_reason_and_its_cost(site):
    s = site([[call("open_page", url="/")], {"done": False, "summary": "The tender list sits behind a login."}])
    pid, portal = s.attach(FOREIGN)
    assert portal["state"] == "failed" and portal["tenderCount"] == 0
    assert "No recipe could be learned" in portal["reason"] and "sits behind a login" in portal["reason"]
    (run,), steps, recipe = s.records(pid)
    assert recipe is None and run.model_calls == 2 and run.usage.cost_usd > 0
    assert [step.seq for step in steps[run.id]] == list(range(1, len(steps[run.id]) + 1))


def test_the_mock_portal_keeps_its_hand_written_recipe_and_costs_nothing(site):
    s = site([])
    pid, portal = s.attach(MOCK)
    assert (portal["state"], portal["tenderCount"]) == ("serving", 45)
    (run,), _, _ = s.records(pid)
    assert run.model_calls == 0 and s.model.requests == []


def test_the_mock_portal_is_learned_by_the_model_when_asked_and_falls_back_when_that_fails(site):
    s = site(LEARN + [{"done": False, "summary": "No list found."}], env={"MOCK_LEARNED_BY_MODEL": "1"})
    pid, portal = s.attach(MOCK)
    assert portal["state"] == "serving"
    (run,), _, _ = s.records(pid)
    assert run.model_calls == 3
    # A second portal on the same mock: the model finds nothing, the hand-written recipe serves it.
    other, portal = s.attach(MOCK + "/?again=1")
    assert portal["state"] == "serving", portal["reason"]
    (run,), _, _ = s.records(other)
    assert run.model_calls == 1 and run.usage.cost_usd > 0


def test_a_changed_layout_is_repaired_by_the_model_and_the_portal_serves_again(site):
    repaired = new_layout().model_dump(mode="json")
    s = site([[call("open_page", url="/tenders")],
              [call("propose_recipe", recipe=repaired, timezone="Europe/Amsterdam", country_code="NL")],
              {"done": True, "what_changed": "The list became cards and the tender page a table with new labels."}])
    pid, portal = s.attach(MOCK)
    assert portal["state"] == "serving" and s.model.requests == []
    before = {t["id"]: t for t in s.client.get(f"/portals/{pid}/tenders").json()}

    s.mock.layout_changed = True
    portal = s.refresh(pid)
    for _ in range(4):  # a breakage is confirmed, then repaired, within a few reads
        if portal["state"] == "serving":
            break
        portal = s.refresh(pid)
    assert portal["state"] == "serving", portal["reason"]
    assert len(s.model.requests) == 3 and s.model.requests[0]["model"] == ModelSettings().repair
    after = {t["id"]: t for t in s.client.get(f"/portals/{pid}/tenders").json()}
    assert set(after) == set(before)
    for tender_id, was in before.items():
        assert after[tender_id]["title"] == was["title"]
        assert after[tender_id]["submissionDeadline"] == was["submissionDeadline"]

    runs, steps, recipe = s.records(pid)
    assert recipe.version == 2 and recipe.parent_version == 1
    assert recipe.rationale == "The list became cards and the tender page a table with new labels."
    fixed = next(run for run in runs if run.model_calls)
    assert fixed.model_calls == 3 and fixed.usage.cost_usd > 0
    mine = steps[fixed.id]
    assert [step.seq for step in mine] == list(range(1, len(mine) + 1))
    assert "repair_done" in [step.name for step in mine]
    assert any(step.name == "repair" and "passed a full read" in step.summary for step in mine)


def test_a_repair_that_finds_nothing_leaves_the_last_good_tenders_and_records_its_cost(site):
    s = site([{"done": False, "what_changed": "The portal shows a different site now."}])
    pid, _ = s.attach(MOCK)
    s.mock.layout_changed = True
    portal = s.refresh(pid)
    for _ in range(3):
        if s.model.requests:
            break
        portal = s.refresh(pid)
    assert portal["state"] in ("healing", "failed") and portal["tenderCount"] == 45
    runs, steps, recipe = s.records(pid)
    assert recipe.version == 1
    tried = next(run for run in runs if run.model_calls)
    assert tried.model_calls == 1 and tried.usage.cost_usd > 0
    assert any(step.name == "repair" and "different site" in step.summary for step in steps[tried.id])

