"""The runner: the only place that calls a model (CONVENTIONS.md, "Agent framework"; CLAUDE.md).

One run is a loop of model calls and tool calls that ends in a validated answer:

  * the model and the cap on calls are named on every run;
  * what each call sends is trimmed: the task, the one-line summaries of the steps that no
    longer fit, and the newest steps in full, so the input stays under `context_tokens`; steps
    are dropped in batches, so that between two batches the prompt cache keeps hitting;
  * the budget (calls and USD) is checked between model calls, outside the tools, and a spent
    budget stops the run;
  * a final answer that does not validate goes back once with the validation message; a second
    failure ends the run (CONVENTIONS.md, rule 10);
  * usage is priced per request (the long-context rate is per request) by the configured model
    name, and every model call and tool call is logged as an `AgentStep`.

A run never raises for what the model or a tool does: it returns an `Outcome` whose `answer`
is None, with the reason in `stopped`.

Framework. This is our own loop on the Responses API, the fallback CONVENTIONS.md names: the
Agents SDK neither trims the context, nor stops on a budget, nor retries an invalid answer
(audit of Q5), and those three are most of what a runner does. `OpenAIModel` is the only code
that imports `openai`; tests hand the runner a model of their own.
"""
from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from app import logs
from app.agent.settings import DEFAULT_AGENT_SETTINGS, AgentSettings
from app.config import cost_usd
from app.models import AgentStep, StepKind, TokenUsage

log = logs.get("agent")

PROMPTS_DIR = Path(__file__).parent / "prompts"


# == Prompts ==

@dataclass(frozen=True)
class Prompt:
    """A prompt read from `prompts/<job>_<name>.md`. Its first line is `version: N`."""

    id: str    # e.g. learn/system@3, logged on every model step
    text: str


def load_prompt(job: str, name: str = "system") -> Prompt:
    raw = (PROMPTS_DIR / f"{job}_{name}.md").read_text(encoding="utf-8")
    first, _, rest = raw.partition("\n")
    if not first.lower().startswith("version:"):
        raise ValueError(f"prompt {job}_{name}.md must start with a line `version: N`")
    return Prompt(id=f"{job}/{name}@{first.split(':', 1)[1].strip()}", text=rest.strip())


# == What a model and a tool are, to the runner ==

@dataclass(frozen=True)
class Said:
    """A tool's answer: the text the model reads, and one line for the operator."""

    text: str
    summary: str


@dataclass(frozen=True)
class Tool:
    """One tool the model may call. `parameters` is a JSON schema that fits strict function calling."""

    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any]], Said]


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # JSON text, as the model wrote it


@dataclass
class ModelReply:
    """One answer of the model. `items` are its output items as the API wants them back."""

    items: list[dict[str, Any]]
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)  # cost_usd is set by the runner


