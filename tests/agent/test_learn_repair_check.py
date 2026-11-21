"""Learn, repair and the spot check on a scripted model and the mock portal.

No test here calls the OpenAI API or sends a request anywhere. Run: pytest tests/agent/test_learn_repair_check.py
"""
from __future__ import annotations

import json

from app.agent.learn import learn
from app.agent.repair import repair
from app.agent.runner import Runner, StepLog
from app.agent.settings import AgentSettings
from app.agent.spotcheck import PageValues, SpotAnswer, ValueCheck, judge, pages_for, spot_check
from app.checks.result import Cause, failed
from app.config import ModelSettings
from app.models import StepKind, TenderRecord
from app.recipe.run import dry_run
from app.recipe.schema import RecipeBody
from mock_portal import MockPortal, recipe as mock_recipe
from tests.agent.helpers import URL, MockFetch, ScriptedModel, call, portal

MODELS = ModelSettings()
GOOD = mock_recipe().model_dump(mode="json")
PROPOSE = call("propose_recipe", recipe=GOOD, timezone="Europe/Amsterdam", country_code="NL")


def run_learn(script, fetch=None, **settings):
    model, steps = ScriptedModel(script), StepLog("run1")
    fetch = fetch or MockFetch()
    result = learn(portal(), fetch=fetch, runner=Runner(model, AgentSettings(**settings)), steps=steps,
                   models=MODELS, settings=AgentSettings(**settings))
    return result, model, steps, fetch


# -- learn --

def test_learn_returns_the_recipe_that_passed_its_dry_run():
    result, model, steps, fetch = run_learn([
        [call("open_page", url=URL)],
        [call("page_links", url=URL, contains=None), call("open_page", url="/tenders")],
        [PROPOSE],
        {"done": True, "summary": "A paged table with a page per tender."},
    ])
    assert result.recipe == mock_recipe() and result.timezone == "Europe/Amsterdam" and result.country_code == "NL"
    assert result.model_calls == 4 and result.usage.input_tokens == 4000 and result.usage.cost_usd > 0
    assert result.requests == len(fetch.asked) and result.requests <= 10
    first = model.requests[0]
    assert first["model"] == MODELS.learn and URL in first["input"][0]["content"]
    assert {"open_page", "try_locator", "propose_recipe", "replace_node"} <= set(first["tools"])
    assert first["instructions"].startswith("You learn how to read one public procurement portal")
    assert steps.steps[-1].name == "learn_done" and "$" in steps.steps[-1].summary
    assert {step.prompt_id for step in steps.steps if step.kind is StepKind.llm} == {"learn/system@3"}
    # The recipe really reads the portal: a dry run on the pages the learn fetched gives the tenders.
    assert all(step.summary and "\n" not in step.summary for step in steps.steps)


def test_learn_without_an_accepted_recipe_gives_none_and_says_why():
    result, _, steps, _ = run_learn([[call("open_page", url=URL)],
                                     {"done": False, "summary": "The list sits behind a login."}])
    assert result.recipe is None and result.reason == "The list sits behind a login." and result.model_calls == 2
    assert steps.steps[-1].name == "learn_failed"


def test_a_model_that_says_done_without_a_passing_recipe_is_not_believed():
    bad = json.loads(json.dumps(GOOD))
    bad["nodes"][0]["items"]["expr"] = "ul.none li"
    result, _, _, _ = run_learn([[call("propose_recipe", recipe=bad, timezone=None, country_code=None)],
                                 {"done": True, "summary": "Done."}])
    assert result.recipe is None


def test_a_spent_budget_still_hands_over_a_recipe_that_already_passed():
    result, _, steps, _ = run_learn([[PROPOSE], [call("check_recipe", show_recipe=False)],
                                     [call("check_recipe", show_recipe=False)]], learn_max_turns=3)
    assert result.recipe == mock_recipe() and "stopped early" in steps.steps[-1].summary


def test_a_spent_budget_without_a_recipe_gives_none_and_does_not_raise():
    result, _, _, _ = run_learn([[call("open_page", url=URL)]] * 5, learn_max_turns=2)
    assert result.recipe is None and "2 model calls" in result.reason


