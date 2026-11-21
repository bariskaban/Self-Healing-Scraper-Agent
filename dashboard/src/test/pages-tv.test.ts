import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { demoDashboard, demoTimeline } from "@/data/demo";
import { isEditable, parsePage, tvParam } from "@/components/pages/nav";
import { TV_SLIDE_MS, costSeries, deliveredSeries, pickRepair, readBuckets, readHealth, readsHourSeries, useTvRotation } from "@/components/pages/tv";
import type { Run } from "@/types";

function setReducedMotion(reduce: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: reduce && query.includes("prefers-reduced-motion"), media: query, onchange: null,
      addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
    }),
  });
}

const timelines = (): Record<string, Run[]> => {
  const out: Record<string, Run[]> = {};
  for (const p of demoDashboard.portals) { const t = demoTimeline(p.id); if (t) out[p.id] = t; }
  return out;
};
const NOW = Date.parse(demoDashboard.asOf);

describe("TV rotation", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); setReducedMotion(false); });

  it("advances every 12 s and wraps after the last slide", () => {
    setReducedMotion(false);
    const { result } = renderHook(() => useTvRotation(3));
    expect(TV_SLIDE_MS).toBe(12_000);
    expect(result.current).toMatchObject({ index: 0, stacked: false, paused: false });
    act(() => { vi.advanceTimersByTime(TV_SLIDE_MS - 1); });
    expect(result.current.index).toBe(0);
    act(() => { vi.advanceTimersByTime(1); });
    expect(result.current.index).toBe(1);
    act(() => { vi.advanceTimersByTime(TV_SLIDE_MS * 2); });
    expect(result.current.index).toBe(0);
  });

  it("goes to the next, previous and a numbered slide by hand, restarts the countdown, and pauses", () => {
    setReducedMotion(false);
    const { result } = renderHook(() => useTvRotation(4));
    act(() => { vi.advanceTimersByTime(TV_SLIDE_MS - 1); });
    act(() => { result.current.next(); });
    expect(result.current.index).toBe(1);
    act(() => { vi.advanceTimersByTime(TV_SLIDE_MS - 1); });
    expect(result.current.index).toBe(1); // the countdown started again after the manual change
    act(() => { vi.advanceTimersByTime(1); });
    expect(result.current.index).toBe(2);
    act(() => { result.current.prev(); });
    expect(result.current.index).toBe(1);
    act(() => { result.current.go(3); });
    expect(result.current.index).toBe(3);
    act(() => { result.current.go(9); }); // no such slide: nothing happens
    expect(result.current.index).toBe(3);
    act(() => { result.current.toggle(); });
    expect(result.current.paused).toBe(true);
    act(() => { vi.advanceTimersByTime(TV_SLIDE_MS * 5); });
    expect(result.current.index).toBe(3);
    act(() => { result.current.toggle(); });
    act(() => { vi.advanceTimersByTime(TV_SLIDE_MS); });
    expect(result.current.index).toBe(0);
  });

  it("does not rotate under reduced motion: no timer runs and the slides are stacked", () => {
    setReducedMotion(true);
    const { result } = renderHook(() => useTvRotation(3));
    expect(vi.getTimerCount()).toBe(0);
    act(() => { vi.advanceTimersByTime(TV_SLIDE_MS * 10); });
    expect(result.current).toMatchObject({ index: 0, stacked: true });
  });

  it("clears its timer when the wallboard closes", () => {
    setReducedMotion(false);
    const { unmount } = renderHook(() => useTvRotation(3));
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("page routes and shortcuts", () => {
  it("matches only the three page hashes", () => {
    expect(parsePage("#/tv")).toBe("tv");
    expect(parsePage("#/scale/")).toBe("scale");
    expect(parsePage("#/tenders")).toBe("tenders");
    expect(parsePage("#/")).toBeNull();
    expect(parsePage("#/portal/tv")).toBeNull();
    expect(parsePage("#/tvx")).toBeNull();
  });

  it("reads ?tv=1 and nothing else as the wallboard switch", () => {
    expect(tvParam("?tv=1")).toBe(true);
    expect(tvParam("?run=m8&tv=1")).toBe(true);
    expect(tvParam("?tv=0")).toBe(false);
    expect(tvParam("")).toBe(false);
  });

  it("never treats typing in a field as the T shortcut", () => {
    expect(isEditable(document.createElement("input"))).toBe(true);
    expect(isEditable(document.createElement("textarea"))).toBe(true);
    expect(isEditable(document.createElement("button"))).toBe(false);
    expect(isEditable(null)).toBe(false);
  });
});

describe("wallboard series, from the demo snapshot", () => {
  it("counts the share of finished reads that passed and leaves running reads out", () => {
    const h = readHealth(demoDashboard.portals);
    expect(h).toMatchObject({ passed: 18, failed: 7, running: 1 });
    expect(h.share).toBeCloseTo(18 / 25);
    expect(readHealth([]).share).toBeNull();
  });

  it("buckets every finished read exactly once, in at most 12 buckets", () => {
    const tl = timelines();
    const s = readBuckets(tl, NOW);
    expect(s).not.toBeNull();
    const finished = Object.values(tl).flat().filter((r) => r.kind === "read" && r.result !== null);
    expect(s!.buckets.length).toBeLessThanOrEqual(12);
    expect(s!.buckets.reduce((n, b) => n + b.passed, 0)).toBe(finished.filter((r) => r.result === "ok").length);
    expect(s!.buckets.reduce((n, b) => n + b.failed, 0)).toBe(finished.filter((r) => r.result === "failed").length);
    expect(readBuckets({}, NOW)).toBeNull();
  });

  it("ends the delivered series at the fleet's current published total", () => {
    const s = deliveredSeries(timelines());
    expect(s.at(-1)).toBe(demoDashboard.portals.reduce((n, p) => n + p.tenderCount, 0));
  });

  it("puts each read of the last hour in one 5-minute window", () => {
    const tl = timelines();
    const s = readsHourSeries(tl, NOW);
    expect(s).toHaveLength(12);
    const lastHour = Object.values(tl).flat().filter((r) => r.kind === "read" && NOW - Date.parse(r.startedAt) < 3_600_000 && Date.parse(r.startedAt) <= NOW);
    expect(s.reduce((n, x) => n + x, 0)).toBe(lastHour.length);
  });

  it("accumulates only recorded usage in the cost series", () => {
    const tl = timelines();
    const recorded = Object.values(tl).flat().reduce((n, r) => n + (r.usage?.costEur ?? 0), 0);
    expect(costSeries(tl).at(-1)).toBeCloseTo(recorded);
    expect(costSeries({})).toEqual([]);
  });

  it("shows the repair in flight, and falls back to the last passing repair", () => {
    const tl = timelines();
    const live = pickRepair(demoDashboard.portals, tl);
    expect(live).toMatchObject({ live: true, run: { id: "m8" }, portal: { id: "mock" } });
    const done = pickRepair(demoDashboard.portals.map((p) => (p.id === "mock" ? { ...p, state: "serving" as const } : p)), tl);
    expect(done).toMatchObject({ live: false, run: { id: "m4" } });
    expect(pickRepair(demoDashboard.portals.filter((p) => p.id !== "mock"), tl)).toBeNull();
  });
});
