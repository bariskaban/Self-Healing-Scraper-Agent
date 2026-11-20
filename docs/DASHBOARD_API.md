# Dashboard API

The JSON the dashboard at `GET /` reads. The Platform fills these routes from SQLite (`app/db.py`). Until they exist, the page shows its bundled demo data with a "Demo data" badge, so nothing breaks.

- `GET /api/dashboard`: every 5 s.
- `GET /api/portals/{id}/timeline` and `GET /portals/{id}/tenders` (the public contract route, unchanged): only while a portal's page is open.
- `POST /api/settings`: the only write. It sets the attach time limit and the robots.txt test switch (mentor answers 1b and 7).

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
interface Tender {
  id: string; url: string; title: string; buyerName: string; publicationDate: string;
  submissionDeadline: Time; status: "open" | "closed" | "withdrawn";
  documents: TenderDocument[] | null; lastChangedAt: Time;
  referenceNumber?: string; description?: string;
  procedureType?: "open" | "restricted" | "negotiated" | "other";
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
cd dashboard && npm ci && npm run build
```

Then replace `app/dashboard/static/` with the contents of `dashboard/dist/`. `GET /` serves `index.html`, and `/assets/*` serves the bundle (`app/main.py`).
