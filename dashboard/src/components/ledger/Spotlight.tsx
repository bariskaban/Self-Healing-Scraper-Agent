import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import { ArrowRight, CheckCircle2, Clock3, GitBranch, History, Pause, Play, Wrench, XCircle, type LucideIcon } from "lucide-react";
import { costText, duration, eur, hostname, runCost, tokens } from "@/data/format";
import { portalHash } from "@/data/hooks";
import { cn } from "@/lib/utils";
import type { Portal, Run } from "@/types";
import { repairEvidence } from "./evidence";
import { clock, stillServing } from "./overview";
import { StateBadge } from "./primitives";
import { setPendingRun } from "./viewState";

const SLIDE_MS = 6000;

interface Slide { label: string; Icon: LucideIcon; tone: string; meta: string; text: string; tags: string[] }

/** The four stops of a repair, each taken from the recorded run and the read that triggered it. */
export function repairSlides(run: Run, timeline: Run[], timeZone: string | null): Slide[] {
  const ev = repairEvidence(run, timeline);
  const steps = [...(run.steps ?? [])].sort((a, b) => a.seq - b.seq);
  const action = steps.find((s) => s.kind === "llm" || s.kind === "decision") ?? steps[0];
  const failedChecks = ev.triggering?.checks?.filter((c) => !c.passed).map((c) => c.name) ?? [];
  const actionTags = action ? [
    action.kind === "llm" ? "Model call" : action.kind === "tool" ? "Tool, no model" : action.kind,
    ...(action.usage ? [`${tokens(action.usage.inputTokens + action.usage.outputTokens)} tokens`, eur(action.usage.costEur)] : []),
    ...(action.durationMs !== null ? [duration(action.durationMs)] : []),
  ] : [];
  const verdict = run.result === null ? "Verification running" : run.result === "ok" ? "Passed" : "Failed";
  return [
    { label: "Broke", Icon: XCircle, tone: "text-failed bg-failed-tint", text: ev.broke,
      meta: ev.triggering ? `Read at ${clock(ev.triggering.startedAt, timeZone)} failed its checks` : "Triggering read not recorded", tags: failedChecks },
    { label: "Agent action", Icon: Wrench, tone: "text-healing bg-healing-tint", text: ev.action,
      meta: action ? `Step ${action.seq}: ${action.name}` : "No agent step recorded", tags: actionTags },
    { label: "Changed", Icon: GitBranch, tone: "text-integrating bg-integrating-tint", text: ev.changed,
      meta: run.recipeChange ? `Recipe v${run.recipeChange.from} → v${run.recipeChange.to}` : "No verified change yet", tags: run.recipeChange?.changedParts ?? [] },
    { label: "Verified", Icon: run.result === null ? Clock3 : run.result === "ok" ? CheckCircle2 : XCircle,
      tone: run.result === null ? "text-integrating bg-integrating-tint" : run.result === "ok" ? "text-serving bg-serving-tint" : "text-failed bg-failed-tint",
      text: ev.verified, meta: verdict, tags: (run.checks ?? []).map((c) => `${c.name} ${c.passed ? "passed" : "failed"}`) },
  ];
}

function Shell({ label, live, children }: { label: string; live?: boolean; children: ReactNode }) {
  return (
    <div className="card flex h-full flex-col overflow-hidden p-6 2xl:p-8">
      <div aria-hidden className="pointer-events-none absolute -top-24 -right-16 size-72 rounded-full bg-[radial-gradient(closest-side,rgb(99_102_241/0.22),transparent)]" />
      <p className="eyebrow flex items-center gap-2.5">{live && <span aria-hidden className="live-dot text-healing" />}{label}</p>
      {children}
    </div>
  );
}

export function SpotlightEmpty({ loading }: { loading?: boolean }) {
  return (
    <section aria-label="Live repair">
      <Shell label="Live repair">
        <p className="display mt-4 text-[1.9rem]">{loading ? "Reading the fleet…" : "No repair is running."}</p>
        {!loading && <p className="mt-3 max-w-xl text-secondary-text">Every portal is being read with its current recipe. When a layout changes, the repair appears here step by step: what broke, what the agent did, what changed and how it was verified.</p>}
      </Shell>
    </section>
  );
}

/**
 * A carousel through one repair: Broke → Agent action → Changed → Verified. It advances every six
 * seconds, pauses on hover, focus or the pause button, answers the arrow keys, and stands still under
 * reduced motion (the advance is driven by a CSS animation, which that setting removes).
 */
