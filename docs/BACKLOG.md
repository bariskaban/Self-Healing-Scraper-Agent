# Backlog

Work that is outside the current purpose. Nothing here is scheduled. Each item says why it is parked.

## B1. Live API response viewer (a page that polls an endpoint in a loop)

**Status:** parked. Outside the track's purpose, so not part of the hand-in.

**What:** a small standalone web page that calls an API endpoint on a fixed interval, forever, and shows the latest response as it arrives. The first target is our own `GET /api/dashboard` (see `docs/DASHBOARD_API.md`). A developer can watch the raw JSON change while a read runs.

**Why it might help:** debugging and demos. It shows the raw contract the dashboard sees, without the dashboard's rendering in between.

**Behaviour**
- A URL field (default `/api/dashboard`) and an interval setting (default 2 s, minimum 1 s).
- Each tick: fetch, then show the status code, the round-trip time, the time received, and the pretty-printed JSON body.
- Highlight what changed since the previous response (changed keys or lines).
- A pause/resume button and a "clear" button. A tick counter and an error counter.
- Failure is shown, never hidden: a network error or non-2xx status appears on the page and the loop continues. The last good response stays visible, marked stale.
- No overlapping requests: the next tick starts only after the previous one finishes (or times out, default 10 s).
- Back off after repeated failures (for example double the interval, up to 30 s) and say so on the page.

**Constraints (from CLAUDE.md and CONVENTIONS.md)**
- Same-origin only, pointed at our own API. It must never poll a live procurement portal or TED. Reject any URL that is not same-origin, or put an allow-list in config.
- The interval, timeout, back-off cap and default URL are settings in config, not constants in the code.
- It is read-only: GET requests only, no `POST /api/settings`.
- No model calls, no keys on the page.
- It lives in its own folder (for example `tools/api-viewer/`), static HTML and JS, with no new runtime package in `pyproject.toml`. It does not touch `app/models.py`, `app/schema.sql` or the recipe schema.
- Work on a branch named `<name>-api-viewer`, and open its own pull request.

**Done when**
- Opened against the running app, it updates on the interval for at least 10 minutes with no growth in memory use or open requests.
- Stopping the API shows the error and the stale marker, and starting it again recovers without a page reload.
- A test (browser or unit) covers: no overlapping requests, back-off after failures, and rejection of a cross-origin URL.

**Open questions**
- Served by the FastAPI app (a route under `dashboard/`), or opened as a local file with the API allowing it? Prefer the app, to keep it same-origin.
- Should it also watch `GET /api/portals/{id}/timeline`, with a portal picker?
