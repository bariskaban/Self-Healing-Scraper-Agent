# Watchtower (Patterno track, MAIN AI Hackathon 2026)

An agent that attaches to European public procurement portals on its own, watches them and repairs itself when one breaks. One Docker container serves the JSON API and the operator dashboard on port 8080.

**Hand-in deadline: Saturday 21 November 2026, 10:30.** Aim to submit by 09:30.

> This README tracks the project status for the team. Before hand-in, replace it with the required one-page README: how the system works, which environment variables it needs, and what one portal costs in model usage.

## How to use this list

`[x]` done · `[ ]` open. Each question lists its research step and the build work that follows from it, so whoever owns a number owns everything under it. Put your name after **Owner**. A question is done when every box under it is ticked. Work that belongs to no single question is under **G** at the end.

## Who owns what

- **Baris:** Q5, Q7, Q8
- **David:** Q1, Q3, Q4
- **Dan:** Q2, Q9, Q11
- **Goktug:** Q6, Q10, Q12
- **Goktug (research only, build not assigned):** Q13, Q14
- **Not assigned yet:** G1 to G8

## Questions and what is left

### [ ] Q1. Recipe model
How we represent what the LLM learned about a portal. **Owner:** David
- [ ] Research: write up in `docs/research/Q1.md`, including a draft recipe for one real portal.
- [ ] Team agrees on the format.
- [ ] Recipe Pydantic model (goes into `Recipe.body` in `app/models.py`, format id `recipe/v1`).
- [ ] Executor that runs a recipe with no model call (`app/recipe/`): list, paging, detail pages, JSON API, multi-step steps.
- [ ] Executor tests on recorded pages.

### [ ] Q2. Field locators
What the recipe stores to find each field and link, and how a break is detected. **Owner:** Dan
- [ ] Research: write up in `docs/research/Q2.md` (locator format, fallback order, value checks per field).
- [ ] Locator types in the recipe (CSS, XPath, label, JSON path, fallbacks).
- [ ] Value checks per field (dates parse, deadline after publication, CPV 8 digits, country 2 letters).
- [ ] Normalizers (`app/extract/`): local dates and times to offset, CPV, procedureType and contractNature mapping, ids.

### [ ] Q3. Explore or map first
Goal-directed exploration vs site mapping, and structured sources to try first. **Owner:** David
- [ ] Research: write up in `docs/research/Q3.md`, with the request count per option and the ordered probe checklist.
- [ ] Source prober: JSON API in network traffic, OCDS, RSS/Atom, sitemap, before crawling HTML.
- [ ] Summary page detection: entry URL that is not the tender list leads to the real list (`Portal.list_url`).

### [ ] Q4. Agent tools
What the learn and repair agents use to see and drive a portal. **Owner:** David
- [ ] Research: write up in `docs/research/Q4.md`, with token counts of page views measured on 2 to 3 real pages.
- [ ] Fetch layer (`app/fetch/`): 1 request/s per host for httpx and every browser sub-request via `page.route`; block images, fonts, media, stylesheets.
- [ ] Network capture to find JSON APIs (`NetworkEntry`, `looks_like_tender_list`).
- [ ] Compact page view for the model.
- [ ] Agent tools (`app/agent/tools.py`): fetch page, page view, list links, click or fill, test locator, download file.
- [ ] Login and captcha detection (feeds Q10).

### [ ] Q5. Agent framework and conventions
**Owner:** Baris
- [x] Research: `docs/research/Q5_Q7_Q8.md` (OpenAI Agents SDK, own loop as fallback).
- [x] Conventions: `CONVENTIONS.md`.
- [ ] Team agrees on the project layout in `CONVENTIONS.md`.
- [ ] Agents SDK spike (about 1 h): two tools, Pydantic `output_type`, `max_turns`, usage logged, runs in Docker.
- [ ] `app/agent/runner.py`: budgets, token and cost bookkeeping, `AgentStep` logging.
- [ ] Learn agent (`app/agent/learn.py`) and repair agent (`app/agent/repair.py`), with prompts in `app/agent/prompts/` (needs Q1 to Q4).

### [ ] Q6. Language
Python only, or TypeScript for part of it. **Owner:** Goktug
- [x] Research: `research/q06-language.md`. Python for the whole system; pin `playwright` to the base image's version.
- [ ] Dockerfile at the repo root: base image with Python 3.12 and Chromium, quick build, `docker build .` works for linux/amd64.
- [ ] Default command starts API and dashboard on port 8080.

### [ ] Q7. Schemas
**Owner:** Baris. Core done and usable now; three small follow-ups left.
- [x] Research: `docs/research/Q5_Q7_Q8.md`.
- [x] `app/models.py`, `app/schema.sql`, 19 passing tests in `tests/test_models.py`.
- [ ] Verify the eForms BT numbers marked (*) in `models.py` (about 15 min).
- [ ] Add the recipe `body` format once Q1 is decided.
- [ ] Align check names with Q10.

