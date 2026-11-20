import type { FleetSummary } from "@/data/view";
import type { PortalState } from "@/types";
import { STATE_INK, CostLabel, Skel } from "./primitives";

const sentenceOrder: PortalState[] = ["serving", "healing", "failed", "integrating"];
export function FleetStrip({ summary, eurPerUsd }: { summary: FleetSummary | null; eurPerUsd: number }) {
  if (!summary) return <section aria-label="Fleet summary"><Skel className="h-8 w-2/3" /><Skel className="mt-3 h-5 w-1/2" /></section>;
  const total = Object.values(summary.counts).reduce((sum, count) => sum + count, 0);
  return (
    <section aria-label="Fleet summary" className="py-1">
      <h2 className="text-2xl font-semibold leading-relaxed"><span>{total} portals: </span>{sentenceOrder.map((state, index) => <span key={state} className="inline-block">{index > 0 && <span className="text-muted-foreground"> · </span>}<span className={STATE_INK[state]}>{summary.counts[state]}</span> {state}{index === 3 ? "." : ""}</span>)}</h2>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-1 text-label text-secondary-text tabular-nums">
        <span><strong className="font-semibold text-foreground">{summary.tendersDelivered}</strong> tenders delivered</span>
        <span><strong className="font-semibold text-foreground">{summary.readsLastHour}</strong> reads in the last hour</span>
        <span>Model cost to date <CostLabel cost={summary.cost} eurPerUsd={eurPerUsd} /></span>
      </div>
    </section>
  );
}
