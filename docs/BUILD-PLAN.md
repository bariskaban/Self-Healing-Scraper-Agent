# Build plan: who builds what from here

Written 20 Nov 2026, about 15 hours before the hand-in (Saturday 21 Nov, 10:30). It covers the parts that had no owner. `DESIGN.md` stays the spec, `CLAUDE.md` and `CONVENTIONS.md` stay the rules; this file only says who builds which part, in what order, and what each part hands to the others.

## What exists

On `main`, with tests and CI: the API with a contract test, the checks and the state machine (Q10), the scheduler's rules as functions (Q12 to Q14), the documents module, the shared records. Nothing reads a portal yet. Four parts are missing between "a portal's address" and "tenders in the API": the network layer, the recipe executor, the learn and repair agent, and the read loop that ties them together.

## The split

| Stream | Who | Builds | Module |
| --- | --- | --- | --- |
| **A** | Goktug, this Claude session | The recipe schema, the recipe executor with its normalisers, the read loop, a small mock portal for tests | `app/recipe/`, `app/extract/`, `app/scheduler.py`, `mock_portal/` |
| **B** | Goktug, second Claude session | The learn and repair agent: runner, tools, learn, repair, spot check, prompts, model settings | `app/agent/`, `app/config.py` |
| **C** | David | The network layer, and the database he already has | `app/fetch/`, `app/db.py` |
| | Danil, Baris | Dashboard and frontend | `app/dashboard/` |

### Why this split

Goktug's side takes the two hardest of the three open parts, because it has two sessions to put on them.

- **The agent is the hardest.** It is the only part whose output is not deterministic. It has to produce a working recipe for a portal nobody has seen, inside a cost cap, and the Agents SDK leaves three things to us (trimming the context, stopping on budget, retrying invalid output). It needs the most rounds of trying, some of them with live model calls.
- **The executor is second.** It has the widest surface: every node kind, every way of paging, every kind of locator, and dates and words in six languages. Every check and the whole read loop depend on what it reports, and it sets what the agent is able to express.
- **The network layer is hard in its details but narrow.** Its job is one sentence (one polite, recorded request), its rules are already written (Q4, rule 1 of the conventions), and it shares no format with the recipe. David wrote the Q4 research, and he is the person who makes the recordings, which need it first.

Inside Goktug's side, the executor and the read loop go together (stream A): what the executor reports is exactly what the checks, the state machine and the scheduler's rules take in, and those are already stream A's. The agent (stream B) needs only two things from A: the recipe schema, and the executor's functions for trying a locator and dry-running a recipe on cached pages.

## Order

Everything waits on two small interfaces, so those come first.

