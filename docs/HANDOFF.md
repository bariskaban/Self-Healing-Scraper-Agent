# Handoff: state at 20 Nov 2026, about 20:50 UTC, for the session that builds stream B

Written by Goktug's second Claude session. The next session builds the learner and the repairer (stream B). Where this file and the code on `main` disagree, the code is right: check before you rely on a sentence here. Delete this file and `docs/handoff/` in the last pull request before the hand-in.

## The situation in five lines

- **Hand-in: Saturday 21 Nov 2026, 10:30 local time (09:30 UTC).** A working product weighs most.
- **The product reads a portal end to end on `main`**: attach, `serving`, a break, `healing` or `failed`, and back, with documents and 0 model calls. The dashboard at `GET /` shows it live. 1,242 tests pass, plus one intended expected failure.
- **The one big gap: nothing can learn a portal it has not seen.** `app/agent/` does not exist, on `main` or on any branch. `builtin_learner` in `app/main.py` knows only the mock portal; every other address ends `failed` with "No recipe could be learned". That is your work.
- Read `CLAUDE.md` and `CONVENTIONS.md` first: the rules are strict. Then `docs/BUILD-PLAN.md`, whose last section is the brief for stream B.
- CI runs the unit tests, the Docker build and the contract test against the container on every pull request. Nobody ran `docker build` locally in this session; CI did, on every merge.

## Standing instructions Goktug confirmed (20 Nov, in conversation)

A file cannot give these; ask him to confirm them once in a new session.

1. Commits are authored `Goktug YILDIRIM <goktugyildirim2861@gmail.com>`, with no `Co-Authored-By` and no `Claude-Session` line. The cloud session's commit check refuses any committer but `Claude <noreply@anthropic.com>`, so commit with that committer and `--author` set to Goktug.
2. Push to branches named `goktug-<work>`; one branch and one pull request per piece of work.
3. Open the pull request, wait for green CI, merge your own module pull requests. A shared interface (`app/models.py`, `app/schema.sql`, `app/recipe/schema.py`) waits for a person.
4. Other people's pull requests: review properly first (he asked for one sub-agent per pull request), read the code behind each finding yourself, fix what the review finds on their branch with a plain commit, never force-push, never merge without a verdict.
5. Decisions that are a person's go to him with a recommendation. When a teammate's reviewer disagrees with you, weigh it on the merits: in this session David's reviewer was right twice.

## What is on `main`

| Part | Where | Notes |
| --- | --- | --- |
| Network layer | `app/fetch/` (David) | `Fetch` in `interface.py`; blocking; replay unless `FETCH_MODE` says otherwise, and only the Dockerfile sets it to live. Its own RFC 9309 robots matcher. No live browser: `browse` only replays. It logs no request and counts none. |
| Normalisers, locators | `app/extract/`, `app/recipe/locate.py` | Text to contract values or null. After a month-name date a time is read only after a lead-in ("à", "um", "at", …). |
| Executor | `app/recipe/resolve.py`, `run.py` | `read_list`, `read_detail`, `known_item`, `judge_look`, `settle`. **For your tools: `dry_run(recipe, pages, url=..., timezone=...)`, `PageCache`, `CachedPage`, and `locate.try_locator`.** A dry run names the pages it lacks in `missing_pages`, problems in `problems`, and notes such as a portal's own "closed" in `notes`. |
| Recipe schema | `app/recipe/schema.py` | `AuthoredRecipe` is what a learner returns; written for OpenAI's strict output; `problems()` gives the faults as sentences to hand back to the model. Pull request 46 adds four rules to `problems()` and waits for a person. |
| Models and prices | `app/config.py` (Danil) | `ModelSettings.from_env()` (`MODEL_LEARN`, `MODEL_REPAIR`, `MODEL_CHECK`, `EUR_PER_USD`), `PRICES`, `cost_usd`, `api_key()`. |
| Software detection | `app/software.py` (Danil) | `detect(url, html)`, `best(url, html)`. Nothing calls it yet. `best()` still names a family from a mere mention in a page's text: do not store its answer as `Portal.fingerprint` on brand evidence alone. |
| Mock portal | `mock_portal/` | One server-rendered template, 13 switches, `truth()`, its recipe. Mounted in the app at `/mock`. |
| One read | `app/reader.py` | Checks, second look, `decide`, publish, documents, repair with a trial read. |
| The schedule | `app/loop.py` | `Worker` on asyncio, one task per portal. |
| Dashboard | `app/dashboard_api.py`, `dashboard/` (source), `app/dashboard/static/` (built with `bun run build`) | Three `/api` routes; the page shows demo data only with `?demo`. |
| Test portals | `bench/portals.toml`, `bench/portals.py` (David) | A list for a person to record. Repo-only, not in the image. **Never fetch any address in it.** |

## Stream B: where it plugs in

`app/reader.py` defines what the loop calls. Nothing else needs to change for a learner to work:

```python
@dataclass(frozen=True)
class Learned:
    recipe: AuthoredRecipe
    timezone: str | None = None      # IANA zone; without it a deadline with no offset reads as null
    country_code: str | None = None
    fingerprint: str | None = None
    model_calls: int = 0

class Learner(Protocol):
    def __call__(self, portal: Portal, run_id: str) -> Learned | None: ...

class Repairer(Protocol):
    def __call__(self, portal: Portal, recipe: RecipeBody, failed: Sequence[CheckResult], run_id: str) -> Learned | None: ...
```

