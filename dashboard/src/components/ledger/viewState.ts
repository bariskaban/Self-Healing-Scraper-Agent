// View-only state that is not part of the data layer: theme, the run a link wants opened, and the
// timelines the overview shows in its spotlight and ticker.
import { useEffect, useMemo, useRef, useState } from "react";
import { getJson, portalPath } from "@/data/api";
import { demoTimeline } from "@/data/demo";
import { timelineSchema } from "@/data/schema";
import { sortPortals } from "@/data/view";
import type { Dashboard, Run, Source } from "@/types";
import { hasActiveRepair } from "./evidence";

export type ThemePref = "dark" | "light" | "system";
const KEY = "watchtower.theme";

/** Dark is the default. The choice is the only thing persisted. */
export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(() => {
    try {
      const v = localStorage.getItem(KEY);
      return v === "light" || v === "system" ? v : "dark";
    } catch { return "dark"; }
  });
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => document.documentElement.classList.toggle("dark", pref === "dark" || (pref === "system" && mq.matches));
    apply();
    mq.addEventListener("change", apply);
    try { localStorage.setItem(KEY, pref); } catch { /* private mode */ }
    return () => mq.removeEventListener("change", apply);
  }, [pref]);
  const cycle = () => setPref((p) => (p === "dark" ? "light" : p === "light" ? "system" : "dark"));
  return { pref, cycle };
}

/** A run to open when the portal page appears: `?run=<id>` on entry, or set by an "Inspect" link. */
let pendingRun: string | null = (() => {
  try { return new URLSearchParams(window.location.search).get("run"); } catch { return null; }
})();
export const setPendingRun = (id: string | null) => { pendingRun = id; };
export const takePendingRun = () => { const id = pendingRun; pendingRun = null; return id; };

/**
 * Timelines for the overview. Demo: the bundled ones, for every portal. Live: only the portal with a
 * repair in flight, re-read with each new snapshot, so the overview stays one snapshot plus at most
 * one timeline. A failed read keeps the last good copy and never mixes in demo data.
 */
export function useOverviewTimelines(d: Dashboard | null, source: Source | null, enabled: boolean): Record<string, Run[]> {
  const [live, setLive] = useState<Record<string, Run[]>>({});
  const repairId = d && source === "live" && enabled ? sortPortals(d.portals).find(hasActiveRepair)?.id ?? null : null;
  const asOf = d?.asOf;
  const inFlight = useRef(false);
  useEffect(() => {
    if (!repairId || inFlight.current) return;
    const ac = new AbortController();
    inFlight.current = true;
    getJson((u, i) => window.fetch(u, i), portalPath(repairId, "timeline"), timelineSchema, ac.signal)
      .then((timeline) => setLive({ [repairId]: timeline }))
      .catch(() => { /* keep the last good copy */ })
      .finally(() => { inFlight.current = false; });
    return () => ac.abort();
  }, [repairId, asOf]);
  const demo = useMemo(() => {
    if (!d || source !== "demo") return null;
    const out: Record<string, Run[]> = {};
    for (const p of d.portals) { const t = demoTimeline(p.id); if (t) out[p.id] = t; }
    return out;
  }, [d, source]);
  if (source === "demo") return demo ?? {};
  return repairId && live[repairId] ? { [repairId]: live[repairId] } : {};
}
