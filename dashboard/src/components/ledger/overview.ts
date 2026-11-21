// Pure view helpers for the overview. Everything here is derived from the wire data; nothing is invented.
import { absTime, hostname } from "@/data/format";
import { sortPortals } from "@/data/view";
import type { Portal, PortalState, Run } from "@/types";
import { hasActiveRepair } from "./evidence";

export interface SentencePart { state: PortalState; count: number; text: string; highlight: boolean }

/** "8 portals. 4 serving, 1 repairing itself, 1 being learned, 2 need attention." */
export function fleetSentence(portals: Portal[]): { total: number; parts: SentencePart[] } {
  const of = (state: PortalState) => portals.filter((p) => p.state === state);
  const healing = of("healing");
  const repairing = healing.length > 0 && healing.every((p) => hasActiveRepair(p) || p.cause === "breakage");
  const failed = of("failed").length;
  const raw: [PortalState, number, string][] = [
    ["serving", of("serving").length, "serving"],
    ["healing", healing.length, repairing ? (healing.length === 1 ? "repairing itself" : "repairing themselves") : "healing"],
    ["integrating", of("integrating").length, "being learned"],
    ["failed", failed, failed === 1 ? "needs attention" : "need attention"],
  ];
  const present = raw.filter(([, count]) => count > 0);
  const lit = present.some(([state]) => state === "healing") ? "healing" : "serving";
  return { total: portals.length, parts: present.map(([state, count, text]) => ({ state, count, text, highlight: state === lit })) };
}

export const stillServing = (p: Portal) =>
  p.state === "healing" && p.tenderCount > 0 ? `still serving ${p.tenderCount} tender${p.tenderCount === 1 ? "" : "s"}` : null;

const mean = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null);

/** Average recorded model cost of the portals that have a validated recipe, repairs included. */
export function costPerPortal(portals: Portal[]) {
  const delivering = portals.filter((p) => p.recipeVersion != null && p.usage);
  const eur = (ps: Portal[]) => mean(ps.map((p) => p.usage?.costEur ?? 0));
  return {
    count: delivering.length,
    average: eur(delivering),
    learned: eur(delivering.filter((p) => !p.reusedFrom)),
    reused: eur(delivering.filter((p) => p.reusedFrom)),
  };
}

/** HH:MM in the portal's zone, or as written when the zone is unknown. */
export const clock = (iso: string, timeZone?: string | null) => /\d{2}:\d{2}/.exec(absTime(iso, timeZone))?.[0] ?? "";

export interface TickerItem { key: string; portalId: string; host: string; time: string | null; kind: Run["kind"] | null; result: Run["result"]; text: string }

/**
 * Latest run summaries across the fleet. With runs for every portal these are the newest runs;
 * otherwise each portal's current reason from the one overview snapshot.
 */
export function tickerItems(portals: Portal[], timelines: Record<string, Run[]> | null, limit = 12): TickerItem[] {
  if (timelines && portals.length > 0 && portals.every((p) => timelines[p.id])) {
    const newest = portals
      .flatMap((p) => (timelines[p.id] ?? []).map((run) => ({ p, run })))
      .sort((a, b) => Date.parse(b.run.startedAt) - Date.parse(a.run.startedAt))
      .slice(0, limit);
    if (newest.length) {
      return newest.map(({ p, run }) => ({
        key: `${p.id}:${run.id}`, portalId: p.id, host: hostname(p.url), time: clock(run.startedAt, p.timezone),
        kind: run.kind, result: run.result, text: run.summary ?? "",
      }));
    }
  }
  return sortPortals(portals).slice(0, limit).map((p) => ({
    key: p.id, portalId: p.id, host: hostname(p.url), time: null,
    kind: p.lastRun?.kind ?? null,
    result: p.lastRun ? p.lastRun.result : p.state === "failed" ? "failed" : p.state === "serving" ? "ok" : null,
    text: p.reason,
  }));
}

/** Newest finished, passing repair across the given timelines. */
export function latestRepair(portals: Portal[], timelines: Record<string, Run[]>): { portal: Portal; run: Run } | null {
  let best: { portal: Portal; run: Run } | null = null;
  for (const portal of portals) {
    for (const run of timelines[portal.id] ?? []) {
      if (run.kind !== "repair" || run.result !== "ok") continue;
      if (!best || Date.parse(run.startedAt) > Date.parse(best.run.startedAt)) best = { portal, run };
    }
  }
  return best;
}

// Fleet analytics

/** Sums per-portal series slot by slot, aligned at the newest end. A portal adds nothing to slots before its history starts. */
function alignRight(series: number[][]): number[] {
  const length = Math.min(30, Math.max(0, ...series.map((s) => s.length)));
  const out = Array<number>(length).fill(0);
  for (const s of series) {
    const tail = s.slice(-length);
    tail.forEach((v, i) => { const at = length - tail.length + i; out[at] = (out[at] ?? 0) + v; });
  }
  return out;
}

