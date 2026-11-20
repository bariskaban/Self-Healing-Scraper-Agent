import { Bot, FileText, Wrench, GitBranch } from "lucide-react";
import { absTime, duration, eur, tokens } from "@/data/format";
import type { Run, Step } from "@/types";
import { stepTiming } from "./evidence";

export function TenderCountChart({ timeline, timeZone }: { timeline: Run[]; timeZone: string | null }) {
  const reads = timeline.filter((run) => run.kind === "read").sort((a, b) => Date.parse(a.startedAt) - Date.parse(b.startedAt));
  if (!reads.length) return <figure><figcaption className="font-semibold">Published per read</figcaption><p className="mt-2 text-label text-muted-foreground">No read events recorded.</p></figure>;
  const W = Math.max(600, reads.length * 80), H = 120, baseline = 66;
  const max = Math.max(1, ...reads.map((run) => run.publishedCount ?? 0));
  const x = (index: number) => 65 + index * ((W - 100) / Math.max(1, reads.length - 1));
  const outcome = (run: Run) => run.result === "failed" ? "Failed" : run.result === null ? "Running" : "Passed";
  const summary = reads.map((run) => `${absTime(run.startedAt, timeZone)}: ${run.publishedCount === undefined ? "no publication recorded (not zero)" : `${run.publishedCount} published`}, ${outcome(run)}`).join("; ");
  return <figure className="min-w-0">
    <figcaption className="mb-2 text-body font-semibold">Published per read</figcaption>
    <div className="overflow-x-auto"><svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="h-[120px] max-w-none" role="img" aria-label={summary}>
      <title>Published per read — discrete recorded read events</title>
      <line x1={35} x2={W - 15} y1={baseline} y2={baseline} className="stroke-divider" />
      <text x={8} y={baseline + 4} className="fill-muted-foreground text-xs">0</text>
      <text x={8} y={20} className="fill-muted-foreground text-xs">{max}</text>
      <text x={8} y={91} className="fill-muted-foreground text-[10px]">Result</text>
      {reads.map((run, index) => {
        const px = x(index), count = run.publishedCount;
        const label = absTime(run.startedAt, timeZone).match(/\d{2}:\d{2}/)?.[0] ?? run.startedAt;
        return <g key={run.id}>
          {count !== undefined && count > 0 && <rect x={px - 10} y={baseline - count / max * 42} width={20} height={count / max * 42} className="fill-primary" />}
          {count !== undefined && <text x={px} y={count === 0 ? baseline - 5 : baseline - count / max * 42 - 5} textAnchor="middle" className="fill-foreground text-xs">{count}</text>}
          {run.result === "failed" ? <path d={`M${px - 4} 82l8 8m0-8l-8 8`} className="stroke-failed" strokeWidth={2} /> : <text x={px} y={90} textAnchor="middle" className={`${run.result === null ? "fill-integrating" : "fill-serving"} text-[10px]`}>{count === undefined ? `${outcome(run)} · no publication` : outcome(run)}</text>}
          <text x={px} y={113} textAnchor="middle" className="fill-muted-foreground text-xs">{label}</text>
        </g>;
      })}
    </svg></div>
    <p className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-micro text-secondary-text"><span>Columns: recorded published count</span><span className="text-failed">× Failed read</span><span>0: actual zero · No publication ≠ zero</span></p>
    <p className="sr-only">{summary}</p>
  </figure>;
}

const stepIcons = { tool: Wrench, llm: Bot, note: FileText, decision: GitBranch };
export function StepWaterfall({ steps, startedAt }: { steps: Step[]; startedAt: string }) {
  if (!steps.length) return <p className="text-label text-muted-foreground">No agent steps recorded.</p>;
  const ordered = [...steps].sort((a, b) => a.seq - b.seq);
  const { mode, total, offsets } = stepTiming(ordered, startedAt);
  return <div>
    {mode !== "none" && <div className="waterfall-scale mb-2 grid gap-x-4 text-micro text-muted-foreground sm:grid-cols-[15rem_minmax(0,1fr)_7rem]"><span>{mode === "elapsed" ? "Elapsed since run start" : "Duration only"}</span><div className="flex justify-between"><span>0 s</span><span>{duration(total / 2)}</span><span>{duration(total)}</span></div><span className="hidden text-right sm:block">Duration</span></div>}
    <ol aria-label={`Agent steps${mode === "elapsed" ? ` on a shared elapsed-time scale, ${duration(total)}` : mode === "duration" ? " on a shared duration scale; start times not recorded" : " in recorded order; timing not recorded"}`} className="divide-y divide-divider">
      {ordered.map((step, index) => {
        const offset = mode === "elapsed" ? offsets[index] ?? 0 : 0;
        const Icon = stepIcons[step.kind];
        const cost = step.kind === "llm" ? step.usage ? `${tokens(step.usage.inputTokens + step.usage.outputTokens)} tokens · ${eur(step.usage.costEur)}` : "Usage not recorded" : null;
        return <li key={step.seq} className="grid min-h-10 grid-cols-[minmax(0,1fr)_7rem] items-center gap-x-4 gap-y-2 py-2 sm:grid-cols-[15rem_minmax(0,1fr)_7rem]">
          <div className="flex min-w-0 items-center gap-2"><span className="w-4 text-label text-muted-foreground">{step.seq}</span><Icon aria-hidden className="size-4 shrink-0 text-secondary-text" /><span className="min-w-0 text-body font-medium break-words">{step.name}<span className="block text-micro font-normal text-muted-foreground">{step.kind}{cost && ` · ${cost}`}</span></span></div>
          {mode !== "none" && <div className="relative h-3 bg-inset max-sm:col-span-2 max-sm:row-start-2" aria-hidden>
            {step.durationMs !== null ? <span className={`absolute h-3 ${step.kind === "llm" ? "bg-integrating" : "bg-primary"}`} style={{ left: `${offset / total * 100}%`, width: `${Math.max(0.4, step.durationMs / total * 100)}%` }} /> : offsets[index] !== null && <span className="absolute h-3 w-[2px] bg-muted-foreground" style={{ left: `${offset / total * 100}%` }} />}
          </div>}
          <span className="text-right text-label tabular-nums text-secondary-text">{step.durationMs === null ? "Not recorded" : duration(step.durationMs)}{mode === "elapsed" && <span className="block text-micro text-muted-foreground">at +{duration(offset)}</span>}</span>
          <span className="sr-only">{step.summary}</span>
        </li>;
      })}
    </ol>
  </div>;
}
