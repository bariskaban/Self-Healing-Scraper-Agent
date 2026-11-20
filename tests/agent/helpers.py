"""Stand-ins for the agent's tests: a model that follows a script, and the mock portal as a network layer."""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.agent.runner import ModelError, ModelReply, ToolCall
from app.checks import Answer
from app.fetch.interface import Fetched
from app.models import Portal, TokenUsage, url_key
from mock_portal import MockPortal

URL = "https://mock.example"


def portal(url: str = URL) -> Portal:
    return Portal(id="p1", url=url, url_key=url_key(url))


def call(name: str, **arguments: Any) -> tuple[str, dict]:
    return name, arguments


class ScriptedModel:
    """Answers each model call with the next entry of its script.

    An entry is a list of `call(...)` (tool calls), a string or dict (the final answer), an
    exception to raise, or a function of the request that returns one of those. `requests`
    keeps what each call was sent.
    """

    def __init__(self, script: list[Any], usage: TokenUsage | None = None) -> None:
        self.script = list(script)
        self.usage = usage or TokenUsage(input_tokens=1000, cached_input_tokens=200, output_tokens=100)
        self.requests: list[dict[str, Any]] = []

    def respond(self, *, model, instructions, input, tools, answer, reasoning) -> ModelReply:
        self.requests.append({"model": model, "instructions": instructions, "input": input,
                              "tools": [tool.name for tool in tools], "answer": answer, "reasoning": reasoning})
        if not self.script:
            raise ModelError("the script is at its end")
        entry = self.script.pop(0)
        if callable(entry):
            entry = entry(self.requests[-1])
        if isinstance(entry, Exception):
            raise entry
        number = len(self.requests)
        if isinstance(entry, list):
            calls = [ToolCall(call_id=f"call_{number}_{i}", name=name, arguments=json.dumps(arguments))
                     for i, (name, arguments) in enumerate(entry)]
            items = [{"type": "function_call", "call_id": c.call_id, "name": c.name, "arguments": c.arguments}
                     for c in calls]
            return ModelReply(items=items, calls=calls, usage=self.usage)
        text = entry if isinstance(entry, str) else json.dumps(entry)
        return ModelReply(items=[{"type": "message", "role": "assistant",
                                  "content": [{"type": "output_text", "text": text}]}], text=text, usage=self.usage)


class MockFetch:
    """The `fetch` of the network layer on a `MockPortal`: no socket, no clock."""

    def __init__(self, mock: MockPortal | None = None) -> None:
        self.mock = mock or MockPortal(tenders=12, page_size=5)
        self.asked: list[tuple[str, str]] = []

    def fetch(self, portal_id, url, *, method="GET", params=None, data=None, json=None, headers=None,
              page_load=True) -> Fetched:
        address = str(httpx.URL(url, params=params)) if params else url
        self.asked.append((method, address))
        status, head, body = self.mock.respond(method, address, data)
        return Fetched(url=address, final_url=address, status=status, headers=httpx.Headers(head), body=body,
                       answer=Answer(status=status, page_load=page_load))