export interface ReadSeries {
  /** per slot, oldest to newest, over the last 30 read slots of every portal */
  passed: number[]; failed: number[]; running: number[];
  totalPassed: number; totalFailed: number; totalRunning: number;
  /** share of finished reads that passed; null when no read has finished */
  passRate: number | null;
}

/** Null when no portal's read history is recorded at all. */
export function readSeries(portals: Portal[]): ReadSeries | null {
  const known = portals.map((p) => p.recentReads).filter((r): r is NonNullable<Portal["recentReads"]> => r !== null);
  if (!known.length) return null;
  const of = (want: "ok" | "failed" | null) => alignRight(known.map((reads) => reads.slice(-30).map((r) => (r === want ? 1 : 0))));
  const passed = of("ok"), failed = of("failed"), running = of(null);
  const sum = (xs: number[]) => xs.reduce((s, x) => s + x, 0);
  const totalPassed = sum(passed), totalFailed = sum(failed);
  return {
    passed, failed, running, totalPassed, totalFailed, totalRunning: sum(running),
    passRate: totalPassed + totalFailed > 0 ? totalPassed / (totalPassed + totalFailed) : null,
  };
}

/** Tenders published per read, summed over portals, oldest to newest. Null when no portal records it. */
export function deliverySeries(portals: Portal[]): number[] | null {
  const known = portals.map((p) => p.deliveryTrend).filter((t): t is number[] => t !== null);
  return known.length ? alignRight(known) : null;
}

export interface CostBar { id: string; host: string; eur: number | null; tokens: number | null }

/** Recorded model cost per portal, highest first; portals without recorded usage come last. */
export function costBars(portals: Portal[]): CostBar[] {
  return portals
    .map((p) => ({ id: p.id, host: hostname(p.url), eur: p.usage ? p.usage.costEur : null, tokens: p.usage ? p.usage.inputTokens + p.usage.outputTokens : null }))
    .sort((a, b) => (b.eur ?? -1) - (a.eur ?? -1) || a.host.localeCompare(b.host));
}

/** Running total of recorded model cost over the fleet's runs, oldest to newest. Null without usage on at least two runs. */
export function costSeries(timelines: Record<string, Run[]> | null): number[] | null {
  if (!timelines) return null;
  const paid = Object.values(timelines).flat().filter((r) => r.usage).sort((a, b) => Date.parse(a.startedAt) - Date.parse(b.startedAt));
  if (paid.length < 2) return null;
  let total = 0;
  return paid.map((r) => (total += r.usage?.costEur ?? 0));
}

export interface FleetEvent {
  key: string; portalId: string; host: string;
  kind: "repair" | "failure" | "attach";
  result: Run["result"];
  title: string; text: string;
  /** when it started; null when the event comes from a portal's current state rather than a run */
  at: string | null;
}

/**
 * Repairs, failed reads and attaches, newest first. From recorded runs when there are any; otherwise
 * from the portals that are failed or healing right now, with their reason.
 */
export function fleetEvents(portals: Portal[], timelines: Record<string, Run[]> | null, limit = 12): FleetEvent[] {
  const events: FleetEvent[] = [];
  for (const p of portals) {
    const host = hostname(p.url);
    for (const run of timelines?.[p.id] ?? []) {
      const base = { key: `${p.id}:${run.id}`, portalId: p.id, host, result: run.result, at: run.startedAt };
      if (run.kind === "repair") {
        const title = run.result === null ? "Repair running" : run.result === "ok" ? "Repair verified" : "Repair failed";
        const fallback = run.result === null ? "The agent is repairing this portal." : run.result === "ok" ? "The repair passed its verifying read." : "The repair did not pass verification.";
        events.push({ ...base, kind: "repair", title, text: run.summary ?? fallback });
      } else if (run.trigger === "attach") {
        const title = run.result === null ? "Attaching" : run.result === "ok" ? "Portal attached" : "Attach failed";
        events.push({ ...base, kind: run.result === "failed" ? "failure" : "attach", title, text: run.summary ?? "First read of a new portal." });
      } else if (run.result === "failed") {
        events.push({ ...base, kind: "failure", title: "Read failed", text: run.summary ?? "A read did not pass its checks." });
      }
    }
  }
  if (events.length) return events.sort((a, b) => Date.parse(b.at ?? "") - Date.parse(a.at ?? "")).slice(0, limit);
  return sortPortals(portals).filter((p) => p.state === "failed" || p.state === "healing").slice(0, limit).map((p): FleetEvent => ({
    key: p.id, portalId: p.id, host: hostname(p.url), kind: p.state === "healing" ? "repair" : "failure",
    result: p.state === "healing" ? null : "failed", title: p.state === "healing" ? "Healing" : "Failed", text: p.reason, at: null,
  }));
}

/** The zone most portals are in, for the wall clock; null when no portal's zone is recorded. */
export function fleetZone(portals: Portal[]): string | null {
  const counts = new Map<string, number>();
  for (const p of portals) if (p.timezone) counts.set(p.timezone, (counts.get(p.timezone) ?? 0) + 1);
  let best: string | null = null;
  for (const [zone, n] of counts) if (best === null || n > (counts.get(best) ?? 0)) best = zone;
  return best;
}
