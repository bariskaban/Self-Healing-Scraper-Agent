import { useEffect, useId, useRef, useState } from "react";
import { Bot, FileText, Wrench, GitBranch } from "lucide-react";
import { absTime, duration, eur, tokens } from "@/data/format";
import type { Run, Step } from "@/types";
import { stepTiming } from "./evidence";
import { clock } from "./overview";

function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => { if (entry) setWidth(Math.max(280, Math.round(entry.contentRect.width))); });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

const Legend = ({ swatch, children }: { swatch: React.ReactNode; children: React.ReactNode }) => <span className="inline-flex items-center gap-2">{swatch}{children}</span>;

/** Published count per read as gradient bars; a failed read is a red tick in its own lane, never a zero bar. */
export function TenderCountChart({ timeline, timeZone }: { timeline: Run[]; timeZone: string | null }) {
  const gid = useId();
  const [ref, W] = useWidth<HTMLDivElement>(960);
  const reads = timeline.filter((run) => run.kind === "read").sort((a, b) => Date.parse(a.startedAt) - Date.parse(b.startedAt));
  if (!reads.length) return <p className="text-secondary-text">No read events recorded.</p>;
  const H = 264, left = 44, right = 12, top = 30, base = 172, lane = 204, labels = 246;
  const max = Math.max(1, ...reads.map((run) => run.publishedCount ?? 0));
  const step = (W - left - right) / reads.length;
  const barW = Math.min(132, Math.max(10, step * 0.5));
  const x = (i: number) => left + step * (i + 0.5);
  const y = (count: number) => base - (count / max) * (base - top - 14);
  const ticks = max <= 5 ? Array.from({ length: max + 1 }, (_, i) => i) : [0, Math.round(max / 2), max];
  const every = Math.max(1, Math.ceil(60 / step));
  const outcome = (run: Run) => run.result === "failed" ? "Failed" : run.result === null ? "Running" : "Passed";
  const summary = reads.map((run) => `${absTime(run.startedAt, timeZone)}: ${run.publishedCount === undefined ? "no publication recorded (not zero)" : `${run.publishedCount} published`}, ${outcome(run)}`).join("; ");
  return (
    <figure className="min-w-0">
      <div ref={ref}>
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block max-w-full" role="img" aria-label={`Published per read. ${summary}`}>
          <defs>
            <linearGradient id={`${gid}-bar`} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="var(--bar-top)" stopOpacity="0.95" /><stop offset="0.55" stopColor="#6366f1" stopOpacity="0.5" /><stop offset="1" stopColor="#6366f1" stopOpacity="0.04" /></linearGradient>
          </defs>
          {ticks.map((t) => <g key={t}>
            <line x1={left} x2={W - right} y1={y(t)} y2={y(t)} stroke="var(--grid-line)" strokeDasharray={t === 0 ? undefined : "2 5"} />
            <text x={left - 12} y={y(t) + 4} textAnchor="end" className="fill-muted-foreground text-[13px]">{t}</text>
          </g>)}
          <text x={left - 12} y={lane + 4} textAnchor="end" className="fill-muted-foreground text-[12px]">Read</text>
          <line x1={left} x2={W - right} y1={lane} y2={lane} stroke="var(--grid-line)" />
          {reads.map((run, i) => {
            const px = x(i), count = run.publishedCount;
            return <g key={run.id}>
              {count !== undefined && count > 0 && <>
                <rect x={px - barW / 2} y={y(count)} width={barW} height={base - y(count)} rx={Math.min(10, barW / 3)} fill={`url(#${gid}-bar)`} />
                <rect x={px - barW / 2} y={y(count)} width={barW} height={2} rx={1} fill="var(--bar-top)" />
              </>}
              {count !== undefined && <text x={px} y={y(count) - 8} textAnchor="middle" className="fill-foreground text-[16px] font-semibold">{count}</text>}
              {run.result === "failed" ? <>
                <line x1={px} x2={px} y1={top + 14} y2={base} stroke="var(--failed)" strokeWidth={1} strokeDasharray="2 5" opacity={0.45} />
                <rect x={px - 2} y={lane - 11} width={4} height={22} rx={2} fill="var(--failed)" />
              </> : run.result === null
                ? <circle cx={px} cy={lane} r={5.5} fill="none" stroke="var(--integrating)" strokeWidth={1.5} strokeDasharray="2 2" />
                : <circle cx={px} cy={lane} r={4} fill="var(--serving)" />}
              {step >= 84 && run.result !== "ok" && <text x={px + 11} y={lane + 5} className={`${run.result === "failed" ? "fill-failed" : "fill-integrating"} text-[13px] font-medium`}>{outcome(run)}</text>}
              {i % every === 0 && <text x={px} y={labels} textAnchor="middle" className="fill-muted-foreground text-[13px]">{clock(run.startedAt, timeZone)}</text>}
            </g>;
          })}
        </svg>
      </div>
      <figcaption className="mt-3 flex flex-wrap gap-x-6 gap-y-1.5 text-sm text-secondary-text">
        <Legend swatch={<span aria-hidden className="h-3 w-2.5 rounded-[3px] bg-gradient-to-b from-[var(--bar-top)] to-transparent" />}>Tenders published by that read</Legend>
        <Legend swatch={<span aria-hidden className="size-1.5 rounded-full bg-serving" />}>Passed</Legend>
        <Legend swatch={<span aria-hidden className="h-3 w-[3px] rounded-full bg-failed" />}>Failed read: nothing published, which is not a zero</Legend>
        <Legend swatch={<span aria-hidden className="size-2 rounded-full border border-dashed border-integrating" />}>Running</Legend>
      </figcaption>
      <p className="sr-only">{summary}</p>
    </figure>
  );
}

