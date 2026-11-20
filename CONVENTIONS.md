# Watchtower conventions (Q5)

## Agent framework
* **OpenAI Agents SDK** (`pip install openai-agents`) for learn, repair and spot-check agents.
  * Tools: plain async Python functions with `@function_tool`.
  * Final answer: `output_type=<Pydantic model>`, so every agent returns a validated object (LearnResult, RepairResult, SpotCheck).
  * Step cap: `Runner.run(agent, input, max_turns=N)` always set explicitly.
  * Usage: `result.context_wrapper.usage` (requests, input/output tokens, per-request entries). Copy it into `TokenUsage` and the `runs` row.
* Token or euro cap per run: the SDK caps turns, not tokens. Our tools check the run's running total and stop the run when the budget is gone.
* Fallback if the SDK gets in the way: our own loop on `openai` (Responses API with tool calls plus `responses.parse` for the final Pydantic object). Same tools, same logging. About 150 lines.
* Nobody imports `openai` outside `app/agent/`. Every model call goes through `app/agent/runner.py`.

## Project layout
```
app/
  main.py            FastAPI: API, dashboard (GET /), /files/{file_id}
  models.py          all records (Q7), schema.sql
  db.py              SQLite access, the only place with SQL
  scheduler.py       periodic reads (Q13), rechecks (Q14), refresh
  state.py           checks -> state + reason (Q10)
  fetch/             THE network choke point: rate limiter, httpx, Playwright, record/replay
  recipe/            recipe format (Q1) and the executor (no model calls, ever)
  extract/           normalizers: dates + timezones, CPV, enums, ids
  docs/              downloads, ZIP unpacking, sha256, size limits
  checks/            validators, one function per check, each returns CheckResult
  agent/
    runner.py        wraps Runner.run: budgets, usage, AgentStep logging
    tools.py         tools the model may call (Q4)
    learn.py repair.py spotcheck.py
    prompts/         one .md file per prompt
  dashboard/         templates + static
bench/               benchmark harness and scorer (Q8)
mock_portal/         the portal we break on purpose
tests/fixtures/      recorded traffic per portal
```

## Rules
1. **One choke point for the network.** Every request (httpx and every browser sub-request via `page.route`) goes through `fetch/`, which enforces 1 request/second per host, logs it, and records or replays it. Block images, fonts, media and stylesheets in the browser.
2. **Regular reads never call a model.** `runs.model_calls` must be 0 for `kind=read` after attach. A test asserts this.
3. **Null over guess.** A normalizer that is not sure returns `None` and writes the raw value to `raw`.
4. **All datetimes are aware.** Store with offset. Deadlines keep the portal's local offset (zone from `portals.timezone`). Our own timestamps are UTC (`+00:00`).
5. **Prompts live in files** (`agent/prompts/learn_system.md` etc.), with a version line at the top. Log `prompt_id` like `learn/system@3` on every LLM step.
6. **Models and prices come from config**, never hard-coded in logic: `MODEL_LEARN`, `MODEL_REPAIR`, `MODEL_CHECK`, `OPENAI_API_KEY`. The price table sits in `app/config.py`, with the date it was copied from OpenAI's pricing page (Q9).
7. **Budgets** (starting values, tune with the benchmark): learn 40 turns, repair 20 turns, spot-check 1 call. Pages shown to the model are cut to a fixed token budget, never raw HTML.
8. **Timeouts and retries.** HTTP: connect 10 s, read 30 s. Browser navigation: 30 s. Model call: 120 s. Retry only timeouts, 5xx and 429 (honour Retry-After), at most 2 times with backoff. Retries count toward the rate limit. Downloads stream to disk; stop at 250 MB and mark `too_large`.
9. **Every step is logged** as an `AgentStep` with a one-line `summary` an operator understands. The dashboard reads only this table for "what the system did".
10. **Structured output errors** go back to the model once with the validation message. A second failure ends the run as `failed`.
11. **Tests replay, never hit live portals.** `FETCH_MODE=record|replay|live`. Executor and checks are tested offline on `tests/fixtures/`. Live portals only in `bench/`, by hand.
12. **Logs** are JSON lines on stdout, each with `portal_id` and `run_id`.
13. **Main always builds.** Small PRs; `docker build .` for linux/amd64 must pass before merging.
