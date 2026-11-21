"""Learn: from a portal's address to a recipe that passed a dry run on the portal's own pages
(DESIGN.md, "Attach: how the learner works").

The model explores with the tools of `app/agent/tools.py` and writes the recipe through them;
its final answer is only "done" and a summary. What counts is the workspace: the newest recipe
whose dry run passed. A run that ends without one, for a spent budget or an invalid answer,
gives no recipe; it does not raise.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.agent.runner import Runner, StepLog, load_prompt
from app.agent.settings import DEFAULT_AGENT_SETTINGS, AgentSettings
from app.agent.tools import Workspace, tools
from app.config import ModelSettings
from app.fetch.interface import Fetch
from app.models import Portal, StepKind, TenderRecord, TokenUsage
from app.recipe.schema import AuthoredRecipe
from app.recipe.settings import DEFAULT_RECIPE_SETTINGS, RecipeSettings


class LearnAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: bool = Field(description="true when the working recipe passed its dry run and reads the portal")
    summary: str = Field(description="what was learned, or in one sentence why it could not be done")


@dataclass
class AgentResult:
    """What a learn or a repair came to. `recipe` is None when it found none; `reason` says why."""

    recipe: AuthoredRecipe | None
    timezone: str | None = None
    country_code: str | None = None
    reason: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    model_calls: int = 0
    requests: int = 0
    rate_limited: bool = False  # no recipe, and the run ended on the model's rate limit: not the portal's fault


def learn(portal: Portal, *, fetch: Fetch, runner: Runner, steps: StepLog,
          models: ModelSettings | None = None, settings: AgentSettings = DEFAULT_AGENT_SETTINGS,
          recipes: RecipeSettings = DEFAULT_RECIPE_SETTINGS, draft: AuthoredRecipe | None = None,
          known: Sequence[TenderRecord] = (), known_documents: Mapping[str, int] | None = None,
          why: str = "", pages: Mapping | None = None) -> AgentResult:
    """Learn a recipe for a portal nobody has read before.

    With `draft` it is a learn again after a repair found nothing (DESIGN.md, Repair, step 3): the
    recipe that no longer reads the portal is handed over as a draft, the tenders of the last good
    read (`known`) must come out again, and the result must differ from the draft.
    """
    models = models or ModelSettings.from_env()
    space = Workspace(portal, fetch, max_requests=settings.learn_max_requests, settings=settings, recipes=recipes)
    task = (f"The portal's address: {portal.url}\n"
            f"You may send at most {settings.learn_max_requests} requests to it and make at most "
            f"{settings.learn_max_turns} model calls. Learn how to read it and leave a working recipe that "
            "passed its dry run.")
    if pages:
        space.pages.update(pages)  # what the repair before this learn already fetched is not fetched again
    if draft is not None:
        parts = urlsplit(portal.url)
        space.recipe = draft
        space.known = {record.tender_id: record for record in known}
        space.known_documents = dict(known_documents or {})
        some = [{"id": r.tender_id, "url": r.url, "title": r.title} for r in list(known)[: settings.check_tenders]]
        task += ("\n\nThis portal was read before, and its recipe stopped working"
                 + (f": {why}" if why else ".") +
                 f" Only the domain can be relied on: start from {parts.scheme}://{parts.netloc}/ when the address "
                 "above no longer answers. The old recipe is the working recipe now, as a draft: keep every part "
                 "of it that still reads its values, and learn again what does not. The tenders must come out "
                 "with the ids of the last good read, for example:\n"
                 + json.dumps(some, ensure_ascii=False, indent=1)
                 + "\nThe draft:\n" + json.dumps(draft.model_dump(mode="json"), ensure_ascii=False))
    outcome = runner.run(job="learn", model=models.learn, prompt=load_prompt("learn"), task=task,
                         tools=tools(space), answer_type=LearnAnswer, max_turns=settings.learn_max_turns,
                         max_usd=settings.learn_max_usd, steps=steps, reasoning=settings.reasoning_learn,
                         portal_id=portal.id)
    return finish("learn", space, outcome, steps, unchanged=draft)


def finish(job: str, space: Workspace, outcome, steps: StepLog, *, unchanged: AuthoredRecipe | None = None,
           rationale: str | None = None) -> AgentResult:
    """The result of a run: the newest recipe that passed its dry run, if there is one."""
    answer = outcome.answer
    said = getattr(answer, "summary", None) or getattr(answer, "what_changed", None) or ""
    result = AgentResult(recipe=None, usage=outcome.usage, model_calls=outcome.model_calls, requests=space.requests)
    best = space.accepted or space.passed
    if best is not None and unchanged is not None and best.recipe == unchanged:
        best = None  # a repair that changed nothing is no repair
    cost = f"{outcome.model_calls} model call(s), {space.requests} request(s), ${outcome.usage.cost_usd:.2f}"
    if best is None:
        result.rate_limited = outcome.rate_limited
        result.reason = (said if answer is not None and said else outcome.stopped
                         or "the model finished without a recipe that passed its dry run")
        steps.add(StepKind.decision, f"{job}_failed", f"No recipe came out of the {job}: {result.reason} ({cost}).",
                  error="no recipe")
        return result
    recipe = best.recipe
    if rationale:
        recipe = recipe.model_copy(update={"rationale": rationale})
    result.recipe, result.timezone, result.country_code = recipe, best.timezone, best.country_code
    result.reason = said or recipe.rationale
    how = "" if outcome.answer is not None else f" The run itself stopped early: {outcome.stopped}."
    steps.add(StepKind.decision, f"{job}_done",
              f"The {job} left a recipe whose dry run read {len(best.result.records)} tender(s) ({cost}).{how}")
    return result
