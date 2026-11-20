// View-only state that is not part of the data layer: theme, the run a link wants opened, and the
// runs the overview shows in its spotlight, ticker and analytics.
import { useEffect, useMemo, useRef, useState } from "react";
import { getJson, portalPath } from "@/data/api";
import { demoTimeline } from "@/data/demo";
import { timelineSchema } from "@/data/schema";
import type { LedgerState, Run } from "@/types";

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

/** The overview reads timelines for at most this many portals. */
export const TIMELINE_CAP = 16;

/**
 * Runs per portal for the overview's spotlight, ticker and analytics, always from the same source
 * as the rows. Demo: the bundled timelines. Basic live: the runs the controller already read from
 * the contract routes. Full live: GET /api/portals/{id}/timeline, read once per portal and again
 * only when that portal's last run changed or is still running; a failed read keeps the last good
 * copy and never mixes in demo data.
 */
export function useOverviewTimelines(state: LedgerState, enabled: boolean): Record<string, Run[]> {
  const { dashboard: d, source, basic, fleetRuns } = state;
  const full = enabled && source === "live" && !basic ? d : null;
  const [live, setLive] = useState<Record<string, Run[]>>({});
  const seen = useRef(new Map<string, string>());
  const inFlight = useRef(false);
  useEffect(() => {
    if (!full || inFlight.current) return;
    const due = full.portals.slice(0, TIMELINE_CAP).filter((p) => {
      const mark = `${p.lastRun?.id ?? ""}:${p.lastRun?.result ?? "running"}`;
      return seen.current.get(p.id) !== mark || (p.lastRun !== null && p.lastRun.result === null);
    });
    if (!due.length) return;
    const ac = new AbortController();
    inFlight.current = true;
    void Promise.allSettled(due.map((p) => getJson((u, i) => window.fetch(u, i), portalPath(p.id, "timeline"), timelineSchema, ac.signal)))
      .then((results) => {
        if (ac.signal.aborted) return;
        const got: Record<string, Run[]> = {};
        results.forEach((r, i) => {
          const p = due[i];
          if (!p || r.status !== "fulfilled") return;
          got[p.id] = r.value;
          seen.current.set(p.id, `${p.lastRun?.id ?? ""}:${p.lastRun?.result ?? "running"}`);
        });
        if (Object.keys(got).length) setLive((prev) => ({ ...prev, ...got }));
      })
      .finally(() => { inFlight.current = false; });
    return () => ac.abort();
  }, [full]);
  const demo = useMemo(() => {
    if (!d || source !== "demo") return null;
    const out: Record<string, Run[]> = {};
    for (const p of d.portals) { const t = demoTimeline(p.id); if (t) out[p.id] = t; }
    return out;
  }, [d, source]);
  const fullLive = useMemo(() => {
    if (!full) return {};
    const out: Record<string, Run[]> = {};
    for (const p of full.portals) { const t = live[p.id]; if (t) out[p.id] = t; }
    return out;
  }, [full, live]);
  if (source === "demo") return demo ?? EMPTY;
  if (source === "live" && basic) return fleetRuns ?? EMPTY;
  return fullLive;
}
const EMPTY: Record<string, Run[]> = {};
