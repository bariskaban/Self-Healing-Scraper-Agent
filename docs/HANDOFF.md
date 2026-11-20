# Handoff: stream A, from Goktug's first Claude session to the next

Written 20 Nov 2026, about 19:20 UTC. The session that wrote this had filled its context; you continue its work. Everything you need is in this file and in the files it points to. Where this file and the code disagree, the code on `main` is right: check before you rely on a sentence here.

## The situation in six lines

- The project is **Watchtower**, for the Patterno track of the MAIN AI Hackathon: one Docker container that attaches to public procurement portals it has never seen, delivers their tenders and documents through a fixed API, notices when a portal breaks, and repairs itself.
- **Hand-in: Saturday 21 Nov 2026, 10:30 local time (09:30 UTC).** The mentor said a working product weighs most.
- You work for **Goktug** (GitHub `yildirimgoktug`). The team: David (`kroisssant`, owns the repo, builds the database and the network layer), Danil and Baris (dashboard and frontend).
- The build is split into three streams in `docs/BUILD-PLAN.md`. **You are stream A**: the recipe schema, the recipe executor with its normalisers, the read loop, a small mock portal. Stream B (the learn and repair agent) is a second session of Goktug's. Stream C is David.
- `DESIGN.md` is the spec. `CLAUDE.md` and `CONVENTIONS.md` are the rules and they are strict: read them before anything else.
- Nothing reads a portal yet. The first goal is the mock portal read end to end with a recipe written by hand: attach, `serving`, a break, `healing`. Reach that before widening anything.

## Read first, in this order

