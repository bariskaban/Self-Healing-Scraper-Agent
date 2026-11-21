import { useEffect, useRef, useState, type MouseEvent } from "react";
import { ChevronRight, ExternalLink, Plus } from "lucide-react";
import { externalHref } from "@/data/api";
import { absTime, hostname, portalCost, relTime } from "@/data/format";
import { portalHash } from "@/data/hooks";
import { sortPortals } from "@/data/view";
import { cn } from "@/lib/utils";
import type { Portal, PortalState } from "@/types";
import { stillServing } from "./overview";
import { CostLabel, DeliverySparkline, ReadHistory30, ResultMark, Skel, StateBadge, idx } from "./primitives";

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
  // Without a read history the runs were not readable at all, so "no runs" would be a guess.
  if (!p.lastRun) return <span className="text-muted-foreground">{p.recentReads === null ? "Not recorded" : "No runs yet"}</span>;
  return <span className="whitespace-nowrap"><span className="capitalize text-secondary-text">{p.lastRun.kind}</span> · <ResultMark result={p.lastRun.result} /></span>;
}

/** Only the exceptions float; healthy rows stay still. */
const Chip = ({ p, i }: { p: Portal; i: number }) => <StateBadge state={p.state} float={p.state !== "serving"} i={i} />;

/** What a healing portal keeps delivering, as its own floating chip beside the host name. */
function StillServing({ p, i }: { p: Portal; i: number }) {
  const note = stillServing(p);
  if (!note) return null;
  return <span className="chip chip-plain float text-xs font-medium text-healing" style={idx(i + 2)}><span aria-hidden className="live-dot" />{note}</span>;
}

/** The host name opens the portal's own website in a new tab; the row and its "Details" link open our page for it. */
export function HostLink({ url, className }: { url: string; className?: string }) {
  const href = externalHref(url);
  const host = hostname(url);
  if (!href) return <span className={className}>{host}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" title={`Open ${href} in a new tab`} className={cn("group/host inline-flex items-center gap-1.5 underline-offset-4 hover:underline break-all", className)}>
      {host}<ExternalLink aria-hidden className="size-[0.85em] shrink-0 text-muted-foreground transition-colors group-hover/host:text-primary" /><span className="sr-only"> (opens the portal's website in a new tab)</span>
    </a>
  );
}

/** A click on a row opens the portal page, unless it landed on a link or button of its own. */
const openRow = (id: string) => (e: MouseEvent<HTMLElement>) => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  if ((e.target as HTMLElement).closest("a,button") || window.getSelection()?.toString()) return;
  window.location.hash = portalHash(id);
};

