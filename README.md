# Watchtower (Patterno track, MAIN AI Hackathon 2026)

An agent that attaches to European public procurement portals on its own, watches them and repairs itself when one breaks. One Docker container serves the JSON API and the operator dashboard on port 8080.

**Hand-in deadline: Saturday 21 November 2026, 10:30.** Aim to submit by 09:30.

> This README tracks the project status for the team. Before hand-in, replace it with the required one-page README: how the system works, which environment variables it needs, and what one portal costs in model usage.

## How to use this list

`[x]` done · `[ ]` open. Each question lists its research step and the build work that follows from it, so whoever owns a number owns everything under it. Put your name after **Owner**. A question is done when every box under it is ticked. Work that belongs to no single question is under **G** at the end.

## Who owns what

- **Baris:** Q5, Q7, Q8
- **David:** Q1, Q3, Q4
- **Danil:** Q2, Q9, Q11
- **Goktug:** Q6, Q10, Q12
- **Goktug (research, and the rules as functions in `app/scheduler.py`; the loop is not assigned):** Q13, Q14
- **G1, the API:** Goktug
- **G2, the database:** David
- **G3, the dashboard and frontend:** Danil and Baris
- **The network layer (`app/fetch/`):** David
- **The recipe schema, the executor and its normalisers, the read loop, a small mock portal (`app/recipe/`, `app/extract/`, `app/scheduler.py`, `mock_portal/`):** Goktug
- **The learn and repair agent (`app/agent/`, `app/config.py`):** Goktug, in a second Claude session
- **Not assigned yet:** G4 to G11

Who builds what from here, in what order, and what each part hands to the others: [docs/BUILD-PLAN.md](docs/BUILD-PLAN.md).

## Questions and what is left

### [ ] Q1. Recipe model
How we represent what the LLM learned about a portal. **Owner:** David
- [x] Research: `research/q01-recipe-model.md`. A typed navigation graph; `research/audit.md` lists what the draft recipe must still express (form-post paging, POST-body APIs, multi-step downloads).
- [ ] Team agrees on the format.
- [x] Recipe Pydantic model (goes into `Recipe.body` in `app/models.py`, format id `recipe/v1`).
- [x] Executor that runs a recipe with no model call (`app/recipe/`): list, paging, detail pages, JSON API, multi-step steps.
- [ ] Executor tests on recorded pages.

### [ ] Q2. Field locators
What the recipe stores to find each field and link, and how a break is detected. **Owner:** Danil
- [x] Research: `research/q02-locators.md`. Two or three locators and value checks per field; per the audit, a single surviving locator counts only when it equals the last good value.
- [x] Locator types in the recipe (CSS, XPath, label, JSON path, fallbacks): `LocatorKind` and `FieldSpec.locators` in `app/recipe/schema.py` (G9).
- [ ] Value checks per field (dates parse, deadline after publication, CPV 8 digits, country 2 letters).
- [x] Normalizers (`app/extract/`): local dates and times to offset, CPV, procedureType and contractNature mapping, ids.

### [ ] Q3. Explore or map first
Goal-directed exploration vs site mapping, and structured sources to try first. **Owner:** David
- [x] Research: `research/q03-explore-or-map.md`. Use the portal's own network calls and links first, then explore with a page budget; never map the site.
- [ ] Source prober: JSON calls in the page's network traffic, feed links the pages carry, embedded app state, before crawling HTML. Guessed paths (`/feed`, `/api`, `/ocds`) found nothing on four portals, so they come last if at all (audit of Q3).
- [ ] Summary page detection: entry URL that is not the tender list leads to the real list (`Portal.list_url`).