def test_the_learned_recipe_reads_every_tender_of_the_portal():
    result, _, _, fetch = run_learn([[PROPOSE], {"done": True, "summary": "ok"}])
    mock = fetch.mock
    pages = {}
    for path in ["/tenders", "/tenders?page=2", "/tenders?page=3", *[f"/tenders/{t['id']}" for t in mock.truth()]]:
        pages[URL + path] = mock.respond("GET", URL + path)[2]
    read = dry_run(result.recipe, pages, url=URL, timezone=result.timezone)
    assert read.ok and {record.tender_id for record in read.records} == {t["id"] for t in mock.truth()}


# -- repair --

def swapped() -> MockPortal:
    mock = MockPortal(tenders=12, page_size=5)
    mock.columns_swapped = True
    return mock


def list_node_reading(published: str, deadline: str) -> dict:
    node = json.loads(json.dumps(GOOD["nodes"][0]))
    for field in node["fields"]:
        if field["name"] == "publication_date":
            field["locators"] = [{"kind": "css", "expr": published, "labels": [], "attr": None}]
        if field["name"] == "submission_deadline":
            field["locators"] = [{"kind": "css", "expr": deadline, "labels": [], "attr": None}]
            field["value"]["formats"] = ["%d.%m.%Y %H:%M"]
    return node


def run_repair(script, known=()):
    model, steps = ScriptedModel(script), StepLog("run1", first=9)
    fetch = MockFetch(swapped())
    rows = [failed("run1", "changed.submission_deadline", "The deadline of 9 of 12 known tenders changed.",
                   cause=Cause.breakage)]
    target = portal().model_copy(update={"timezone": "Europe/Amsterdam"})
    result = repair(target, RecipeBody.from_authored(mock_recipe()), rows, fetch=fetch, known=known,
                    runner=Runner(model), steps=steps, models=MODELS)
    return result, model, steps, fetch


def test_repair_starts_from_the_current_recipe_its_dry_run_today_and_the_failed_checks():
    newest = swapped().truth()[0]
    assert newest["id"] == "MP-2026-0012"
    record = TenderRecord(portal_id="p1", tender_id=newest["id"], title=newest["title"], url=newest["url"])
    node = list_node_reading("td.published", "td.deadline")
    result, model, steps, fetch = run_repair([
        [call("replace_node", node=node)],
        {"done": True, "what_changed": "The two date columns of the list changed places."}], known=[record])
    task = model.requests[0]["input"][0]["content"]
    assert "changed.submission_deadline: The deadline of 9 of 12 known tenders changed." in task
    assert '"list_rows": 10' in task and "MP-2026-0012" in task and '"start": "list"' in task
    assert "Europe/Amsterdam" in task and '"format"' not in task and "expectations" not in task
    assert model.requests[0]["model"] == MODELS.repair and model.requests[0]["instructions"].startswith("You repair")
    assert result.recipe is not None and result.recipe != mock_recipe()
    assert result.recipe.nodes[0].model_dump(mode="json") == node
    assert result.recipe.nodes[1] == mock_recipe().nodes[1]  # the other node is untouched
    assert result.recipe.rationale == "The two date columns of the list changed places."
    assert result.timezone == "Europe/Amsterdam"
    assert steps.steps[0].seq == 9 and steps.steps[-1].name == "repair_done"


def test_a_repair_that_changes_nothing_is_no_repair():
    result, _, steps, _ = run_repair([[call("check_recipe", show_recipe=False)],
                                      {"done": True, "what_changed": "Nothing needed changing."}])
    assert result.recipe is None and steps.steps[-1].name == "repair_failed" and result.model_calls == 2


def test_a_repair_the_model_gives_up_on_gives_none_with_its_reason():
    result, _, _, _ = run_repair([{"done": False, "what_changed": "The portal now asks for a login."}])
    assert result.recipe is None and result.reason == "The portal now asks for a login."


# -- the spot check --

PAGE = PageValues("MP-1", f"{URL}/tenders/MP-1",
                  "Road works, lot 1 Contracting authority City of Utrecht Deadline for tenders 12.03.2027 10:00",
                  {"title": "Road works, lot 1", "submission_deadline": "2027-03-12T10:00:00+01:00"})


def answer(*checks) -> dict:
    return {"checks": [{"tender_id": "MP-1", "field": f, "agrees": a, "quote": q} for f, a, q in checks]}