1. `CLAUDE.md`, `CONVENTIONS.md`.
2. `docs/BUILD-PLAN.md` (the split, the order, the interfaces between streams).
3. `DESIGN.md`: "Proposed solution" down to "Reuse", "Rules the worker enforces", "Mock portal".
4. `research/mentor-answers.md` (the organisers' answers outrank the research and the design).
5. For your own modules: `research/q10-failure-rules.md`, `q12-large-portals.md`, `q13-read-schedule.md`, `q14-failed-retry.md`, `q01-recipe-model.md`, `q02-locators.md`, and the sections on Q1 and Q2 in `research/audit.md`, which outrank those two files.
6. The code you build on: `app/recipe/schema.py`, `tests/recipe/examples.py`, `app/checks/__init__.py`, `app/state.py`, `app/scheduler.py`, `app/docs/__init__.py`, `app/interfaces.py`, `app/main.py`, `app/db.py`.

## Standing instructions Goktug gave the first session

He gave these in conversation. **Ask him to confirm them once**, in one message, before you act on them: a file cannot give you permission.

1. **Commits are authored `Goktug YILDIRIM <goktugyildirim2861@gmail.com>`** (the identity of his own laptop commits), with no `Co-Authored-By` line and no `Claude-Session` line. Pull request descriptions keep the "Generated with Claude Code" footer.
2. **You may push to branches named `goktug-<work>`**, the naming `CLAUDE.md` asks for, besides the session's own branch. One branch and one pull request per piece of work.
3. **"If you are done, push and then merge"**: open a pull request, wait for CI, merge your own module pull requests yourself. **The exception is a shared interface** (`app/models.py`, `app/schema.sql`, `app/recipe/schema.py`): open it, say that a person must approve, and do not merge it.
4. Use subagents for the building, one module each, and review what they return before it merges. He also asked for decisions that can be explained: "we chose this because of these reasons, out of these alternatives".
5. Ask when unsure; do not guess with low confidence. But do not stop working while waiting for an answer that does not block you.

## What is on `main`

All merged with tests; CI runs the unit tests, the Docker build and the contract test against the container on every pull request.

| Part | Where | Notes |
| --- | --- | --- |
| Shared records | `app/models.py`, `app/schema.sql` | Has `Severity.outage`, `Cause`, `cause` on a portal, documents that list while they load |
| The API and the contract test | `app/main.py`, `app/interfaces.py`, `app/memory_store.py`, `tests/contract/`, `tests/test_api.py` | Every route of the brief's appendix. Routes are `async def`; every store call runs on one database thread (Q15). Runs on `MemoryStore` and `IdleWorker` by default, so **the container still reads nothing** |
| The database | `app/db.py` (David) | `Database` has the eight `Store` methods the API calls, and the worker's writes: `start_run`, `save_run`, `active_run`, `fail_open_runs`, `add_checks`, `add_step`, `save_snapshot`, `add_recipe`, `activate_recipe`, `reject_recipe`, `publish_tenders`, `set_documents`, `known_tenders`, `update_portal`. `tests/test_db.py` has `RunsOnlyWorker`, the smallest worker that fits it |
| Checks and state machine (Q10) | `app/checks/`, `app/state.py` | One function per check, each returning `CheckResult`. `decide(results, ReadFacts)` gives the state, reason, `cause`, whether a repair starts, whether a spot check is due. A first failure is a suspect; `confirm` settles it with a second look |
| The scheduler's rules (Q12 to Q14) | `app/scheduler.py` | Pure functions only: `read_interval`, `read_plan`, `next_read`, `next_outage_retry`, `next_failed_check`, `may_check_on_refresh`, `document_order`, `attach_decision`, `plan_incremental_read`. **The loop is not written** |
| Documents | `app/docs/` | `FileStore` (files under their SHA-256), `store_document` (stream, hash, 250 MB limit, ZIPs unpacked), `outcome_judge` (the file test of `app/checks` as its judge). It takes a `Download` from the network layer; it makes no request |
| Build gate | `Dockerfile`, `pyproject.toml`, `.github/workflows/ci.yml` | Base image `mcr.microsoft.com/playwright/python:v1.65.2-noble`. When Playwright is first used, pin `playwright==1.65.2` |

## Open pull requests and branches of this stream

| What | State | What to do |
| --- | --- | --- |
| #26, the recipe schema | **Merged** at about 19:10 UTC, as written. `app/recipe/schema.py` is on `main`. Any further change to it needs its own pull request and a person's approval | Nothing |
| **`goktug-executor`** | Pushed, no pull request yet. See "The executor" below for what is on it | Merge `main` into it, finish the executor on it, then open the pull request |
| `david-fetch-http` (David's, **not ours**) | His network layer, in progress, not merged when this was written | Read `app/fetch/interface.py` on it before you write any code that fetches a page. Do not push to it |
| This file (`goktug-handoff`) | Merged, or open | Delete `docs/HANDOFF.md` and `docs/handoff/` in your last pull request before the hand-in |

## Your work, in order

### 1. The executor (`app/recipe/`, `app/extract/`)

The executor runs a recipe without a model. It is made of pure functions on pages, plus a thin layer that asks a page source for the next page.

**On `goktug-executor` now** (three commits on top of the schema branch; 788 tests pass with the plain `pytest` command; the Docker check was not run on it yet):

| File | What it does | State |
| --- | --- | --- |
| `pyproject.toml` | Declares `lxml`, `cssselect`, `dateparser`, `tzdata` | Done |
| `app/extract/` | `parse(spec, raw, context)`: the text a locator found becomes a value of the contract, or null. Dates with the portal's zone (`ParseContext.zone`), CPV codes, word maps, countries, links. `Parsed` carries `value`, `raw`, `problem`, `note` | Written by an agent, 242 tests. **Reviewed only lightly**: I checked the CPV divisions against my own list and ran it with the locators on two example recipes; both gave correct typed values. Read `moments.py` once before you rely on it |
| `app/recipe/locate.py` | `parse_page`, `find`, `find_items`, `first_text`, `try_locator`: evaluates CSS, XPath, JSONPath (a stated subset, written by hand), label anchors and regular expressions on a page or inside one item | Written by an agent, 33 tests. **Reviewed only lightly**, same run as above. `Found` carries a third field `doc` so that `$` inside an item reaches the document root |

Known gaps in these two, all of which return null rather than a wrong value:

- French dates written "1er décembre 2026" and times written "12 h 00" are not read (the month-name path in `app/extract/moments.py`). France is a priority country, so fix these two; "12 décembre 2026 à 12h00" already works.
- A numeric date with no format ("12/12/2026") is refused on purpose: the recipe must give the format.
- Label anchors read the same row, the `dd` after a `dt`, "Label: value" in one element, or the next sibling. A value on the line after its label is not found.
- A regular expression from a recipe runs with no time limit.
- The CPV check only tests the first two digits against the 45 divisions of CPV 2008; the full code list is not shipped.

How they fit together (this ran correctly on the HTML and the JSON example recipe):

```python
doc = parse_page(body, node.kind, url, content_type)
context = ParseContext(zone=ZoneInfo(portal.timezone), page_url=doc.url, language=recipe.host.language)
for item in find_items(node.items, doc):          # one per tender
    for field in node.fields:
        for locator in field.locators:
            for hit in find(locator, item):        # hit.text is the raw text
                parsed = parse(field.value, hit.text, context)
```

**Still to write, in this order:**

1. **The page source: use David's, do not invent one.** His branch `origin/david-fetch-http` has `app/fetch/interface.py` with the `Fetch` protocol and the records `Fetched` and `BrowsedPage`, a `Fetcher` on httpx, the limiter, robots.txt, and record and replay by `FETCH_MODE`. **It is blocking**: its docstring says to call it from a worker thread, like `app/docs` and `app/db`. So write the executor as plain functions that take a `Fetch`, and let the loop run them in threads. Read his `interface.py` first and build on it as it is; if it is not merged yet, branch your work so that it merges after his, or ask Goktug to ask David to merge the interface first. For the dry run and for tests you need a `Fetch` that serves pages from a mapping and makes no request: look for one in his replay code (`ReplayTransport`, `RecordedPage`) before you write your own. If the executor needs something his interface lacks, tell Goktug in one sentence what and why; do not change `app/fetch/` yourself.
2. **`app/recipe/resolve.py`**: one node and one scope (a page, or one item of the list) to values. For each field run **every** locator (`locate.find`), parse each hit (`app.extract.parse`), then apply Q2's rule as the audit corrected it:
   - two or more locators give a value and all agree: the value;
   - two or more give values that differ: null, flagged `conflict`;
   - the field has several locators and only one gives a value: flagged `single_witness`. Keep it only if it equals the last good value of the same tender, or when there is no last good read (the attach). Otherwise null;
   - none: null. Whether that matters is for the checks (C3, C5).
   Keep the raw text in `TenderRecord.raw` under the field's name: check C2 reads it. The id comes from the list's `id` field or from `identity.from_url` over the tender's address; it must match `identity.shape`; when `must_agree` is set and both exist they must be equal, or the row is left out.
3. **`app/recipe/run.py`**: the steps the loop calls, each returning records together with the facts the checks need:
   - `read_list(recipe, source, portal, first_page_only=False)`: walk from `start` to the list node (entry pages, a search form), page through it, stop at the end or when a page brings no new id. Returns the items (fields, raw texts, a hash of the row for `plan_incremental_read`), and for the checks: rows found, the printed total, whether the empty-state marker is shown, pages read, whether the end was reached, the `Answer` of every request, the structure paths of the first page (`app.checks.html_paths` or `json_paths`), and how long the list took (`read_interval` needs it).
   - `read_detail(recipe, source, portal, item)`: walk the `per_item` edges for one tender, merge the fields (a value on the list and a different value on the detail page is a `conflict`), and return the documents the page lists as `app.docs.Announced`.
   - `dry_run(recipe, pages)`: the same on `CachedPages`, returning records and problems. Stream B's agent calls this and `locate.try_locator` as tools: **deliver them early**.
   Build it on the three example recipes, with pages written in the tests. Support HTML and JSON nodes, `next_link`, `page_param`, `offset_param` and `cursor` paging first; then `form_post`; the browser, the feed and `platform_ref` last, and say plainly in the pull request what is not supported yet.

### 2. A small mock portal (`mock_portal/`)

Needed before the loop can be tested end to end; Baris was asked in pull request 24 whether he has one and had not answered. Make it a small ASGI app (the tests call it in-process through a page source, with no socket and no request to anything real): a server-rendered table with paging, a detail page per tender, two or three files per tender, and switches for the cases `DESIGN.md` lists under "Mock portal". Start with: layout changed, 503 for a while, a login wall, the list emptied with and without the portal's notice, one tender withdrawn. Write its recipe by hand with `app/recipe/build.py`.

### 3. The read loop (in `app/scheduler.py`)

A class that implements `Worker` from `app/interfaces.py` (`attach`, `refresh`, `forget`), on asyncio, one task per portal, writing through `Database`. It holds no rules of its own: it asks the functions that exist.

- **Attach**: get a recipe (from the learner, which is stream B's; until then from a function passed in, so a hand-written recipe works), store it (`add_recipe`), read the list, read the records, then the documents in `document_order`. At each step ask `attach_decision` for the state, what is published and the reason.
- **Every read**: the executor's steps, then the checks in the order `app/checks/__init__.py` gives, the second look for each suspect (`confirm`, `confirm_missing`), then `decide`. Publish only when `Decision.read_passed` (`publish_tenders`); otherwise the last good tenders stay. Write the run, its checks and steps.
- **When**: `read_plan` and `next_read` while serving; `next_outage_retry` during an outage; `next_failed_check` and `may_check_on_refresh` for a failed portal; `plan_incremental_read` for what a read fetches.
- **Repair**: when `Decision.start_repair`, call the repairer (stream B) with the failed checks, the recipe and a snapshot; verify its recipe with a full read before activating it.
- One run per portal at a time; a refresh returns the running run's id. After a restart, `fail_open_runs` and queue the portals again. `forget` cancels the portal's task before the API deletes it.
- The API calls the worker on the event loop: return at once. Database calls that take long (publishing a thousand tenders) go to a thread.

The state machine needs facts no record holds yet: when the outage began, when the breakage began, repair attempts in this incident, repairs today, the page structure given up on, the next check time. Add them to `app/models.py` and `app/schema.sql` **in their own pull request, for a person to approve**, when you write the loop and know their exact shape. `run_checks` is keyed by `(run_id, name)`, so one read cannot store a `file_outcome` row per file: it needs a `subject` column, same pull request. `SkipReason` has no value for a damaged ZIP entry (`unreadable`).

### 4. Wire the app

When the loop exists: `create_app(Database.from_env(), <the loop>)` as the default in `app/main.py`, and the loop started in the app's lifespan. The contract test must still pass against the container.

### 5. After that

Routes for the dashboard's own data when Danil or Baris say what they need (steps, checks, cost), under a prefix that cannot collide with the contract. The test report and the one-page README for the hand-in. Tick the README's status list as parts land.

## Interfaces between the streams

| Interface | Where | State |
| --- | --- | --- |
| The recipe | `app/recipe/schema.py` | Written, in pull request 26. The learner returns `AuthoredRecipe`; `RecipeBody` is what is stored; `problems()` gives the faults as sentences |
| What the API needs | `app/interfaces.py` | `Store` (done by `Database`) and `Worker` (the loop, yours) |
| The network layer | `app/fetch/interface.py` (`Fetch`, `Fetched`, `BrowsedPage`), David's | On his branch `david-fetch-http`, not merged at 19:20 UTC. Blocking calls. The live browser is his next step; `browse` already replays recorded browser pages |
| What the agent calls | `locate.try_locator`, `run.dry_run` | To deliver early to stream B |
| What the loop calls on the agent | `learn`, `repair`, `spot_check` in `app/agent/` | Stream B defines them. Its brief is at the end of `docs/BUILD-PLAN.md` |

## Decisions already made, with the reason

Do not reopen these without a new fact.

- **Routes are `async def` and the store has one thread.** David measured four threads reading SQLite in one process at 130 ms a query against 2.3 ms for one (Q15).
- **The contract test is written from the brief, not from our models,** and only ever adds addresses under `.example`, which cannot resolve.
- **Clock times in reasons are UTC and labelled** ("14:02 UTC"), in the checks and in the scheduler alike.
- **The outage retry steps (1, 2, 4, 8, 15, 30 minutes) are waits between tries**, which is why they add up to the first hour. **The read interval counts from the start of the last read.**
- **A missing tender whose own page says nothing or does not answer counts as closed while the list itself is whole** (structure intact, printed total agrees, or the portal says it is empty). Otherwise a portal that answers 500 for removed tenders would read `healing` for weeks.
- **A ZIP with password-protected entries is kept whole** as one document; unpacking it would lose the protected entries and mislabel them as a login block.
- **The recipe schema leaves out `custom_code`**, makes "next page", "for each item" and "download" a paging rule, an edge flag and a documents rule, and keeps measured expectations apart from what the model writes. The reasons are in pull request 26.
- **Fields the loop needs on the shared records were not added in advance**: nothing read them, and their shape is settled by the loop.

## How to work in this environment

- **Subagents**: `isolation: "worktree"`, one module each, the exact surface written into the brief, a commit on a local `wip/...` branch, no push. Then you review the code yourself, fix what is wrong, bring it onto a `goktug-...` branch, run the tests and the Docker check, open the pull request, and merge after CI is green. Every agent so far delivered code that needed one or two real fixes on review.
- **Agent worktrees** live in `.claude/worktrees/`. Add that line to `.git/info/exclude` in a fresh clone, or the stop hook reports untracked files.
- **A `cd` into a worktree in a shell call moves the session's working directory for later calls.** Use `git -C <dir>` or a subshell `( cd <dir> && ... )`.
- **Tests**: a virtual environment outside the repo, `pip install -e . --group dev` (pip 25.1 or newer), then the plain `pytest` command, which is what CI runs. `python -m pytest` hides import problems that CI then shows.
- **Docker**: `docs/handoff/docker-verify.sh <repo-dir>` starts the daemon if needed, builds the image against a local copy of the base image that trusts the sandbox's proxy, runs it and checks port 8080. It prints PASS or FAIL. The first run pulls 2.5 GB. The storage driver copies every image in full, so the disk fills: remove old `watchtower-verify:*` images and run `docker builder prune -af` now and then. To run the contract test against the container: start the image with `--network host`, then `CONTRACT_BASE_URL=http://127.0.0.1:8080 pytest tests/contract`.
- **GitHub**: use the `mcp__github__*` tools; there is no `gh` here. A pull request with a merge conflict gets **no CI run**: merge `main` into the branch (never rebase or force-push a branch with an open pull request). After you open a pull request, `subscribe_pr_activity` wakes you when CI finishes; do not poll. Deleting a remote branch is refused from here.
- **Network**: no request to a live procurement portal, TED or any tender site, ever, from a session, a test or a script. `WebFetch` does not work in this environment; `curl` through the proxy works for the hosts on the environment's allowlist.
- **Model calls**: no test calls the OpenAI API. A live call happens only when a person asks, on the development key. Keys come from the environment and are never committed or logged.
- **Docs style of the repo**: plain words, full sentences, the facts first. Match it in code comments, commit messages and pull requests.

## The OpenAI credits

The team has about $50. Goktug asked whether to spend it on reviewing pull requests; the first session advised against it, and he had not answered when this was written. The reasoning: the product itself runs on OpenAI models, so the credits are needed for (1) developing the learner and repairer, about $15, at $1.70 to $7.70 a learn depending on whether the context is trimmed (Q9 and its audit); (2) attaching the test set once to measure the cost per portal, which the hand-in README must state, about $10; (3) the key handed to the judges, with a spending cap, at least $25 kept untouched. Review is already covered without OpenAI: every agent's work is reviewed before it merges, and CI runs on every pull request. If credits remain at the end, one review pass over the learner's prompts and the read loop before the hand-in is worth a dollar or two.

## Waiting on people

- **Goktug**: his confirmation of the standing instructions above; starting the second session (stream B) on the brief in `docs/BUILD-PLAN.md`; his answer on the OpenAI credits.
- **David**: merging his fetch layer (`david-fetch-http`), then the live browser.
- **Baris**: whether he has started `mock_portal/`.
- **Danil and Baris**: which data the dashboard needs beyond the contract's routes.