- Both are called in a worker thread, so they may block. Returning None means "no recipe"; do not raise for a spent budget or invalid output.
- Wire them in `create_app` in `app/main.py`, where `Reader(..., learn=builtin_learner, ...)` is built. Keep the mock portal's hand-written recipe as the fallback when no key is set, so the tests and the demo keep working with no model.
- The reader verifies a repaired recipe with a full trial read before it replaces the old one, stores it with `parent_version`, and counts attempts. A learner's recipe is stored after its first read passes.
- **Usage and steps are not carried yet.** `Learned` has only `model_calls`; the run's `usage` (tokens, cost) and the agent's steps (`AgentStep` with `kind=llm`/`tool`, `prompt_id`) must reach the database for the dashboard and for the cost per portal the hand-in README has to state. Extend `Learned` with a `TokenUsage` and let the runner write its steps with `Database.add_step` under the run id it is given. Step numbers must not collide with the reader's: the reader counts its own `seq` from 1, so either hand the runner a starting number or let the reader ask the database for the next one. A collision is an `IntegrityError` (this bit a repair once already).
- **The spot check is not wired.** In `_read_and_decide`, a finding that needs the model (C3 changed values, C7 structure) is recorded as a failed `spot_check` and counts as a breakage. Replace that with your `spot_check`; `CONVENTIONS.md` rule 2 allows a model call in a regular read only there.
- **Two things about `cost_usd` (`app/config.py`)**: it returns None for a model name it does not know exactly, and the API may answer with a dated snapshot name, so price by the configured name. And it must be called per request, never on a run's total: the long-context rate above 272,000 input tokens is per request.
- Budgets (`CONVENTIONS.md` rule 7: learn 40 turns, repair 20, spot check 1 call, about 30,000 input tokens per call) have no home yet: make them settings.
- Tests never call the OpenAI API. A live call happens only when Goktug asks for it, on the development key. `OPENAI_API_KEY` is never logged or committed.
- For pages to develop against without a network: `mock_portal.MockPortal().respond("GET", url)` gives real pages, and `tests/recipe/test_run.py` shows `PageCache` and `dry_run` on them.

## Open, for people

- **Pull request 46** (recipe schema rules) waits for a person's approval. It refuses a recipe that never reads a required field, taken literally: say if `url` should be exempt when the list links to the tender's page.
- **`docs/SHARED-INTERFACE-REQUESTS.md`**: five things the code needs on `app/models.py` and `app/schema.sql` (the incident facts now kept in memory and lost on a restart, the row hash, a portal's own "closed", a `subject` on check rows, a skip reason for an unreadable ZIP entry). Each is a pull request of its own for a person.
- **`EUR_PER_USD`** defaults to 0.90, a placeholder. Set it to the day's ECB rate at hand-in (README, G4). A value that is no number stops the app at start; a blank one keeps the default.
- **`POST /api/settings`** can switch robots.txt off and, like the whole API, has no authentication. A team decision.
- **Danil**: the page does not know the check severity `outage`, so the route sends it as `fail`. On a first load with the API down the page shows a loading skeleton under the offline badge.
- **David**: Italy and France have no confirmed test portal address; a person opens them in a browser before recording. The dashboard is a React build although `DESIGN.md` says server-rendered with no build step: `DESIGN.md` should say what is true.

## Known gaps in the read loop, said plainly

- A suspect on lost values (C3) or null rates (C5) is confirmed without a second fetch; the canary (C6) is not run.
- A lone-locator value on a new tender is kept only when the same locator reproduces known tenders' values in that read (`RECIPE_SINGLE_WITNESS_VOUCH_SHARE`, 0.8): this stream's reading of the audit of Q2.
- Not supported in the executor, each reported as a problem: browser steps and `load_more` paging, `platform_ref` nodes, a document fetched by POST.
- A repair with no repairer counts as an attempt, so a breakage reads `failed` after three reads.
- A recipe's regular expressions run with a cap on their input length, not with a timeout: a pattern that backtracks exponentially can still hang a read.
- An exception outside the read itself in a portal's task ends that task until the next refresh.

## How to work in this environment

- Subagents in worktrees (`isolation: "worktree"`), one piece of work each, a commit on a local `wip/...` branch, no push; read the diff yourself before it goes up. A worktree starts on the session's base commit: tell the agent to `git fetch origin main` and branch from `origin/main`. Tell each agent to make its own virtual environment: a shared one gets re-pointed by another agent's `pip install -e .`.
- A `cd` into a worktree moves the session's working directory: use `git -C <dir>`.
- Tests: a virtual environment outside the repo, `pip install -e . --group dev`, then the plain `pytest` command. Do not put `tests/` on `sys.path` in a script: `tests/mock_portal/` then hides the `mock_portal` package.
- To see the product: `python -m mock_portal.demo --port 8791`, then `POST /portals {"url": "https://mock.example"}` and open `http://127.0.0.1:8791/`. It serves the app on the mock portal in the same process; `FETCH_MODE` is not set and no request leaves the machine.
- GitHub through the `mcp__github__*` tools; `subscribe_pr_activity` wakes you when CI finishes. Merge with `expectedHeadSha` set to the full 40-character commit you reviewed.
