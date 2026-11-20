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
 * Latest run summaries across the fleet. With timelines for every portal (the bundled snapshot) these
 * are the newest runs; otherwise each portal's current reason from the one overview snapshot.
 */
export function tickerItems(portals: Portal[], timelines: Record<string, Run[]> | null, limit = 12): TickerItem[] {
  if (timelines && portals.length > 0 && portals.every((p) => timelines[p.id])) {
    return portals
      .flatMap((p) => (timelines[p.id] ?? []).map((run) => ({ p, run })))
      .sort((a, b) => Date.parse(b.run.startedAt) - Date.parse(a.run.startedAt))
      .slice(0, limit)
      .map(({ p, run }) => ({
        key: `${p.id}:${run.id}`, portalId: p.id, host: hostname(p.url), time: clock(run.startedAt, p.timezone),
        kind: run.kind, result: run.result, text: run.summary,
      }));
  }
  return sortPortals(portals).slice(0, limit).map((p) => ({
    key: p.id, portalId: p.id, host: hostname(p.url), time: null,
    kind: p.lastRun?.kind ?? null, result: p.lastRun ? p.lastRun.result : "ok", text: p.reason,
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
