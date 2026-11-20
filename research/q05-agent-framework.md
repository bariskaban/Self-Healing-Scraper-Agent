# Q5. Agent framework and conventions

Owner: teammate who took Q5, Q7 and Q8 · Status: **open, no answer in the repo yet**

## Question

Which framework do we build the agents on, and which conventions do we fix first?

Options: the OpenAI Python SDK with our own tool loop, the OpenAI Agents SDK, PydanticAI, LangGraph.

Judge on:
- Tool calling with OpenAI models.
- Structured outputs validated by Pydantic.
- Step and token budgets per run.
- Logging token usage per run (we must report cost per portal).
- Async support.
- How fast 3-4 people learn it in 24 hours.
- Docker footprint.

Also recommend conventions: project layout, prompts kept in files, timeouts and retries, logging every model call with its tokens, and tests that replay saved pages instead of hitting live portals.

Deliverable: a recommendation, plus a one-page conventions list we can paste into the repo.

## Answer

None yet. When it is written, it follows the answer standard in [README.md](README.md).