class ModelError(Exception):
    """A model call that got no usable answer, after the client's own retries.

    `rate_limited` says the API refused it for the rate limit (HTTP 429); `retry_after` is the
    wait in seconds the API named, when it named one."""

    def __init__(self, message: str, *, rate_limited: bool = False, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.rate_limited, self.retry_after = rate_limited, retry_after


class Model(Protocol):
    def respond(self, *, model: str, instructions: str, input: list[dict[str, Any]],
                tools: Sequence[Tool], answer: tuple[str, dict[str, Any]] | None,
                reasoning: str | None, cache_key: str | None = None) -> ModelReply:
        """One model call. `cache_key` is the same for every call of a run: it keeps them on one prompt cache. `answer` is the name and JSON schema the final answer must fit.
        Raises ModelError when no answer came."""
        ...


# == Strict schemas ==

def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The JSON schema of a Pydantic model, as OpenAI's strict output accepts it.

    Pydantic writes a description next to a `$ref`; strict output allows no keyword beside one.
    Everything else is the model's business: every field required, no unknown keys, no defaults
    (`tests/recipe/test_recipe_schema.py` holds the recipe to that).
    """
    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return {"$ref": node["$ref"]}
            return {key: clean(value) for key, value in node.items()}
        if isinstance(node, list):
            return [clean(value) for value in node]
        return node

    return clean(model.model_json_schema())


# == Steps ==

class StepLog:
    """Writes a run's agent steps, numbered after the steps the run already has.

    `write` is `Database.add_step`; `first` is the number of the first step written here. The
    reader counts its own steps, so it reads `next` back after an agent ran (two steps with one
    number are an IntegrityError).
    """

    def __init__(self, run_id: str, write: Callable[[AgentStep], None] | None = None, first: int = 1,
                 preview_chars: int = DEFAULT_AGENT_SETTINGS.step_preview_chars) -> None:
        self.run_id, self._write, self.next, self._preview = run_id, write, first, preview_chars
        self.steps: list[AgentStep] = []

    @classmethod
    def on_database(cls, database: Any, run_id: str, settings: AgentSettings = DEFAULT_AGENT_SETTINGS) -> "StepLog":
        taken = [step.seq for step in database.list_steps(run_id)]
        return cls(run_id, database.add_step, first=max(taken, default=0) + 1,
                   preview_chars=settings.step_preview_chars)

    def _cut(self, text: str | None) -> str | None:
        if text is None or len(text) <= self._preview:
            return text
        return text[: self._preview] + f" … ({len(text)} characters)"

    def add(self, kind: StepKind, name: str, summary: str, *, prompt_id: str | None = None,
            args: dict[str, Any] | None = None, result: str | None = None, duration_ms: int | None = None,
            usage: TokenUsage | None = None, error: str | None = None) -> AgentStep:
        if args is not None:
            args = {key: self._cut(value) if isinstance(value, str) else
                    (value if isinstance(value, (int, float, bool, type(None))) else self._cut(json.dumps(value)))
                    for key, value in args.items()}
        step = AgentStep(run_id=self.run_id, seq=self.next, kind=kind, name=name, summary=_one_line(summary),
                         prompt_id=prompt_id, args=args, result=self._cut(result), duration_ms=duration_ms,
                         usage=usage, error=error)
        self.next += 1
        self.steps.append(step)
        if self._write is not None:
            try:
                self._write(step)
            except Exception:  # a step that cannot be stored must not end the run (the portal may be gone)
                log.exception("agent step could not be stored")
        return step


def _one_line(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# == One run ==

@dataclass
class Outcome:
    """What a run came to. `answer` is None when it gave none; `stopped` then says why."""

    answer: BaseModel | None
    stopped: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    model_calls: int = 0
    unpriced: bool = False  # the model has no price in the table: `usage.cost_usd` misses its calls
    rate_limited: bool = False  # the run ended because the API's rate limit did not pass in time


@dataclass
class _Turn:
    """One model call and what followed it: the items to send back, and a line per step."""

    items: list[dict[str, Any]]
    lines: list[str]


class Runner:
    """Runs agents on one model client. One instance for the process; `run` blocks."""

    def __init__(self, model: Model, settings: AgentSettings = DEFAULT_AGENT_SETTINGS,
                 sleep: Callable[[float], None] = time.sleep,
                 chance: Callable[[], float] = random.random) -> None:
        self.model, self.settings, self._sleep, self._chance = model, settings, sleep, chance
        # Says whether a portal still exists. Set by `Agents`: a run for a deleted portal stops at its next call.
        self.alive: Callable[[str], bool] | None = None

    def _respond(self, steps: StepLog, job: str, **request: Any) -> ModelReply:
        """One model call. A rate limit is waited out and the call tried again, until the waiting
        for this call has taken `rate_limit_wait_budget_seconds`: several portals learning at once
        share one limit of tokens a minute, and a learn must not die of that."""
        settings, waits, waited = self.settings, 0, 0.0
        while True:
            try:
                return self.model.respond(**request)
            except ModelError as error:
                left = settings.rate_limit_wait_budget_seconds - waited
                if not error.rate_limited or left <= 0:
                    raise
                waits += 1
                ours = min(settings.rate_limit_wait_seconds * 2 ** (waits - 1), settings.rate_limit_wait_max_seconds)
                pause = max(error.retry_after or 0.0, ours)
                pause = min(pause * (1 + settings.rate_limit_wait_jitter * self._chance()), left)
                waited += pause
                steps.add(StepKind.note, f"{job}_rate_limited",
                          f"The model's rate limit was reached; waiting {pause:.0f} s before trying again "
                          f"({waited:.0f} of at most {settings.rate_limit_wait_budget_seconds:.0f} s of waiting).")
                self._sleep(pause)

    def _size(self, items: Sequence[dict[str, Any]]) -> int:
        """About how many tokens these items are as input."""
        return int(sum(len(json.dumps(item, ensure_ascii=False)) for item in items) / self.settings.chars_per_token)

    def _keep_from(self, task: str, turns: Sequence[_Turn], dropped: int) -> int:
        """How many of the oldest turns are sent as one line each from now on.

        Turns are dropped in batches: nothing changes while the input fits `context_tokens`, and
        when it no longer does, enough turns go to bring it down to `context_keep_share` of that.
        Between two batches every call's input is the one before it with more at the end, so
        the prompt cache keeps hitting; a prefix that changed on every call would never hit.
        """
        room = self.settings.context_tokens - self._size([{"role": "user", "content": task}])
        sizes = [self._size(turn.items) for turn in turns]
        if sum(sizes[dropped:]) <= room:
            return dropped
        target = room * self.settings.context_keep_share
        while dropped < len(turns) - 1 and sum(sizes[dropped:]) > target:  # the newest turn always goes in whole
            dropped += 1
        return dropped

    def _input(self, task: str, turns: Sequence[_Turn], dropped: int) -> list[dict[str, Any]]:
        """The task, a summary of the first `dropped` steps, and the steps after them in full."""
        out: list[dict[str, Any]] = [{"role": "user", "content": task}]
        if dropped:
            lines = [line for turn in turns[:dropped] for line in turn.lines]
            out.append({"role": "user", "content":
                        "Your earlier steps in this run, shortened to save context (the pages you opened are "
                        "still cached, and the working recipe is kept: use the tools to see them again):\n"
                        + "\n".join(f"- {line}" for line in lines)})
        for turn in turns[dropped:]:
            out += turn.items
        return out

    def run(self, *, job: str, model: str, prompt: Prompt, task: str, tools: Sequence[Tool],
            answer_type: type[BaseModel], max_turns: int, max_usd: float | None, steps: StepLog,
            reasoning: str | None = None, portal_id: str | None = None) -> Outcome:
        """Run one agent to its answer. Never raises for what the model or a tool does."""
        out = Outcome(answer=None)
        log.debug("%s starts for portal %s: model %s, up to %d call(s)%s, %d tool(s), prompt %s", job, portal_id, model,
                  max_turns, f" and ${max_usd:.2f}" if max_usd is not None else "", len(tools), prompt.id)
        by_name = {tool.name: tool for tool in tools}
        answer = (answer_type.__name__, strict_schema(answer_type))
        turns: list[_Turn] = []
        dropped = 0
        retried = False
        cache_key = f"{job}-{steps.run_id}"[:64]  # one cache route per run

        def stop(reason: str) -> Outcome:
            out.stopped = reason
            steps.add(StepKind.decision, f"{job}_stopped", f"The {job} run stopped: {reason}", error=reason)
            self._log(job, portal_id, steps.run_id, "stopped", reason=reason, model_calls=out.model_calls,
                      cost_usd=round(out.usage.cost_usd, 6))
            return out

        while True:
            if portal_id and self.alive is not None and not self.alive(portal_id):
                return stop("the portal was deleted")
            if out.model_calls >= max_turns:
                return stop(f"its budget of {max_turns} model calls is spent")
            if max_usd is not None and out.usage.cost_usd >= max_usd:
                return stop(f"its budget of ${max_usd:.2f} is spent")
            began = time.monotonic()
            try:
                dropped = self._keep_from(task, turns, dropped)
                reply = self._respond(steps, job, model=model, instructions=prompt.text,
                                      input=self._input(task, turns, dropped), tools=tools, answer=answer,
                                      reasoning=reasoning or None, cache_key=cache_key)
            except ModelError as error:
                out.rate_limited = error.rate_limited
                return stop(f"the model call failed: {error}")
            took = int((time.monotonic() - began) * 1000)
            out.model_calls += 1
            usage = reply.usage
            # Priced per request and by the configured name: the API may answer with a dated
            # snapshot name the table does not hold, and the long-context rate is per request.
            cost = cost_usd(model, usage.input_tokens, usage.output_tokens, usage.cached_input_tokens)
            if cost is None:
                out.unpriced = True
            usage = usage.model_copy(update={"cost_usd": cost or 0.0})
            out.usage = out.usage.add(usage)
            did = (f"it called {', '.join(call.name for call in reply.calls)}" if reply.calls
                   else "it gave its answer")
            steps.add(StepKind.llm, model, f"Asked {model} (call {out.model_calls} of at most {max_turns}): {did}.",
                      prompt_id=prompt.id, duration_ms=took, usage=usage,
                      result=reply.text or None)
            self._log(job, portal_id, steps.run_id, "model_call", model=model, call=out.model_calls,
                      input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                      cached_input_tokens=usage.cached_input_tokens, cost_usd=round(usage.cost_usd, 6), ms=took)

            turn = _Turn(items=list(reply.items), lines=[])
            turns.append(turn)
            if reply.calls:
                for call in reply.calls:
                    said = self._call(by_name, call, steps)
                    turn.items.append({"type": "function_call_output", "call_id": call.call_id, "output": said.text})
                    turn.lines.append(said.summary)
                left = max_turns - out.model_calls
                if left <= 2:
                    turn.items.append({"role": "user", "content":
                                       f"{left} model call(s) are left in this run's budget. Give your final "
                                       "answer now, with what you have."})
                continue

            try:
                out.answer = answer_type.model_validate_json(reply.text)
            except ValidationError as error:
                message = _validation_message(error)
                log.warning("%s: the final answer did not validate%s: %s", job, " (second time)" if retried else "",
                            logs.clip(message, 200))
                if retried:
                    return stop(f"its final answer was invalid twice: {message}")
                retried = True
                steps.add(StepKind.note, f"{job}_invalid_answer",
                          f"The model's final answer did not validate; sent back once: {message}", error=message)
                turn.items.append({"role": "user", "content":
                                   "Your final answer is not valid. Send it again, corrected, as JSON that fits "
                                   f"the schema. What is wrong:\n{message}"})
                turn.lines.append(f"Gave a final answer that was not valid: {message}")
                continue
            self._log(job, portal_id, steps.run_id, "answered", model_calls=out.model_calls,
                      cost_usd=round(out.usage.cost_usd, 6))
            return out

    def _call(self, tools: dict[str, Tool], call: ToolCall, steps: StepLog) -> Said:
        began = time.monotonic()
        args: dict[str, Any] | None = None
        error: str | None = None
        tool = tools.get(call.name)
        if tool is None:
            said = Said(f"There is no tool named {call.name}. The tools are: {', '.join(sorted(tools))}.",
                        f"{call.name}: no such tool")
            error = "no such tool"
        else:
            try:
                args = json.loads(call.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("the arguments must be a JSON object")
                said = tool.run(args)
            except Exception as problem:  # a tool's fault goes back to the model; it never ends the run
                error = f"{type(problem).__name__}: {problem}"
                said = Said(f"The call failed: {_one_line(str(problem), 1500)}",
                            f"{call.name} failed: {_one_line(str(problem), 120)}")
        steps.add(StepKind.tool, call.name, said.summary, args=args if isinstance(args, dict) else None,
                  result=said.text, duration_ms=int((time.monotonic() - began) * 1000), error=error)
        (log.warning if error else log.debug)("tool %s(%s) took %d ms, %d chars back%s: %s", call.name,
                                              logs.clip(logs.safe_mapping(args), 140), int((time.monotonic() - began) * 1000),
                                              len(said.text), f", ERROR {logs.clip(error, 100)}" if error else "",
                                              logs.clip(said.summary, 160))
        return said

    @staticmethod
    def _log(job: str, portal_id: str | None, run_id: str, event: str, **more: Any) -> None:
        # JSON lines with portal_id and run_id (CONVENTIONS.md, rule 12). No key, no prompt, no page.
        log.info(json.dumps({"event": f"agent.{event}", "job": job, "portal_id": portal_id, "run_id": run_id, **more}))


def _validation_message(error: ValidationError, limit: int = 12) -> str:
    lines = []
    for fault in error.errors()[:limit]:
        where = ".".join(str(part) for part in fault["loc"]) or "the answer"
        lines.append(f"{where}: {fault['msg']}")
    more = len(error.errors()) - limit
    return "; ".join(lines) + (f"; and {more} more" if more > 0 else "")


# == The OpenAI client ==

class OpenAIModel:
    """`Model` on OpenAI's Responses API. The only code that imports `openai` (CLAUDE.md).

    Nothing is stored on OpenAI's side (`store=False`): the runner owns the conversation and
    sends what it kept, so the encrypted reasoning items are asked for and passed back with the
    tool calls they belong to. The key is read by the caller and never logged.
    """

    def __init__(self, api_key: str, settings: AgentSettings = DEFAULT_AGENT_SETTINGS, *,
                 http_client: Any = None) -> None:
        from openai import OpenAI  # imported here, so the app starts without a key and without a call

        # `http_client` is for tests: an httpx client on a transport that answers in the process.
        self._client = OpenAI(api_key=api_key, timeout=settings.model_timeout_seconds,
                              max_retries=settings.model_retries, http_client=http_client)

    def respond(self, *, model: str, instructions: str, input: list[dict[str, Any]],
                tools: Sequence[Tool], answer: tuple[str, dict[str, Any]] | None,
                reasoning: str | None, cache_key: str | None = None) -> ModelReply:
        import openai

        request: dict[str, Any] = {"model": model, "instructions": instructions, "input": input, "store": False}
        if tools:
            request["tools"] = [{"type": "function", "name": tool.name, "description": tool.description,
                                 "parameters": tool.parameters, "strict": True} for tool in tools]
            request["include"] = ["reasoning.encrypted_content"]
        if answer is not None:
            request["text"] = {"format": {"type": "json_schema", "name": answer[0], "schema": answer[1],
                                          "strict": True}}
        if reasoning:
            request["reasoning"] = {"effort": reasoning}
        if cache_key:
            request["prompt_cache_key"] = cache_key
        log.debug("model request: %s, %d input item(s), %d tool(s), reasoning=%s, instructions %d chars", model,
                  len(input), len(tools), reasoning, len(instructions))
        began = time.monotonic()
        try:
            response = self._client.responses.create(**request)
        except openai.RateLimitError as error:
            wait = None
            try:
                wait = float(error.response.headers.get("retry-after") or "")
            except (AttributeError, ValueError):
                pass
            raise ModelError(f"RateLimitError: {_one_line(str(error), 300)}", rate_limited=True,
                             retry_after=wait) from None
        except openai.OpenAIError as error:
            log.warning("model request failed after %.1fs: %s", time.monotonic() - began, type(error).__name__)
            # The message of an API error names the fault, never the key.
            raise ModelError(f"{type(error).__name__}: {_one_line(str(error), 300)}") from None
        items = [item.to_dict() for item in response.output]
        calls = [ToolCall(call_id=item["call_id"], name=item["name"], arguments=item.get("arguments") or "{}")
                 for item in items if item.get("type") == "function_call"]
        used = response.usage
        usage = TokenUsage()
        if used is not None:
            cached = getattr(used.input_tokens_details, "cached_tokens", 0) or 0
            thought = getattr(used.output_tokens_details, "reasoning_tokens", 0) or 0
            usage = TokenUsage(input_tokens=used.input_tokens, cached_input_tokens=min(cached, used.input_tokens),
                               output_tokens=used.output_tokens, reasoning_tokens=thought)
        return ModelReply(items=items, text=response.output_text or "", calls=calls, usage=usage)
