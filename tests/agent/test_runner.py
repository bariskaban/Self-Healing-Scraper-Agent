"""The runner on a scripted model: budgets, trimming, the one retry, usage and steps.

No test here calls the OpenAI API. Run: pytest tests/agent/test_runner.py
"""
from __future__ import annotations

import json
import sys

import pytest
from pydantic import BaseModel, ConfigDict

from app.agent.runner import ModelError, Runner, Said, StepLog, Tool, load_prompt, strict_schema
from app.agent.settings import AgentSettings
from app.config import cost_usd
from app.models import StepKind, TokenUsage
from app.recipe.schema import AuthoredRecipe
from tests.agent.helpers import ScriptedModel, call


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    done: bool
    summary: str


PROMPT = load_prompt("learn")
GOOD = {"done": True, "summary": "ok"}


def echo(size: int = 10) -> Tool:
    def run(args: dict) -> Said:
        if args.get("text") == "boom":
            raise RuntimeError("the tool broke")
        return Said("x" * size, f"echoed {args.get('text')}")
    return Tool("echo", "says x", {"type": "object", "properties": {"text": {"type": "string"}},
                                   "required": ["text"], "additionalProperties": False}, run)


def run(model, *, settings=AgentSettings(), max_turns=10, max_usd=None, tools=None, name="gpt-6.2-sol"):
    steps = StepLog("run1")
    out = Runner(model, settings).run(job="learn", model=name, prompt=PROMPT, task="the task",
                                      tools=tools if tools is not None else [echo()], answer_type=Answer,
                                      max_turns=max_turns, max_usd=max_usd, steps=steps, reasoning="medium")
    return out, steps


def test_a_run_ends_in_a_validated_answer_and_logs_every_step():
    model = ScriptedModel([[call("echo", text="a")], GOOD])
    out, steps = run(model)
    assert out.answer == Answer(done=True, summary="ok") and out.stopped is None and out.model_calls == 2
    kinds = [(step.kind, step.name) for step in steps.steps]
    assert kinds == [(StepKind.llm, "gpt-6.2-sol"), (StepKind.tool, "echo"), (StepKind.llm, "gpt-6.2-sol")]
    assert [step.seq for step in steps.steps] == [1, 2, 3]
    llm = steps.steps[0]
    assert llm.prompt_id == PROMPT.id == "learn/system@1" and llm.usage.input_tokens == 1000
    assert "call 1 of at most 10" in llm.summary and "echo" in llm.summary
    assert steps.steps[1].summary == "echoed a" and steps.steps[1].args == {"text": "a"}
    # The model and the answer's schema are named on every call.
    assert all(r["model"] == "gpt-6.2-sol" and r["answer"][0] == "Answer" and r["reasoning"] == "medium"
               for r in model.requests)
    # The second call carries the tool call and its output back.
    kinds = [item.get("type") or item.get("role") for item in model.requests[1]["input"]]
    assert kinds == ["user", "function_call", "function_call_output"]


