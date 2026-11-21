# Dashboard API

The JSON the dashboard at `GET /` reads. The Platform fills these routes from SQLite (`app/db.py`). Until they exist, the page runs on the public contract routes alone ("Live · basic", see below); only when the API cannot be reached at all does it show its bundled demo data with a "Demo data" badge.

- `GET /api/dashboard`: every 5 s.
- `GET /api/portals/{id}/timeline`: every 5 s, only while a portal's page is open.
- `GET /api/portals/{id}/tenders?limit=50&offset=N`: the tender list of a portal's page, 50 rows per request, the next page only when the user scrolls near the end of the list box, at most 500 rows. The poll never reloads it. `GET /api/portals/{id}/tenders/{tenderId}`: one tender with its files, when its row is opened. No page calls the public `GET /portals/{id}/tenders` route.
- The overview also reads `GET /api/portals/{id}/timeline`, for at most 16 portals: once per portal, and again only when that portal's `lastRun` changed or is still running. It feeds the "Live repair" card, the run ticker and the "Recent events" feed. Nothing changed, no extra request.
- `POST /api/settings`: sets the attach time limit and the robots.txt test switch (mentor answers 1b and 7).
- `POST /portals {"url"}` (the public contract route): the "Add portal" sheet sends one request per address, one after another, then reads the data again at once. The same address gives the same id, which the sheet shows as "Already watched". This and the settings are the page's only writes; it never deletes, refreshes or repairs.

## Live without /api/dashboard ("Live · basic")

Order of sources: 1. the `/api` routes ("Live"). 2. If the server answers but `/api/dashboard` is not there (404, or an answer that is not a dashboard) and `GET /portals` answers a JSON array, the page renders live from the public contract routes ("Live · basic"). 3. The bundled snapshot ("Demo data"), only when the API is unreachable or a request the view needs fails. One view never mixes live and demo data.

In basic mode a row is `PortalOut` (`id`, `url`, `state`, `reason`, `tenderCount`, `lastSuccessAt`, `cause`). The overview also reads `GET /portals/{id}/runs` per portal (the first 24 rows), which gives the last run, the 30-read history and the reads in the last hour. A portal page reads `GET /portals/{id}/runs` as its timeline and, once per page open (not on every poll), `GET /portals/{id}/tenders`, cut to the first 500 rows in the browser with a note in the header. This is the only place the page uses that route. Everything the contract does not carry (software, recipe, next read, published counts, model usage, run summaries, checks, agent steps, the EUR rate, settings) is null and shows as "Not recorded"; nothing is invented. Settings are read-only in this mode.

Field names follow `app/models.py` (`Portal`, `Run`, `RunStats`, `TokenUsage`, `CheckResult`, `AgentStep`, `Recipe.rationale`), in camelCase. These are extra routes; the public Patterno contract is not changed. Written with GPT-6.2 Astra, 20 Nov 2026.


Use two **read projections** over the store. The overview is one snapshot, not eight detail requests. The timeline is a bare run array enriched for inspection; the tenders endpoint remains the **public** bare array. IDs are opaque. All `Time` strings include an offset. The examples in §6 are the wire shapes (unwrap one portal key for a detail GET).

