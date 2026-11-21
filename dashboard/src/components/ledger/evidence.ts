import type { Portal, Run, Step } from "@/types";
import { newestFirst, triggeringRead } from "@/data/view";

export const hasActiveRepair = (portal: Portal) =>
  portal.state === "healing" && portal.lastRun?.kind === "repair" && portal.lastRun.result === null;

export function repairRuns(portal: Portal, timeline: Run[]) {
  const active = hasActiveRepair(portal)
    ? timeline.find((run) => run.id === portal.lastRun?.id && run.kind === "repair" && run.result === null) ?? null
    : null;
  const earlier = active ? newestFirst(timeline).find((run) =>
    run.kind === "repair" && run.result === "ok" && run.finishedAt !== null &&
    Date.parse(run.startedAt) < Date.parse(active.startedAt)) ?? null : null;
  return { active, earlier };
}

export function repairEvidence(run: Run, timeline: Run[]) {
  // A read that passed did not trigger the repair. On the live backend the failing read is often
  // the start of the repair run itself (a read, then a second look), not a run of its own.
  const before = triggeringRead(timeline, run);
  const triggering = before?.result === "failed" ? before : null;
  const failed = triggering?.checks?.filter((check) => !check.passed) ?? [];
  const steps = [...(run.steps ?? [])].sort((a, b) => a.seq - b.seq);
  const firstAgent = steps.findIndex((step) => step.kind === "llm" || step.kind === "decision");
  const inRun = triggering ? [] : steps.slice(0, firstAgent < 0 ? 0 : firstAgent).filter((step) => step.kind === "note" && step.summary);
  const inRunChecks = inRun.flatMap((step) => /because of: ([^.]+)/.exec(step.summary)?.[1]?.split(/,\s*/) ?? []);
  const action = steps.find((step) => step.kind === "llm" || step.kind === "decision") ?? steps[0];
  const verification = run.checks ?? [];
  return {
    triggering,
    broke: failed.length ? failed.map((check) => check.message).join(" ") : inRun.length ? inRun.map((step) => step.summary).join(" ") : "Not recorded",
    /** when the failing read happened: the triggering run, or the start of this run when the read is inside it */
    brokeAt: triggering ? triggering.startedAt : inRun.length ? run.startedAt : null,
    brokeChecks: failed.length ? failed.map((check) => check.name) : inRunChecks,
    brokeInRun: inRun.length > 0,
    action: action?.summary ?? "Not recorded",
    changed: run.recipeChange
      ? `Recipe v${run.recipeChange.from} → v${run.recipeChange.to}: ${run.recipeChange.rationale}`
      : run.finishedAt === null ? "Pending — no verified change yet." : "Not recorded",
    verified: verification.length
      ? `${run.result === "ok" ? "Passed" : run.result === "failed" ? "Failed" : "Pending"}: ${verifiedText(verification)}`
      : run.finishedAt === null ? `Pending — ${steps.find((step) => step.name === "verify")?.summary ?? "verification not yet recorded."}` : "Not recorded",
  };
}

export function stepTiming(steps: Step[], startedAt: string) {
  const origin = Date.parse(startedAt);
  const offsets = steps.map((step) => Number.isFinite(Date.parse(step.at) - origin) ? Math.max(0, Date.parse(step.at) - origin) : null);
  const mode = offsets.some((offset) => offset !== null) ? "elapsed" : steps.some((step) => step.durationMs !== null) ? "duration" : "none";
  const total = Math.max(1, ...steps.map((step, i) => (mode === "elapsed" ? offsets[i] ?? 0 : 0) + (step.durationMs ?? 0)));
  return { mode, total, offsets };
}

const KEY_CHECKS = ["list_outcome", "paging_complete", "known_ids_missing"];

/** A long check list reads as a count and its key facts; a short one, or any failure, is told in full. */
function verifiedText(checks: { name: string; passed: boolean; message: string }[]): string {
  const failed = checks.filter((check) => !check.passed);
  if (checks.length <= 4) return checks.map((check) => check.message).join(" ");
  if (failed.length) return `${failed.length} of ${checks.length} checks failed. ${failed.map((check) => check.message).join(" ")}`;
  const key = checks.filter((check) => KEY_CHECKS.includes(check.name));
  return `all ${checks.length} checks passed. ${(key.length ? key : checks.slice(0, 2)).map((check) => check.message).join(" ")}`;
}
