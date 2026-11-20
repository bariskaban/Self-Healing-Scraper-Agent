# Q5. Agent framework and conventions

Owner: Baris · Status: **answered** in [q05-q07-q08-framework-schemas-benchmark.md](q05-q07-q08-framework-schemas-benchmark.md)

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

**Build the learn, repair and spot-check agents on the OpenAI Agents SDK**, with our own tools and Pydantic output types; our own loop on the `openai` package is the fallback.

The full answer, its alternatives and sources are in [q05-q07-q08-framework-schemas-benchmark.md](q05-q07-q08-framework-schemas-benchmark.md) and `CONVENTIONS.md`. The end check is in [audit.md](audit.md).

## Inputs from answered questions

- **Q6:** all four candidates exist for Python; PydanticAI exists only for Python. See [q06-language.md](q06-language.md).
- **Audit of Q9:** the advice to use the Responses API stands, but the reason differs by model: the `gpt-6.1` pages say tool calling requires it; for `gpt-6-sol` and `gpt-6-luna` Chat Completions accepts tool calls only at reasoning "none". See [audit.md](audit.md).
- **Audit of Q9:** a learn loop that appends every tool result to one conversation costs about $7.74 on `gpt-6.2-sol`, against $1.68 if each call stays at 30K input. Whatever framework is chosen must make trimming the context easy.
