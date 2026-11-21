import { useEffect, useRef, type ReactNode } from "react";
import { eur, hostname, tokens } from "@/data/format";
import { sortPortals, type FleetSummary } from "@/data/view";
import type { Portal } from "@/types";
import { cn } from "@/lib/utils";
import { hasActiveRepair } from "./evidence";
import { costPerPortal, fleetSentence } from "./overview";
import { Skel, idx } from "./primitives";

/** The entrance plays on the first load only, never on a poll or when coming back from a portal. */
let revealed = false;
function useFirstReveal() {
  const first = useRef(!revealed).current;
  useEffect(() => { revealed = true; }, []);
  return first ? "reveal" : "";
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function FleetHero({ portals, summary }: { portals: Portal[] | null; summary: FleetSummary | null }) {
  const reveal = useFirstReveal();
  if (!portals || !summary) {
    return <section aria-label="Fleet summary" aria-busy="true" className="pt-10 2xl:pt-14"><Skel className="h-4 w-28" /><Skel className="mt-5 h-14 w-4/5" /><Skel className="mt-3 h-14 w-3/5" /><Skel className="mt-6 h-6 w-1/2" /></section>;
  }
  const { total, parts } = fleetSentence(portals);
  const repairing = sortPortals(portals).find(hasActiveRepair);
  const sub = total === 0
    ? "No portal is attached yet."
    : repairing && repairing.tenderCount > 0
      ? `${hostname(repairing.url)} is still serving ${plural(repairing.tenderCount, "tender")} from its last correct read while the agent repairs it. ${plural(summary.tendersDelivered, "tender")} available across the fleet.`
      : `${plural(summary.tendersDelivered, "tender")} available across the fleet.`;
  return (
    <section aria-label="Fleet summary" className="pt-8 2xl:pt-10">
      <p className={cn("eyebrow", reveal)} style={idx(0)}>Fleet status</p>
      <h2 className={cn("display mt-4 text-[clamp(2rem,3.4vw,3.2rem)]", reveal)} style={idx(1)}>
        <span className="sm:whitespace-nowrap">{plural(total, "portal")}.</span>{" "}
        {parts.map((part, i) => (
          <span key={part.state}>
            <span className="sm:whitespace-nowrap"><span className={part.highlight ? "highlight font-normal" : undefined}>{part.count} {part.text}</span>{i < parts.length - 1 ? "," : "."}</span>{" "}
          </span>
        ))}
      </h2>
      <p className={cn("mt-5 max-w-[52rem] text-[1.1rem] leading-relaxed text-secondary-text", reveal)} style={idx(2)}>{sub}</p>
    </section>
  );
}

function Stat({ label, value, unit, prefix, caption, i, reveal }: { label: string; value: string; unit?: string; prefix?: string | undefined; caption: ReactNode; i: number; reveal: string }) {
  return (
    <div className={cn("card flex min-h-[10.5rem] flex-col overflow-hidden p-5 2xl:p-6", reveal)} style={idx(i)}>
      <dt className="text-sm font-medium text-muted-foreground">{label}</dt>
      <dd className="flex flex-1 flex-col pt-5">
        <p className="flex flex-wrap items-baseline gap-x-2">
          {prefix && <span className="text-sm text-muted-foreground">{prefix}</span>}
          <span className="silver tnum text-[clamp(2.5rem,3.5vw,3.5rem)] leading-none font-semibold tracking-[-0.035em]">{value}</span>
          {unit && <span className="text-base font-medium text-muted-foreground">{unit}</span>}
        </p>
        <p className="mt-auto pt-4 text-sm leading-snug text-secondary-text">{caption}</p>
      </dd>
    </div>
  );
}

const amount = (v: number) => eur(v).replace(" EUR", "");
/** Keeps "< 0.01 EUR" on one line. */
const money = (v: number) => eur(v).replaceAll(" ", "\u00a0");

export function StatCards({ portals, summary, eurPerUsd, basic }: { portals: Portal[] | null; summary: FleetSummary | null; eurPerUsd: number | null; basic: boolean }) {
  const reveal = useFirstReveal();
  if (!portals || !summary) return <div className="grid grid-cols-2 gap-4" aria-hidden>{[0, 1, 2, 3].map((i) => <Skel key={i} className="min-h-[10.5rem] rounded-[1.25rem]" />)}</div>;
  const cost = summary.cost;
  const per = costPerPortal(portals);
  const delivering = portals.filter((p) => p.tenderCount > 0).length;
  const missing = basic ? "Not on the contract routes yet; it arrives with /api/dashboard." : "Not recorded.";
  return (
    <dl aria-label="Fleet numbers" className="grid grid-cols-1 gap-4 min-[420px]:grid-cols-2">
      <Stat i={3} reveal={reveal} label="Tenders delivered" value={String(summary.tendersDelivered)}
        caption={`Records available now from ${plural(delivering, "portal")}.`} />
      <Stat i={4} reveal={reveal} label="Reads in the last hour" value={summary.readsLastHour === null ? "—" : String(summary.readsLastHour)}
        caption={summary.readsLastHour === null ? missing : "Read runs started in the last 60 minutes, repairs excluded."} />
      {cost.kind === "known"
        ? <Stat i={5} reveal={reveal} label="Model cost to date" prefix={cost.incomplete ? "At least" : undefined} value={amount(cost.eur)} unit="EUR"
            caption={`${tokens(cost.tokens)} tokens${cost.incomplete ? " · incomplete usage" : ""}. Model only${eurPerUsd ? `, 1\u00a0USD\u00a0=\u00a0${eurPerUsd}\u00a0EUR, fixed` : ""}.`} />
        : <Stat i={5} reveal={reveal} label="Model cost to date" value="—" caption={missing} />}
      {per.average !== null
        ? <Stat i={6} reveal={reveal} label="Cost per new portal" value={amount(per.average)} unit="EUR"
            caption={<>Average model cost of {plural(per.count, "portal")} with a working recipe, repairs included.{per.learned !== null && per.reused !== null && <> Learned: {money(per.learned)}. Reused recipe: {money(per.reused)}.</>}</>} />
        : <Stat i={6} reveal={reveal} label="Cost per new portal" value="—" caption={basic ? missing : "Not recorded: no portal has a working recipe yet."} />}
    </dl>
  );
}