### [ ] Q4. Agent tools
What the learn and repair agents use to see and drive a portal. **Owner:** David
- [x] Research: `research/q04-agent-tools.md`, with token counts measured on real pages in `research/q04-page-views-measured.md`.
- [x] Fetch interface and HTTP side (`app/fetch/`): `Fetch` in `app/fetch/interface.py`; one request start per second per portal, redirects walked hop by hop, rules T1 and T2, robots.txt obeyed (`IGNORE_ROBOTS_TXT` for a test), downloads as `app/docs` takes them. Tests in `tests/fetch/`.
- [ ] Browser side: Playwright through the same limiter (every sub-request via `context.route`); block images, fonts, media, stylesheets, third-party origins; script cache; service workers off; WebSockets blocked; network capture. `browse` already replays recorded pages.
- [ ] Network capture to find JSON APIs (`NetworkEntry`, `looks_like_tender_list`).
- [ ] Compact page view for the model.
- [ ] Agent tools (`app/agent/tools.py`): fetch page, page view, list links, click or fill, test locator, download file.
- [x] Login and captcha detection (feeds Q10): `app/fetch/answer.py` reads login redirects, password fields, bot-wall headers and pages, captcha markers and maintenance pages into `Answer`.

### [ ] Q5. Agent framework and conventions
**Owner:** Baris
- [x] Research: `research/q05-q07-q08-framework-schemas-benchmark.md` (OpenAI Agents SDK, own loop as fallback).
- [x] Conventions: `CONVENTIONS.md`.
- [ ] Team agrees on the project layout in `CONVENTIONS.md`.
- [ ] Agents SDK spike (about 1 h): two tools, Pydantic `output_type`, `max_turns`, usage logged, runs in Docker.
- [ ] `app/agent/runner.py`: budgets, token and cost bookkeeping, `AgentStep` logging.
- [ ] Learn agent (`app/agent/learn.py`) and repair agent (`app/agent/repair.py`), with prompts in `app/agent/prompts/` (needs Q1 to Q4).

### [x] Q6. Language
Python only, or TypeScript for part of it. **Owner:** Goktug
- [x] Research: `research/q06-language.md`. Python for the whole system; pin `playwright` to the base image's version.
- [x] Dockerfile at the repo root: base image with Python 3.12 and Chromium, quick build, `docker build .` works for linux/amd64. CI builds it on every pull request (`.github/workflows/ci.yml`).
- [x] Default command starts the app on port 8080, with the API and the dashboard (G1, G3).

### [ ] Q7. Schemas
**Owner:** Baris. Core done and usable now; three small follow-ups left.
- [x] Research: `research/q05-q07-q08-framework-schemas-benchmark.md`.
- [x] `app/models.py`, `app/schema.sql`, 19 passing tests in `tests/test_models.py`.
- [ ] Verify the eForms BT numbers marked (*) in `models.py` (about 15 min).
- [x] Add the recipe `body` format once Q1 is decided: `RecipeBody` in `app/recipe/schema.py`.
- [ ] Align check names with Q10.

### [ ] Q8. Benchmark
**Owner:** Baris
- [x] Design: `docs/BENCHMARK.md`.
- [ ] Mock portal with variants and the 25 scenarios in `docs/BENCHMARK.md` (`mock_portal/`). Done: the server-rendered template with 13 switches and its recipe, mounted in the app at `/mock`. Open: the JSON and multi-step templates, the large variant, the 250 MB ZIP, the scenario runner.
- [x] Record and replay mode in `app/fetch/` (`FETCH_MODE`; replay is the default, the Dockerfile sets live).
- [x] Real test set: `bench/portals.toml` (read with `bench.portals.load_portals()`): 49 portals in 7 countries plus Mercell, led by Poland, Italy and France as the mentor's answers suggest; 2 held back unseen, 2 expected to fail at login, aggregators listed as excluded. Each address says how sure we are of it.
- [ ] Record the test set (a person, `FETCH_MODE=record`), Poland first; find the 18 missing addresses and confirm the 10 example or doubtful ones.
- [ ] Gold labels: open-id list per portal plus 5 checked tenders each (about 1.5 h, split).
- [ ] Harness and scorer (`bench/run.py`, 2 to 3 h).

