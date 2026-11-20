import { ApiError, getJson, portalPath, type FetchLike } from "./api";
import { dashboardSchema, tendersSchema, timelineSchema } from "./schema";
import { demoDashboard, demoTenders, demoTimeline } from "./demo";
import type { Dashboard, DetailView, LedgerState, Route } from "@/types";

export const POLL_MS = 5000;

type Loaded = { source: "live" | "demo"; dashboard: Dashboard; detail: DetailView | null };

/**
 * One source per commit: either every required request is live, or everything is demo.
 * Demo data only when asked for (`?demo` in the address). Otherwise a failed request throws, and
 * the page keeps the last live snapshot marked offline: made-up portals must never look real.
 */
export async function loadRoute(
  fetchImpl: FetchLike,
  route: Route,
  signal: AbortSignal,
  timeoutMs?: number,
  allowDemo = false,
): Promise<Loaded> {
  try {
    if (route.name === "overview") {
      const dashboard = await getJson(fetchImpl, "/api/dashboard", dashboardSchema, signal, timeoutMs);
      return { source: "live", dashboard, detail: null };
    }
    const [d, tl, td] = await Promise.allSettled([
      getJson(fetchImpl, "/api/dashboard", dashboardSchema, signal, timeoutMs),
      getJson(fetchImpl, portalPath(route.id, "timeline"), timelineSchema, signal, timeoutMs),
      getJson(fetchImpl, portalPath(route.id, "tenders"), tendersSchema, signal, timeoutMs),
    ]);
    if (d.status === "rejected") throw d.reason;
    const dashboard = d.value;
    const portal = dashboard.portals.find((p) => p.id === route.id);
    if (!portal) return { source: "live", dashboard, detail: { kind: "notFound" } };
    if (tl.status === "rejected") throw tl.reason;
    if (td.status === "rejected") throw td.reason;
    return {
      source: "live",
      dashboard,
      detail: { kind: "ok", portal, timeline: tl.value, tenders: td.value },
    };
  } catch (e) {
    if (signal.aborted || (e instanceof ApiError && e.kind === "aborted")) throw e;
    if (allowDemo) return loadDemo(route);
    throw e;
  }
}

export function loadDemo(route: Route): Loaded {
  const dashboard = demoDashboard;
  if (route.name === "overview") return { source: "demo", dashboard, detail: null };
  const portal = dashboard.portals.find((p) => p.id === route.id);
  const timeline = demoTimeline(route.id);
  const tenders = demoTenders(route.id);
  if (!portal) return { source: "demo", dashboard, detail: { kind: "notInDemo" } };
  return {
    source: "demo",
    dashboard,
    detail: { kind: "ok", portal, timeline: timeline ?? [], tenders: tenders ?? [] },
  };
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
      dashboard: null,
      detail: null,
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
    this.set({ ...this.state, route, detail: null, source: route.name === "overview" ? this.state.source : null });
    if (this.running) void this.cycle();
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
      loaded = await loadRoute(
        this.fetchImpl,
        route,
        ac.signal,
        this.opts.timeoutMs,
        this.opts.allowDemo,
      );
    } catch (e) {
      loaded = null;
      failed = !ac.signal.aborted && !(e instanceof ApiError && e.kind === "aborted"); // the API, not a navigation
    }
    if (gen !== this.gen) return; // obsolete
    this.ac = null;
    if (failed) this.set({ ...this.state, offline: true });
    if (loaded) {
      const live = loaded.source === "live";
      const now = (this.opts.now ?? Date.now)();
      this.set({
        route,
        source: loaded.source,
        dashboard: loaded.dashboard,
        detail: loaded.detail,
        liveAt: live ? now : this.state.liveAt,
        everOnline: this.state.everOnline || live,
        livePulse: live ? this.state.livePulse + 1 : this.state.livePulse,
        offline: false,
      });
    }
    if (this.running) {
      this.timer = setTimeout(() => void this.cycle(), this.opts.intervalMs ?? POLL_MS);
    }
  }

  /** Replace settings after an acknowledged save. */
  acceptSettings(settings: Dashboard["settings"]) {
    if (!this.state.dashboard) return;
    this.set({ ...this.state, dashboard: { ...this.state.dashboard, settings } });
  }
}
