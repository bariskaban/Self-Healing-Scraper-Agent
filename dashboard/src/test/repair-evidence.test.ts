import { describe, expect, it } from "vitest";
import { demoDashboard, demoTimeline } from "@/data/demo";
import { hasActiveRepair, repairEvidence, repairRuns, stepTiming } from "@/components/ledger/evidence";
import type { Run, Step } from "@/types";

describe("selected repair evidence", () => {
  const portal = demoDashboard.portals.find((p) => p.id === "mock");
  const timeline = demoTimeline("mock") ?? [];
  it("qualifies only an active healing repair, not a running read", () => {
    expect(demoDashboard.portals.filter(hasActiveRepair).map((p) => p.id)).toEqual(["mock"]);
  });
  it("keeps active missing links separate from the earlier deadline repair", () => {
    if (!portal) throw new Error("Missing fixture");
    const { active, earlier } = repairRuns(portal, timeline);
    expect(active?.id).toBe("m8");
    expect(earlier?.id).toBe("m4");
    if (!active || !earlier) throw new Error("Missing repair");
    expect(repairEvidence(active, timeline).triggering?.id).toBe("m7");
    expect(repairEvidence(earlier, timeline).triggering?.id).toBe("m3");
    expect(repairEvidence(active, timeline).changed).toContain("Pending");
    expect(repairEvidence(active, timeline).verified).not.toContain("Passed");
    expect(earlier.recipeChange).toMatchObject({ from: 1, to: 2 });
    expect(earlier.checks?.every((check) => check.passed)).toBe(true);
  });
  it("uses Not recorded instead of manufacturing absent evidence", () => {
    const run = { id: "missing", kind: "repair", finishedAt: "2026-11-20T20:00:00Z", result: "failed" } as Run;
    expect(repairEvidence(run, []).changed).toBe("Not recorded");
    expect(repairEvidence(run, []).verified).toBe("Not recorded");
  });
});
describe("recorded waterfall timing", () => {
  it("shares elapsed offsets without treating unknown durations as zero duration", () => {
    const run = demoTimeline("mock")?.find((run) => run.id === "m8");
    if (!run?.steps) throw new Error("Missing fixture");
    const timing = stepTiming(run.steps, run.startedAt);
    expect(timing.offsets).toEqual([0, 6000, 13000]);
    expect(run.steps[2]?.durationMs).toBeNull();
  });
  it("duration-only steps do not imply a start offset", () => {
    const steps = [{ seq: 1, at: "", durationMs: 8000 }] as Step[];
    expect(stepTiming(steps, "")).toMatchObject({ mode: "duration", total: 8000, offsets: [null] });
    expect(stepTiming([{ ...steps[0], durationMs: null }] as Step[], "").mode).toBe("none");
  });
});