### [ ] Q9. OpenAI models and cost
**Owner:** Danil
- [x] Research: `research/q09-models-cost.md`. Learn and repair on `gpt-6.2-sol`, spot checks on `gpt-6-luna`; per the audit, quote the cost per portal only once measured.
- [x] `app/config.py`: model per job (`MODEL_LEARN`, `MODEL_REPAIR`, `MODEL_CHECK`) and the price table with its date.
- [ ] Pick models from the benchmark (needs Q8).
- [ ] Cost per portal (attach and repair) for the hand-in README.

### [ ] Q10. Failure rules
**Owner:** Goktug
- [x] Research: `research/q10-failure-rules.md`: rules, thresholds, state and reason text per rule, and the check names for `CheckResult`.
- [x] Add an `outage` severity (healing without a repair) to `app/models.py`, and `cause` on a portal (pull request 18, approved by a person). The checks use both.
- [x] Checks (`app/checks/`), one function each, returning `CheckResult`: T1, T2, T4, O1, O2, C1 to C7, D1, F1 and the confirm step. Settings come from the environment (`CHECKS_*`).
- [x] State machine (`app/state.py`): `decide` turns the checks of one read into the state, the reason, the `cause`, and whether a repair or a spot check follows.
- [x] Call the checks and `decide` from the read loop, and store the last good tenders so they stay served while healing (needs the executor and `app/db.py`).
- [x] No false alarm on portals with few or no open tenders, in unit tests: 1 of 3 tenders withdrawn, a list emptied with and without the portal's notice.
- [ ] The same on the mock portal (scenario 13), once it exists.

### [ ] Q11. Reuse across portals
**Owner:** Danil
- [x] Research: `research/q11-reuse.md`. Host, path or brand match makes a candidate, trusted only after a canary read; per the audit, also match on page structure.
- [ ] Fingerprint detector (`Portal.fingerprint`).
- [ ] Reuse rule: candidates by host, path, brand text or page structure; trust one only after the canary read, the full first read and a spot check (DESIGN.md, Reuse).

### [ ] Q12. Large portals
**Owner:** Goktug
- [x] Research: `research/q12-large-portals.md`: read order, state rule, request math for 100, 1,000 and 5,000 tenders (`research/tools/q12_request_math.py`).
- [x] Ask the mentors how long the harness waits and whether `serving` may have documents pending. Answered (`research/mentor-answers.md`): 20 to 30 minutes, and yes. The 10-minute rule stays; the attach time limit is 20 minutes.
- [x] Incremental reads, the plan: which tenders are fetched, which are no longer listed, and the detail-page rotation (`plan_incremental_read` in `app/scheduler.py`).
- [x] Incremental reads, in the loop: run the plan against the executor and the store (`detail_fetched_at`, `docs_status`).
- [x] Documents (`app/docs/`): streaming to disk with the SHA-256 computed as the bytes arrive, the 250 MB limit, files stored once under their hash, ZIP unpacking (nested too, within caps), file names, disk rules. It takes the bytes from the network layer and the file test (O2) from `app/checks/` as parameters.
- [x] Documents use the file test of `app/checks/` (`outcome_judge` in `app/docs/judge.py`): a web page or a login page in place of a file is never stored, and a captcha on a page whose file downloads changes nothing.
- [ ] Documents, wiring: the download through `app/fetch/` (multi-step downloads are recipe steps) and storing the records (`app/db.py`).

### [ ] Q13. Read schedule
**Owner:** Goktug for the rules; the loop: _____
- [x] Research: `research/q13-read-schedule.md`. It replaces the 15 minutes with: every 2 minutes, or 10 times the list's read time, at most 30 minutes.
- [ ] Team agrees on that rule. Details and files only for new or changed tenders; refresh starts a read or returns the running read's `runId`. (`closed` is already computed at answer time, Q7.)
- [x] The rules as functions in `app/scheduler.py`: the interval, the first-page read on long lists, the attach phases with their state and reason, the document order. Settings come from the environment (`READ_INTERVAL_SECONDS`, `ATTACH_TIME_LIMIT_SECONDS` and others).
- [x] The loop that calls them: one run per portal, portals side by side, refresh (needs `app/fetch/`, the executor and `app/db.py`).

