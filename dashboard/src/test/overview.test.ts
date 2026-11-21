import { describe, expect, it } from "vitest";
import { demoDashboard, demoTimeline } from "@/data/demo";
import { costPerPortal, fleetSentence, lastVerifiedRepair, latestRepair, stillServing, tickerItems } from "@/components/ledger/overview";
import { causeWord, stateTip } from "@/data/view";
import { portalSchema } from "@/data/schema";
import { repairSlides } from "@/components/ledger/Spotlight";
import type { Portal, Run } from "@/types";

const portals = demoDashboard.portals;
const timelines = Object.fromEntries(portals.map((p) => [p.id, demoTimeline(p.id) ?? []])) as Record<string, Run[]>;

describe("overview copy is derived from the snapshot", () => {
  it("writes the fleet sentence from the state counts and highlights the repair", () => {
    const { total, parts } = fleetSentence(portals);
    expect(total).toBe(8);
    expect(parts.map((p) => `${p.count} ${p.text}`)).toEqual(["4 serving", "1 repairing itself", "1 being learned", "1 needs attention", "1 not answering"]);
    expect(parts.filter((p) => p.highlight).map((p) => p.state)).toEqual(["healing"]);
  });
  it("leaves out states with no portal and never calls an outage wait a repair", () => {
    const waiting = { ...portals[0], state: "healing", cause: "outage", lastRun: null } as Portal;
    expect(fleetSentence([waiting]).parts.map((p) => p.text)).toEqual(["healing"]);
  });
  it("says what a healing portal still serves, and nothing for other states", () => {
    expect(portals.map(stillServing).filter(Boolean)).toEqual(["still serving 2 tenders", "still serving 3 tenders"]);
  });
  it("averages recorded cost over portals with a recipe only", () => {
    const per = costPerPortal(portals);
    expect(per.count).toBe(6);
    expect(per.average).toBeCloseTo(0.02505, 5);
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

describe("review fixes (21 Nov 2026)", () => {
  const fr = portals.find((p) => p.id === "fr")!;
  it("names the cause next to the state", () => {
    expect(causeWord(fr)).toBe("Outage");
    expect(causeWord(portals.find((p) => p.id === "merc")!)).toBe("Login required");
    expect(causeWord(portals.find((p) => p.id === "mock")!)).toBe("Layout changed");
    expect(causeWord(portals.find((p) => p.id === "tn")!)).toBeNull();
    expect(stateTip(fr)).toMatch(/still served/);
  });
  it("finds the newest verified repair", () => {
    const run = lastVerifiedRepair(timelines["mock"]);
    expect(run?.kind).toBe("repair");
    expect(run?.result).toBe("ok");
    expect(lastVerifiedRepair(timelines["tn"])).toBeNull();
    expect(lastVerifiedRepair(undefined)).toBeNull();
  });
  it("reads an unknown state as failed instead of rejecting the portal", () => {
    const raw = { ...fr, state: "paused", cause: 42, reason: undefined };
    const r = portalSchema.safeParse(raw);
    expect(r.success).toBe(true);
    if (r.success) { expect(r.data.state).toBe("failed"); expect(r.data.cause).toBeNull(); expect(r.data.reason).toBe(""); }
  });
});

describe("a live repair whose failing read is inside the run", () => {
  it("takes what broke from the run's own first steps, not from an earlier read that passed", async () => {
    const { repairEvidence } = await import("@/components/ledger/evidence");
    const step = (seq: number, kind: string, name: string, summary: string) => ({ seq, at: "2026-11-21T01:50:40Z", kind, name, summary, durationMs: null, usage: null });
    const read = { id: "r1", kind: "read", trigger: "attach", startedAt: "2026-11-21T01:50:00Z", finishedAt: "2026-11-21T01:50:35Z", result: "ok", modelCalls: 0, checks: [] } as unknown as Run;
    const repair = {
      id: "r2", kind: "repair", trigger: "refresh", startedAt: "2026-11-21T01:50:40Z", finishedAt: "2026-11-21T01:51:18Z", result: "ok", modelCalls: 6,
      steps: [step(1, "note", "read_list", "Read the tender list: 1 page(s), 0 row(s), 0 tender(s)."),
        step(2, "note", "second_look", "Looked a second time because of: list_outcome. The list gave 0 row(s)."),
        step(3, "llm", "gpt-6.2-sol", "Asked the model.")],
      recipeChange: { from: 1, to: 2, rationale: "Cards instead of a table.", changedParts: ["nodes.list"] },
    } as unknown as Run;
    const ev = repairEvidence(repair, [read, repair]);
    expect(ev.triggering).toBeNull();
    expect(ev.broke).toMatch(/0 row\(s\).*second time/);
    expect(ev.brokeChecks).toEqual(["list_outcome"]);
    expect(ev.brokeAt).toBe(repair.startedAt);
    expect(ev.changed).toBe("Recipe v1 → v2: Cards instead of a table.");
  });
});
