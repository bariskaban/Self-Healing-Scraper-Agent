import { AlertOctagon, CheckCircle2, Loader2, Sparkles, Wrench, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { STATE_META, readSlots, runResultWord } from "@/data/view";
import { costText, eur, tokens, type CostSummary } from "@/data/format";
import type { Portal, PortalState } from "@/types";

const STATE_ICON = { serving: CheckCircle2, healing: Wrench, integrating: Sparkles, failed: AlertOctagon };
export const STATE_CLASS: Record<PortalState, string> = {
  serving: "text-serving bg-serving-tint",
  healing: "text-healing bg-healing-tint",
  integrating: "text-integrating bg-integrating-tint",
  failed: "text-failed bg-failed-tint",
};
export const STATE_INK: Record<PortalState, string> = {
  serving: "text-serving", healing: "text-healing", integrating: "text-integrating", failed: "text-failed",
};

export function StateBadge({ state, className }: { state: PortalState; className?: string }) {
  const Icon = STATE_ICON[state];
  const m = STATE_META[state];
  return (
    <span
      title={`${m.label}: ${m.tip}`}
      className={cn("inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-label font-semibold", STATE_CLASS[state], className)}
    >
      <Icon aria-hidden className="size-[1em]" />
      {m.label}
    </span>
  );
}

export function ResultMark({ result }: { result: "ok" | "failed" | null }) {
  const word = runResultWord(result);
  const Icon = result === null ? Loader2 : result === "ok" ? CheckCircle2 : XCircle;
  const ink = result === null ? "text-integrating" : result === "ok" ? "text-serving" : "text-failed";
  return (
    <span className={cn("inline-flex items-center gap-1 font-medium", ink)}>
      <Icon aria-hidden className="size-[1em]" />
      {word}
    </span>
  );
}

export function ReadHistory30({ reads }: { reads: Portal["recentReads"] }) {
  const slots = readSlots(reads);
  const ok = reads.filter((r) => r === "ok").length;
  const failed = reads.filter((r) => r === "failed").length;
  const running = reads.filter((r) => r === null).length;
  const label = reads.length
    ? `Last ${Math.min(30, reads.length)} reads, oldest to newest: ${ok} passed, ${failed} failed${running ? `, ${running} running` : ""}.`
    : "No reads yet.";
  return (
    <div role="img" aria-label={label} title={label} className="flex h-6 w-[208px] shrink-0 items-end gap-[2px]">
      {slots.map((s, i) => (
        <span
          key={i}
          className={cn(
            "w-[5px] shrink-0 rounded-[1px]",
            s === "empty" && "h-2 bg-inset outline outline-1 -outline-offset-1 outline-divider",
            s === "ok" && "h-6 bg-serving",
            s === "failed" && "h-3 bg-failed",
            s === "running" && "hatch h-6 text-integrating",
          )}
        />
      ))}
    </div>
  );
}

export function DeliverySparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <span className="text-micro text-muted-foreground">No trend yet</span>;
  const w = 64, h = 20;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - (v / max) * (h - 2) - 1}`).join(" ");
  const label = `Published counts over recent reads: ${values.join(", ")}.`;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label} className="text-primary">
      <title>{label}</title>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export function CostLabel({ cost, eurPerUsd, className }: { cost: CostSummary; eurPerUsd: number; className?: string }) {
  const tip = `Model usage only (LLM calls), converted at the recorded fixed rate of ${eurPerUsd} EUR per USD.`;
  if (cost.kind !== "known") return <span title={tip} className={cn("text-muted-foreground", className)}>{costText(cost)}</span>;
  return (
    <span title={tip} className={cn("whitespace-nowrap", className)}>
      {cost.incomplete && <span className="text-muted-foreground">At least </span>}
      <span className="font-semibold">{eur(cost.eur)}</span>
      <span className="text-muted-foreground"> · {tokens(cost.tokens)} tokens{cost.running ? " so far" : ""}{cost.incomplete ? " · incomplete usage" : ""}</span>
    </span>
  );
}

export function Skel({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-sm bg-inset", className)} />;
}