### [ ] Q14. Retrying failed portals
**Owner:** Goktug for the rules; the loop: _____
- [x] Research: `research/q14-failed-retry.md`. Check on every refresh, and on our own after 5 minutes, 15 minutes, 1 hour, then every 6 hours; one repair only when the page is one we have not already failed on.
- [ ] Team agrees on that rule.
- [x] The rules as functions in `app/scheduler.py`: when a failed portal is checked next, the outage retries, the once-a-minute limit on refresh.
- [x] Recheck job in the scheduler's loop (`RunTrigger.recheck`).

### [ ] G. Work outside any one question
**Owner:** _____
- [x] G1. API (`app/main.py`): every endpoint with the exact answers from the appendix, `/files/{file_id}`. It talks to the store and the worker through `app/interfaces.py`, and runs on an in-memory stand-in (`app/memory_store.py`) until both exist.
- [x] The contract test (`tests/contract/`): plays the judges on every route. CI runs it against the built container on every pull request.
- [x] G1, wiring the store: with `DATA_DIR` set (the Dockerfile sets `/data`) the app runs on `app/db.py` and its records survive a restart; without it, in memory (`default_store()` in `app/main.py`).
- [x] G1, wiring the worker: with `DATA_DIR` the app runs on the read loop (`app/loop.py`, one read in `app/reader.py`). Until the learning agent exists, only the mock portal mounted at `/mock` can be attached (`builtin_learner` in `app/main.py`).
- [x] G2. `app/db.py` on top of `app/schema.sql`: the eight `Store` methods the API calls, and the worker's writes (portal state, runs, checks, steps, snapshots, recipes, publishing tenders and documents). One read and one write connection, each behind a lock (research in `research/q15-storage.md`). Tests in `tests/test_db.py`.
- [x] G3. Dashboard at `GET /`: every portal, state and reason, what broke, what the system did (`agent_steps`), cost.
  - [x] No demo data in place of a down API: the page says "API offline, retrying"; the demo snapshot only with `?demo`.
- [ ] G4. Hand-in README (one page: how it works, environment variables, cost per portal).
- [ ] G5. Video, at most 3 minutes, including the dashboard (mock portal break and repair makes a good demo).
- [ ] G6. Dedicated OpenAI key with a spending limit for the judges, revoked after judging.
- [ ] G7. Team decision on the Patterno participant declaration (required for the track prize and the final).
- [ ] G8. Submit the repository link in the hackathon submission.
- [x] G9. Recipe schema before the agents fan out: `app/recipe/schema.py`, format `recipe/v1`, with three worked examples in `tests/recipe/examples.py`. Approved by a person in its own pull request. The executor, the learner and the repairer build against it.
- [x] G10. Add to `CLAUDE.md`: no agent sends requests to a live portal. Each test portal is recorded once at the fetch layer (`FETCH_MODE=record`) and agents work from the recordings only (`FETCH_MODE=replay`). Several agents testing the same portal at once would break the 1 request per second rule.
- [ ] G11. Model calls in tests are mocked or replayed, never live. Development uses its own OpenAI key with a spending cap, separate from the judging key (G6). The rule is in `CLAUDE.md`; the development key itself is still to make.

## Files so far

- `DESIGN.md`: the spec, draft 3, built from the finished research
- `CLAUDE.md`: rules for the agents that build the system (source of truth, one module per agent, no live portals, no live model calls in tests)
- `app/models.py`: all records and the exact API models (Q7)
- `app/schema.sql`: SQLite tables (Q7)
- `tests/test_models.py`: tests for the schemas (Q7)
- `CONVENTIONS.md`: project layout and rules (Q5)
- `docs/BENCHMARK.md`: benchmark design (Q8)
- `research/`: one file per question, the register in `research/README.md`, and the end check of every answer in `research/audit.md`