export function Spotlight({ portal, run, timeline, earlier, live, eurPerUsd }: { portal: Portal; run: Run; timeline: Run[]; earlier: Run | null; live: boolean; eurPerUsd: number }) {
  const slides = repairSlides(run, timeline, portal.timezone);
  const [index, setIndex] = useState(0);
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const [stopped, setStopped] = useState(false);
  useEffect(() => setIndex(0), [run.id]);
  const go = (n: number) => setIndex((n + slides.length) % slides.length);
  const step = (d: number) => setIndex((i) => (i + d + slides.length) % slides.length);
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
  };
  const note = stillServing(portal);
  const name = live ? "Live repair" : "Latest repair";
  return (
    <section aria-roledescription="carousel" aria-label={`${name}: ${hostname(portal.url)}`} data-paused={hover || focus || stopped}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      onFocus={() => setFocus(true)} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setFocus(false); }} onKeyDown={onKey}>
      <Shell label={name} live={live}>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
          <h3 className="display text-[1.9rem] break-all"><a href={portalHash(portal.id)} className="hover:underline">{hostname(portal.url)}</a></h3>
          <StateBadge state={portal.state} note={note} float />
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {run.finishedAt === null ? `Repair started ${clock(run.startedAt, portal.timezone)}, not finished` : `Repair ${clock(run.startedAt, portal.timezone)} to ${clock(run.finishedAt, portal.timezone)}`}
          {" · "}<span title={`Model usage only, fixed rate ${eurPerUsd} EUR/USD`}>{costText(runCost(run))}</span>
        </p>

        <div className="slides mt-6 flex-1">
          {slides.map((s, i) => (
            <div key={s.label} role="group" aria-roledescription="slide" aria-label={`${i + 1} of ${slides.length}: ${s.label}`} aria-hidden={i !== index} data-active={i === index} className="slide">
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <span className={cn("grid size-9 place-items-center rounded-full", s.tone)}><s.Icon aria-hidden className="size-[1.1rem]" /></span>
                <span className="text-xs font-semibold tracking-[0.16em] uppercase">{String(i + 1).padStart(2, "0")} · {s.label}</span>
                <span className="text-muted-foreground">{s.meta}</span>
              </p>
              <p className="mt-4 max-w-[46rem] text-[1.45rem] leading-[1.35] font-light tracking-[-0.01em]">{s.text}</p>
              {s.tags.length > 0 && <ul className="mt-4 flex flex-wrap gap-2">{s.tags.map((t) => <li key={t} className="chip chip-plain text-xs text-secondary-text">{t}</li>)}</ul>}
            </div>
          ))}
        </div>

        <div className="mt-6 flex items-end gap-3">
          <ol className="flex min-w-0 flex-1 gap-2" aria-label="Repair steps">
            {slides.map((s, i) => (
              <li key={s.label} className="min-w-0 flex-1">
                <button type="button" onClick={() => go(i)} aria-label={`Show step ${i + 1}: ${s.label}`} aria-current={i === index ? "step" : undefined} className="group block w-full cursor-pointer rounded-md py-1 text-left">
                  <span className="dot-track block">
                    <span className="dot-fill" data-state={i < index ? "done" : i === index ? "active" : "idle"} style={{ ["--slide-ms" as string]: `${SLIDE_MS}ms` }}
                      onAnimationEnd={i === index ? () => step(1) : undefined} />
                  </span>
                  <span className={cn("mt-2 block truncate text-xs font-medium transition-colors", i === index ? "text-foreground" : "text-muted-foreground group-hover:text-foreground")}>{s.label}</span>
                </button>
              </li>
            ))}
          </ol>
          <button type="button" onClick={() => setStopped((v) => !v)} aria-label={stopped ? "Resume the slideshow" : "Pause the slideshow"} title={stopped ? "Resume" : "Pause"} className="pill-ghost mb-0.5 !p-2 motion-reduce:hidden">
            {stopped ? <Play aria-hidden className="size-3.5" /> : <Pause aria-hidden className="size-3.5" />}
          </button>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-x-7 gap-y-2 border-t border-divider pt-4 text-sm">
          <a href={portalHash(portal.id)} onClick={() => setPendingRun(run.id)} className="link-arrow">Inspect {live ? "this repair" : "the repair"} <ArrowRight aria-hidden className="size-4" /></a>
          {earlier && <a href={portalHash(portal.id)} onClick={() => setPendingRun(earlier.id)} className="link-arrow"><History aria-hidden className="size-4" /> Earlier verified repair, {clock(earlier.startedAt, portal.timezone)} <ArrowRight aria-hidden className="size-4" /></a>}
        </div>
      </Shell>
    </section>
  );
}
