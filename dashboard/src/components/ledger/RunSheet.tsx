import { Fragment, type ReactNode, type RefObject } from "react";
import { CheckCircle2, ChevronDown, XCircle, Wrench, GitBranch, Clock3 } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { absTime, costText, runCost } from "@/data/format";
import { repairEvidence } from "./evidence";
import type { Check, Run } from "@/types";
import { ResultMark, idx } from "./primitives";
import { StepWaterfall } from "./Charts";
import { clock } from "./overview";

const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

function Checks({ checks }: { checks: Check[] | undefined }) {
  if (!checks?.length) return <p className="text-secondary-text">No checks recorded.</p>;
  return (
    <ul className="grid gap-2.5 @3xl:grid-cols-2">
      {checks.map((c, i) => (
        <li key={`${c.name}-${i}`} className="rounded-2xl border border-divider bg-inset p-4">
          <div className="flex flex-wrap items-center gap-2 font-medium">
            {c.passed ? <CheckCircle2 aria-hidden className="size-[1.1rem] text-serving" /> : <XCircle aria-hidden className="size-[1.1rem] text-failed" />}
            <span className="font-mono text-sm break-all">{c.name}</span>
            <span className={c.passed ? "text-serving" : "text-failed"}>{c.passed ? "Passed" : "Failed"}</span>
            {!c.passed && <span className="rounded-full bg-failed-tint px-2 py-0.5 text-xs tracking-wide text-failed uppercase">{c.severity}</span>}
          </div>
          <p className="mt-1.5 leading-relaxed text-secondary-text">{c.message}</p>
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

export function RunSheet({ run, timeline, timeZone, eurPerUsd, onClose, returnFocus }: { run: Run | null; timeline: Run[]; timeZone: string | null; eurPerUsd: number; onClose: () => void; returnFocus: RefObject<HTMLElement | null> }) {
  const evidence = run?.kind === "repair" ? repairEvidence(run, timeline) : null;
  return (
    <Sheet open={!!run} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="run-sheet w-full max-w-full overflow-y-auto border-l-[var(--glass-border)] bg-[var(--panel)] p-5 backdrop-blur-2xl backdrop-saturate-150 duration-700 ease-spring sm:w-[68rem] sm:max-w-[97vw] sm:rounded-l-[1.75rem] sm:p-9 2xl:p-11" onCloseAutoFocus={(event) => { event.preventDefault(); returnFocus.current?.focus(); }}>
        {run && <>
          <SheetHeader className="space-y-0 pr-8 text-left">
            <p className="eyebrow">{run.kind} · trigger: {run.trigger}</p>
            <SheetTitle className="display mt-3 text-[clamp(1.9rem,3.2vw,2.9rem)] font-light">
              {run.kind === "repair" ? "Repair" : "Read"} at {clock(run.startedAt, timeZone)}{run.recipeChange && <>, <span className="highlight font-normal">recipe v{run.recipeChange.from} → v{run.recipeChange.to}</span></>}
            </SheetTitle>
            <SheetDescription asChild><div className="!mt-4 flex flex-wrap items-center gap-2 text-sm text-secondary-text">
              <span className="chip chip-plain"><ResultMark result={run.result} /></span>
              <span className="chip chip-plain"><time dateTime={run.startedAt}>{absTime(run.startedAt, timeZone)}</time></span>
              <span className="chip chip-plain tnum" title={`Model usage only, fixed rate ${eurPerUsd} EUR/USD`}>{costText(runCost(run))}</span>
              <span className="chip chip-plain tnum">{run.modelCalls} model call{run.modelCalls === 1 ? "" : "s"}</span>
            </div></SheetDescription>
          </SheetHeader>
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
            <Label>Agent steps</Label>
            <StepWaterfall steps={run.steps ?? []} startedAt={run.startedAt} />
            <div className="mt-9 border-b border-divider">
              <Disclosure label="Triggering read and full checks">{evidence.triggering ? <><p className="mb-3 text-sm"><ResultMark result={evidence.triggering.result} /> · {absTime(evidence.triggering.startedAt, timeZone)}</p><p className="mb-4">{evidence.triggering.summary}</p><Checks checks={evidence.triggering.checks} /></> : <p className="text-muted-foreground">Not recorded</p>}</Disclosure>
              <Disclosure label="What changed: recipe details">{run.recipeChange ? <><p className="font-semibold">Recipe v{run.recipeChange.from} → v{run.recipeChange.to}</p><p className="mt-2 text-secondary-text">{run.recipeChange.rationale}</p><ul className="mt-3 flex flex-wrap gap-2">{run.recipeChange.changedParts.map((part) => <li key={part} className="chip chip-plain text-sm">{part}</li>)}</ul></> : <p className="text-secondary-text">{evidence.changed}</p>}</Disclosure>
              <Disclosure label="Verification checks and observed / expected values"><p className="mb-4">{run.summary}</p><Checks checks={run.checks} /></Disclosure>
              <Disclosure label="Recorded counters"><Stats stats={run.stats} />{(!run.stats || !Object.keys(run.stats).length) && <p className="text-muted-foreground">Not recorded</p>}</Disclosure>
              <Disclosure label="Full agent step records"><ol className="flex flex-col gap-3">{run.steps?.map((step) => <li key={step.seq}><p className="font-semibold">{step.seq}. {step.name} · {absTime(step.at, timeZone)}</p><p className="text-secondary-text">{step.summary}</p></li>)}</ol>{!run.steps?.length && <p className="text-muted-foreground">Not recorded</p>}</Disclosure>
            </div>
          </> : <>
            <p className="mt-7 max-w-[52rem] text-[1.3rem] leading-relaxed font-light">{run.summary}</p>
            <Label>Checks</Label><Checks checks={run.checks} />
            {run.stats && Object.keys(run.stats).length > 0 && <><Label>Recorded counters</Label><Stats stats={run.stats} /></>}
            <Label>Agent steps</Label><StepWaterfall steps={run.steps ?? []} startedAt={run.startedAt} />
          </>}
        </>}
      </SheetContent>
    </Sheet>
  );
}
