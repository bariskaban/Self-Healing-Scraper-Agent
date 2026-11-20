import { useEffect, useRef, useState } from "react";
import { ArrowLeft, BookOpen, ChevronRight, Wrench } from "lucide-react";
import { absTime, costText, hostname, portalCost, relTime, runCost } from "@/data/format";
import { newestFirst } from "@/data/view";
import type { DetailView, Source } from "@/types";
import { CostLabel, ResultMark, SectionHead, Skel, StateBadge, idx } from "./primitives";
import { TenderCountChart } from "./Charts";
import { RunSheet } from "./RunSheet";
import { TenderTable } from "./TenderTable";
import { RepairBand } from "./RepairBand";
import { repairRuns } from "./evidence";
import { clock, stillServing } from "./overview";
import { takePendingRun } from "./viewState";

const Back = () => (
  <a href="#/" className="link-arrow text-sm"><ArrowLeft aria-hidden className="size-4" /> Back to portals</a>
);

export function PortalDetail({ detail, source, now, eurPerUsd }: { detail: DetailView | null; source: Source | null; now: number; eurPerUsd: number }) {
  const [selected, setSelected] = useState<string | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const openRun = (id: string) => { returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setSelected(id); };
  // A link that asked for a run (an "Inspect" link, or ?run=<id> on entry) opens it once the timeline is here.
  const loaded = detail?.kind === "ok";
  useEffect(() => {
    if (!loaded || detail?.kind !== "ok") return;
    const wanted = takePendingRun();
    if (wanted && detail.timeline.some((r) => r.id === wanted)) setSelected(wanted);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded]);
  if (!detail) return <DetailSkeleton />;
  if (detail.kind !== "ok") {
    return (
      <div className="card mt-10 flex flex-col items-start gap-4 p-8">
        <Back />
        <h1 className="display text-[2.4rem]">{detail.kind === "notFound" ? "Portal not found" : "Portal not in demo data"}</h1>
        <p className="text-secondary-text">{detail.kind === "notFound" ? "The API no longer lists this portal." : "The API is unavailable and the bundled snapshot has no record of this portal."}</p>
      </div>
    );
  }
  const { portal: p, timeline, tenders } = detail;
  const runs = newestFirst(timeline);
  const { active, earlier } = repairRuns(p, timeline);
  const run = selected ? timeline.find((r) => r.id === selected) ?? null : null;
  const quiet = "font-normal text-muted-foreground";
  const facts: [string, React.ReactNode][] = [
    ["Software", p.fingerprint ?? <span className={quiet}>Not identified</span>],
    ["Active recipe", p.recipeVersion != null ? <>v{p.recipeVersion}{p.reusedFrom && <span className="block text-sm font-normal text-muted-foreground">Reused from {p.reusedFrom}</span>}</> : <span className={quiet}>None yet</span>],
    ["Next read", p.nextReadAt ? <time dateTime={p.nextReadAt} title={absTime(p.nextReadAt, p.timezone)}>{relTime(p.nextReadAt, now)}</time> : <span className={quiet}>Not scheduled</span>],
    ["Last success", p.lastSuccessAt ? <time dateTime={p.lastSuccessAt} title={absTime(p.lastSuccessAt, p.timezone)}>{relTime(p.lastSuccessAt, now)}</time> : <span className={quiet}>Never</span>],
    ["Model cost", <CostLabel cost={portalCost(p)} eurPerUsd={eurPerUsd} stacked />],
  ];
  return (
    <div className="flex flex-col gap-10 pt-8 2xl:gap-12 2xl:pt-10">
      <div>
        <Back />
        <p className="eyebrow mt-7">Portal{p.cause ? ` · cause: ${p.cause}` : ""}</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-3">
          <h1 className="display text-[clamp(2.1rem,4.6vw,4.1rem)] break-all">{hostname(p.url)}</h1>
          <StateBadge state={p.state} note={stillServing(p)} float className="text-[0.95rem]" />
        </div>
        <p className="mt-4 max-w-[62rem] text-[1.2rem] leading-relaxed text-secondary-text">{p.reason}</p>
        <p className="mt-2 font-mono text-sm break-all text-muted-foreground">{p.url}</p>
        <dl className="mt-7 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {facts.map(([k, v], i) => (
            <div key={k} className="glass rounded-2xl px-4 py-3.5" style={idx(i)}>
              <dt className="text-[0.7rem] font-semibold tracking-[0.14em] text-muted-foreground uppercase">{k}</dt>
              <dd className="mt-1 text-[1.1rem] font-medium">{v}</dd>
            </div>
          ))}
        </dl>
      </div>

      {active && <RepairBand portal={p} active={active} earlier={earlier} timeline={timeline} onInspect={openRun} />}

      <section aria-labelledby="chart-h">
        <SectionHead id="chart-h" label="Delivery" title="Published per read">
          <p className="text-sm text-muted-foreground">One column per recorded read, oldest to newest</p>
        </SectionHead>
        <div className="card p-5 2xl:p-7"><TenderCountChart timeline={timeline} timeZone={p.timezone} /></div>
      </section>

      <section aria-labelledby="tenders-h">
        <SectionHead id="tenders-h" label="Delivered tenders" title={<>{tenders.length} {tenders.length === 1 ? "record" : "records"} <span className="text-muted-foreground">available now</span></>}>
          {p.lastSuccessAt && <p className="text-sm text-muted-foreground">Last correct delivery at <time dateTime={p.lastSuccessAt}>{clock(p.lastSuccessAt, p.timezone)}</time></p>}
        </SectionHead>
        <TenderTable tenders={tenders} timeZone={p.timezone} live={source === "live"} />
      </section>

      <section aria-labelledby="runs-h">
        <SectionHead id="runs-h" label="Run history" title={<>{runs.length} {runs.length === 1 ? "run" : "runs"}, <span className="text-muted-foreground">newest first</span></>}>
          <p className="text-sm text-muted-foreground">Select a run for its checks and agent steps</p>
        </SectionHead>
        {runs.length === 0 ? <p className="card p-6 text-secondary-text">No runs yet.</p> : (
          <ol className="relative flex flex-col gap-2">
            <span aria-hidden className="run-rail-line" />
            {runs.map((r) => {
              const repair = r.kind === "repair";
              const Icon = repair ? Wrench : BookOpen;
              return (
                <li key={r.id} className="relative pl-12">
                  <span aria-hidden className={`absolute top-4 left-0 grid size-[2.15rem] place-items-center rounded-full border border-border ${repair ? "bg-raised text-healing" : "bg-surface text-secondary-text"}`}><Icon className="size-4" /></span>
                  <button type="button" onClick={() => openRun(r.id)} className={`group card flex w-full cursor-pointer flex-wrap items-center gap-x-5 gap-y-1.5 rounded-2xl px-4 py-3.5 text-left transition-colors duration-500 ease-spring hover:border-[var(--border-strong)] 2xl:px-5 ${repair ? "border-[color-mix(in_srgb,var(--healing)_28%,transparent)]" : ""}`}>
                    <span className="flex min-w-0 flex-1 basis-[28rem] flex-col gap-1">
                      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                        <time className="tnum text-[1.05rem] font-semibold" dateTime={r.startedAt} title={absTime(r.startedAt, p.timezone)}>{clock(r.startedAt, p.timezone)}</time>
                        <span className="font-semibold capitalize">{r.kind}</span>
                        <ResultMark result={r.result} />
                        <span className="chip chip-plain !py-0.5 text-xs text-muted-foreground">{r.trigger}</span>
                        {r.recipeChange && <span className="chip chip-plain !py-0.5 text-xs text-integrating">Recipe v{r.recipeChange.from} → v{r.recipeChange.to}</span>}
                      </span>
                      <span className="leading-relaxed text-secondary-text">{r.summary}</span>
                    </span>
                    <span className="tnum shrink-0 text-sm text-muted-foreground">{costText(runCost(r))}</span>
                    <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground transition-transform duration-500 ease-spring group-hover:translate-x-1 group-hover:text-primary max-sm:hidden" />
                  </button>
                </li>
              );
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
    <div className="flex flex-col gap-6 pt-8" aria-busy="true" aria-label="Loading portal">
      <Skel className="h-5 w-32" /><Skel className="mt-4 h-14 w-[34rem] max-w-full" /><Skel className="h-6 w-2/3" />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <Skel key={i} className="h-[4.5rem] rounded-2xl" />)}</div>
      <Skel className="h-[18rem] rounded-[1.25rem]" /><Skel className="h-[14rem] rounded-[1.25rem]" />
    </div>
  );
}
