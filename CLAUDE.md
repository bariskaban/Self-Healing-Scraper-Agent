# CLAUDE.md

Guidance for working in this repository. See README.md for how to run it and CHECKME.md for the team's guide and project status.

## Source of truth

- `DESIGN.md` is the spec. Read it before you start, and build what it says.
- Each decision in `DESIGN.md` names its research question (Q1 to Q14). The reasons and thresholds are in `research/qNN-*.md`; the register is `research/README.md`.
- Order of precedence, highest first: the track description and the API contract (`hackathon-pdfs/Patterno-Track-Description.pdf`, summarised in `DESIGN.md`); the corrections in `research/audit.md`; the research answer files; `DESIGN.md`; `CONVENTIONS.md`. Between two research files, the question owner's file beats side notes in other files, and our own measurements beat published figures.
- If you find two of these disagreeing, do not settle it yourself in code. Say so in the pull request, or stop and ask.
- Numbers the design marks as our own choice (thresholds, intervals, budgets) are settings in config, never constants in the logic.

## Building with agents

- The system is written by AI agents, one module per agent and branch. The modules are listed in `DESIGN.md` (Build plan, Modules) and laid out in `CONVENTIONS.md`. Stay inside your module, and use other modules only through their interfaces.
- Shared interfaces change only in a pull request of their own, approved by a person: `app/models.py`, `app/schema.sql` and the recipe schema. Never change them as a side effect of other work.
- A pull request is done when the unit tests, the contract test and `docker build .` for linux/amd64 pass. Say in the pull request which of these you ran and what they returned. Do not report work as done otherwise.
- Follow `CONVENTIONS.md`: one network choke point, no model call in a regular read, prompts in files, models and prices in config, every step logged.

## Network: no live portals

- Never send a request to a live procurement portal, TED or any other tender site, whether from an agent session, a test or a script.
- Each test portal is recorded once, by a person, with `FETCH_MODE=record`. Agents work with `FETCH_MODE=replay`, the mock portal in `mock_portal/`, or the fixtures in `tests/fixtures/`. Replay is the default of `app/fetch`; only the Dockerfile sets `FETCH_MODE=live`. Never set it anywhere else.
- If a recording you need is missing, stop and ask for one. Do not fetch it live.
- Every request the code makes goes through `app/fetch/`. No direct httpx calls or Playwright navigation anywhere else.
- Why: several agents testing the same portal at once break the rule of 1 request per second per portal before the judges ever see the system, and can get our address blocked.

## Model calls

- Tests never call the OpenAI API. Mock the model, or replay recorded responses.
- Every model call goes through `app/agent/runner.py`. Nothing imports `openai` outside `app/agent/`.
- Live model calls happen only when a person asks for them, on the development key, which has its own spending cap. Never use the judging key for development.
- Keys come from environment variables. Never commit a key, and never write one to a log.

## Git workflow

- Never commit directly to `main`. Every change is made on a separate branch.
- Branch naming: `<name>-<work>`, where `<name>` is the person doing the work, or the person running the agent, and `<work>` is a short description of the change, in lowercase with hyphens (for example `joshua-gateway-allowlists`).
- When the work is done, push the branch, open a pull request into `main`, and merge the PR. Do not merge branches locally or push straight to `main`.
- Keep each branch and PR focused on one piece of work.

## Dependencies

- Every new package must be added to `pyproject.toml` in the same change that starts using it. Put runtime packages under `dependencies` and development-only tools (test, lint) under the `dev` dependency group.
- `pyproject.toml` does not exist yet. The first change that needs a package creates it, declaring `pydantic`, which `app/models.py` already uses.
- Do not install a package into the virtual environment without also declaring it in `pyproject.toml`. The environment must be reproducible from `pyproject.toml` alone.
- Use sensible minimum version constraints, as the existing entries do.
- Pin `playwright` to the version of the Playwright base image in the Dockerfile (Q6).

## Environment

- The project uses Python 3.12 (3.11 or newer required). `.python-version` does not exist yet; the first setup change adds it with `3.12`.
- Work inside the `.venv` virtual environment, and never commit it.
- Do not commit secrets, `.env` files or generated local data. There is no `.gitignore` yet: check `git status` before every commit, and the first setup change adds one covering `.venv/`, `.env`, `DATA_DIR` and recordings.
