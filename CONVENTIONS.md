# Watchtower conventions (Q5)

## Agent framework
* **Our own loop on OpenAI's Responses API**, in `app/agent/runner.py`, for the learn, repair and spot-check agents. The OpenAI Agents SDK was the first choice (Q5); its audit found that it neither trims the context, nor stops on a budget, nor retries an invalid answer, and those three are most of what a runner does.
  * Tools: plain Python functions wrapped as `Tool`, each with a strict JSON schema built from a Pydantic model (`strict_schema`).
  * Final answer: a small Pydantic model per job, sent as a strict `json_schema` format. The recipe itself is written through the tools (`propose_recipe`, `replace_node`) and counts only once its dry run passed.
  * Step cap: `max_turns` is set on every run, and the model is always named.
  * Usage: read from each response, priced per request by the configured model name, copied into `TokenUsage`, the agent steps and the `runs` row.
* Token or euro cap per run: the runner checks the running total between model calls and stops the run from outside the tools.
* Context: the runner trims what each call sends: the task, one line per older step, the newest steps in full. A learn whose context grows with every tool result costs about 4.6 times as much (audit of Q9).
* Nothing is stored on OpenAI's side (`store=False`); reasoning items go back with the tool calls they belong to.
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
    runner.py        the model loop: budgets, trimming, usage, AgentStep logging
    tools.py         tools the model may call (Q4)
    learn.py repair.py spotcheck.py
    prompts/         one .md file per prompt
  dashboard/         templates + static
bench/               benchmark harness and scorer (Q8)
mock_portal/         the portal we break on purpose
tests/fixtures/      recorded traffic per portal
```

## Rules
1. **One choke point for the network.** Every request (httpx and every browser sub-request via `context.route`) goes through `fetch/`, which enforces 1 request/second per portal (not per host: a portal's files often sit on a second host), logs it, and records or replays it. Redirect hops and WebSockets get past `page.route`: our client walks redirects itself, and WebSockets are blocked unless a recipe needs one. In the browser, block images, fonts, media, stylesheets and third-party origins, serve same-origin scripts from a cache after their first load, and turn service workers off (Q4 and its audit).
2. **Regular reads never call a model**, with one exception: a spot check when C3 (changed values) or C7 (structure) fires (Q10). `runs.model_calls` must be 0 for `kind=read` after attach unless one of those checks fired. A test asserts this.
3. **Null over guess.** A normalizer that is not sure returns `None` and writes the raw value to `raw`.
4. **All datetimes are aware.** Store with offset. Deadlines keep the portal's local offset (zone from `portals.timezone`). Our own timestamps are UTC (`+00:00`).
5. **Prompts live in files** (`agent/prompts/learn_system.md` etc.), with a version line at the top. Log `prompt_id` like `learn/system@3` on every LLM step.
6. **Models and prices come from config**, never hard-coded in logic: `MODEL_LEARN`, `MODEL_REPAIR`, `MODEL_CHECK`, `OPENAI_API_KEY`. The price table sits in `app/config.py`, with the date it was copied from OpenAI's pricing page (Q9).
7. **Budgets** (starting values, tune with the benchmark): learn 40 turns, repair 20 turns, spot-check 1 call. Pages shown to the model are trimmed HTML (DESIGN.md, Attach), never raw HTML, and each call's context stays near 30K input tokens.
8. **Timeouts and retries.** HTTP: connect 10 s, read 30 s. Browser navigation: 30 s. Model call: 120 s. Retry only timeouts, connection errors and HTTP 408, 500, 502, 503, 504, 520 to 524: at most 2 retries (3 tries) with randomised, growing pauses, obeying a `Retry-After` of up to 60 s (Q10, T1). A 429, or a 403 or 503 with `Retry-After`, halves the portal's request rate instead (Q10, T2). Retries count toward the rate limit. Downloads stream to disk; stop at 250 MB and mark `too_large`.
9. **Every step is logged** as an `AgentStep` with a one-line `summary` an operator understands. The dashboard reads only this table for "what the system did".
10. **Structured output errors** go back to the model once with the validation message. A second failure ends the run as `failed`.
11. **Tests replay, never hit live portals.** `FETCH_MODE=record|replay|live`. Executor and checks are tested offline on `tests/fixtures/`. Live portals only in `bench/`, run by a person, never by an agent (`CLAUDE.md`).
12. **Logs** are JSON lines on stdout, each with `portal_id` and `run_id`. Every module logs through `app/logs.py` (`logs.get("fetch")` is `watchtower.fetch`); `LOG_LEVEL=debug` (or `LOG_LEVEL_FETCH=debug` for one area) shows each request, check, decision and state change. The container sets `LOG_FORMAT=json`; locally the default is readable text. Never log a key, a page, a prompt or an answer in full: use `logs.clip` and `logs.safe_url`; a scrubber removes the key from every line as a last guard.
13. **Main always builds.** Small PRs; `docker build .` for linux/amd64 must pass before merging.
