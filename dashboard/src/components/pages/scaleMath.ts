// Cost & scale: pure math. Inputs come from the dashboard snapshot; everything that is a guess about
// the future is a named assumption in `ProjectionInput`, never a constant buried in a formula.
import type { Portal } from "@/types";

export const TARGET_PORTALS = 4500;

const mean = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null);
const hasRecipe = (p: Portal) => p.recipeVersion != null;

export interface CostSide { portals: number; recorded: number; averageEur: number | null }
export interface CostBasis {
  /** Portals with a working recipe that was learned from scratch. */
  learned: CostSide;
  /** Portals with a working recipe taken over from a portal on the same software. */
  reused: CostSide;
  /** Portals without a working recipe yet (being learned, or failed); not part of either average. */
  withoutRecipe: number;
}

/**
 * Recorded model cost to date per portal, split by how the portal got its recipe. The cost is the
 * portal's cumulative usage, so repairs so far are included. Same definition as the overview's
 * "Cost per new portal" card. A portal without recorded usage counts in `portals`, not in `recorded`.
 */
export function costBasis(portals: Portal[]): CostBasis {
  const side = (ps: Portal[]): CostSide => {
    const costs = ps.filter((p) => p.usage).map((p) => p.usage?.costEur ?? 0);
    return { portals: ps.length, recorded: costs.length, averageEur: mean(costs) };
  };
  const ready = portals.filter(hasRecipe);
  return {
    learned: side(ready.filter((p) => !p.reusedFrom)),
    reused: side(ready.filter((p) => p.reusedFrom)),
    withoutRecipe: portals.length - ready.length,
  };
}

export interface Family {
  fingerprint: string;
  portals: Portal[];
  /** Portals of the family that run on a recipe taken over from another portal. */
  reused: number;
  /** Portals of the family that have a working recipe. */
  withRecipe: number;
  /** Sum of the recorded model cost of the family's portals; null when none is recorded. */
  costEur: number | null;
  sentence: string;
}

const count = (n: number) => `${n} portal${n === 1 ? "" : "s"}`;

/** Portals grouped by software family (`fingerprint`), largest family first. Unfingerprinted portals come back apart. */
export function families(portals: Portal[]): { families: Family[]; unknown: Portal[] } {
  const groups = new Map<string, Portal[]>();
  const unknown: Portal[] = [];
  for (const p of portals) {
    const key = p.fingerprint?.trim();
    if (!key) { unknown.push(p); continue; }
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  const out = [...groups.entries()].map(([fingerprint, ps]): Family => {
    const reused = ps.filter((p) => hasRecipe(p) && p.reusedFrom).length;
    const withRecipe = ps.filter(hasRecipe).length;
    const costs = ps.filter((p) => p.usage).map((p) => p.usage?.costEur ?? 0);
    const sentence = ps.length === 1
      ? `1 portal on ${fingerprint}`
      : reused > 0
        ? `${count(withRecipe)} on ${fingerprint} share one recipe${withRecipe < ps.length ? `; ${ps.length - withRecipe} more on it without a recipe yet` : ""}`
        : `${count(ps.length)} on ${fingerprint}, no recipe reused yet`;
    return { fingerprint, portals: ps, reused, withRecipe, costEur: costs.length ? costs.reduce((s, x) => s + x, 0) : null, sentence };
  });
  out.sort((a, b) => b.portals.length - a.portals.length || a.fingerprint.localeCompare(b.fingerprint));
  return { families: out, unknown };
}

export interface KnownShare { fingerprinted: number; distinct: number; share: number | null }

/**
 * Observed share of portals on software we already know: each family has to be learned once, every
 * further portal on it can reuse the recipe. So of F fingerprinted portals in D families, F − D are
 * "on a known family". null when no portal has a fingerprint.
 */
export function observedKnownShare(portals: Portal[]): KnownShare {
  const prints = portals.map((p) => p.fingerprint?.trim()).filter((f): f is string => !!f);
  const distinct = new Set(prints).size;
  return { fingerprinted: prints.length, distinct, share: prints.length ? (prints.length - distinct) / prints.length : null };
}

export interface ProjectionInput {
  /** Assumption: the fleet size to project to. */
  portals: number;
  /** Assumption: share (0 to 1) of those portals that run software we have already learned. */
  knownShare: number;
  /** Input from data: average recorded cost of a portal learned from scratch, EUR. Null = not recorded. */
  costPerLearnEur: number | null;
  /** Input from data: average recorded cost of a portal on a reused recipe, EUR. Null = not recorded. */
  costPerReuseEur: number | null;
}

export interface Projection {
  learns: number;
  reuses: number;
  learnCostEur: number | null;
  reuseCostEur: number | null;
  /** null when a cost that the split needs is not recorded */
  totalEur: number | null;
  /** The same fleet with every portal learned from scratch. */
  allLearnedEur: number | null;
  savingEur: number | null;
}

/**
 * total = learns × costPerLearn + reuses × costPerReuse, with reuses = round(portals × knownShare)
 * and learns = portals − reuses. A missing cost makes its term null, and the total null with it,
 * unless that term counts zero portals.
 */
export function project(input: ProjectionInput): Projection {
  const portals = Math.max(0, Math.round(input.portals));
  const share = Math.min(1, Math.max(0, input.knownShare));
  const reuses = Math.round(portals * share);
  const learns = portals - reuses;
  const term = (n: number, unit: number | null) => (n === 0 ? 0 : unit === null ? null : n * unit);
  const learnCostEur = term(learns, input.costPerLearnEur);
  const reuseCostEur = term(reuses, input.costPerReuseEur);
  const totalEur = learnCostEur === null || reuseCostEur === null ? null : learnCostEur + reuseCostEur;
  const allLearnedEur = term(portals, input.costPerLearnEur);
  return {
    learns, reuses, learnCostEur, reuseCostEur, totalEur, allLearnedEur,
    savingEur: totalEur === null || allLearnedEur === null ? null : allLearnedEur - totalEur,
  };
}

/** EUR with enough digits for sub-cent unit costs and separators for fleet totals. */
export function eurFine(v: number): string {
  if (v === 0) return "0.00 EUR";
  const digits = v < 0.01 ? 4 : v < 1 ? 3 : 2;
  return `${v.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits })} EUR`;
}
