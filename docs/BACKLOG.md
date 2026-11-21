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

## Portals with more tenders than the limit: read them in rounds

**Status:** not built. Decided on 21 Nov 2026 (Goktug), a few hours before the hand-in.

**What we met.** `ezamowienia.gov.pl` lists more than 10,000 tenders. The learner found its JSON API and wrote a recipe for $0.53. The first full read then asked for page after page, 100 tenders each, and the API answered HTTP 500 on page 101. Its search does not serve anything past result 10,000, however the pages are cut. So every read made 202 requests, ended as an outage ("the portal did not answer"), and the portal delivered nothing.

**What we did.** `RECIPE_MAX_TENDERS_PER_PORTAL` now defaults to 500 (it was 0, no limit). A read stops at 500 tenders, its reason says "Stopped at the limit of 500 tenders per portal", and the portal is `serving`.

**Why 500 and not more.** In the same run TenderNed was learned in under five minutes, and its list of 4,132 tenders was read in under a minute. Then every tender's own page had to be read, one request a second, before the first tender could be delivered: more than an hour of `integrating` with "nothing delivered yet". We first chose 2,000, which would still have meant about 35 minutes. With 500 a portal of any size delivers in about ten minutes, and a portal with fewer than 500 tenders is not touched by the limit at all. The price: of a portal above the limit only the first 500 tenders are delivered, and the brief asks for every open tender. We chose a part in ten minutes over the whole in an hour or never. The limit is a setting, on the dashboard and in the environment, so an operator who can wait raises it. A list cut at the limit counts as partial, so no tender is closed for being past it. Where the portal lists newest first, every new tender is in the next read, so nothing new is missed from then on; only the old backlog stays out. An operator who wants more sets the variable higher, or to 0.

**What we did not build: rounds.** The first read would take tenders 1 to 500, the next 501 to 1,000, and so on to the end of the list; then it would start again at the top.
- How: keep, per portal, the place where the last round stopped (a page number or an offset). Each read starts there. A tender is closed only when a full pass over all rounds has not seen it, not when one read has not.
- Why not now: today "not in this read" is how the reader learns that a tender left the list. Rounds change that rule in the core of the reader (`app/reader.py`, the plan in `app/scheduler.py`, the check `known_ids_missing`). A mistake there closes open tenders or keeps closed ones open on every portal, and "a wrong value is worse than a missing one".
- It would not have reached the end of e-Zamowienia anyway, because of the API's own stop at 10,000.

**What reaching the end of such a portal would take: slices.** Split the list by a filter the portal offers (publication date by month, region, CPV division), so that each slice has fewer results than the portal's stop, and read every slice as a list of its own.
- How: the learner would have to find a filter, prove that the slices together cover the whole list (their totals add up to the printed total), and write it into the recipe as a new kind of paging. The reader would walk the slices as it walks pages.
- Why not now: it needs a new field in the recipe schema (a shared interface, changed only in a pull request of its own), a new skill for the learner, and a check that the slices are complete. That is a feature of days, not hours.

**Order, when someone picks this up:** rounds first (they help every portal above the limit), slices second (they help only portals whose own API stops early).

