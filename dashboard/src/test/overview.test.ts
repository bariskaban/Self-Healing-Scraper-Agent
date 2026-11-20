import { describe, expect, it } from "vitest";
import { demoDashboard, demoTimeline } from "@/data/demo";
import { costPerPortal, fleetSentence, latestRepair, stillServing, tickerItems } from "@/components/ledger/overview";
import { repairSlides } from "@/components/ledger/Spotlight";
import type { Portal, Run } from "@/types";

const portals = demoDashboard.portals;
const timelines = Object.fromEntries(portals.map((p) => [p.id, demoTimeline(p.id) ?? []])) as Record<string, Run[]>;

describe("overview copy is derived from the snapshot", () => {
  it("writes the fleet sentence from the state counts and highlights the repair", () => {
    const { total, parts } = fleetSentence(portals);
    expect(total).toBe(8);
    expect(parts.map((p) => `${p.count} ${p.text}`)).toEqual(["4 serving", "1 repairing itself", "1 being learned", "2 need a person"]);
    expect(parts.filter((p) => p.highlight).map((p) => p.state)).toEqual(["healing"]);
  });
  it("leaves out states with no portal and never calls an outage wait a repair", () => {
    const waiting = { ...portals[0], state: "healing", cause: "outage", lastRun: null } as Portal;
    expect(fleetSentence([waiting]).parts.map((p) => p.text)).toEqual(["healing"]);
  });
  it("says what a healing portal still serves, and nothing for other states", () => {
    expect(portals.map(stillServing).filter(Boolean)).toEqual(["still serving 2 tenders"]);
  });
  it("averages recorded cost over portals with a recipe only", () => {
    const per = costPerPortal(portals);
    expect(per.count).toBe(5);
    expect(per.average).toBeCloseTo(0.02376, 5);
    expect(per.reused).toBeCloseTo(0.0018, 5);
    expect(costPerPortal([]).average).toBeNull();
  });
});

describe("ticker and spotlight use recorded runs", () => {
  it("lists the newest run summaries when every timeline is present", () => {
    const items = tickerItems(portals, timelines, 3);
    expect(items.map((i) => i.key)).toEqual(["merc:mc1", "mock:m8", "t24:t1"]);
    expect(items[1]?.text).toContain("Testing a new path");
  });
  it("falls back to each portal's reason when timelines are missing", () => {
    const items = tickerItems(portals, { mock: timelines["mock"] ?? [] });
    expect(items).toHaveLength(8);
    expect(items.every((i) => i.time === null)).toBe(true);
  });
  it("walks the active repair without claiming a change or a pass", () => {
    const run = timelines["mock"]?.find((r) => r.id === "m8");
    if (!run) throw new Error("Missing fixture");
    const slides = repairSlides(run, timelines["mock"] ?? [], "Europe/Amsterdam");
    expect(slides.map((s) => s.label)).toEqual(["Broke", "Agent action", "Changed", "Verified"]);
    expect(slides[0]?.tags).toEqual(["detail_links"]);
    expect(slides[2]?.meta).toBe("No verified change yet");
    expect(slides[3]?.meta).toBe("Verification running");
  });
  it("finds the newest verified repair", () => {
    expect(latestRepair(portals, timelines)?.run.id).toBe("m4");
  });
});