```ts
type Time = string;
type State = "serving" | "healing" | "integrating" | "failed";
type Cause = "outage" | "block" | "breakage" | null;
type Kind = "read" | "repair";
type Result = "ok" | "failed" | null;
type Trigger = "attach" | "schedule" | "refresh" | "recheck" | "heal";
type Settings = { attachTimeLimitMinutes: number; ignoreRobotsTxt: boolean };

interface Usage {
  inputTokens: number; outputTokens: number;
  cachedInputTokens?: number; reasoningTokens?: number; // omitted subsets = 0
  costUsd: number; costEur: number;
}
interface PortalRow {
  id: string; url: string; state: State; reason: string;
  tenderCount: number; lastSuccessAt: Time | null;
  cause: Cause; fingerprint: string | null; timezone: string | null;
  recipeVersion: number | null; reusedFrom?: string; nextReadAt: Time | null;
  lastRun: { id: string; kind: Kind; result: Result } | null;
  recentReads: Result[];       // last ≤30 read starts, oldest first; null = running
  deliveryTrend: number[];     // last ≤30 publications, oldest first
  readsLastHour: number;       // computed before limiting history
  usage: Usage | null;         // cumulative posted model usage, null = unknown
}
interface Dashboard {         // GET /api/dashboard
  asOf: Time; eurPerUsd: number; settings: Settings; portals: PortalRow[];
}
interface RunStats {
  httpRequests: number; pagesFetched: number; tendersSeen: number;
  tendersNew: number; tendersChanged: number; tendersUnlisted: number;
  filesDownloaded: number; filesSkipped: number; bytesDownloaded: number;
}
interface Check {
  name: string; passed: boolean; severity: "info" | "warn" | "fail" | "block";
  message: string; observed?: unknown; expected?: unknown;
}
interface Step {
  seq: number; at: Time; kind: "llm" | "tool" | "decision" | "note";
  name: string; summary: string; durationMs: number | null; usage?: Usage | null;
}
interface Run {
  id: string; kind: Kind; startedAt: Time; finishedAt: Time | null; result: Result;
  trigger: Trigger; recipeVersion?: number; summary: string;
  publishedCount?: number;    // length of snapshot published by THIS run; 0 is a publication
  stats?: Partial<RunStats>;  // only reported counters; absent ≠ measured zero
  modelCalls: number; usage?: Usage | null;
  checks?: Check[]; steps?: Step[]; // nested rows belong to enclosing run
  recipeChange?: { from: number; to: number; rationale: string; changedParts: string[] };
}
type TimelineResponse = Run[]; // GET /api/portals/{id}/timeline; chronological on wire

interface TenderDocument {
  fileName: string; sizeBytes: number | null; sha256: string | null; path: string | null;
}
interface Tender {               // TenderOut in app/models.py
  // Always present, null when the portal does not show the value:
  id: string; url: string | null; title: string | null; buyerName: string | null;
  publicationDate: string | null;  // a plain date, "2026-12-09", no time and no offset
  submissionDeadline: Time | null; status: "open" | "closed" | "withdrawn";
  documents: TenderDocument[] | null; lastChangedAt: Time;
  // Left out when empty, never sent as null:
  referenceNumber?: string; description?: string;
  procedureType?: "open" | "restricted" | "negotiated" | "other";
  // Also sent when known, not shown by the page: contractNature?, cpvCodes?, placeOfPerformance?
}
type TendersResponse = Tender[]; // GET /portals/{id}/tenders
// POST /api/settings: body Settings → 200 Settings (effective values)
// Invalid values → 422; positive integer minutes, strict boolean, no extra keys.
```

Settings request and success shape: `{"attachTimeLimitMinutes":20,"ignoreRobotsTxt":false}`. Read current settings from the dashboard; update the drawer from the POST acknowledgement. Do not reset dirty inputs on polls.

`summary` projects `reasonAfter`, a short error, or the last recorded progress message. `recipeChange` compares the validated recipe with its parent and takes the wording from `Recipe.rationale`; a candidate version isn't an active version. `publishedCount` is captured at commit, **not** estimated from `stats.tendersSeen`. `cause:null` is normal for an attach in progress without an incident. Optional check/trace arrays with no detail display “No checks recorded” / “No steps recorded”, not “All passed”.

`costEur = costUsd × eurPerUsd` throughout, same fixed rate for the snapshot and its timelines. Server aggregates across all runs, not just those loaded on screen. Run usage may be omitted for `modelCalls:0` (known zero); for a paid call with unavailable accounting use `null`. A tool step with no model has no model charge; an LLM step with missing usage has **unknown** cost. Derive the state counts, total delivered, reads and recorded spend from `portals` in one render.


## Building the page

The source is in `dashboard/` (React, Vite, TypeScript, Tailwind; designed in Lovable, project "Tender Trail Watchtower"). The built page is committed in `app/dashboard/static/`, so `docker build` needs no Node:

```bash
cd dashboard && bun install --frozen-lockfile && bun run build
```

Only `bun.lock` is committed, so use bun, not `npm ci`. Then replace `app/dashboard/static/` with the contents of `dashboard/dist/`. The Inter font is bundled from `@fontsource-variable/inter`, so the page still makes no request to a font host or CDN. `/?run=<run id>#/portal/<id>` opens that run's sheet directly, which is handy for the demo video. `GET /` serves `index.html`, and `/assets/*` serves the bundle (`app/main.py`).

- **A run's `kind` on these two routes.** The reader repairs inside the read that confirmed the breakage, so the stored run is a `read`. Here it is sent as `repair` when it changed the recipe (`recipeChange` is set) or when the repairer worked in it (it has a step of the repairer), and a portal's `lastRun` is sent as `repair` while a run is going on and the portal is `healing` a breakage. The brief's own route, `GET /portals/{id}/runs`, sends the stored kind unchanged.
