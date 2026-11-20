# Q5, Q7 and Q8. Agent framework, schemas and benchmark

Owner: Baris. Researched 2026-11-20. Sources were checked on that date; library versions and docs change fast.

## Q5. Agent framework and conventions

**Recommendation.** Build the learn, repair and spot-check agents on the OpenAI Agents SDK, with our own tools and Pydantic output types. If the SDK gets in the way, fall back to our own ~150 line loop on the `openai` package with the same tools and logging.

**Options compared**
* **OpenAI Agents SDK** (chosen). Native to our provider. `Runner.run(..., max_turns=N)` caps the loop; with `output_type` set, the loop runs until the model returns an object matching that type, so final answers come back as validated Pydantic objects. Usage per run is in `result.context_wrapper.usage`, including a per-request breakdown, which is what we need for cost per portal. Pure Python, small Docker footprint, async.
  * Watch out: turn defaults are permissive, so always set `max_turns`. The SDK caps turns, not tokens; our tools enforce the token or euro budget themselves.
  * OpenAI usage semantics: cached tokens are included in input tokens, reasoning tokens in output tokens. Do not count them twice.
* **PydanticAI.** Strong second. `UsageLimits` caps requests, tool calls and tokens per run, and it is model-agnostic. Not chosen because the provider is fixed to OpenAI, so its main extra (portability) buys us little, and it is one more abstraction to learn.
* **LangGraph.** Graph orchestration with persistence. Too heavy to learn and debug in 24 hours for a loop this simple.
* **Own loop on the `openai` SDK.** Full control, nothing to learn, but we write tool dispatch, retries and usage bookkeeping ourselves. Kept as the fallback.

**Conventions.** See `CONVENTIONS.md`: project layout, one network choke point, no model calls in regular reads, prompts in files, models and prices in config, budgets, timeouts and retries, step logging, replay-only tests.

**Prototype first (about 1 hour).** One agent with two tools (fetch page, test a locator), `output_type` set to a small Pydantic model, `max_turns` set, usage copied into a `TokenUsage` row, all running inside our Docker image.

**Sources**
* OpenAI Agents SDK, usage tracking: https://openai.github.io/openai-agents-python/usage
* OpenAI Agents SDK on PyPI (loop, `max_turns`, `output_type`): https://pypi.org/p/openai-agents
* Agents SDK field guide (verified 2026-05-06; `max_turns` defaults are permissive): https://rkalani1.github.io/agent-builder-field-guide/platforms/openai-api/
* OpenAI token categories (cached in input, reasoning in output): https://developers.openai.com/api/docs/guides/agents-api/observability
* PydanticAI usage and `UsageLimits`: https://pydantic.dev/docs/ai/api/pydantic-ai/usage/
* PydanticAI spend limits: https://pydantic.dev/docs/ai/harness/spend/

## Q7. Schemas

**Recommendation.** Two layers in `app/models.py`. The API models produce the appendix answers exactly. The internal records map one to one onto the SQLite tables in `app/schema.sql`. Workstreams build against these now; only the recipe `body` waits for Q1.

**What is in it**
* API models: `PortalOut`, `RunOut`, `TenderOut`, `DocumentOut`, `PlaceOfPerformance`, plus request and answer bodies (`PortalCreate`, `CreatedId`, `RunAccepted`).
* Internal records: `Portal`, `Recipe` (versioned envelope with `parent_version`), `Run` (stats, tokens, cost, `model_calls`), `CheckResult` (severity decides the state), `AgentStep` (the dashboard trail), `PortalSnapshot` (pages, network log, last good ids for the repair oracle), `TenderRecord`, `FileRecord`, `TenderFile`.
* Tables: portals, recipes, runs, run_checks, agent_steps, snapshots, tenders, files, tender_files, plus a `portal_costs` view.

**Contract rules enforced in code**
* Required tender fields always present, `null` when not shown; optional fields left out when not shown.
* Datetimes always with an offset (`+01:00`, `+00:00`), never `Z`.
* CPV codes: 8 digits, check digit removed, duplicates dropped.
* Same address twice gives the same portal id (`url_key`).
* At most one running read per portal (unique index), so refresh returns that run's id.
* `closed` is computed at answer time from the deadline; a passing deadline also moves `lastChangedAt`, so `?changedSince=` picks it up.
* Files are stored once by content and linked to tenders by name. ZIPs are unpacked: only their members are delivered. Files over 250 MB are marked `too_large` and left out.

