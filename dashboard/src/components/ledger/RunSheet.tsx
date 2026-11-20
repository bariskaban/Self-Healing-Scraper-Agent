import { Fragment, type RefObject } from "react";
import { CheckCircle2, XCircle, Wrench, GitBranch, Clock3 } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { absTime, costText, runCost } from "@/data/format";
import { repairEvidence } from "./evidence";
import type { Check, Run } from "@/types";
import { ResultMark } from "./primitives";
import { StepWaterfall } from "./Charts";

const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

function Checks({ checks }: { checks: Check[] | undefined }) {
  if (!checks?.length) return <p className="text-label text-muted-foreground">No checks recorded.</p>;
  return (
    <ul className="flex flex-col gap-2">
      {checks.map((c, i) => (
        <li key={`${c.name}-${i}`} className="rounded-md border border-divider p-3 text-label">
          <div className="flex items-center gap-2 font-medium">
            {c.passed ? <CheckCircle2 aria-hidden className="size-4 text-serving" /> : <XCircle aria-hidden className="size-4 text-failed" />}
            {c.name}
            <span className={c.passed ? "text-serving" : "text-failed"}>{c.passed ? "Passed" : "Failed"}</span>
            {!c.passed && <span className="rounded-sm bg-failed-tint px-1.5 text-micro uppercase text-failed">{c.severity}</span>}
          </div>
          <p className="mt-1 text-secondary-text">{c.message}</p>
          {(c.observed !== undefined || c.expected !== undefined) && (
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 font-mono text-micro">
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
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-label">
      {Object.entries(stats).map(([k, v]) => <Fragment key={k}><dt className="text-muted-foreground">{k}</dt><dd>{String(v)}</dd></Fragment>)}
    </dl>
  );
}

const H = ({ children }: { children: React.ReactNode }) => <h3 className="mt-6 mb-2 text-body font-semibold">{children}</h3>;

function Disclosure({ label, children }: { label: string; children: React.ReactNode }) {
  return <details className="border-t border-divider py-3"><summary className="cursor-pointer text-body font-semibold">{label}</summary><div className="mt-3">{children}</div></details>;
}

export function RunSheet({ run, timeline, timeZone, eurPerUsd, onClose, returnFocus }: { run: Run | null; timeline: Run[]; timeZone: string | null; eurPerUsd: number; onClose: () => void; returnFocus: RefObject<HTMLElement | null> }) {
  const evidence = run?.kind === "repair" ? repairEvidence(run, timeline) : null;
  return (
    <Sheet open={!!run} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="run-sheet w-full max-w-full overflow-y-auto p-5 sm:w-[1080px] sm:max-w-[100vw] sm:p-8" onCloseAutoFocus={(event) => { event.preventDefault(); returnFocus.current?.focus(); }}>
        {run && <>
          <SheetHeader className="pr-8 text-left">
            <SheetTitle className="text-section capitalize">{run.kind} · {run.trigger}</SheetTitle>
            <SheetDescription asChild><div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-label">
              <ResultMark result={run.result} />
              <time dateTime={run.startedAt}>{absTime(run.startedAt, timeZone)}</time>
              <span title={`Model usage only, fixed rate ${eurPerUsd} EUR/USD`}>{costText(runCost(run))} · {run.modelCalls} model call{run.modelCalls === 1 ? "" : "s"}</span>
            </div></SheetDescription>
          </SheetHeader>
          {evidence ? <>
            <ol aria-label="Repair evidence" className="repair-sequence my-6 border-y border-divider py-5">
              {[
                { label: "Broke", text: evidence.broke, Icon: XCircle, ink: "text-failed" },
                { label: "Agent action", text: evidence.action, Icon: Wrench, ink: "text-healing" },
                { label: "Changed", text: evidence.changed, Icon: GitBranch, ink: "text-secondary-text" },
                { label: "Verified", text: evidence.verified, Icon: run.result === null ? Clock3 : run.result === "ok" ? CheckCircle2 : XCircle, ink: run.result === null ? "text-integrating" : run.result === "ok" ? "text-serving" : "text-failed" },
              ].map(({ label, text, Icon, ink }) => <li key={label} className="evidence-stop"><div className="flex items-center gap-2 text-label font-semibold"><Icon aria-hidden className={`size-4 shrink-0 ${ink} max-sm:absolute max-sm:left-0`} />{label}</div><p className="mt-2 text-body leading-relaxed">{text}</p></li>)}
            </ol>
            <h3 className="mb-3 text-section font-semibold">Agent steps</h3>
            <StepWaterfall steps={run.steps ?? []} startedAt={run.startedAt} />
            <div className="mt-6">
              <Disclosure label="Triggering read and full checks">{evidence.triggering ? <><p className="mb-3 text-label"><ResultMark result={evidence.triggering.result} /> · {absTime(evidence.triggering.startedAt, timeZone)}</p><p className="mb-3 text-body">{evidence.triggering.summary}</p><Checks checks={evidence.triggering.checks} /></> : <p className="text-muted-foreground">Not recorded</p>}</Disclosure>
              <Disclosure label="What changed — recipe details">{run.recipeChange ? <><p className="font-semibold">Recipe v{run.recipeChange.from} → v{run.recipeChange.to}</p><p className="mt-2">{run.recipeChange.rationale}</p><ul className="mt-2 list-inside list-disc text-label">{run.recipeChange.changedParts.map((part) => <li key={part}>{part}</li>)}</ul></> : <p>{evidence.changed}</p>}</Disclosure>
              <Disclosure label="Verification checks and observed / expected values"><p className="mb-3">{run.summary}</p><Checks checks={run.checks} /></Disclosure>
              <Disclosure label="Recorded counters"><Stats stats={run.stats} />{(!run.stats || !Object.keys(run.stats).length) && <p className="text-muted-foreground">Not recorded</p>}</Disclosure>
              <Disclosure label="Full agent step records"><ol className="flex flex-col gap-3">{run.steps?.map((step) => <li key={step.seq}><p className="text-label font-semibold">{step.seq}. {step.name} · {absTime(step.at, timeZone)}</p><p className="text-label text-secondary-text">{step.summary}</p></li>)}</ol>{!run.steps?.length && <p className="text-muted-foreground">Not recorded</p>}</Disclosure>
            </div>
          </> : <>
            <p className="mt-4 text-body">{run.summary}</p><H>Checks</H><Checks checks={run.checks} />
            {run.stats && <><H>Recorded counters</H><Stats stats={run.stats} /></>}
            <H>Agent steps</H><StepWaterfall steps={run.steps ?? []} startedAt={run.startedAt} />
          </>}
        </>}
      </SheetContent>
    </Sheet>
  );
}
