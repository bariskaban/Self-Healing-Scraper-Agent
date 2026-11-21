import type { z } from "zod";
import { ApiError, contractPath, getJson, portalPath, type FetchLike } from "./api";
import { contractPortalsSchema, contractRunsSchema, dashboardSchema, tendersSchema, timelineSchema } from "./schema";
import { demoDashboard, demoTenders, demoTimeline } from "./demo";
import type { Dashboard, DetailView, LedgerState, Portal, Route, Run } from "@/types";

export const POLL_MS = 5000;
/** Basic live reads each portal's runs for the overview; a very large fleet gets them for the first rows only. */
export const BASIC_RUNS_CAP = 24;

type Loaded = {
  source: "live" | "demo";
  basic: boolean;
  dashboard: Dashboard;
  detail: DetailView | null;
  fleetRuns: Record<string, Run[]> | null;
};
type ContractPortal = z.infer<typeof contractPortalsSchema>[number];
type ContractRun = z.infer<typeof contractRunsSchema>[number];

/** /api/dashboard itself did not deliver; the cause decides whether the contract routes are worth a try. */
class NoDashboard extends Error {
  constructor(public readonly reason: unknown) { super("no dashboard"); }
}

const aborted = (e: unknown, signal: AbortSignal) => signal.aborted || (e instanceof ApiError && e.kind === "aborted");

/**
 * Order of sources. 1: the /api routes (full live). 2: when the server answers but /api/dashboard is
 * not there (404, or an answer that is not a dashboard), the public contract routes (basic live).
 * 3: the bundled snapshot, only when asked for (`?demo` in the address). Otherwise a failed request
 *    throws and the page keeps the last live snapshot, marked offline.
 * One source per commit: a view never mixes live and demo data.
 */
export async function loadRoute(
  fetchImpl: FetchLike,
  route: Route,
  signal: AbortSignal,
  timeoutMs?: number,
  allowDemo = false,
  now: () => number = Date.now,
): Promise<Loaded> {
  try {
    return await loadFull(fetchImpl, route, signal, timeoutMs);
  } catch (e) {
    if (aborted(e, signal)) throw e;
    const cause = e instanceof NoDashboard ? e.reason : null;
    if (aborted(cause, signal)) throw cause;
    if (cause instanceof ApiError && cause.kind !== "network") {
      try {
        return await loadBasic(fetchImpl, route, signal, timeoutMs, now);
      } catch (e2) {
        if (aborted(e2, signal)) throw e2;
      }
    }
    // Demo data only when asked for (`?demo`): made-up portals must never stand in for a down API.
    if (allowDemo) return loadDemo(route);
    throw cause ?? e;
  }
}

async function loadFull(fetchImpl: FetchLike, route: Route, signal: AbortSignal, timeoutMs?: number): Promise<Loaded> {
  const full = { source: "live" as const, basic: false, fleetRuns: null };
  if (route.name === "overview") {
    let dashboard: Dashboard;
    try {
      dashboard = await getJson(fetchImpl, "/api/dashboard", dashboardSchema, signal, timeoutMs);
    } catch (e) {
      throw new NoDashboard(e);
    }
    return { ...full, dashboard, detail: null };
  }
  const [d, tl, td] = await Promise.allSettled([
    getJson(fetchImpl, "/api/dashboard", dashboardSchema, signal, timeoutMs),
    getJson(fetchImpl, portalPath(route.id, "timeline"), timelineSchema, signal, timeoutMs),
    getJson(fetchImpl, portalPath(route.id, "tenders"), tendersSchema, signal, timeoutMs),
  ]);
  if (d.status === "rejected") throw new NoDashboard(d.reason);
  const dashboard: Dashboard = d.value;
  const portal = dashboard.portals.find((p) => p.id === route.id);
  if (!portal) return { ...full, dashboard, detail: { kind: "notFound" } };
  if (tl.status === "rejected") throw tl.reason;
  if (td.status === "rejected") throw td.reason;
  return { ...full, dashboard, detail: { kind: "ok", portal, timeline: tl.value, tenders: td.value } };
}

