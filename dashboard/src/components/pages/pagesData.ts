// Fleet-wide reads for the extra pages: one fleet snapshot, plus each portal's timeline and/or
// tenders when a page asks for them. Same rule as the data layer: one source per commit. Either the
// snapshot is live and every per-portal read is live (a failed one is null, shown as "Not recorded"),
// or everything is the bundled demo snapshot. Demo data is never mixed into a live commit.
import { useEffect, useRef, useState } from "react";
import { contractPath, getJson, portalPath, tenderPagePath, type FetchLike } from "@/data/api";
import { loadRoute } from "@/data/controller";
import { demoDashboard, demoTenderPage, demoTimeline, toTenderItem } from "@/data/demo";
import { tenderPageSchema, tendersSchema, timelineSchema } from "@/data/schema";
import { TENDER_PAGE_SIZE } from "@/data/tenderPaging";
import type { Dashboard, Run, Source, TenderItem } from "@/types";

export interface Want { timelines: boolean; tenders: boolean }

export interface FleetData {
  source: Source;
  /** Live from the public contract routes only: recipe, fingerprint, cost and run details are null. */
  basic: boolean;
  dashboard: Dashboard;
  /** Per portal id. null = asked for and could not be read. Empty object when the page did not ask. */
  timelines: Record<string, Run[] | null>;
  /** Per portal id: its first page of tenders (no files). null = asked for and could not be read. */
  tenders: Record<string, TenderItem[] | null>;
  /** Per portal id: how many tenders it delivers in all, for the "first 50" line. */
  tenderTotals: Record<string, number>;
}

const PARALLEL = 6;

async function mapPool<T, R>(items: T[], fn: (item: T) => Promise<R>): Promise<R[]> {
  const out = new Array<R>(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i] as T);
    }
  };
  await Promise.all(Array.from({ length: Math.min(PARALLEL, items.length) }, worker));
  return out;
}

export function demoFleet(want: Want): FleetData {
  const ids = demoDashboard.portals.map((p) => p.id);
  return {
    source: "demo",
    basic: false,
    dashboard: demoDashboard,
    timelines: want.timelines ? Object.fromEntries(ids.map((id) => [id, demoTimeline(id)])) : {},
    tenders: want.tenders ? Object.fromEntries(ids.map((id) => [id, demoTenderPage(id, TENDER_PAGE_SIZE, 0)?.items ?? null])) : {},
    tenderTotals: want.tenders ? Object.fromEntries(ids.map((id) => [id, demoTenderPage(id, TENDER_PAGE_SIZE, 0)?.total ?? 0])) : {},
  };
}

/**
 * The snapshot comes from the data layer's own overview read, so the pages follow the same order of
 * sources as the overview: the /api routes, then the public contract routes ("basic" live), then the
 * bundled snapshot. On the /api routes each timeline is its own request; on the contract routes the
 * runs that overview read already hold are the timelines. Tenders are the first page (50) of each
 * portal from the paged /api route; only basic live, where that route is missing, reads the public
 * contract route (once per portal, kept in `basicCache`) and cuts it to the first page.
 */
export async function loadFleet(fetchImpl: FetchLike, want: Want, signal: AbortSignal, timeoutMs?: number,
  allowDemo = typeof window !== "undefined" && new URLSearchParams(window.location.search).has("demo"),
  basicCache: Map<string, { items: TenderItem[]; total: number } | null> = new Map()): Promise<FleetData> {
  const base = await loadRoute(fetchImpl, { name: "overview" }, signal, timeoutMs, allowDemo);
  if (base.source === "demo") return demoFleet(want);
  const dashboard = base.dashboard;
  const ids = dashboard.portals.map((p) => p.id);
  const orNull = async <T>(read: Promise<T>): Promise<T | null> => {
    try { return await read; } catch (e) { if (signal.aborted) throw e; return null; }
  };
  const [timelines, tenders] = await Promise.all([
    !want.timelines ? null
      : base.basic ? ids.map((id): Run[] | null => base.fleetRuns?.[id] ?? null)
        : mapPool(ids, (id): Promise<Run[] | null> => orNull(getJson(fetchImpl, portalPath(id, "timeline"), timelineSchema, signal, timeoutMs))),
    want.tenders ? mapPool(ids, (id): Promise<{ items: TenderItem[]; total: number } | null> => orNull(
      base.basic
        ? (async () => {
            const hit = basicCache.get(id);
            if (hit) return hit;
            const all = await getJson(fetchImpl, contractPath(id, "tenders"), tendersSchema, signal, timeoutMs);
            const first = { items: all.slice(0, TENDER_PAGE_SIZE).map(toTenderItem), total: all.length };
            basicCache.set(id, first);
            return first;
          })()
        : getJson(fetchImpl, tenderPagePath(id, TENDER_PAGE_SIZE, 0), tenderPageSchema, signal, timeoutMs)
            .then((p) => ({ items: p.items, total: p.total })),
    )) : null,
  ]);
  return {
    source: "live",
    basic: base.basic,
    dashboard,
    timelines: timelines ? Object.fromEntries(ids.map((id, i) => [id, timelines[i] ?? null])) : {},
    tenders: tenders ? Object.fromEntries(ids.map((id, i) => [id, tenders[i]?.items ?? null])) : {},
    tenderTotals: tenders ? Object.fromEntries(ids.map((id, i) => [id, tenders[i]?.total ?? 0])) : {},
  };
}

export interface FleetState {
  data: FleetData | null;
  /** ms epoch of the last live commit */
  liveAt: number | null;
  everOnline: boolean;
}

/** Polls while mounted. Cycles never overlap; the next one starts `intervalMs` after the last finished. */
export function useFleet(timelines: boolean, tenders: boolean, intervalMs: number): FleetState {
  const [state, setState] = useState<FleetState>({ data: null, liveAt: null, everOnline: false });
  const basicCache = useRef(new Map<string, { items: TenderItem[]; total: number } | null>());
  useEffect(() => {
    const ac = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const cycle = async () => {
      try {
        const data = await loadFleet((u, i) => window.fetch(u, i), { timelines, tenders }, ac.signal, undefined, undefined, basicCache.current);
        if (ac.signal.aborted) return;
        const live = data.source === "live";
        setState((s) => ({ data, liveAt: live ? Date.now() : s.liveAt, everOnline: s.everOnline || live }));
      } catch { /* aborted */ }
      if (!ac.signal.aborted) timer = setTimeout(() => void cycle(), intervalMs);
    };
    void cycle();
    return () => { ac.abort(); if (timer) clearTimeout(timer); };
  }, [timelines, tenders, intervalMs]);
  return state;
}

/** Only the timelines that were read, for helpers that take a plain record. */
export function knownTimelines(timelines: Record<string, Run[] | null>): Record<string, Run[]> {
  const out: Record<string, Run[]> = {};
  for (const [id, t] of Object.entries(timelines)) if (t) out[id] = t;
  return out;
}

/** Demo data is a frozen snapshot, so "now" is its own timestamp; live data uses the wall clock. */
export const dataNow = (data: FleetData | null, wallClock: number) =>
  data && data.source === "demo" ? Date.parse(data.dashboard.asOf) : wallClock;
