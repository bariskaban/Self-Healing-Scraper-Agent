import { describe, expect, it } from "vitest";
import { demoDashboard } from "@/data/demo";
import { TARGET_PORTALS, costBasis, eurFine, families, observedKnownShare, project } from "@/components/pages/scaleMath";
import type { Portal } from "@/types";

const portals = demoDashboard.portals;
const portal = (over: Partial<Portal>): Portal => ({ ...(portals[0] as Portal), ...over });

describe("cost per portal", () => {
  it("splits recorded cost by learned and reused recipes, leaving out portals without a recipe", () => {
    const b = costBasis(portals);
    // learned: tn 0.018, nrw 0.036, vm 0.027, mock 0.036; reused: t24 0.0018; es, merc, fr have no recipe
    expect(b.learned).toMatchObject({ portals: 4, recorded: 4 });
    expect(b.learned.averageEur).toBeCloseTo(0.02925);
    expect(b.reused).toMatchObject({ portals: 1, recorded: 1 });
    expect(b.reused.averageEur).toBeCloseTo(0.0018);
    expect(b.withoutRecipe).toBe(3);
  });

  it("reports a missing average as null, never as zero", () => {
    const b = costBasis([portal({ id: "a", usage: null })]);
    expect(b.learned).toEqual({ portals: 1, recorded: 0, averageEur: null });
    expect(b.reused.averageEur).toBeNull();
  });
});

describe("software families", () => {
  it("groups by fingerprint and says which families share a recipe", () => {
    const { families: fams, unknown } = families(portals);
    expect(fams[0]).toMatchObject({ fingerprint: "vmstart", reused: 1, withRecipe: 2, sentence: "2 portals on vmstart share one recipe" });
    expect(fams[0]?.portals.map((p) => p.id).sort()).toEqual(["t24", "vm"]);
    expect(fams).toHaveLength(6);
    expect(unknown.map((p) => p.id)).toEqual(["fr"]);
  });

  it("does not claim a shared recipe when none was reused", () => {
    const { families: fams } = families([portal({ id: "a", fingerprint: "x", reusedFrom: null }), portal({ id: "b", fingerprint: "x", reusedFrom: null })]);
    expect(fams[0]?.sentence).toBe("2 portals on x, no recipe reused yet");
  });

  it("derives the observed share on known software from fingerprints", () => {
    expect(observedKnownShare(portals)).toEqual({ fingerprinted: 7, distinct: 6, share: 1 / 7 });
    expect(observedKnownShare([portal({ fingerprint: null })]).share).toBeNull();
  });
});

describe("projection to 4,500 portals", () => {
  it("is learns × cost per learn + reuses × cost per reuse", () => {
    const p = project({ portals: TARGET_PORTALS, knownShare: 0.8, costPerLearnEur: 0.03, costPerReuseEur: 0.002 });
    expect(p.reuses).toBe(3600);
    expect(p.learns).toBe(900);
    expect(p.learnCostEur).toBeCloseTo(27);
    expect(p.reuseCostEur).toBeCloseTo(7.2);
    expect(p.totalEur).toBeCloseTo(34.2);
    expect(p.allLearnedEur).toBeCloseTo(135);
    expect(p.savingEur).toBeCloseTo(100.8);
  });

  it("keeps learns + reuses equal to the fleet for any share", () => {
    for (const share of [0, 1 / 7, 0.333, 0.5, 0.999, 1]) {
      const p = project({ portals: TARGET_PORTALS, knownShare: share, costPerLearnEur: 1, costPerReuseEur: 0 });
      expect(p.learns + p.reuses).toBe(TARGET_PORTALS);
    }
  });

  it("clamps the share to 0..1", () => {
    expect(project({ portals: 100, knownShare: 1.7, costPerLearnEur: 1, costPerReuseEur: 0.1 }).reuses).toBe(100);
    expect(project({ portals: 100, knownShare: -3, costPerLearnEur: 1, costPerReuseEur: 0.1 }).reuses).toBe(0);
  });

  it("gives no total when a needed cost is not recorded", () => {
    const p = project({ portals: 100, knownShare: 0.5, costPerLearnEur: 0.03, costPerReuseEur: null });
    expect(p.reuseCostEur).toBeNull();
    expect(p.totalEur).toBeNull();
    expect(p.savingEur).toBeNull();
    expect(p.allLearnedEur).toBeCloseTo(3);
  });

  it("does not need a cost for a term that counts no portal", () => {
    expect(project({ portals: 100, knownShare: 0, costPerLearnEur: 0.03, costPerReuseEur: null }).totalEur).toBeCloseTo(3);
    expect(project({ portals: 100, knownShare: 1, costPerLearnEur: null, costPerReuseEur: 0.002 }).totalEur).toBeCloseTo(0.2);
  });

  it("projects the demo snapshot from its own numbers", () => {
    const b = costBasis(portals), share = observedKnownShare(portals).share ?? 0;
    const p = project({ portals: TARGET_PORTALS, knownShare: share, costPerLearnEur: b.learned.averageEur, costPerReuseEur: b.reused.averageEur });
    expect(p.reuses).toBe(643);
    expect(p.learns).toBe(3857);
    expect(p.totalEur).toBeCloseTo(3857 * 0.02925 + 643 * 0.0018);
  });
});

describe("money format", () => {
  it("keeps sub-cent unit costs readable and separates thousands", () => {
    expect(eurFine(0.0018)).toBe("0.0018 EUR");
    expect(eurFine(0.02925)).toBe("0.029 EUR");
    expect(eurFine(113.9697)).toBe("113.97 EUR");
    expect(eurFine(13162.5)).toBe("13,162.50 EUR");
    expect(eurFine(0)).toBe("0.00 EUR");
  });
});