const basicRun = (r: ContractRun): Run => ({ ...r, trigger: null, summary: null, modelCalls: null });

/**
 * A row from PortalOut. Its runs, when they were read, give the last run, the read history and the
 * reads in the last hour. Everything else the contract does not carry stays null.
 */
export function basicRow(p: ContractPortal, runs: ContractRun[] | null, now: number): Portal {
  const reads = runs?.filter((r) => r.kind === "read") ?? null;
  const last = runs?.length ? runs[runs.length - 1] : undefined;
  return {
    id: p.id, url: p.url, state: p.state, reason: p.reason, tenderCount: p.tenderCount,
    lastSuccessAt: p.lastSuccessAt, cause: p.cause ?? null,
    fingerprint: null, timezone: null, recipeVersion: null, nextReadAt: null, usage: null,
    lastRun: last ? { id: last.id, kind: last.kind, result: last.result } : null,
    recentReads: reads ? reads.slice(-30).map((r) => r.result) : null,
    deliveryTrend: null,
    readsLastHour: reads
      ? reads.filter((r) => { const age = now - Date.parse(r.startedAt); return age >= 0 && age <= 3_600_000; }).length
      : null,
  };
}

/** Live from the public contract routes only: GET /portals, and per portal /runs and /tenders. */
async function loadBasic(
  fetchImpl: FetchLike, route: Route, signal: AbortSignal, timeoutMs: number | undefined, now: () => number,
): Promise<Loaded> {
  const list = await getJson(fetchImpl, "/portals", contractPortalsSchema, signal, timeoutMs);
  const at = now();
  const shell = (portals: Portal[]): Dashboard => ({ asOf: new Date(at).toISOString(), eurPerUsd: null, settings: null, portals });
  const runsOf = (id: string) => getJson(fetchImpl, contractPath(id, "runs"), contractRunsSchema, signal, timeoutMs);
  if (route.name === "overview") {
    const settled = await Promise.allSettled(list.slice(0, BASIC_RUNS_CAP).map((p) => runsOf(p.id)));
    if (signal.aborted) throw new ApiError("aborted", "aborted");
    const fleetRuns: Record<string, Run[]> = {};
    const portals = list.map((p, i) => {
      const r = settled[i];
      const runs = r && r.status === "fulfilled" ? r.value : null;
      if (runs) fleetRuns[p.id] = runs.map(basicRun);
      return basicRow(p, runs, at);
    });
    return { source: "live", basic: true, dashboard: shell(portals), detail: null, fleetRuns };
  }
  const row = list.find((p) => p.id === route.id);
  if (!row) {
    return { source: "live", basic: true, dashboard: shell(list.map((p) => basicRow(p, null, at))), detail: { kind: "notFound" }, fleetRuns: null };
  }
  // Both are required for the page: if either fails, the caller falls back to the snapshot as a whole.
  const [runs, tenders] = await Promise.all([
    runsOf(route.id),
    getJson(fetchImpl, contractPath(route.id, "tenders"), tendersSchema, signal, timeoutMs),
  ]);
  const portal = basicRow(row, runs, at);
  return {
    source: "live", basic: true,
    dashboard: shell(list.map((p) => (p.id === route.id ? portal : basicRow(p, null, at)))),
    detail: { kind: "ok", portal, timeline: runs.map(basicRun), tenders },
    fleetRuns: null,
  };
}

export function loadDemo(route: Route): Loaded {
  const demo = { source: "demo" as const, basic: false, fleetRuns: null };
  const dashboard: Dashboard = demoDashboard;
  if (route.name === "overview") return { ...demo, dashboard, detail: null };
  const portal = dashboard.portals.find((p) => p.id === route.id);
  const timeline = demoTimeline(route.id);
  const tenders = demoTenders(route.id);
  if (!portal) return { ...demo, dashboard, detail: { kind: "notInDemo" } };
  return { ...demo, dashboard, detail: { kind: "ok", portal, timeline: timeline ?? [], tenders: tenders ?? [] } };
}