| Step | Stream A | Stream B | Stream C |
| --- | --- | --- | --- |
| 1. Now | **Recipe schema** `recipe/v1` as a Pydantic model, in its own pull request. A person approves it (CHECKME, G9). | The runner on a mocked model: budgets, context trimming, usage, steps, the one retry. Needs nothing from A or C. | **The fetch interface** and a replay implementation that reads `tests/fixtures/`, so A and B can code against it. |
| 2 | The executor on pages from disk: locators, value parsing, HTML and JSON list nodes, paging, detail pages, documents. Then `try_locator` and `dry_run` for B. | The tools (on the fetch interface and A's two functions), then learn, on the mock portal's pages. | The limiter, httpx, the browser, record and replay. `app/db.py` behind the API's `Store`. |
| 3 | The read loop on the mock portal with a hand-written recipe: attach, `serving`, a break, `healing`. No agent needed yet. | Repair and the spot check. | What the loop needs to write: recipes, runs, checks, steps, tenders, files. |
| 4 | The loop calls the agent: learn on attach, repair on a breakage. | Learn against the mock portal with the development key (a person starts each live run). | Recordings of the test portals (a person, `FETCH_MODE=record`). |
| 5 | All: recorded real portals end to end, cost per portal measured, test report, README, video. | | |

Step 3 is the first moment the product runs end to end, on the mock portal with a recipe written by hand. Reach it before widening anything.

## What each stream hands to the others

Each interface is written down in code by the stream that owns it, as early as it can, with a stand-in the others can test against. Change one only by telling the streams that use it.

| Interface | Owner | Used by | What it is |
| --- | --- | --- | --- |
| The recipe | A | B, C (stores it) | `app/recipe/schema.py`: the Pydantic model of `Recipe.body`, format `recipe/v1`, inside OpenAI's rules for strict output. **A shared interface: changes only in its own pull request, approved by a person.** |
| Fetch | C | A, B | **In `app/fetch/interface.py` (`Fetch`, `Fetched`, `BrowsedPage`); `app.fetch.Fetcher` provides it.** One HTTP request through the limiter; one browser page with the network calls it made; one download as the `Download` that `app/docs` takes. Each answer carries the facts Q10 needs (`Answer` in `app/checks/transport.py`: status, error kind, `Retry-After`, login redirect, password field, bot-wall signs, maintenance page). Record and replay by `FETCH_MODE`. A replay implementation for tests comes first. |
| Trying a recipe | A | B | `try_locator(locator, page)`: the values a locator finds on a cached page. `dry_run(recipe, pages)`: the records a recipe gives on cached pages, with what failed. No request is made. |
| The agent | B | A | `learn`, `repair`, `spot_check`: each takes what it needs as plain arguments and returns a validated result with its usage and steps. On a spent budget or invalid output it returns a failed result; it does not raise. |
| The store | C | A, the API | `Store` in `app/interfaces.py` for the API (done). What the loop writes is added to that file when the loop is written. |
| The worker | A | the API | `Worker` in `app/interfaces.py` (`attach`, `refresh`, `forget`). |

## Rules that matter most here

- No request to a live portal from an agent session, a test or a script. Streams A and B work on the mock portal, on fixtures and on recordings a person made.
- No test calls the OpenAI API. A live model call happens only when a person asks for it, on the development key.
- One module per stream. Reach into another stream's module only through its interface.
- Branches are named `<name>-<work>`. A pull request says which checks ran: unit tests, the contract test, `docker build .`. CI runs all three.

## Brief for stream B (the second session)

Read `CLAUDE.md`, `CONVENTIONS.md`, then `DESIGN.md` ("Attach: how the learner works", "Repair", "Cost per portal"), then `research/q03-explore-or-map.md`, `research/q04-agent-tools.md`, `research/q04-page-views-measured.md`, `research/q05-agent-framework.md`, `research/q09-models-cost.md`, and the sections on those questions in `research/audit.md`, which outrank the research files.

You build `app/agent/` and `app/config.py`, on branches named `goktug-agent-<work>`:

1. **`runner.py`**: the only place that calls a model. It names the model and sets `max_turns` on every run, trims what each call sends so the input stays near 30,000 tokens, stops a run from outside the tools when its budget is spent, sends an invalid final answer back once with the validation message, copies usage into `TokenUsage`, and logs every step as an `AgentStep` with a one-line summary an operator understands. Tested on a mocked model.
2. **`config.py`**: the model per job (`MODEL_LEARN`, `MODEL_REPAIR`, `MODEL_CHECK`) and the price table with the date it was copied, from Q9.
3. **`tools.py`**: the tools of Q4, on the fetch interface and on stream A's `try_locator` and `dry_run`. Every page is cached the first time it is fetched; the model sees trimmed HTML as Q4 measured it.
4. **`learn.py`**, **`repair.py`**, **`spotcheck.py`**, with their prompts as files in `prompts/`. Learn returns a recipe that validates against `app/recipe/schema.py` and passes a dry run on the cached pages. Repair gets the failed checks, the old recipe and a snapshot, and changes as little as it can. The spot check is one small call that must quote the page for each value.

Until the recipe schema is merged, start with the runner and `config.py`, which need nothing else. Nothing imports `openai` outside `app/agent/`.
