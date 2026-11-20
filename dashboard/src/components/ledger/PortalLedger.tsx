import { useEffect, useRef, useState } from "react";
import { absTime, hostname, portalCost, relTime } from "@/data/format";
import { portalHash } from "@/data/hooks";
import { sortPortals } from "@/data/view";
import { cn } from "@/lib/utils";
import type { Portal, PortalState } from "@/types";
import { CostLabel, DeliverySparkline, ReadHistory30, ResultMark, Skel, StateBadge } from "./primitives";

function useFlashes(portals: Portal[], live: boolean) {
  const prev = useRef<Map<string, PortalState> | null>(null);
  const wasLive = useRef(false);
  const [flash, setFlash] = useState<Record<string, number>>({});
  useEffect(() => {
    const next = new Map(portals.map((p) => [p.id, p.state]));
    const before = prev.current;
    if (before && live && wasLive.current) {
      const changed = portals.filter((p) => before.has(p.id) && before.get(p.id) !== p.state);
      if (changed.length) setFlash((f) => { const n = { ...f }; changed.forEach((p) => (n[p.id] = (n[p.id] ?? 0) + 1)); return n; });
    }
    prev.current = next;
    wasLive.current = live;
  }, [portals, live]);
  return flash;
}

function LastSuccess({ p, now }: { p: Portal; now: number }) {
  if (!p.lastSuccessAt) return <span className="text-muted-foreground">Never</span>;
  return <time dateTime={p.lastSuccessAt} title={absTime(p.lastSuccessAt, p.timezone)}>{relTime(p.lastSuccessAt, now)}</time>;
}

function LastRun({ p }: { p: Portal }) {
  if (!p.lastRun) return <span className="text-muted-foreground">No runs yet</span>;
  return <span className="whitespace-nowrap"><span className="capitalize text-secondary-text">{p.lastRun.kind}</span> · <ResultMark result={p.lastRun.result} /></span>;
}

export function PortalLedger({ portals, now, eurPerUsd, live }: { portals: Portal[]; now: number; eurPerUsd: number; live: boolean }) {
  const rows = sortPortals(portals);
  const flash = useFlashes(portals, live);
  const th = "px-3 py-2 text-left text-label font-medium text-secondary-text 2xl:px-4";
  const td = "px-3 py-2 align-middle 2xl:px-4 2xl:py-2.5";
  return (
    <>
      <div className="hidden overflow-hidden rounded-lg border border-border bg-surface md:block">
        <table className="w-full border-collapse text-label ledger-table">
          <caption className="sr-only">Portals, sorted by state then hostname</caption>
          <thead className="border-b border-divider bg-inset">
            <tr>
              <th scope="col" className={th}>State</th>
              <th scope="col" className={th}>Portal / Reason</th>
              <th scope="col" className={cn(th, "text-right")}>Tenders</th>
              <th scope="col" className={th}>Last success</th>
              <th scope="col" className={th}>Last run</th>
              <th scope="col" className={th}>Last 30 reads</th>
              <th scope="col" className={cn(th, "text-right")}>Model cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-divider">
            {rows.map((p) => (
              <tr key={`${p.id}-${flash[p.id] ?? 0}`} className={cn("hover:bg-inset", live && flash[p.id] && `animate-state-flash flash-${p.state}`)}>
                <td className={td}><StateBadge state={p.state} /></td>
                <td className={cn(td, "w-[40%] min-w-[16rem]")}>
                  <a href={portalHash(p.id)} className="text-body font-semibold text-primary underline-offset-2 hover:underline break-words">{hostname(p.url)}</a>
                  <p className="text-label leading-relaxed text-secondary-text">{p.reason}</p>
                </td>
                <td className={cn(td, "text-right")}>
                  <div className="flex items-center justify-end gap-3"><DeliverySparkline values={p.deliveryTrend} /><span className="font-semibold">{p.tenderCount}</span></div>
                </td>
                <td className={td}><LastSuccess p={p} now={now} /></td>
                <td className={td}><LastRun p={p} /></td>
                <td className={td}><ReadHistory30 reads={p.recentReads} /></td>
                <td className={cn(td, "text-right")}><CostLabel cost={portalCost(p)} eurPerUsd={eurPerUsd} className="text-label" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="flex flex-col gap-3 md:hidden" aria-label="Portals">
        {rows.map((p) => (
          <li key={`${p.id}-${flash[p.id] ?? 0}`} className={cn("rounded-lg border border-border bg-surface p-4", live && flash[p.id] && `animate-state-flash flash-${p.state}`)}>
            <div className="flex items-start justify-between gap-2">
              <a href={portalHash(p.id)} className="font-semibold text-primary break-all">{hostname(p.url)}</a>
              <StateBadge state={p.state} />
            </div>
            <p className="mt-1 text-label text-secondary-text">{p.reason}</p>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-label">
              <dt className="text-muted-foreground">Tenders</dt><dd className="font-semibold">{p.tenderCount}</dd>
              <dt className="text-muted-foreground">Last success</dt><dd><LastSuccess p={p} now={now} /></dd>
              <dt className="text-muted-foreground">Last run</dt><dd><LastRun p={p} /></dd>
              <dt className="col-span-2 text-muted-foreground">Last 30 reads</dt><dd className="col-span-2"><ReadHistory30 reads={p.recentReads} /></dd>
              <dt className="col-span-2 text-muted-foreground">Model cost</dt><dd className="col-span-2"><CostLabel cost={portalCost(p)} eurPerUsd={eurPerUsd} className="whitespace-normal" /></dd>
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}

export function LedgerSkeleton() {
  return (
    <div className="rounded-lg border border-border bg-surface" aria-busy="true" aria-label="Loading portals">
      <div className="h-10 border-b border-divider bg-inset" />
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex h-[3.6rem] items-center gap-6 border-b border-divider px-4 last:border-0">
          <Skel className="h-6 w-24" /><Skel className="h-5 flex-1" /><Skel className="h-5 w-16" /><Skel className="h-5 w-20" /><Skel className="h-5 w-24" /><Skel className="h-6 w-40" /><Skel className="h-5 w-28" />
        </div>
      ))}
    </div>
  );
}

const CURL = `curl -X POST http://localhost:8080/portals -H 'Content-Type: application/json' -d '{"url":"https://your-public-portal.example"}'`;

export function EmptyFleet() {
  return (
    <div className="rounded-lg border border-border bg-surface p-8">
      <h2 className="text-section font-semibold">No portals yet</h2>
      <p className="mt-2 text-secondary-text">Attach a public tender portal through the API:</p>
      <pre tabIndex={0} aria-label="Command to attach a portal" className="mt-4 overflow-x-auto rounded-md bg-inset p-4 font-mono text-label select-all">{CURL}</pre>
    </div>
  );
}