def check(script):
    model, steps = ScriptedModel(script), StepLog("run1")
    return spot_check([PAGE], runner=Runner(model), steps=steps, finding="The page's structure changed.",
                      models=MODELS), model, steps


def test_the_spot_check_passes_when_every_value_is_quoted_from_the_page():
    result, model, steps = check([answer(("title", True, "Road works,  lot 1"),
                                         ("submission_deadline", True, "deadline for tenders 12.03.2027 10:00"))])
    assert result.passed and "confirmed all 2 value(s)" in result.message and result.model_calls == 1
    request = model.requests[0]
    assert request["model"] == MODELS.check and request["tools"] == [] and not request["reasoning"]
    assert "The page's structure changed." in request["input"][0]["content"]
    assert [step.kind for step in steps.steps] == [StepKind.llm, StepKind.decision]
    assert steps.steps[0].prompt_id == "check/system@1"


def test_a_quote_that_is_not_on_the_page_counts_against_the_value():
    result, _, _ = check([answer(("title", True, "Road works, lot 1"),
                                 ("submission_deadline", True, "Deadline: 12 March 2027"))])
    assert not result.passed and "quote" in result.wrong[0] and "1 of 2" in result.message


def test_a_value_the_model_disagrees_with_or_skips_fails_the_check():
    result, _, _ = check([answer(("title", False, None))])
    assert not result.passed and len(result.wrong) == 2
    assert judge([PAGE], SpotAnswer(checks=[ValueCheck(tender_id="MP-9", field="title", agrees=True, quote="Road")]))


def test_a_spot_check_that_cannot_be_done_answers_none():
    assert check(["this is not json"])[0] is None  # one call only: no second try
    steps = StepLog("run1")
    assert spot_check([], runner=Runner(ScriptedModel([])), steps=steps, models=MODELS) is None
    assert steps.steps[0].error == "no pages"


def test_the_pages_of_a_spot_check_come_through_the_network_layer_as_plain_text():
    fetch = MockFetch()
    truth = fetch.mock.truth()
    records = [TenderRecord(portal_id="p1", tender_id=t["id"], title=t["title"], url=t["url"],
                            buyer_name=t["buyer_name"], submission_deadline=t["submission_deadline"]) for t in truth]
    records.insert(0, TenderRecord(portal_id="p1", tender_id="no-page", title="x"))
    pages = pages_for(portal(), records, fetch, AgentSettings(check_tenders=2))
    assert [page.tender_id for page in pages] == [truth[0]["id"], truth[1]["id"]] and len(fetch.asked) == 2
    assert truth[0]["title"] in pages[0].text and "<" not in pages[0].text
    assert pages[0].values["submission_deadline"] == truth[0]["submission_deadline"].isoformat()


def test_a_repair_whose_records_differ_from_the_last_good_read_is_not_accepted():
    # The portal swapped its two date columns. A "repair" that leaves the swap in reads dates, but the wrong ones.
    fetch = MockFetch(swapped())
    truth = fetch.mock.truth()
    known = [TenderRecord(portal_id="p1", tender_id=t["id"], title=t["title"], url=t["url"], buyer_name=t["buyer_name"],
                          publication_date=t["publication_date"], submission_deadline=t["submission_deadline"])
             for t in truth]
    # Read the dates from the list only, so that the swapped columns show in the records.
    list_only = json.loads(json.dumps(GOOD))
    list_only["nodes"][0]["fields"] = list_node_reading("td.published", "td.deadline")["fields"]
    list_only["nodes"][1]["fields"] = [f for f in list_only["nodes"][1]["fields"]
                                       if f["name"] not in ("publication_date", "submission_deadline")]
    model, steps = ScriptedModel([[call("propose_recipe", recipe=list_only, timezone="Europe/Amsterdam",
                                        country_code="NL")],
                                  {"done": True, "what_changed": "Read the dates from the list."}]), StepLog("run1")
    target = portal().model_copy(update={"timezone": "Europe/Amsterdam"})
    result = repair(target, RecipeBody.from_authored(mock_recipe()), [], fetch=fetch, known=known,
                    runner=Runner(model), steps=steps, models=MODELS)
    assert result.recipe is None
    said = next(item["output"] for item in model.requests[1]["input"] if item.get("type") == "function_call_output")
    assert '"accepted": false' in said and "differs from the last good read" in said and "publication_date" in said
