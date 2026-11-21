import { useId, type CSSProperties, type ReactNode } from "react";
import { AlertOctagon, CheckCircle2, Loader2, Sparkles, Wrench, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { STATE_META, readSlots, runResultWord } from "@/data/view";
import { costText, eur, tokens, type CostSummary } from "@/data/format";
import type { Portal, PortalState } from "@/types";

export const STATE_ICON = { serving: CheckCircle2, healing: Wrench, integrating: Sparkles, failed: AlertOctagon };
export const STATE_CLASS: Record<PortalState, string> = {
  serving: "text-serving bg-serving-tint",
  healing: "text-healing bg-healing-tint",
  integrating: "text-integrating bg-integrating-tint",
  failed: "text-failed bg-failed-tint",
};
export const STATE_INK: Record<PortalState, string> = {
  serving: "text-serving", healing: "text-healing", integrating: "text-integrating", failed: "text-failed",
};

/** `--i` staggers the reveal and float animations. */
export const idx = (i: number) => ({ "--i": i }) as CSSProperties;

/** Glass status chip: icon in a tinted dot, the state word, and an optional plain-language note. */
export function StateBadge({ state, note, float, i = 0, className }: { state: PortalState; note?: string | null; float?: boolean; i?: number; className?: string }) {
  const Icon = STATE_ICON[state];
  const m = STATE_META[state];
  return (
    <span title={m.tip} style={{ ...idx(i), ["--tint" as string]: `var(--${state}-tint)` }} className={cn("chip chip-state", float && "float", className)}>
      <span className={cn("grid size-[1.4em] shrink-0 place-items-center rounded-full", STATE_CLASS[state])}><Icon aria-hidden className="size-[0.9em]" /></span>
      <span className={cn("font-semibold", STATE_INK[state])}>{m.label}</span>
      {note && <span className="border-l border-border-strong pl-2 text-secondary-text">{note}</span>}
    </span>
  );
}

export function ResultMark({ result, className }: { result: "ok" | "failed" | null; className?: string }) {
  const word = runResultWord(result);
  const Icon = result === null ? Loader2 : result === "ok" ? CheckCircle2 : XCircle;
  const ink = result === null ? "text-integrating" : result === "ok" ? "text-serving" : "text-failed";
  return (
    <span className={cn("inline-flex items-center gap-1 font-medium", ink, className)}>
      <Icon aria-hidden className="size-[1em]" />
      {word}
    </span>
  );
}

const SLOT_CLASS = {
  empty: "h-[5px] bg-[var(--border-strong)]",
  ok: "h-6 bg-serving/75",
  failed: "h-3 rounded-b-none bg-failed",
  running: "hatch h-6 text-integrating",
};

/** 30 read slots, oldest to newest, with the counts in words underneath. Null means the history is not recorded. */
export function ReadHistory30({ reads }: { reads: Portal["recentReads"] }) {
  if (reads === null) return <span className="text-muted-foreground" title="The read history is not on the routes this page could reach.">Not recorded</span>;
  const slots = readSlots(reads);
  const ok = reads.filter((r) => r === "ok").length;
  const failed = reads.filter((r) => r === "failed").length;
  const running = reads.filter((r) => r === null).length;
  const words = [ok && `${ok} passed`, failed && `${failed} failed`, running && `${running} running`].filter(Boolean).join(" · ");
  const label = reads.length
    ? `Last ${Math.min(30, reads.length)} reads, oldest to newest: ${ok} passed, ${failed} failed${running ? `, ${running} running` : ""}.`
    : "No reads yet.";
  return (
    <div className="w-[208px] shrink-0">
      <div role="img" aria-label={label} title={label} className="flex h-6 items-end gap-[2px]">
        {slots.map((s, i) => <span key={i} className={cn("w-[5px] shrink-0 rounded-full", SLOT_CLASS[s])} />)}
      </div>
      <p aria-hidden className="mt-1 text-xs whitespace-nowrap text-muted-foreground">{words || "No reads yet"}</p>
    </div>
  );
}

/** What the marks in the 30-read history mean. */
export function ReadLegend() {
  const item = (slot: keyof typeof SLOT_CLASS, word: string) => (
    <span className="inline-flex items-end gap-1.5"><span aria-hidden className={cn("inline-block w-[5px] rounded-full", SLOT_CLASS[slot], slot === "empty" && "mb-[5px]")} />{word}</span>
  );
  return (
    <p className="flex flex-wrap items-end gap-x-4 gap-y-1 text-sm text-muted-foreground">
      <span>Read history, oldest to newest:</span>
      {item("ok", "Passed")}{item("failed", "Failed")}{item("running", "Running")}{item("empty", "No read")}
    </p>
  );
}

export function DeliverySparkline({ values }: { values: number[] | null }) {
  const id = useId();
  if (values === null) return <span className="text-xs whitespace-nowrap text-muted-foreground" title="Published counts per read are not recorded on these routes.">—</span>;
  if (values.length < 2) return <span className="text-xs whitespace-nowrap text-muted-foreground">No trend yet</span>;
  const w = 72, h = 24;
  const max = Math.max(...values, 1);
  const xy = values.map((v, i) => [(i / (values.length - 1)) * (w - 4) + 2, h - 3 - (v / max) * (h - 8)] as const);
  const line = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const last = xy[xy.length - 1] ?? [0, 0];
  const label = `Published counts over recent reads: ${values.join(", ")}.`;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label} className="shrink-0 text-[var(--bar-top)]">
      <title>{label}</title>
      <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="currentColor" stopOpacity="0.35" /><stop offset="1" stopColor="currentColor" stopOpacity="0" /></linearGradient></defs>
      <polygon points={`2,${h} ${line} ${w - 2},${h}`} fill={`url(#${id})`} />
      <polyline points={line} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="2.2" fill="currentColor" />
    </svg>
  );
}

export function CostLabel({ cost, eurPerUsd, className, stacked }: { cost: CostSummary; eurPerUsd: number | null; className?: string; stacked?: boolean }) {
  const tip = eurPerUsd ? `Model usage only (LLM calls), converted at the recorded fixed rate of ${eurPerUsd} EUR per USD.` : "Model usage only (LLM calls). No usage is recorded on the routes this page could reach.";
  if (cost.kind !== "known") return <span title={tip} className={cn("whitespace-nowrap text-muted-foreground", className)}>{costText(cost)}</span>;
  const meta = `${tokens(cost.tokens)} tokens${cost.running ? " so far" : ""}${cost.incomplete ? " · incomplete usage" : ""}`;
  return (
    <span title={tip} className={cn("tnum whitespace-nowrap", className)}>
      {cost.incomplete && <span className="text-muted-foreground">At least </span>}
      <span className="font-semibold">{eur(cost.eur)}</span>
      {stacked ? <span className="block text-xs text-muted-foreground">{meta}</span> : <span className="text-muted-foreground"> · {meta}</span>}
    </span>
  );
}

export function Skel({ className }: { className?: string }) {
  return <div aria-hidden className={cn("shimmer rounded-lg", className)} />;
}

/** Small uppercase tracked label over a light heading. */
export function SectionHead({ label, title, id, children }: { label: string; title: ReactNode; id?: string; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
      <div>
        <p className="eyebrow">{label}</p>
        <h2 id={id} className="display mt-2 text-[1.9rem]">{title}</h2>
      </div>
      {children}
    </div>
  );
}
