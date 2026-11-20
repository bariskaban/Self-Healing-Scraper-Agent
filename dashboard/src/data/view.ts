import type { Dashboard, Portal, PortalState, Run } from "@/types";
import { hostname, sumUsage, type CostSummary } from "./format";

export const STATE_ORDER: PortalState[] = ["failed", "healing", "integrating", "serving"];

export const STATE_META: Record<PortalState, { label: string; tip: string }> = {
  serving: { label: "Serving", tip: "Validated records are available." },
  healing: {
    label: "Healing",
    tip: "Fresh delivery is interrupted; the last correct records stay available during repair or wait.",
  },
  integrating: { label: "Integrating", tip: "Learning the portal; nothing published yet." },
  failed: { label: "Failed", tip: "Cannot deliver correctly; still being checked." },
};

export function sortPortals(ps: Portal[]): Portal[] {
  return [...ps].sort(
    (a, b) =>
      STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state) ||
      hostname(a.url).localeCompare(hostname(b.url)),
  );
}

export interface FleetSummary {
  counts: Record<PortalState, number>;
  tendersDelivered: number;
  readsLastHour: number;
  cost: CostSummary;
}

export function fleetSummary(d: Dashboard): FleetSummary {
  const counts = { failed: 0, healing: 0, integrating: 0, serving: 0 };
  for (const p of d.portals) counts[p.state]++;
  return {
    counts,
    tendersDelivered: d.portals.reduce((s, p) => s + p.tenderCount, 0),
    readsLastHour: d.portals.reduce((s, p) => s + p.readsLastHour, 0),
    cost: sumUsage(d.portals.map((p) => p.usage)),
  };
}

export type Slot = "ok" | "failed" | "running" | "empty";

/** 30 slots oldest → newest, padded with empty slots on the left. */
export function readSlots(recent: Portal["recentReads"]): Slot[] {
  const last = recent.slice(-30).map((r): Slot => (r === null ? "running" : r));
  return [...Array<Slot>(30 - last.length).fill("empty"), ...last];
}

export function runResultWord(result: "ok" | "failed" | null): "Passed" | "Failed" | "Running" {
  return result === null ? "Running" : result === "ok" ? "Passed" : "Failed";
}

export const newestFirst = (runs: Run[]) =>
  [...runs].sort((a, b) => Date.parse(b.startedAt) - Date.parse(a.startedAt));

/** The read that immediately precedes a repair in the chronological timeline. */
export function triggeringRead(timeline: Run[], repair: Run): Run | null {
  const idx = timeline.findIndex((r) => r.id === repair.id);
  for (let i = idx - 1; i >= 0; i--) {
    const r = timeline[i];
    if (r && r.kind === "read") return r;
  }
  return null;
}

/** Points for the tender-count chart; runs without publishedCount are gaps, not zeros. */
export function publicationSeries(timeline: Run[]) {
  return timeline
    .filter((r) => r.kind === "read")
    .map((r) => ({ id: r.id, t: Date.parse(r.startedAt), count: r.publishedCount ?? null, result: r.result }));
}
