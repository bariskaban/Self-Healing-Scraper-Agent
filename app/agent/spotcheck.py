"""The spot check: one small model call that must quote the page for each value (DESIGN.md,
"Notice"; CONVENTIONS.md, rule 2: the only model call a regular read may make).

The model gets the plain text of a few tenders' pages and the values the read took from them.
For each value it says whether the page states it, with the words of the page. Its word alone
is not taken: every quote is looked up in the page text here, and a value passes only when the
model agrees and its quote is really there. The check passes when every value passes.

It answers None when it could not be done (no page to read, no answer from the model); the
caller then treats the finding as it does without a model.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from app.agent.runner import Runner, StepLog, load_prompt
from app.agent.settings import DEFAULT_AGENT_SETTINGS, AgentSettings
from app.config import ModelSettings
from app.fetch.interface import Fetch, RobotsForbidden, RobotsUnavailable
from app.models import Portal, StepKind, TenderRecord, TokenUsage
from app.recipe.locate import parse_page
from app.recipe.schema import NodeKind

CHECKED = ("title", "buyer_name", "publication_date", "submission_deadline", "reference_number")
_SPACE = re.compile(r"\s+")


class ValueCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tender_id: str
    field: str
    agrees: bool = Field(description="the page states this value for this field of this tender")
    quote: str | None = Field(description="the exact words of the page that state it, or null when it is not there")


class SpotAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[ValueCheck]


@dataclass
class PageValues:
    """One tender's page as plain text, and the values read from it."""

    tender_id: str
    url: str
    text: str
    values: dict[str, str]


@dataclass
class SpotResult:
    passed: bool
    message: str
    wrong: list[str] = field(default_factory=list)  # "tender field: why", for the check row
    usage: TokenUsage = field(default_factory=TokenUsage)
    model_calls: int = 0


def _plain(text: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


def values_of(record: TenderRecord) -> dict[str, str]:
    out = {}
    for name in CHECKED:
        value = getattr(record, name)
        if value is not None and str(value).strip():
            out[name] = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return out


def pages_for(portal: Portal, records: Sequence[TenderRecord], fetch: Fetch,
              settings: AgentSettings = DEFAULT_AGENT_SETTINGS) -> list[PageValues]:
    """The pages of the first few tenders that have one, fetched through the network layer."""
    out: list[PageValues] = []
    for record in records:
        if len(out) >= settings.check_tenders:
            break
        values = values_of(record)
        if not record.url or not values:
            continue
        try:
            got = fetch.fetch(portal.id, record.url)
        except (RobotsForbidden, RobotsUnavailable, LookupError, NotImplementedError):
            continue
        if not got.ok:
            continue
        kind = NodeKind.json if "json" in (got.content_type or "") else NodeKind.html
        try:
            text = parse_page(got.body, kind, got.final_url, got.headers.get("content-type")).text
        except ValueError:
            continue
        out.append(PageValues(record.tender_id, record.url, text[: settings.check_page_chars], values))
    return out


def judge(pages: Sequence[PageValues], answer: SpotAnswer) -> list[str]:
    """What is wrong, one line per value: the model disagreed, did not answer, or quoted words the page lacks."""
    answered = {(check.tender_id, check.field): check for check in answer.checks}
    wrong = []
    for page in pages:
        text = _plain(page.text)
        for name, value in page.values.items():
            check = answered.get((page.tender_id, name))
            if check is None:
                wrong.append(f"{page.tender_id} {name}: the model gave no answer for it")
            elif not check.agrees:
                wrong.append(f"{page.tender_id} {name}: the page does not state {value!r}")
            elif not check.quote or _plain(check.quote) not in text:
                wrong.append(f"{page.tender_id} {name}: the model's quote for {value!r} is not on the page")
    return wrong


def spot_check(pages: Sequence[PageValues], *, runner: Runner, steps: StepLog, finding: str = "",
               models: ModelSettings | None = None, settings: AgentSettings = DEFAULT_AGENT_SETTINGS,
               portal_id: str | None = None) -> SpotResult | None:
    """Check the values of a few tenders against their pages with one model call."""
    if not pages:
        steps.add(StepKind.note, "spot_check", "The spot check had no tender page to read, so it was not done.",
                  error="no pages")
        return None
    models = models or ModelSettings.from_env()
    parts = [f"Why this check runs: {finding}" if finding else "A check asked for a look at these values."]
    for page in pages:
        parts.append(f"=== Tender {page.tender_id} ({page.url}) ===\n"
                     f"Values the program read:\n{json.dumps(page.values, ensure_ascii=False, indent=1)}\n"
                     f"The page's text:\n{page.text}")
    outcome = runner.run(job="check", model=models.check, prompt=load_prompt("check"), task="\n\n".join(parts),
                         tools=(), answer_type=SpotAnswer, max_turns=1, max_usd=settings.check_max_usd,
                         steps=steps, reasoning=settings.reasoning_check, portal_id=portal_id)
    if not isinstance(outcome.answer, SpotAnswer):
        return None
    wrong = judge(pages, outcome.answer)
    total = sum(len(page.values) for page in pages)
    if wrong:
        message = (f"The spot check found {len(wrong)} of {total} value(s) on {len(pages)} tender page(s) that "
                   f"the page does not confirm, for example {wrong[0]}.")
    else:
        message = f"The spot check confirmed all {total} value(s) on {len(pages)} tender page(s) against the page text."
    steps.add(StepKind.decision, "spot_check", message, error=None if not wrong else "values not confirmed")
    return SpotResult(passed=not wrong, message=message, wrong=wrong, usage=outcome.usage,
                      model_calls=outcome.model_calls)
