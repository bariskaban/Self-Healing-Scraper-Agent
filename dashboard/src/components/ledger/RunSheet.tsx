import { Fragment, type ReactNode, type RefObject } from "react";
import { CheckCircle2, ChevronDown, XCircle, Wrench, GitBranch, Clock3 } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { absTime, duration, eur } from "@/data/format";
import { repairEvidence } from "./evidence";
import type { Check, Run } from "@/types";
import { ResultMark, idx } from "./primitives";
import { StepWaterfall } from "./Charts";
import { clock } from "./overview";

const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

function Checks({ checks }: { checks: Check[] | undefined }) {
  if (!checks?.length) return <p className="text-secondary-text">No checks recorded.</p>;
  return (
    <ul className="flex flex-col gap-2.5">
      {checks.map((c, i) => (
        <li key={`${c.name}-${i}`} className="rounded-2xl border border-divider bg-inset p-4">
          <div className="flex flex-wrap items-center gap-2 font-medium">
            {c.passed ? <CheckCircle2 aria-hidden className="size-[1.1rem] text-serving" /> : <XCircle aria-hidden className="size-[1.1rem] text-failed" />}
            <span className={c.passed ? "text-serving" : "text-failed"}>{c.passed ? "Passed" : "Failed"}</span>
            <span className="font-mono text-sm break-all text-secondary-text">{c.name}</span>
            {!c.passed && <span className="rounded-full bg-failed-tint px-2 py-0.5 text-xs tracking-wide text-failed uppercase">{c.severity}</span>}
          </div>
          <p className="mt-1.5 leading-relaxed">{c.message}</p>
          {(c.observed !== undefined || c.expected !== undefined) && (
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-xs">
              {c.observed !== undefined && <><dt className="text-muted-foreground">observed</dt><dd className="break-all">{show(c.observed)}</dd></>}
              {c.expected !== undefined && <><dt className="text-muted-foreground">expected</dt><dd className="break-all">{show(c.expected)}</dd></>}
            </dl>
          )}
        </li>
      ))}
    </ul>
  );
}

function Stats({ stats }: { stats: Run["stats"] }) {
  if (!stats || !Object.keys(stats).length) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5">
      {Object.entries(stats).map(([k, v]) => <Fragment key={k}><dt className="font-mono text-sm text-muted-foreground">{k}</dt><dd className="font-medium">{String(v)}</dd></Fragment>)}
    </dl>
  );
}

const Label = ({ children }: { children: ReactNode }) => <h3 className="eyebrow mt-9 mb-4">{children}</h3>;

function Disclosure({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="group border-t border-divider">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-[1.05rem] font-medium [&::-webkit-details-marker]:hidden">{label}<ChevronDown aria-hidden className="size-4 shrink-0 text-muted-foreground transition-transform duration-500 ease-spring group-open:rotate-180" /></summary>
      <div className="pb-5">{children}</div>
    </details>
  );
}