export function PortalLedger({ portals, now, eurPerUsd, live }: { portals: Portal[]; now: number; eurPerUsd: number | null; live: boolean }) {
  const rows = sortPortals(portals);
  const flash = useFlashes(portals, live);
  const th = "px-3 pb-1 text-left text-[0.7rem] font-semibold tracking-[0.14em] whitespace-nowrap text-muted-foreground uppercase first:pl-5 last:pr-5 2xl:px-5";
  const td = "px-3 py-3.5 align-middle first:pl-5 last:pr-4 2xl:px-5";
  return (
    <>
      <div className="hidden min-[1360px]:block">
        <table className="ledger-table w-full text-[0.92rem]">
          <caption className="sr-only">Portals, sorted by state then hostname</caption>
          <thead>
            <tr>
              <th scope="col" className={th}>State</th>
              <th scope="col" className={th}>Portal / Reason</th>
              <th scope="col" className={cn(th, "text-right")}>Tenders</th>
              <th scope="col" className={th}>Last success</th>
              <th scope="col" className={th}>Last run</th>
              <th scope="col" className={th}>Last 30 reads</th>
              <th scope="col" className={cn(th, "text-right")}>Model cost</th>
              <th scope="col" className={th}><span className="sr-only">Details</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <tr key={`${p.id}-${flash[p.id] ?? 0}`} onClick={openRow(p.id)} className={cn("group cursor-pointer", live && flash[p.id] && `flash-row flash-${p.state}`)}>
                <td className={cn(td, "w-px whitespace-nowrap")}><Chip p={p} i={i} /></td>
                <td className={cn(td, "min-w-[17rem]")}>
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <HostLink url={p.url} className="text-[1.05rem] font-semibold tracking-tight text-foreground" />
                    <StillServing p={p} i={i} />
                  </span>
                  <p className="mt-0.5 max-w-[60rem] leading-relaxed text-secondary-text">{p.reason}</p>
                </td>
                <td className={cn(td, "text-right")}>
                  <div className="flex items-center justify-end gap-3"><DeliverySparkline values={p.deliveryTrend} /><span className="min-w-[1.5ch] text-[1.35rem] leading-none font-semibold tracking-tight">{p.tenderCount}</span></div>
                </td>
                <td className={cn(td, "whitespace-nowrap")}><LastSuccess p={p} now={now} /></td>
                <td className={td}><LastRun p={p} /></td>
                <td className={td}><ReadHistory30 reads={p.recentReads} /></td>
                <td className={cn(td, "text-right")}><CostLabel cost={portalCost(p)} eurPerUsd={eurPerUsd} stacked /></td>
                <td className={cn(td, "w-px")}>
                  <a href={portalHash(p.id)} aria-label={`Details of ${hostname(p.url)}`} title="Open the portal page" className="pill-ghost !gap-1 !py-1.5 !pr-2 !pl-3 text-xs whitespace-nowrap group-hover:border-[var(--border-strong)]">
                    Details <ChevronRight aria-hidden className="size-3.5 transition-transform duration-500 ease-spring group-hover:translate-x-0.5" />
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="grid gap-3 md:grid-cols-2 min-[1360px]:hidden" aria-label="Portals">
        {rows.map((p, i) => (
          <li key={`${p.id}-${flash[p.id] ?? 0}`} className={cn("card p-4 sm:p-5", live && flash[p.id] && `flash-row flash-${p.state}`)}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <HostLink url={p.url} className="text-[1.05rem] font-semibold tracking-tight" />
              <Chip p={p} i={i} />
            </div>
            {stillServing(p) && <p className="mt-2"><StillServing p={p} i={i} /></p>}
            <p className="mt-2 text-sm leading-relaxed text-secondary-text">{p.reason}</p>
            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Tenders</dt><dd className="font-semibold">{p.tenderCount}</dd>
              <dt className="text-muted-foreground">Last success</dt><dd><LastSuccess p={p} now={now} /></dd>
              <dt className="text-muted-foreground">Last run</dt><dd><LastRun p={p} /></dd>
              <dt className="col-span-2 text-muted-foreground">Last 30 reads</dt><dd className="col-span-2 overflow-hidden"><ReadHistory30 reads={p.recentReads} /></dd>
              <dt className="col-span-2 text-muted-foreground">Model cost</dt><dd className="col-span-2"><CostLabel cost={portalCost(p)} eurPerUsd={eurPerUsd} className="whitespace-normal" /></dd>
            </dl>
            <a href={portalHash(p.id)} aria-label={`Details of ${hostname(p.url)}`} className="link-arrow mt-4 text-sm">Portal details <ChevronRight aria-hidden className="size-4" /></a>
          </li>
        ))}
      </ul>
    </>
  );
}

export function LedgerSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading portals">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="card flex h-[4.6rem] items-center gap-6 rounded-2xl px-5">
          <Skel className="h-7 w-28 rounded-full" /><Skel className="h-5 flex-1" /><Skel className="hidden h-5 w-16 md:block" /><Skel className="hidden h-5 w-20 md:block" /><Skel className="hidden h-6 w-40 lg:block" /><Skel className="hidden h-5 w-24 lg:block" />
        </div>
      ))}
    </div>
  );
}

const CURL = `curl -X POST http://localhost:8080/portals -H 'Content-Type: application/json' -d '{"url":"https://your-public-portal.example"}'`;

export function EmptyFleet({ onAddPortal }: { onAddPortal: () => void }) {
  return (
    <div className="card p-8">
      <h2 className="display text-[1.9rem]">No portals yet</h2>
      <p className="mt-2 text-secondary-text">Add a public tender portal to start watching it.</p>
      <button type="button" onClick={onAddPortal} className="pill-cta mt-5"><Plus aria-hidden className="size-4" /> Add portal</button>
      <p className="mt-6 text-sm text-muted-foreground">Or through the API:</p>
      <pre tabIndex={0} aria-label="Command to attach a portal" className="mt-2 overflow-x-auto rounded-xl bg-inset p-4 font-mono text-sm select-all">{CURL}</pre>
    </div>
  );
}
