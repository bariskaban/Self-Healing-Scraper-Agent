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
  const triggering = triggeringRead(timeline, run);
  const failed = triggering?.checks?.filter((check) => !check.passed) ?? [];
  const steps = [...(run.steps ?? [])].sort((a, b) => a.seq - b.seq);
  const action = steps.find((step) => step.kind === "llm" || step.kind === "decision") ?? steps[0];
  const verification = run.checks ?? [];
  return {
    triggering,
    broke: failed.length ? failed.map((check) => check.message).join(" ") : "Not recorded",
    action: action?.summary ?? "Not recorded",
    changed: run.recipeChange
      ? `Recipe v${run.recipeChange.from} → v${run.recipeChange.to}: ${run.recipeChange.rationale}`
      : run.finishedAt === null ? "Pending — no verified change yet." : "Not recorded",
    verified: verification.length
      ? `${run.result === "ok" ? "Passed" : run.result === "failed" ? "Failed" : "Pending"}: ${verification.map((check) => check.message).join(" ")}`
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