/** Three large figures for the run: how long, how many model tokens, what it cost. Unknown stays unknown. */
function Kpis({ run, now, eurPerUsd, timeZone }: { run: Run; now: number; eurPerUsd: number | null; timeZone: string | null }) {
  const started = Date.parse(run.startedAt);
  const elapsed = run.finishedAt ? Date.parse(run.finishedAt) - started : Math.max(0, now - started);
  const u = run.usage ?? null;
  const zero = !u && run.modelCalls === 0;
  const calls = run.modelCalls === null ? "Model calls not recorded" : `${run.modelCalls} model call${run.modelCalls === 1 ? "" : "s"}`;
  const items: { label: string; value: string; unit?: string; note: string }[] = [
    { label: "Elapsed", value: duration(elapsed), note: run.finishedAt ? `${clock(run.startedAt, timeZone)} to ${clock(run.finishedAt, timeZone)}` : `So far, started ${clock(run.startedAt, timeZone)}` },
    { label: "Model tokens", value: u ? (u.inputTokens + u.outputTokens).toLocaleString("en-GB") : zero ? "0" : "—", note: u ? `${u.inputTokens.toLocaleString("en-GB")} input + ${u.outputTokens.toLocaleString("en-GB")} output` : zero ? "No model call" : "Not recorded" },
    { label: run.kind === "repair" ? "Repair cost" : "Read cost", value: u ? eur(u.costEur).replace(" EUR", "") : zero ? "0.00" : "—", ...(u || zero ? { unit: "EUR" } : {}),
      note: `${calls}${run.finishedAt ? "" : u ? ", so far" : ""}${eurPerUsd && u ? ` · 1 USD = ${eurPerUsd} EUR` : ""}` },
  ];
  return (
    <dl className="mt-7 grid gap-x-8 gap-y-5 border-y border-divider py-5 @3xl:grid-cols-3" aria-label="Run figures">
      {items.map((k, i) => (
        <div key={k.label} className="evidence-stop !p-0" style={idx(i)}>
          <dt className="text-xs font-semibold tracking-[0.16em] text-muted-foreground uppercase">{k.label}</dt>
          <dd className="mt-1.5 flex items-baseline gap-2"><span className="silver tnum text-[clamp(2.2rem,3.4vw,3.2rem)] leading-none font-semibold tracking-[-0.03em]">{k.value}</span>{k.unit && <span className="text-lg font-medium text-muted-foreground">{k.unit}</span>}</dd>
          <dd className="tnum mt-1.5 text-sm text-secondary-text">{k.note}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RunSheet({ run, timeline, timeZone, eurPerUsd, now, basic, onClose, returnFocus }: {
  run: Run | null; timeline: Run[]; timeZone: string | null; eurPerUsd: number | null; now: number; basic: boolean; onClose: () => void; returnFocus: RefObject<HTMLElement | null>;
}) {
  const evidence = run?.kind === "repair" ? repairEvidence(run, timeline) : null;
  const noSummary = basic ? "No summary is recorded on the contract routes." : "No summary recorded.";
  return (
    <Sheet open={!!run} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="run-sheet w-full max-w-full overflow-y-auto border-l-[var(--glass-border)] bg-[var(--panel)] p-5 backdrop-blur-2xl backdrop-saturate-150 duration-700 ease-spring sm:w-[68rem] sm:max-w-[97vw] sm:rounded-l-[1.75rem] sm:p-9 2xl:p-11" onCloseAutoFocus={(event) => { event.preventDefault(); returnFocus.current?.focus(); }}>
        {run && <>
          <SheetHeader className="space-y-0 pr-8 text-left">
            <p className="eyebrow">{run.kind}{run.trigger ? ` · trigger: ${run.trigger}` : ""}</p>
            <SheetTitle className="display mt-3 text-[clamp(1.9rem,3.2vw,2.9rem)] font-light">
              {run.kind === "repair" ? "Repair" : "Read"} at {clock(run.startedAt, timeZone)}{run.recipeChange && <>, <span className="highlight font-normal">recipe v{run.recipeChange.from} → v{run.recipeChange.to}</span></>}
            </SheetTitle>
            <SheetDescription asChild><div className="!mt-4 flex flex-wrap items-center gap-2 text-sm text-secondary-text">
              <span className="chip chip-plain"><ResultMark result={run.result} /></span>
              <span className="chip chip-plain"><time dateTime={run.startedAt}>{absTime(run.startedAt, timeZone)}</time></span>
              {evidence?.triggering && <span className="chip chip-plain">Triggered by the read at {clock(evidence.triggering.startedAt, timeZone)}</span>}
            </div></SheetDescription>
          </SheetHeader>
          <Kpis key={run.id} run={run} now={now} eurPerUsd={eurPerUsd} timeZone={timeZone} />
          {evidence ? <>
            <Label>Repair story</Label>
            <ol key={run.id} aria-label="Repair evidence" className="repair-sequence">
              {[
                { label: "Broke", text: evidence.broke, Icon: XCircle, tone: "text-failed bg-failed-tint" },
                { label: "Agent action", text: evidence.action, Icon: Wrench, tone: "text-healing bg-healing-tint" },
                { label: "Changed", text: evidence.changed, Icon: GitBranch, tone: "text-integrating bg-integrating-tint" },
                { label: "Verified", text: evidence.verified, Icon: run.result === null ? Clock3 : run.result === "ok" ? CheckCircle2 : XCircle, tone: run.result === null ? "text-integrating bg-integrating-tint" : run.result === "ok" ? "text-serving bg-serving-tint" : "text-failed bg-failed-tint" },
              ].map(({ label, text, Icon, tone }, i, all) => (
                <li key={label} className="evidence-stop" style={idx(i)}>
                  <span aria-hidden className={`evidence-node grid size-[2.4rem] place-items-center rounded-full ${tone}`}><Icon className="size-[1.15rem]" /></span>
                  {i < all.length - 1 && <span aria-hidden className="evidence-link" style={idx(i)} />}
                  <p className="text-xs font-semibold tracking-[0.16em] uppercase">{String(i + 1).padStart(2, "0")} · {label}</p>
                  <p className="mt-2 text-[1.08rem] leading-relaxed text-secondary-text">{text}</p>
                </li>
              ))}
            </ol>
            {run.recipeChange && run.recipeChange.changedParts.length > 0 && (
              <p className="mt-6 flex flex-wrap items-center gap-2 text-sm"><span className="font-semibold">Changed parts</span>{run.recipeChange.changedParts.map((part) => <span key={part} className="chip chip-plain text-secondary-text">{part}</span>)}</p>
            )}
            <Label>Agent steps</Label>
            <StepWaterfall steps={run.steps ?? []} startedAt={run.startedAt} />
            <Label>Checks</Label>
            <div className="grid gap-x-8 gap-y-7 @3xl:grid-cols-2">
              <section aria-label="Triggering read">
                <h4 className="flex flex-wrap items-baseline gap-x-3 text-[1.1rem] font-semibold">Triggering read{evidence.triggering && <span className="text-sm font-normal text-muted-foreground">{clock(evidence.triggering.startedAt, timeZone)} · <ResultMark result={evidence.triggering.result} /></span>}</h4>
                {evidence.triggering ? <>
                  <p className="mt-1.5 mb-3 leading-relaxed text-secondary-text">{evidence.triggering.summary ?? noSummary}</p>
                  <Checks checks={evidence.triggering.checks} />
                </> : evidence.brokeInRun ? <p className="mt-1.5 leading-relaxed text-secondary-text">At the start of this run: {evidence.broke}</p>
                  : <p className="mt-1.5 text-secondary-text">Not recorded.</p>}
              </section>
              <section aria-label="Verified repair">
                <h4 className="flex flex-wrap items-baseline gap-x-3 text-[1.1rem] font-semibold">{run.result === "ok" ? "Verified repair" : run.result === null ? "Verification, still running" : "Verification"}<span className="text-sm font-normal text-muted-foreground">{clock(run.startedAt, timeZone)} · <ResultMark result={run.result} /></span></h4>
                <p className="mt-1.5 mb-3 leading-relaxed text-secondary-text">{run.summary ?? noSummary}</p>
                <Checks checks={run.checks} />
              </section>
            </div>
            <div className="mt-9 border-b border-divider">
              <Disclosure label="What changed: recipe details">{run.recipeChange ? <><p className="font-semibold">Recipe v{run.recipeChange.from} → v{run.recipeChange.to}</p><p className="mt-2 text-secondary-text">{run.recipeChange.rationale}</p><ul className="mt-3 flex flex-wrap gap-2">{run.recipeChange.changedParts.map((part) => <li key={part} className="chip chip-plain text-sm">{part}</li>)}</ul></> : <p className="text-secondary-text">{evidence.changed}</p>}</Disclosure>
              <Disclosure label="Recorded counters"><Stats stats={run.stats} />{(!run.stats || !Object.keys(run.stats).length) && <p className="text-muted-foreground">Not recorded</p>}</Disclosure>
              <Disclosure label="Full agent step records"><ol className="flex flex-col gap-3">{run.steps?.map((step) => <li key={step.seq}><p className="font-semibold">{step.seq}. {step.name} · {absTime(step.at, timeZone)}</p><p className="text-secondary-text">{step.summary}</p></li>)}</ol>{!run.steps?.length && <p className="text-muted-foreground">Not recorded</p>}</Disclosure>
            </div>
          </> : <>
            <p className="mt-7 max-w-[52rem] text-[1.3rem] leading-relaxed font-light">{run.summary ?? noSummary}</p>
            <Label>Checks</Label><Checks checks={run.checks} />
            {run.stats && Object.keys(run.stats).length > 0 && <><Label>Recorded counters</Label><Stats stats={run.stats} /></>}
            <Label>Agent steps</Label><StepWaterfall steps={run.steps ?? []} startedAt={run.startedAt} />
          </>}
          {basic && <p className="mt-8 text-sm text-muted-foreground">This run comes from the public contract routes, which carry its kind, times and result. Checks, agent steps, tokens and cost arrive with the /api routes.</p>}
        </>}
      </SheetContent>
    </Sheet>
  );
}
