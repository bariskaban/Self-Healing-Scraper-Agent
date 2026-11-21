import type { Dashboard, Portal, PortalState, Run } from "@/types";
import { hostname, sumUsage, type CostSummary } from "./format";

export const STATE_ORDER: PortalState[] = ["failed", "healing", "integrating", "serving"];

export const STATE_META: Record<PortalState, { label: string; tip: string }> = {
  serving: { label: "Serving", tip: "Serving: the last read passed every check and its tenders are delivered." },
  healing: {
    label: "Healing",
    tip: "Repairing itself: the site changed; the agent is fixing the recipe; the last correct tenders are still served.",
  },
  integrating: { label: "Integrating", tip: "Being learned: the agent is working out how to read this portal; nothing is published yet." },
  failed: { label: "Failed", tip: "Needs a person: the portal cannot be read correctly (a login, a block or a failed repair), or it is not answering (an outage); it is still re-checked." },
};

/** The cause in a few words, next to the state. Null when there is no cause or the state already says it. */
export function causeWord(p: Pick<Portal, "state" | "cause" | "reason">): string | null {
  if (!p.cause || p.state === "serving" || p.state === "integrating") return null;
  if (p.cause === "outage") return "Outage";
  if (p.cause === "breakage") return "Layout changed";
  if (p.cause === "block") return /log ?in|sign ?in/i.test(p.reason) ? "Login required" : "Blocked";
  return null;
}

/** The tooltip of a state badge, told for its cause when that changes what it means. */
export function stateTip(p: Pick<Portal, "state" | "cause" | "reason">): string {
  if (p.state === "failed" && p.cause === "outage") return "Outage: the portal is not answering right now. Its last good tenders are still served and it is checked again automatically.";
  return STATE_META[p.state].tip;
}

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
  /** null when no portal's read count is recorded (contract-only rows whose runs could not be read) */
  readsLastHour: number | null;
  cost: CostSummary;
}

export function fleetSummary(d: Dashboard): FleetSummary {
  const counts = { failed: 0, healing: 0, integrating: 0, serving: 0 };
  for (const p of d.portals) counts[p.state]++;
  const reads = d.portals.map((p) => p.readsLastHour).filter((n): n is number => n !== null);
  return {
    counts,
    tendersDelivered: d.portals.reduce((s, p) => s + p.tenderCount, 0),
    readsLastHour: d.portals.length > 0 && reads.length === 0 ? null : reads.reduce((s, n) => s + n, 0),
    cost: sumUsage(d.portals.map((p) => p.usage)),
  };
}

export type Slot = "ok" | "failed" | "running" | "empty";

/** 30 slots oldest → newest, padded with empty slots on the left. */
export function readSlots(recent: NonNullable<Portal["recentReads"]>): Slot[] {
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
