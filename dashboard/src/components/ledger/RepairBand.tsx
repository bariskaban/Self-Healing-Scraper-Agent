import { ArrowRight, History } from "lucide-react";
import { costText, runCost } from "@/data/format";
import type { Portal, Run } from "@/types";
import { repairEvidence } from "./evidence";
import { clock, stillServing } from "./overview";
import { StateBadge } from "./primitives";

/** The repair in flight on a portal page: what broke, what the agent is doing, and what is still served. */
export function RepairBand({ portal, active, earlier, timeline, onInspect }: {
  portal: Portal; active: Run; earlier: Run | null; timeline: Run[]; onInspect: (id: string) => void;
}) {
  const ev = repairEvidence(active, timeline);
  const stops = [["Broke", ev.broke], ["Agent action", ev.action], ["Changed", ev.changed], ["Verified", ev.verified]] as const;
  return (
    <section aria-label="Active repair" className="card overflow-hidden p-6 2xl:p-8">
      <div aria-hidden className="pointer-events-none absolute -top-28 -right-10 size-80 rounded-full bg-[radial-gradient(closest-side,rgb(251_191_36/0.1),transparent)]" />
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div>
          <p className="eyebrow flex items-center gap-2.5"><span aria-hidden className="live-dot text-healing" />Repair in progress</p>
          <h2 className="display mt-2 text-[1.9rem]">Repairing since {clock(active.startedAt, portal.timezone)}, <span className="highlight font-normal">{stillServing(portal) ?? "nothing delivered yet"}</span></h2>
        </div>
        <StateBadge state="healing" float />
      </div>
      <ol className="mt-6 grid gap-x-6 gap-y-4 md:grid-cols-2 2xl:grid-cols-4">
        {stops.map(([label, text], i) => (
          <li key={label} className="border-t border-divider pt-3">
            <p className="text-xs font-semibold tracking-[0.16em] text-muted-foreground uppercase">{String(i + 1).padStart(2, "0")} · {label}</p>
            <p className="mt-1.5 leading-relaxed text-secondary-text">{text}</p>
          </li>
        ))}
      </ol>
      <div className="mt-6 flex flex-wrap items-center gap-x-7 gap-y-2 text-sm">
        <button type="button" className="pill-cta" onClick={() => onInspect(active.id)}>Inspect this repair <ArrowRight aria-hidden className="size-4" /></button>
        {earlier && <button type="button" className="link-arrow" onClick={() => onInspect(earlier.id)}><History aria-hidden className="size-4" /> Earlier verified repair, {clock(earlier.startedAt, portal.timezone)} <ArrowRight aria-hidden className="size-4" /></button>}
        <span className="text-muted-foreground sm:ml-auto">{costText(runCost(active))}</span>
      </div>
    </section>
  );
}
