"""Repair: the current recipe, the checks that failed and the portal as it is now go to the model,
which changes as little as it can (DESIGN.md, "Repair", step 2).

Before the model is asked, the current recipe is dry-run on freshly fetched pages, so the model
starts from what the recipe gives today. The result is a recipe that differs from the current
one and passed its dry run; the reader then verifies it with a full read before it replaces
anything. Trying other stored recipes first (step 1) and learning again from scratch (step 3)
are not built.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.agent.learn import AgentResult, finish
from app.agent.runner import Runner, StepLog, load_prompt
from app.agent.settings import DEFAULT_AGENT_SETTINGS, AgentSettings
from app.agent.tools import Workspace, tools
from app.config import ModelSettings
from app.fetch.interface import Fetch
from app.models import CheckResult, Portal, TenderRecord
from app.recipe.schema import AuthoredRecipe
from app.recipe.settings import DEFAULT_RECIPE_SETTINGS, RecipeSettings


class RepairAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: bool = Field(description="true when the changed recipe passed its dry run and reads the portal again")
    what_changed: str = Field(description="one plain sentence: what moved on the portal and what was changed, "
                                          "or why it could not be repaired")


def authored(recipe: AuthoredRecipe) -> AuthoredRecipe:
    """A stored recipe body as the part a model writes: without its format and what we measured."""
    return AuthoredRecipe.model_validate(recipe.model_dump(mode="json", include=set(AuthoredRecipe.model_fields)))


def _last_good(known: Sequence[TenderRecord], count: int) -> list[dict]:
    out = []
    for record in list(known)[:count]:
        out.append({"id": record.tender_id, "url": record.url, "title": record.title,
                    "buyer_name": record.buyer_name,
                    "publication_date": record.publication_date.isoformat() if record.publication_date else None,
                    "submission_deadline": record.submission_deadline.isoformat() if record.submission_deadline else None,
                    "reference_number": record.reference_number})
    return out


def repair(portal: Portal, recipe: AuthoredRecipe, failed: Sequence[CheckResult], *, fetch: Fetch, runner: Runner,
           steps: StepLog, known: Sequence[TenderRecord] = (), models: ModelSettings | None = None,
           settings: AgentSettings = DEFAULT_AGENT_SETTINGS,
           recipes: RecipeSettings = DEFAULT_RECIPE_SETTINGS) -> AgentResult:
    """Repair a recipe whose read failed its checks. `known` are tenders of the last good read."""
    models = models or ModelSettings.from_env()
    current = authored(recipe)
    space = Workspace(portal, fetch, max_requests=settings.repair_max_requests, settings=settings, recipes=recipes)
    space.recipe = current
    space.known = {record.tender_id: record for record in known}
    result, warnings = space.check()  # what the current recipe gives on the portal as it is now
    today = space.report(result, warnings).text
    space.accepted = space.passed = None  # the unchanged recipe is never the repair
    parts = urlsplit(portal.url)
    root = f"{parts.scheme}://{parts.netloc}/"
    checks = "\n".join(f"- {row.name}: {row.message}" for row in failed) or "- (no check was named)"
    task = "\n\n".join([
        f"The portal's address when it was learned: {portal.url}\nThe domain's root, the one address that can be "
        f"relied on: {root}\nIts time zone: {portal.timezone or 'unknown'}",
        f"The checks that failed on the last read:\n{checks}",
        "The dry run of the current recipe on the portal as it is now:\n" + today,
        "Tenders of the last good read (the repaired recipe must give these again, with these ids):\n"
        + json.dumps(_last_good(known, settings.check_tenders), ensure_ascii=False, indent=1),
        "The current recipe (it is the working recipe; change it with replace_node):\n"
        + json.dumps(current.model_dump(mode="json"), ensure_ascii=False),
        f"You may send at most {max(settings.repair_max_requests - space.requests, 0)} more requests and make at "
        f"most {settings.repair_max_turns} model calls.",
    ])
    outcome = runner.run(job="repair", model=models.repair, prompt=load_prompt("repair"), task=task,
                         tools=tools(space), answer_type=RepairAnswer, max_turns=settings.repair_max_turns,
                         max_usd=settings.repair_max_usd, steps=steps, reasoning=settings.reasoning_repair,
                         portal_id=portal.id)
    said = outcome.answer.what_changed if isinstance(outcome.answer, RepairAnswer) and outcome.answer.done else None
    return finish("repair", space, outcome, steps, unchanged=current, rationale=said)
