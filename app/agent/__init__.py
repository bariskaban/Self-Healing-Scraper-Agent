"""The learning and repair agent (docs/BUILD-PLAN.md, stream B).

`Agents` is what the app wires into the reader: a learner, a repairer and a spot checker, as
the protocols of `app/reader.py` ask for them. `Agents.from_env` gives None when no
OPENAI_API_KEY is set; the app then runs without a model.

Every model call goes through `app/agent/runner.py`, and nothing outside this package imports
`openai` (CLAUDE.md).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

from app import logs
from app.agent.learn import AgentResult, learn
from app.agent.repair import repair
from app.agent.runner import Model, ModelError, ModelReply, OpenAIModel, Runner, Said, StepLog, Tool, ToolCall
from app.agent.settings import DEFAULT_AGENT_SETTINGS, AgentSettings
from app.agent.spotcheck import SpotResult, pages_for, spot_check
from app.config import ModelSettings, api_key
from app.fetch.interface import Fetch
from app.models import CheckResult, Portal, TenderRecord
from app.recipe.schema import AuthoredRecipe
from app.recipe.settings import DEFAULT_RECIPE_SETTINGS, RecipeSettings

__all__ = ["AgentResult", "AgentSettings", "Agents", "Model", "ModelError", "ModelReply", "OpenAIModel", "Runner",
           "Said", "SpotResult", "StepLog", "Tool", "ToolCall", "learn", "repair", "spot_check"]


log = logs.get("agent")


class _Slot:
    """`with` form of a semaphore the caller has already acquired: it releases on exit."""

    def __init__(self, semaphore: threading.BoundedSemaphore) -> None:
        self._semaphore = semaphore

    def __enter__(self) -> "_Slot":
        return self

    def __exit__(self, *exc: object) -> None:
        self._semaphore.release()


class Agents:
    """The three jobs of the model, on one model client, one network layer and one database.

    Each method blocks (the reader calls them in a worker thread), writes its steps under the
    run it is given, and returns None-like results instead of raising.
    """

    def __init__(self, model: Model, fetch: Fetch, database: Any, *, models: ModelSettings | None = None,
                 settings: AgentSettings = DEFAULT_AGENT_SETTINGS,
                 recipes: RecipeSettings = DEFAULT_RECIPE_SETTINGS) -> None:
        self.runner = Runner(model, settings)
        self.fetch, self.db = fetch, database
        if database is not None:  # DELETE: the system stops calling the portal within a minute
            self.runner.alive = lambda portal_id: database.get_portal(portal_id) is not None
        # At most this many runs use the model at once; the others wait here, and a portal waiting is `integrating`.
        self._slots = threading.BoundedSemaphore(settings.max_concurrent_runs)
        self.models = models or ModelSettings.from_env()
        self.settings, self.recipes = settings, recipes

    @classmethod
    def from_env(cls, fetch: Fetch, database: Any, environ: Mapping[str, str] | None = None, *,
                 recipes: RecipeSettings = DEFAULT_RECIPE_SETTINGS) -> "Agents | None":
        """The agents on OpenAI when OPENAI_API_KEY is set, else None."""
        key = api_key(environ)
        if key is None:
            log.info("OPENAI_API_KEY is not set: no learner, repairer or spot check")
            return None
        settings = AgentSettings.from_env(environ)
        log.info("OPENAI_API_KEY is set (%d chars, not logged); budgets: %s", len(key), logs.clip(settings, 300))
        return cls(OpenAIModel(key, settings), fetch, database, models=ModelSettings.from_env(environ),
                   settings=settings, recipes=recipes)

    def _steps(self, run_id: str) -> StepLog:
        return StepLog.on_database(self.db, run_id, self.settings)

    def _slot(self, job: str, portal: Portal):
        """Wait for a free place among the runs that may use the model now (`max_concurrent_runs`)."""
        began = time.monotonic()
        self._slots.acquire()
        waited = time.monotonic() - began
        if waited >= 1.0:
            log.info("portal %s: the %s waited %.0f s for a free place among the model runs", portal.id, job, waited)
        return _Slot(self._slots)

    def learn(self, portal: Portal, run_id: str) -> AgentResult:
        with self._slot("learn", portal):
            return learn(portal, fetch=self.fetch, runner=self.runner, steps=self._steps(run_id), models=self.models,
                         settings=self.settings, recipes=self.recipes)

    def repair(self, portal: Portal, recipe: AuthoredRecipe, failed: Sequence[CheckResult], run_id: str
               ) -> AgentResult:
        with self._slot("repair", portal):
            return self._repair(portal, recipe, failed, run_id)

    def _repair(self, portal: Portal, recipe: AuthoredRecipe, failed: Sequence[CheckResult], run_id: str
                ) -> AgentResult:
        files: dict[str, int] = {}
        try:
            known = self.db.known_tenders(portal.id)
            # The newest tenders are the ones a dry run reads: how many files each had, to compare.
            for record in sorted(known, key=lambda r: r.first_seen_at, reverse=True)[: 4 * self.settings.dry_run_details]:
                files[record.tender_id] = len(self.db.tender_documents(portal.id, record.tender_id))
        except Exception:  # the last good tenders are a help to the model, not a need
            known = []
        return repair(portal, recipe, failed, fetch=self.fetch, runner=self.runner, steps=self._steps(run_id),
                      known=known, known_documents=files, models=self.models, settings=self.settings,
                      recipes=self.recipes)

    def spot_check(self, portal: Portal, records: Sequence[TenderRecord], finding: str, run_id: str
                   ) -> SpotResult | None:
        with self._slot("spot check", portal):
            steps = self._steps(run_id)
            pages = pages_for(portal, records, self.fetch, self.settings)
            return spot_check(pages, runner=self.runner, steps=steps, finding=finding, models=self.models,
                              settings=self.settings, portal_id=portal.id)