def test_usage_is_priced_per_request_by_the_configured_name():
    usage = TokenUsage(input_tokens=300_000, cached_input_tokens=0, output_tokens=1000)  # over the long-context line
    out, steps = run(ScriptedModel([[call("echo", text="a")], GOOD], usage=usage))
    one = cost_usd("gpt-6.2-sol", 300_000, 1000, 0)
    assert out.usage.cost_usd == pytest.approx(2 * one) and out.usage.input_tokens == 600_000
    assert one > cost_usd("gpt-6.2-sol", 600_000 // 4, 1000, 0) * 2  # a total priced as one request would differ
    assert steps.steps[0].usage.cost_usd == pytest.approx(one) and not out.unpriced


def test_a_model_without_a_price_is_said_to_be_unpriced_and_costs_nothing():
    out, _ = run(ScriptedModel([GOOD]), name="gpt-6.2-sol-2026-11-17")
    assert out.unpriced and out.usage.cost_usd == 0 and out.answer is not None


def test_the_turn_budget_stops_the_run_from_outside_the_tools():
    model = ScriptedModel([[call("echo", text=str(n))] for n in range(10)])
    out, steps = run(model, max_turns=3)
    assert out.answer is None and "3 model calls" in out.stopped and out.model_calls == 3
    assert len(model.requests) == 3
    assert steps.steps[-1].kind is StepKind.decision and steps.steps[-1].error
    # Near the end the model is told to finish.
    assert "left in this run's budget" in json.dumps(model.requests[-1]["input"])


def test_the_money_budget_stops_the_run():
    usage = TokenUsage(input_tokens=100_000, output_tokens=10_000)  # $0.30 a call on Sol
    model = ScriptedModel([[call("echo", text=str(n))] for n in range(10)], usage=usage)
    out, _ = run(model, max_usd=0.5, max_turns=10)
    assert out.answer is None and "$0.50" in out.stopped and out.model_calls == 2


def test_an_invalid_final_answer_goes_back_once_with_the_validation_message():
    model = ScriptedModel(['{"done": "perhaps"}', GOOD])
    out, steps = run(model)
    assert out.answer is not None and out.model_calls == 2
    sent_back = model.requests[1]["input"][-1]["content"]
    assert "not valid" in sent_back and "summary" in sent_back
    assert any(step.name == "learn_invalid_answer" for step in steps.steps)


def test_a_second_invalid_answer_ends_the_run_as_failed():
    model = ScriptedModel(["not json", '{"done": true}', GOOD])
    out, _ = run(model)
    assert out.answer is None and "invalid twice" in out.stopped and len(model.requests) == 2


def test_a_tool_that_raises_and_an_unknown_tool_go_back_to_the_model():
    model = ScriptedModel([[call("echo", text="boom"), call("nope")], GOOD])
    out, steps = run(model)
    assert out.answer is not None
    outputs = [item["output"] for item in model.requests[1]["input"] if item.get("type") == "function_call_output"]
    assert "the tool broke" in outputs[0] and "no tool named nope" in outputs[1]
    assert [step.error is not None for step in steps.steps if step.kind is StepKind.tool] == [True, True]


def test_a_failed_model_call_ends_the_run_without_raising():
    out, _ = run(ScriptedModel([ModelError("APITimeoutError: timed out")]))
    assert out.answer is None and "timed out" in out.stopped and out.model_calls == 0


def test_each_call_stays_near_the_context_budget_and_older_steps_become_one_line_each():
    settings = AgentSettings(context_tokens=3000)
    big = echo(size=7000)  # about 2,000 tokens a tool answer
    model = ScriptedModel([[call("echo", text=f"t{n}")] for n in range(8)] + [GOOD])
    out, _ = run(model, settings=settings, tools=[big], max_turns=20)
    assert out.answer is not None
    sizes = [len(json.dumps(r["input"])) / settings.chars_per_token for r in model.requests]
    assert max(sizes) < 2 * settings.context_tokens, sizes  # a context that grew would reach 16K here
    last = model.requests[-1]["input"]
    assert last[0] == {"role": "user", "content": "the task"}
    summary = last[1]["content"]
    assert "echoed t0" in summary and "echoed t5" in summary and "echoed t7" not in summary
    # What is sent stays well formed: every tool output follows its call.
    calls = {item["call_id"] for item in last if item.get("type") == "function_call"}
    outputs = {item["call_id"] for item in last if item.get("type") == "function_call_output"}
    assert calls == outputs and calls


def test_the_newest_step_is_sent_whole_even_when_it_alone_is_over_the_budget():
    settings = AgentSettings(context_tokens=500)
    model = ScriptedModel([[call("echo", text="a")], GOOD])
    run(model, settings=settings, tools=[echo(size=9000)])
    assert any(item.get("type") == "function_call_output" and len(item["output"]) == 9000
               for item in model.requests[1]["input"])


def test_steps_are_numbered_after_the_steps_a_run_already_has():
    steps = StepLog("run1", first=7)
    steps.add(StepKind.note, "x", "a  line\nwith breaks")
    assert steps.steps[0].seq == 7 and steps.steps[0].summary == "a line with breaks" and steps.next == 8


def test_the_recipe_schema_fits_strict_output_once_cleaned():
    def refs_with_siblings(node):
        if isinstance(node, dict):
            if "$ref" in node and len(node) > 1:
                yield node
            for value in node.values():
                yield from refs_with_siblings(value)
        elif isinstance(node, list):
            for value in node:
                yield from refs_with_siblings(value)

    assert list(refs_with_siblings(AuthoredRecipe.model_json_schema())), "pydantic writes a description beside a $ref"
    assert not list(refs_with_siblings(strict_schema(AuthoredRecipe)))


def test_importing_the_agent_does_not_import_openai_and_needs_no_key(monkeypatch):
    monkeypatch.delitem(sys.modules, "openai", raising=False)
    import app.agent  # noqa: F401
    from app.agent import Agents

    assert Agents.from_env(None, None, {}) is None and Agents.from_env(None, None, {"OPENAI_API_KEY": " "}) is None
    assert "openai" not in sys.modules


def test_nothing_outside_the_agent_imports_openai():
    from pathlib import Path

    root = Path(__file__).parents[2]
    for path in [*root.glob("app/**/*.py"), *root.glob("mock_portal/**/*.py"), *root.glob("bench/**/*.py")]:
        text = path.read_text(encoding="utf-8")
        if "import openai" in text or "from openai" in text:
            assert path.relative_to(root).as_posix() == "app/agent/runner.py", path
