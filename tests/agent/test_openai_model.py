"""The OpenAI client of the runner, on a transport that answers in this process.

No request leaves the process and no key exists: the API is stood in for by `httpx.MockTransport`.
Run: pytest tests/agent/test_openai_model.py
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.agent.runner import ModelError, OpenAIModel, Said, Tool
from app.agent.settings import AgentSettings

ANSWER = {
    "id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-6.2-sol-2026-11-17", "status": "completed",
    "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
    "output": [
        {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "sealed"},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "open_page",
         "arguments": "{\"url\": \"/\"}", "status": "completed"},
    ],
    "usage": {"input_tokens": 1200, "input_tokens_details": {"cached_tokens": 200}, "output_tokens": 300,
              "output_tokens_details": {"reasoning_tokens": 250}, "total_tokens": 1500},
}
FINAL = {**ANSWER, "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                               "content": [{"type": "output_text", "text": "{\"done\": true}", "annotations": []}]}]}
TOOL = Tool("open_page", "Open a page.", {"type": "object", "properties": {"url": {"type": "string"}},
                                          "required": ["url"], "additionalProperties": False},
            lambda args: Said("", ""))


def model(answer: dict | int, sent: list) -> OpenAIModel:
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append((request, json.loads(request.content)))
        if isinstance(answer, int):
            return httpx.Response(answer, json={"error": {"message": "Incorrect API key provided.", "type": "x"}})
        return httpx.Response(200, json=answer)

    return OpenAIModel("test-key", AgentSettings(model_retries=0),
                       http_client=httpx.Client(transport=httpx.MockTransport(handle)))


def test_a_call_names_the_model_sends_strict_tools_and_reads_tool_calls_and_usage():
    sent: list = []
    reply = model(ANSWER, sent).respond(
        model="gpt-6.2-sol", instructions="Learn the portal.", input=[{"role": "user", "content": "the task"}],
        tools=[TOOL], answer=("LearnAnswer", {"type": "object", "properties": {}, "required": [],
                                              "additionalProperties": False}), reasoning="medium",
        cache_key="learn-run1")
    request, body = sent[0]
    assert request.url.path.endswith("/responses") and len(sent) == 1
    assert body["model"] == "gpt-6.2-sol" and body["instructions"] == "Learn the portal."
    assert body["store"] is False and body["include"] == ["reasoning.encrypted_content"]
    assert body["reasoning"] == {"effort": "medium"}
    assert body["prompt_cache_key"] == "learn-run1"
    assert body["tools"] == [{"type": "function", "name": "open_page", "description": "Open a page.",
                              "parameters": TOOL.parameters, "strict": True}]
    assert body["text"]["format"]["type"] == "json_schema" and body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["name"] == "LearnAnswer"

    (call,) = reply.calls
    assert (call.call_id, call.name, json.loads(call.arguments)) == ("call_1", "open_page", {"url": "/"})
    # The reasoning item goes back with the tool call it belongs to.
    assert [item["type"] for item in reply.items] == ["reasoning", "function_call"]
    assert reply.items[0]["encrypted_content"] == "sealed"
    usage = reply.usage
    assert (usage.input_tokens, usage.cached_input_tokens, usage.output_tokens, usage.reasoning_tokens) == \
           (1200, 200, 300, 250)


def test_a_final_answer_is_read_as_text_and_a_call_without_tools_asks_for_no_reasoning_items():
    sent: list = []
    reply = model(FINAL, sent).respond(model="gpt-6-luna", instructions="Check.", input=[], tools=[], answer=None,
                                       reasoning=None)
    assert reply.text == '{"done": true}' and reply.calls == []
    body = sent[0][1]
    assert "tools" not in body and "include" not in body and "reasoning" not in body and "text" not in body and "prompt_cache_key" not in body


def test_an_api_error_becomes_a_model_error_that_does_not_carry_the_key():
    with pytest.raises(ModelError) as raised:
        model(401, []).respond(model="gpt-6.2-sol", instructions="", input=[], tools=[], answer=None, reasoning=None)
    assert "AuthenticationError" in str(raised.value) and "test-key" not in str(raised.value)