const stepIcons = { tool: Wrench, llm: Bot, note: FileText, decision: GitBranch };
const stepKind = { tool: "Tool", llm: "Model call", note: "Note", decision: "Decision" };

/** One row per agent step on a shared time axis, with duration, tokens and EUR in aligned columns. */
export function StepWaterfall({ steps, startedAt }: { steps: Step[]; startedAt: string }) {
  if (!steps.length) return <p className="text-secondary-text">No agent steps recorded.</p>;
  const ordered = [...steps].sort((a, b) => a.seq - b.seq);
  const { mode, total, offsets } = stepTiming(ordered, startedAt);
  const head = "text-[0.68rem] font-semibold tracking-[0.14em] text-muted-foreground uppercase";
  return (
    <div>
      <div className={`waterfall-row border-b border-divider pb-2 ${head} hidden @3xl:grid`} aria-hidden>
        <span>Step</span>
        <span className="flex justify-between normal-case tracking-normal">{mode === "none" ? <span>Timing not recorded</span> : <><span>{mode === "elapsed" ? "0 s" : "Duration only"}</span><span>{duration(total / 2)}</span><span>{duration(total)}</span></>}</span>
        <span className="text-right">Duration</span><span className="text-right">Tokens</span><span className="text-right">Cost</span>
      </div>
      <ol aria-label={`Agent steps${mode === "elapsed" ? ` on a shared elapsed-time scale, ${duration(total)}` : mode === "duration" ? " on a shared duration scale; start times not recorded" : " in recorded order; timing not recorded"}`} className="divide-y divide-divider">
        {ordered.map((step, index) => {
          const offset = mode === "elapsed" ? offsets[index] ?? 0 : 0;
          const Icon = stepIcons[step.kind];
          const llm = step.kind === "llm";
          return (
            <li key={step.seq} className="waterfall-row tnum py-3.5">
              <div className="flex min-w-0 items-center gap-3">
                <span className={`grid size-9 shrink-0 place-items-center rounded-full ${llm ? "bg-integrating-tint text-integrating" : "bg-inset text-secondary-text"}`}><Icon aria-hidden className="size-[1.05rem]" /></span>
                <span className="min-w-0"><span className="block text-[1.06rem] leading-tight font-semibold break-words">{step.seq}. {step.name}</span><span className="block text-xs text-muted-foreground">{stepKind[step.kind]}{mode === "elapsed" && ` · starts at +${duration(offset)}`}</span></span>
              </div>
              <span className="text-right text-[1.02rem] font-medium @3xl:hidden">{step.durationMs === null ? "Running" : duration(step.durationMs)}</span>
              {mode !== "none" && <div className="waterfall-bar relative h-3.5 rounded-full bg-inset" aria-hidden>
                {step.durationMs !== null
                  ? <span className={`absolute inset-y-0 rounded-full ${llm ? "bar-llm" : "bar-tool"}`} style={{ left: `${offset / total * 100}%`, width: `${Math.max(0.8, step.durationMs / total * 100)}%` }} />
                  : offsets[index] !== null && <span className="hatch absolute inset-y-0 w-10 rounded-full text-integrating" style={{ left: `min(${offset / total * 100}%, calc(100% - 2.5rem))` }} />}
              </div>}
              <span className="hidden text-right text-[1.02rem] font-medium @3xl:block">{step.durationMs === null ? <span className="text-integrating">Running</span> : duration(step.durationMs)}</span>
              <span className="text-sm @3xl:text-right @3xl:text-[1.02rem]">{llm ? step.usage ? tokens(step.usage.inputTokens + step.usage.outputTokens) : <span className="text-muted-foreground">Not recorded</span> : <span className="text-muted-foreground">No model</span>}<span className="@3xl:hidden"> {llm && step.usage ? "tokens" : ""}</span></span>
              <span className="text-right text-[1.02rem] font-semibold">{llm ? step.usage ? eur(step.usage.costEur) : <span className="font-normal text-muted-foreground">Not recorded</span> : <span className="font-normal text-muted-foreground">0.00 EUR</span>}</span>
              <p className="col-span-full -mt-1 text-sm leading-relaxed text-secondary-text @3xl:pl-12">{step.summary}</p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
