import { useRef, useState } from "react";
import { ArrowLeft, BookOpen, Wrench } from "lucide-react";
import { absTime, costText, hostname, portalCost, relTime, runCost } from "@/data/format";
import { newestFirst } from "@/data/view";
import type { DetailView, Source } from "@/types";
import { CostLabel, ResultMark, Skel, StateBadge } from "./primitives";
import { TenderCountChart } from "./Charts";
import { RunSheet } from "./RunSheet";
import { TenderTable } from "./TenderTable";
import { Button } from "@/components/ui/button";
import { RepairBand } from "./RepairBand";
import { repairRuns } from "./evidence";

const Back = () => (
  <a href="#/" className="inline-flex items-center gap-1 rounded-sm text-label text-primary hover:underline"><ArrowLeft aria-hidden className="size-4" /> Back to portals</a>
);

export function PortalDetail({ detail, source, now, eurPerUsd }: { detail: DetailView | null; source: Source | null; now: number; eurPerUsd: number }) {
  const [selected, setSelected] = useState<string | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const openRun = (id: string) => { returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setSelected(id); };
  if (!detail) return <DetailSkeleton />;
  if (detail.kind !== "ok") {
    return (
      <div className="flex flex-col items-start gap-4 rounded-lg border border-border bg-surface p-8">
        <Back />
        <h1 className="text-heading font-semibold">{detail.kind === "notFound" ? "Portal not found" : "Portal not in demo data"}</h1>
        <p className="text-secondary-text">{detail.kind === "notFound" ? "The API no longer lists this portal." : "The API is unavailable and the bundled snapshot has no record of this portal."}</p>
      </div>
    );
  }
  const { portal: p, timeline, tenders } = detail;
  const runs = newestFirst(timeline);
  const { active, earlier } = repairRuns(p, timeline);
  const run = selected ? timeline.find((r) => r.id === selected) ?? null : null;
  const facts: [string, React.ReactNode][] = [
    ["Software", p.fingerprint ?? <span className="text-muted-foreground">Not identified</span>],
    ["Active recipe", p.recipeVersion != null ? <>v{p.recipeVersion}{p.reusedFrom && <span className="text-muted-foreground"> · reused from {p.reusedFrom}</span>}</> : <span className="text-muted-foreground">None yet</span>],
    ["Next read", p.nextReadAt ? <time dateTime={p.nextReadAt} title={absTime(p.nextReadAt, p.timezone)}>{relTime(p.nextReadAt, now)}</time> : <span className="text-muted-foreground">Not scheduled</span>],
    ["Last success", p.lastSuccessAt ? <time title={absTime(p.lastSuccessAt, p.timezone)}>{relTime(p.lastSuccessAt, now)}</time> : <span className="text-muted-foreground">Never</span>],
    ["Model cost", <CostLabel cost={portalCost(p)} eurPerUsd={eurPerUsd} />],
  ];
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Back />
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-heading font-semibold break-all">{hostname(p.url)}</h1>
          <StateBadge state={p.state} />
        </div>
        <p className="font-mono text-label text-muted-foreground break-all">{p.url}</p>
        {!active && <p className="max-w-[70rem] text-body">{p.reason}</p>}
        {p.cause && <p className="text-label text-secondary-text">Cause: {p.cause}</p>}
        <dl className="grid grid-cols-2 gap-3 border-y border-divider py-3 xl:grid-cols-5">
          {facts.map(([k, v]) => <div key={k}><dt className="text-label text-muted-foreground">{k}</dt><dd className="text-body">{v}</dd></div>)}
        </dl>
      </div>

      {active && <RepairBand portal={p} active={active} earlier={earlier} onInspect={openRun} />}
      <section aria-labelledby="tenders-h">
        <h2 id="tenders-h" className="mb-3 text-section font-semibold">Delivered tenders <span className="text-body font-normal text-muted-foreground">({tenders.length})</span></h2>
        <TenderTable tenders={tenders} timeZone={p.timezone} live={source === "live"} />
      </section>
      <section aria-labelledby="runs-h" className="border-t border-divider pt-4">
        <h2 id="runs-h" className="mb-3 text-section font-semibold">Run history</h2>
        <TenderCountChart timeline={timeline} timeZone={p.timezone} />
        {runs.length === 0 ? <p className="mt-4 text-secondary-text">No runs yet.</p> : (
          <ol className="run-rail ml-3 mt-5 flex flex-col">
            {runs.map((r) => {
              const Icon = r.kind === "read" ? BookOpen : Wrench;
              return <li key={r.id} className="relative pl-7">
                <Icon aria-hidden className="absolute -left-2 top-3 size-4 bg-background text-secondary-text" />
                <Button variant="ghost" type="button" onClick={() => openRun(r.id)} className="h-auto w-full justify-start whitespace-normal rounded-sm px-2 py-2 text-left">
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-label">
                      <span className="font-semibold capitalize">{r.kind}</span><ResultMark result={r.result} />
                      <time className="text-muted-foreground" dateTime={r.startedAt} title={absTime(r.startedAt, p.timezone)}>{absTime(r.startedAt, p.timezone)}</time>
                      <span className="text-micro text-muted-foreground">{r.trigger}</span>
                    </span>
                    <span className="text-label font-normal text-secondary-text">{r.summary}</span>
                  </span>
                  <span className="ml-auto hidden shrink-0 text-micro font-normal text-muted-foreground sm:inline">{costText(runCost(r))}</span>
                </Button>
                <p className="pb-2 pl-2 text-micro text-muted-foreground sm:hidden">{costText(runCost(r))}</p>
              </li>;
            })}
          </ol>
        )}
      </section>
      <RunSheet run={run} timeline={timeline} timeZone={p.timezone} eurPerUsd={eurPerUsd} onClose={() => setSelected(null)} returnFocus={returnFocus} />
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading portal">
      <Skel className="h-5 w-32" /><Skel className="h-9 w-96" /><Skel className="h-5 w-2/3" /><Skel className="h-20 w-full" />
      <div className="grid gap-6 xl:grid-cols-[1fr_1.2fr]"><Skel className="h-[30rem]" /><Skel className="h-[30rem]" /></div>
    </div>
  );
}
