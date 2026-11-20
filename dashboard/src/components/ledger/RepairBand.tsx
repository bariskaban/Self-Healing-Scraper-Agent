import { ArrowRight, History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { absTime, hostname } from "@/data/format";
import { portalHash } from "@/data/hooks";
import type { Portal, Run } from "@/types";
import { StateBadge } from "./primitives";

export function RepairBand({ portal, active, earlier, onInspect }: {
  portal: Portal; active?: Run | null; earlier?: Run | null; onInspect?: (id: string) => void;
}) {
  return (
    <section aria-label="Active repair" className="flex flex-wrap items-center gap-x-5 gap-y-3 border border-border border-l-2 border-l-healing bg-raised px-4 py-3">
      <div className="flex items-center gap-3"><StateBadge state="healing" /><span className="text-body font-semibold break-all">{hostname(portal.url)}</span></div>
      <p className="min-w-0 flex-[1_1_30rem] text-label leading-relaxed">{portal.reason}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {onInspect && active ? <Button variant="link" className="h-auto px-0 text-label" onClick={() => onInspect(active.id)}>Inspect repair <ArrowRight aria-hidden /></Button>
          : <Button asChild variant="link" className="h-auto px-0 text-label"><a href={portalHash(portal.id)}>Inspect repair <ArrowRight aria-hidden /></a></Button>}
        {earlier && onInspect && <Button variant="link" className="h-auto max-w-full justify-start whitespace-normal px-0 text-left text-label" onClick={() => onInspect(earlier.id)}><History aria-hidden /> Earlier verified repair · {absTime(earlier.startedAt, portal.timezone)}</Button>}
      </div>
    </section>
  );
}