**Mapping to OCDS 1.1 and eForms** (also in the field descriptions)
* submissionDeadline: OCDS `tender.tenderPeriod.endDate`, eForms BT-131 Deadline Receipt Tenders.
* procedureType: OCDS `tender.procurementMethod`, eForms BT-105. Codes map as open → open, restricted → restricted, neg-w-call and neg-wo-call → negotiated, comp-dial, innovation, oth-single and oth-mult → other.
* contractNature: OCDS `tender.mainProcurementCategory` (goods → supplies), eForms BT-23.
* cpvCodes: OCDS classification with scheme CPV, eForms BT-262 (main) and BT-263 (additional).
* title BT-21, description BT-24, referenceNumber BT-22, buyerName BT-500, documents BT-15, place BT-5121/5131/5141: from memory, marked (*) in the code, still to verify.

**Prototype.** Done: 19 tests in `tests/test_models.py` pass.

**Sources**
* OCDS release reference: https://standard.open-contracting.org/latest/en/schema/reference/
* OCDS for eForms, field mappings: https://standard.open-contracting.org/profiles/eforms/latest/en/mapping
* eForms business terms (SDK 1.12): https://docs.ted.europa.eu/eforms/1.12/reference/business-terms/index.html
* eForms BT-131: https://docs.ted.europa.eu/eforms/latest/reference/business-terms/BT-131.html
* eForms BT-105 codes in business rules: https://docs.ted.europa.eu/eforms/latest/reference/business-rules/notice-subtype-23.html
* eForms BT-23 example notice: https://ted.europa.eu/documents/d/ted/eforms_2022-05-10

## Q8. Benchmark

**Recommendation.** Two test beds. A mock portal we change on purpose is the main ground for Notice and Repair (16 scripted scenarios, fully deterministic, exact gold for free). Real portals are replayed from traffic recorded at our own fetch layer, with "record on miss" and a frozen recording. Full design: `docs/BENCHMARK.md`.

**Key findings**
* Agents explore differently on each run, so a pure replay fails on requests it never recorded. Replay when the request is known, otherwise fetch live and add it; freeze after two or three full runs and report how many requests still went live.
* Recording at our own fetch layer is simpler than HAR because all traffic already passes through it. Playwright HAR (`record_har_path` to record, `route_from_har` to replay; `update` defaults to false, which means replay) stays as the alternative for browser-only flows.
* Score fields as recall minus 2 × error rate, so a wrong value costs more than a missing one, like the judges' rule.
* Gold: full open-id list for every real portal, plus 5 hand-checked tenders per portal (about 40 tenders, about 1.5 hours split over the team).

**Effort.** Roughly 8 to 10 person-hours: mock portal 3 to 4 h, record and replay 1 to 2 h, harness and scorer 2 to 3 h, gold labels about 1.5 h.

**Sources**
* Playwright Python, mocking with HAR files: https://playwright.dev/python/docs/mock
* HAR recording approaches and options: https://stevekinney.com/courses/self-testing-ai-agents/approaches-to-har-recording

## Effects on other questions
* **Q1:** recipes are versioned JSON in the `recipes` table with `parent_version`. Q1 only decides the format of `body`.
* **Q4:** all traffic, including browser sub-requests via `page.route`, goes through one fetch layer that rate limits, records and replays. Block images, fonts, media and stylesheets.
* **Q6:** nothing in Q5, Q7 or Q8 needs anything other than Python.
* **Q9:** `TokenUsage` stores cached and reasoning tokens separately so cost can be priced correctly; prices live in config with a date.
* **Q10:** `CheckResult.severity` maps to state (`fail` → healing, `block` → failed) and `message` becomes the portal's reason.
* **Q11, Q12:** `fingerprint`, `docs_status` and `detail_fetched_at` are already in the schema for reuse and incremental reads.

## Remaining work for Q5, Q7, Q8
**Q5**
* [ ] Agents SDK spike (about 1 h): two tools, Pydantic `output_type`, `max_turns`, usage logged, runs in Docker. Then mark Q5 closed or switch to the fallback loop.
* [ ] Write `app/agent/runner.py` (budgets, usage, `AgentStep` logging).
* [ ] Confirm the token budget check inside tools actually stops a run.
* [ ] Team agrees on the layout in `CONVENTIONS.md`.

**Q7**
* [ ] Verify the BT numbers marked (*) in `models.py` (about 15 min).
* [ ] Fill in the recipe `body` format once Q1 is decided.
* [ ] Align check names with Q10.
* [ ] Thin `app/db.py` on top of `schema.sql` (likely the backend owner).

**Q8**
* [ ] Mock portal with variants and the 16 scenarios (3 to 4 h).
* [ ] Record and replay mode in `fetch/`, together with the Q4 owner (1 to 2 h).
* [ ] `bench/run.py` harness and scorer (2 to 3 h).
* [ ] Gold labels for the real test set (about 1.5 h, split).

## Files in this push
* `app/models.py`
* `app/schema.sql`
* `tests/test_models.py`
* `CONVENTIONS.md`
* `docs/BENCHMARK.md`
* `research/q05-q07-q08-framework-schemas-benchmark.md` (this file)
