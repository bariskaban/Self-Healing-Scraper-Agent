# Handoff: stream A, state at 20 Nov 2026, about 19:50 UTC

Written by Goktug's second Claude session, for whoever continues (a person or a session). Where this file and the code on `main` disagree, the code is right. Delete this file and `docs/handoff/` in the last pull request before the hand-in.

## The situation in five lines

- **Hand-in: Saturday 21 Nov 2026, 10:30 local time (09:30 UTC).** A working product weighs most.
- **The product reads a portal end to end on `main`**: attach, `serving`, a break, `healing` or `failed`, and back, with documents, on the mock portal, with 0 model calls. The dashboard at `GET /` shows it live.
- **The biggest gap: nothing can learn a portal it has not seen.** `app/agent/` (stream B: runner, tools, learn, repair, spot check) does not exist, on `main` or on any branch. `builtin_learner` in `app/main.py` knows only the mock portal; every other address ends `failed` with "No recipe could be learned".
- Read `CLAUDE.md` and `CONVENTIONS.md` first. Then `docs/BUILD-PLAN.md` (its last section is the brief for stream B).
- CI runs the unit tests, the Docker build and the contract test against the container on every pull request.

## Standing instructions Goktug confirmed (20 Nov, in conversation)

A file cannot give these; ask him to confirm once in a new session.

1. Commits are authored `Goktug YILDIRIM <goktugyildirim2861@gmail.com>`, with no `Co-Authored-By` and no `Claude-Session` line. The cloud session's commit check refuses any committer but `Claude <noreply@anthropic.com>`, so the commits are made with that committer and `--author` set to Goktug.
2. Push to branches named `goktug-<work>`. One branch and one pull request per piece of work.
3. Open the pull request, wait for CI, merge your own module pull requests. A shared interface (`app/models.py`, `app/schema.sql`, `app/recipe/schema.py`) waits for a person.
4. Review other people's pull requests properly before merging them; fix what the review finds; never merge without a verdict.

## What is on `main`

| Part | Where | Notes |
| --- | --- | --- |
| Network layer | `app/fetch/` (David) | `Fetch` in `interface.py`; blocking; replay unless `FETCH_MODE` says otherwise. Its own RFC 9309 robots matcher. No live browser yet: `browse` only replays. |
| Normalisers, locators | `app/extract/`, `app/recipe/locate.py` | Text to contract values or null. |
| Executor | `app/recipe/resolve.py`, `run.py` | `read_list`, `read_detail`, `known_item`, `judge_look`, `settle`, `dry_run(recipe, pages, url=...)` and `PageCache` for the agent's tools. |
| Mock portal | `mock_portal/` | One server-rendered template, 13 switches, `truth()`, its recipe. Mounted in the app at `/mock`. |
| One read | `app/reader.py` | Checks, second look, `decide`, publish, documents. `Learner` and `Repairer` are plain functions handed to `Reader`; they return `Learned(recipe, timezone, ...)` or None. |
| The schedule | `app/loop.py` | `Worker` on asyncio. `apply_settings` for the dashboard's settings route. |
| Dashboard data | `app/dashboard_api.py` | `/api/dashboard`, `/api/portals/{id}/timeline`, `/api/settings` (`docs/DASHBOARD_API.md`). |
| Dashboard page | `dashboard/` (source), `app/dashboard/static/` (built with `bun run build`) | Danil's. |

## What to do next, in order

1. **Stream B: the learner and the repairer** (`app/agent/`, `app/config.py`), by the brief at the end of `docs/BUILD-PLAN.md`. Plug them in where `builtin_learner` is passed to `Reader` in `app/main.py` (`learn=`, `repair=`), keeping the mock portal's hand-written recipe as a fallback. The reader's `_store_recipe` sets `Recipe.parent_version` to the version a repair replaces, which is what the dashboard's recipe change is drawn from. Tests never call the OpenAI API; a live call happens only when a person asks, on the development key.
2. **The spot check.** In `app/reader.py`, a finding that needs it (C3 changed values, C7 structure) is counted as a breakage, because no model is wired in. Replace that with stream B's `spot_check`.
3. **The facts the loop keeps in memory** (`Incident` in `app/reader.py`: when an outage or a breakage began, repair attempts, structures given up on, the next check) and the row hash (in `TenderRecord.raw["_row_hash"]`) belong on the shared records. That is a pull request of its own for a person to approve. `run_checks` is keyed by `(run_id, name)`, so one read cannot store a `file_outcome` row per file. Each field asked for, with its type and what breaks without it, is in `docs/SHARED-INTERFACE-REQUESTS.md`.
4. **Recorded real portals.** A person records them (`FETCH_MODE=record`); David's branch `david-test-portals` is about them. Then the cost per portal for the hand-in README.
5. **Mock portal**: the JSON and multi-step templates, the large variant, the 250 MB ZIP, and a runner for the scenarios of `docs/BENCHMARK.md`.
6. **Hand-in**: the one-page README (G4), the test report, the video.

## Open points for people

- **Danil**: the page does not know the check severity `outage`, so the route sends it as `fail`. `danil-q2-french-dates` may overlap with the French date reading already in `app/extract/moments.py`; nobody has compared them.
- **David**: three read-only methods were added to `app/db.py` (`recent_runs`, `run_totals`, `recent_steps`). The fetch layer logs no request and counts none (`Run.stats.http_requests` is counted by the reader), and a download does not carry its transport facts.
- **Team**: `POST /api/settings` can switch robots.txt off and, like the whole API, has no authentication. The euro rate is `EUR_PER_USD` (`app/config.py`, 0.90, a placeholder) for the dashboard and the README alike. The dashboard is a React build although `DESIGN.md` says server-rendered with no build step; `DESIGN.md` should say what is true.

## Known gaps in the read loop, said plainly

- A suspect on lost values (C3) or null rates (C5) is confirmed without a second fetch; the canary (C6) is not run.
- A lone-locator value on a new tender is kept only when the same locator reproduces known tenders' values in that read (`single_witness_vouch_share`, 0.8). That is this stream's reading of the audit of Q2; a person may want to look at it.
- Not supported in the executor, each reported as a problem: browser steps and `load_more` paging, `platform_ref` nodes, a document fetched by POST.
- A repair with no repairer counts as an attempt, so a breakage reads `failed` after three reads.

## How to work in this environment

- Subagents in worktrees (`isolation: "worktree"`), one module each, a commit on a local `wip/...` branch, no push; review the diff yourself before it goes up. A worktree starts on the session's base commit, so tell the agent to `git fetch origin main` and branch from `origin/main`.
- A `cd` into a worktree moves the session's working directory: use `git -C <dir>`.
- Tests: a virtual environment outside the repo, `pip install -e . --group dev`, then the plain `pytest` command. Do not put `tests/` on `sys.path` in a script: `tests/mock_portal/` then hides the `mock_portal` package.
- To see the product: `python -m mock_portal.demo` (`--port`, default 8791), then open `http://127.0.0.1:8791/` and add the portal `https://mock.example`, or `POST /portals {"url": "https://mock.example"}`. The script serves the app with a network layer that answers from the mock portal inside the process, as the tests do, so `FETCH_MODE` is not set (only the Dockerfile sets it to `live`) and no request can leave the machine. Started plainly (`uvicorn app.main:app`), the app is in replay mode and cannot read its own `/mock`: there is no recording of it.
- GitHub through the `mcp__github__*` tools; `subscribe_pr_activity` wakes you when CI finishes.