export const routesEqual = (a: Route, b: Route) =>
  a.name === b.name && (a.name === "overview" || (b.name === "portal" && a.id === b.id));

/**
 * Polls the route's required endpoints. Cycles never overlap; a route change aborts the
 * in-flight cycle and ignores its late result.
 */
export class LedgerController {
  state: LedgerState;
  private gen = 0;
  private ac: AbortController | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private listeners = new Set<(s: LedgerState) => void>();

  constructor(
    private fetchImpl: FetchLike,
    route: Route,
    private opts: {
      intervalMs?: number;
      timeoutMs?: number;
      now?: () => number;
      allowDemo?: boolean;
    } = {},
  ) {
    this.state = {
      route,
      source: null,
      basic: false,
      dashboard: null,
      detail: null,
      fleetRuns: null,
      liveAt: null,
      everOnline: false,
      livePulse: 0,
    };
  }

  subscribe(fn: (s: LedgerState) => void) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private set(next: LedgerState) {
    this.state = next;
    this.listeners.forEach((l) => l(next));
  }

  start() {
    this.running = true;
    void this.cycle();
  }

  stop() {
    this.running = false;
    this.gen++;
    this.ac?.abort();
    this.ac = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  setRoute(route: Route) {
    if (routesEqual(route, this.state.route)) return;
    this.gen++;
    this.ac?.abort();
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    // keep dashboard (header/strip) but drop detail so the new route skeletons once
    this.set({ ...this.state, route, detail: null, source: route.name === "overview" ? this.overviewSource() : null });
    if (this.running) void this.cycle();
  }

  /**
   * The source of the overview when no cycle has committed for it. While the API is offline the
   * dashboard kept from the last live answer is still the last live snapshot (a failed request
   * never loads the demo), so the overview goes on showing it instead of a skeleton that never ends.
   */
  private overviewSource(offline = this.state.offline): LedgerState["source"] {
    return this.state.source ?? (offline && this.state.dashboard ? "live" : null);
  }

  /** Read again now, for example right after a portal was added. Replaces any cycle in flight. */
  refresh(): Promise<void> {
    this.ac?.abort();
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    return this.cycle();
  }

  /** Runs one cycle; resolves after committing (or discarding a stale result). */
  async cycle(): Promise<void> {
    const gen = ++this.gen;
    const ac = new AbortController();
    this.ac = ac;
    const route = this.state.route;
    let loaded: Loaded | null = null;
    let failed = false;
    try {
      loaded = await loadRoute(this.fetchImpl, route, ac.signal, this.opts.timeoutMs, this.opts.allowDemo, this.opts.now);
    } catch (e) {
      loaded = null;
      failed = !ac.signal.aborted && !(e instanceof ApiError && e.kind === "aborted"); // the API, not a navigation
    }
    if (gen !== this.gen) return; // obsolete
    this.ac = null;
    if (failed) this.set({ ...this.state, offline: true, source: route.name === "overview" ? this.overviewSource(true) : this.state.source });
    if (loaded) {
      const live = loaded.source === "live";
      const now = (this.opts.now ?? Date.now)();
      this.set({
        route,
        source: loaded.source,
        basic: loaded.basic,
        dashboard: loaded.dashboard,
        detail: loaded.detail,
        fleetRuns: loaded.fleetRuns,
        liveAt: live ? now : this.state.liveAt,
        everOnline: this.state.everOnline || live,
        livePulse: live ? this.state.livePulse + 1 : this.state.livePulse,
        offline: false,
      });
    }
    if (this.running) {
      if (this.timer) clearTimeout(this.timer);
      this.timer = setTimeout(() => void this.cycle(), this.opts.intervalMs ?? POLL_MS);
    }
  }

  /** Replace settings after an acknowledged save. */
  acceptSettings(settings: Dashboard["settings"]) {
    if (!this.state.dashboard) return;
    this.set({ ...this.state, dashboard: { ...this.state.dashboard, settings } });
  }
}