### [ ] Q8. Benchmark
**Owner:** Baris
- [x] Design: `docs/BENCHMARK.md`.
- [ ] Mock portal with variants and the 16 scenarios (`mock_portal/`, 3 to 4 h).
- [ ] Record and replay mode in `app/fetch/`, together with the Q4 owner (1 to 2 h).
- [ ] Real test set: 8+ portals, 4+ countries, 3+ software packages, 1 to 2 behind login or captcha.
- [ ] Gold labels: open-id list per portal plus 5 checked tenders each (about 1.5 h, split).
- [ ] Harness and scorer (`bench/run.py`, 2 to 3 h).

### [ ] Q9. OpenAI models and cost
**Owner:** Dan
- [ ] Research: write up in `docs/research/Q9.md`, from OpenAI's current pricing page, dated.
- [ ] `app/config.py`: model per job (`MODEL_LEARN`, `MODEL_REPAIR`, `MODEL_CHECK`) and the price table with its date.
- [ ] Pick models from the benchmark (needs Q8).
- [ ] Cost per portal (attach and repair) for the hand-in README.

### [ ] Q10. Failure rules
**Owner:** Goktug
- [x] Research: `research/q10-failure-rules.md`: rules, thresholds, state and reason text per rule, and the check names for `CheckResult`.
- [ ] Add an `outage` severity (healing without a repair) to `app/models.py`, with the Q7 owner.
- [ ] Checks (`app/checks/`), one function each, returning `CheckResult`.
- [ ] State machine (`app/state.py`): checks to state and reason; keep serving last good tenders while healing.
- [ ] No false alarm on portals with few or no open tenders (mock scenario 13).

### [ ] Q11. Reuse across portals
**Owner:** Dan
- [ ] Research: write up in `docs/research/Q11.md`: common platforms per country and their fingerprints.
- [ ] Fingerprint detector (`Portal.fingerprint`).
- [ ] Reuse rule: try a stored recipe with the same fingerprint first; trust it only if it passes every check plus a spot check.

### [ ] Q12. Large portals
**Owner:** Goktug
- [x] Research: `research/q12-large-portals.md`: read order, state rule, request math for 100, 1,000 and 5,000 tenders (`research/tools/q12_request_math.py`).
- [ ] Ask the mentors how long the harness waits and whether `serving` may have documents pending; the 10-minute rule depends on it.
- [ ] Incremental reads: details and files only for new or changed tenders (`detail_fetched_at`, `docs_status`).
- [ ] Documents (`app/docs/`): multi-step downloads, streaming, ZIP unpacking, sha256, 250 MB limit, captcha-but-file-downloads case.

### [ ] Q13. Read schedule
**Owner:** _____
- [x] Research: `research/q13-read-schedule.md`. It replaces the 15 minutes with: every 2 minutes, or 10 times the list's read time, at most 30 minutes.
- [ ] Team agrees on that rule. Details and files only for new or changed tenders; refresh starts a read or returns the running read's `runId`. (`closed` is already computed at answer time, Q7.)
- [ ] Scheduler (`app/scheduler.py`).

### [ ] Q14. Retrying failed portals
**Owner:** _____
- [x] Research: `research/q14-failed-retry.md`. Check on every refresh, and on our own after 5 minutes, 15 minutes, 1 hour, then every 6 hours; one repair only when the page is one we have not already failed on.
- [ ] Team agrees on that rule.
- [ ] Recheck job in the scheduler (`RunTrigger.recheck`).

### [ ] G. Work outside any one question
**Owner:** _____
- [ ] G1. API (`app/main.py`): every endpoint with the exact answers from the appendix, `/files/{file_id}`.
- [ ] G2. `app/db.py` on top of `app/schema.sql`.
- [ ] G3. Dashboard at `GET /`: every portal, state and reason, what broke, what the system did (`agent_steps`), cost.
- [ ] G4. Hand-in README (one page: how it works, environment variables, cost per portal).
- [ ] G5. Video, at most 3 minutes, including the dashboard (mock portal break and repair makes a good demo).
- [ ] G6. Dedicated OpenAI key with a spending limit for the judges, revoked after judging.
- [ ] G7. Team decision on the Patterno participant declaration (required for the track prize and the final).
- [ ] G8. Submit the repository link in the hackathon submission.
- [ ] G9. Recipe schema before the agents fan out. One agent writes the Q1 recipe format as a Pydantic model (`Recipe.body`, `recipe/v1`) and a person approves it. Only then do agents start on the executor, learner, repairer, checks and reuse, which all build against it.
- [ ] G10. Add to `CLAUDE.md`: no agent sends requests to a live portal. Each test portal is recorded once at the fetch layer (`FETCH_MODE=record`) and agents work from the recordings only (`FETCH_MODE=replay`). Several agents testing the same portal at once would break the 1 request per second rule.
- [ ] G11. Model calls in tests are mocked or replayed, never live. Development uses its own OpenAI key with a spending cap, separate from the judging key (G6).

## Files so far

- `app/models.py`: all records and the exact API models (Q7)
- `app/schema.sql`: SQLite tables (Q7)
- `tests/test_models.py`: tests for the schemas (Q7)
- `CONVENTIONS.md`: project layout and rules (Q5)
- `docs/BENCHMARK.md`: benchmark design (Q8)
- `research/`: one file per question, the register in `research/README.md`, and the end check of every answer in `research/audit.md`
