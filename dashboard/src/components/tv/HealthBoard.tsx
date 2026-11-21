import type { Portal } from "@/types";
import type { FleetSummary } from "@/data/view";
import { FleetHero } from "@/components/ledger/FleetStrip";
import { CostCard, DeliveryCard, HealthCard, KpiRow, ReadsCard, StatesCard } from "./Infographic";

/**
 * The fleet health board, slide 1 of TV mode: the fleet sentence, the four numbers and one chart
 * per card. It used to open the main page; the main page is the portal ledger now.
 */
export function HealthBoard({ portals, summary, basic }: { portals: Portal[]; summary: FleetSummary; basic: boolean }) {
  return (
    <div className="tv-board flex h-full min-h-0 flex-col gap-4">
      <FleetHero portals={portals} summary={summary} />
      <KpiRow portals={portals} summary={summary} basic={basic} />
      <div className="grid min-h-0 gap-4 xl:grid-cols-4">
        <DeliveryCard portals={portals} basic={basic} />
        <HealthCard portals={portals} basic={basic} />
        <StatesCard summary={summary} total={portals.length} />
      </div>
      <div className="grid min-h-0 gap-4 xl:grid-cols-2">
        <CostCard portals={portals} basic={basic} />
        <ReadsCard portals={portals} basic={basic} />
      </div>
    </div>
  );
}
