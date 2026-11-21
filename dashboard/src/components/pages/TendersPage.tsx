import { useId, useMemo, useState } from "react";
import { ArrowDownNarrowWide, ArrowUpNarrowWide, Download, ExternalLink, FileCheck2, FileClock, Search, X } from "lucide-react";
import { safeFileHref } from "@/data/api";
import { absTime, bytes, hostname, relTime } from "@/data/format";
import { portalHash } from "@/data/hooks";
import { Skel } from "@/components/ledger/primitives";
import { cn } from "@/lib/utils";
import type { Tender, TenderItem } from "@/types";
import { PageHero, PagesShell } from "./PagesShell";
import { dataNow, useFleet } from "./pagesData";
import { NO_FILTERS, WINDOW_LABEL, downloadText, exportName, externalHref, filterRows, flattenTenders, toCsv, toJson, type DeadlineWindow, type Filters, type StatusFilter, type TenderRow } from "./tenderRows";

const PAGE_SIZE = 100;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const missing = <span className="font-normal text-muted-foreground">Not stated</span>;

const STATUS_CLASS = { open: "text-serving bg-serving-tint", closed: "text-muted-foreground bg-inset", withdrawn: "text-failed bg-failed-tint" };
const STATUSES: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" }, { value: "open", label: "Open" }, { value: "closed", label: "Closed" }, { value: "withdrawn", label: "Withdrawn" },
];

function Docs({ docs, live }: { docs: Tender["documents"]; live: boolean }) {
  if (docs === null) return <span className="text-muted-foreground">Not collected</span>;
  if (!docs.length) return <span className="text-muted-foreground">None listed</span>;
  return (
    <ul className="flex flex-col gap-1.5">
      {docs.map((d, i) => {
        const href = live ? safeFileHref(d.path) : null;
        return (
          <li key={`${d.fileName}-${i}`} className="flex items-start gap-2 text-sm">
            {d.path ? <FileCheck2 aria-hidden className="mt-0.5 size-4 shrink-0 text-serving" /> : <FileClock aria-hidden className="mt-0.5 size-4 shrink-0 text-healing" />}
            <span className="min-w-0">
              {href ? <a href={href} className="break-words text-primary underline-offset-4 hover:underline">{d.fileName}</a> : <span className="break-words">{d.fileName}</span>}
              <span className="block text-xs text-muted-foreground">{bytes(d.sizeBytes)} · {d.path ? "downloaded" : "file pending"}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** The list rows carry only the number of files; the files are on the portal's page, one tender at a time. */
function Count({ n }: { n: number | null }) {
  if (n === null) return <span className="text-muted-foreground">Not collected</span>;
  if (n === 0) return <span className="text-muted-foreground">None listed</span>;
  return <span className="text-secondary-text">{n} {n === 1 ? "file" : "files"}</span>;
}

function Row({ row, now, live }: { row: TenderRow; now: number; live: boolean }) {
  const t: TenderItem = row.tender;
  const page = externalHref(t.url);
  const host = hostname(row.portalUrl);
  return (
    <tr role="row">
      <td role="cell" data-label="Tender">
        <p className="text-[1.02rem] leading-snug font-semibold tracking-tight">
          {page
            ? <a href={page} target="_blank" rel="noopener noreferrer" className="underline-offset-4 hover:underline">{t.title ?? "Untitled tender"}<ExternalLink aria-hidden className="mb-0.5 ml-1.5 inline size-[0.85em] text-muted-foreground" /><span className="sr-only"> (tender page, opens in a new tab)</span></a>
            : t.title ?? missing}
        </p>
        <p className="mt-0.5 text-xs break-all text-muted-foreground">{[t.referenceNumber, t.id].filter(Boolean).join(" · ")}{!page && " · no tender page stated"}</p>
      </td>
      <td role="cell" data-label="Buyer" className="text-secondary-text">{t.buyerName ?? missing}</td>
      <td role="cell" data-label="Portal"><a href={portalHash(row.portalId)} className="break-all text-primary underline-offset-4 hover:underline">{host}</a></td>
      <td role="cell" data-label="Deadline" className="lg:whitespace-nowrap">
        {t.submissionDeadline === null ? missing : <div>
          <time dateTime={t.submissionDeadline}>{absTime(t.submissionDeadline, row.timeZone)}</time>
          <span className="block text-xs text-muted-foreground">{relTime(t.submissionDeadline, now)}</span>
        </div>}
      </td>
      <td role="cell" data-label="Status"><span className={cn("inline-block rounded-full px-2.5 py-0.5 text-sm font-medium capitalize", STATUS_CLASS[t.status])}>{t.status}</span></td>
      <td role="cell" data-label="Documents">{t.documents !== undefined ? <Docs docs={t.documents} live={live} /> : <Count n={t.documentCount} />}</td>
    </tr>
  );
}

export function TendersPage() {
  const fleet = useFleet(false, true, 30_000);
  const searchId = useId(), windowId = useId();
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const data = fleet.data;
  const live = data?.source === "live";
  const now = useMemo(() => dataNow(data, Date.now()), [data]);
  const portals = useMemo(() => data?.dashboard.portals ?? [], [data]);
  const all = useMemo(() => (data ? flattenTenders(portals, data.tenders) : []), [data, portals]);
  const rows = useMemo(() => filterRows(all, filters, now), [all, filters, now]);
  const totalAll = data ? Object.values(data.tenderTotals).reduce((a, b) => a + b, 0) : 0;
  const unread = live && data ? portals.filter((p) => data.tenders[p.id] === null) : [];
  const withTenders = new Set(all.map((r) => r.portalId)).size;
  const filtered = filters.query !== "" || filters.status !== "all" || filters.window !== "any";
  const set = (patch: Partial<Filters>) => { setFilters((f) => ({ ...f, ...patch })); setLimit(PAGE_SIZE); };
  const th = "px-4 pb-1 text-left text-[0.7rem] font-semibold tracking-[0.14em] text-muted-foreground uppercase 2xl:px-5";
  const SortIcon = filters.sort === "asc" ? ArrowUpNarrowWide : ArrowDownNarrowWide;
  const field = "h-10 rounded-full border border-[var(--glass-border)] bg-inset text-sm text-foreground";

  return (
    <PagesShell page="tenders" fleet={fleet}>
      <PageHero label="Tender explorer"
        title={!data ? "Reading the tenders…" : <><span className="highlight font-normal">{plural(all.length, "tender")}</span> from {plural(withTenders, "portal")}, in one list.</>}>
        The first 50 tenders of each portal, one paged request per portal. Search, filter, then take the rows with you as CSV or JSON; the export is built in the browser from the rows on screen.
      </PageHero>

      <section aria-label="Filters and export" className="card mt-10 flex flex-wrap items-center gap-x-3 gap-y-3 p-3 sm:p-4">
        <div className="relative min-w-56 flex-1">
          <label htmlFor={searchId} className="sr-only">Search by title or buyer</label>
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <input id={searchId} type="search" value={filters.query} onChange={(e) => set({ query: e.target.value })} placeholder="Search title or buyer" autoComplete="off"
            className={cn(field, "w-full pr-4 pl-10 placeholder:text-muted-foreground")} />
        </div>
        <div role="group" aria-label="Status" className="flex items-center gap-1 rounded-full border border-[var(--glass-border)] bg-inset p-1">
          {STATUSES.map((s) => (
            <button key={s.value} type="button" aria-pressed={filters.status === s.value} onClick={() => set({ status: s.value })}
              className={cn("cursor-pointer rounded-full px-3 py-1.5 text-sm font-medium transition-colors", filters.status === s.value ? "bg-[var(--cta-bg)] text-[var(--cta-fg)]" : "text-secondary-text hover:text-foreground")}>
              {s.label}
            </button>
          ))}
        </div>
        <div>
          <label htmlFor={windowId} className="sr-only">Deadline window</label>
          <select id={windowId} value={filters.window} onChange={(e) => set({ window: e.target.value as DeadlineWindow })} className={cn(field, "cursor-pointer px-4")}>
            {(Object.keys(WINDOW_LABEL) as DeadlineWindow[]).map((w) => <option key={w} value={w}>{WINDOW_LABEL[w]}</option>)}
          </select>
        </div>
        <button type="button" onClick={() => set({ sort: filters.sort === "asc" ? "desc" : "asc" })} className="pill-ghost"
          aria-label={`Sorted by deadline, ${filters.sort === "asc" ? "soonest first" : "latest first"}. Reverse the order`}>
          <SortIcon aria-hidden className="size-4" /> Deadline: {filters.sort === "asc" ? "soonest first" : "latest first"}
        </button>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button type="button" className="pill-ghost disabled:cursor-not-allowed disabled:opacity-45" disabled={rows.length === 0}
            onClick={() => downloadText(`${exportName(Date.now())}.csv`, "text/csv;charset=utf-8", `\ufeff${toCsv(rows)}`)}>
            <Download aria-hidden className="size-4" /> Download CSV
          </button>
          <button type="button" className="pill-ghost disabled:cursor-not-allowed disabled:opacity-45" disabled={rows.length === 0}
            onClick={() => downloadText(`${exportName(Date.now())}.json`, "application/json", toJson(rows))}>
            <Download aria-hidden className="size-4" /> Download JSON
          </button>
        </div>
      </section>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-1 text-sm text-muted-foreground">
        <p role="status" aria-live="polite">
          {!data ? "Loading…" : filtered ? `${rows.length} of ${plural(all.length, "tender")} match. The export holds these ${rows.length}.` : `${plural(all.length, "tender")}. The export holds all of them.`}
        </p>
        {filtered && <button type="button" onClick={() => set({ query: "", status: "all", window: "any" })} className="link-arrow text-sm"><X aria-hidden className="size-4" /> Clear filters</button>}
      </div>
      {data && totalAll > all.length && (
        <p className="mt-2 px-1 text-sm text-muted-foreground">
          {all.length >= 500 ? `Showing the first ${all.length} of ${totalAll.toLocaleString("en-US")} tenders. ` : ""}First 50 per portal. Open a portal for more.
        </p>
      )}
      {unread.length > 0 && (
        <p className="mt-3 rounded-2xl bg-failed-tint px-4 py-3 text-sm text-failed">
          The tenders of {plural(unread.length, "portal")} could not be read and are missing from this list: {unread.map((p) => hostname(p.url)).join(", ")}. The next refresh tries again.
        </p>
      )}

      <div className="mt-3">
        {!data ? (
          <div className="flex flex-col gap-2" aria-busy="true">{[0, 1, 2, 3].map((i) => <Skel key={i} className="h-20 rounded-2xl" />)}</div>
        ) : all.length === 0 ? (
          <p className="card p-8 text-secondary-text">{portals.length === 0 ? "No portal is attached yet, so there are no tenders." : "No tenders delivered yet. They appear here after a portal's first passing read."}</p>
        ) : rows.length === 0 ? (
          <p className="card p-8 text-secondary-text">No tender matches these filters.</p>
        ) : (
          <table role="table" className="tx-table text-[0.95rem]">
            <caption className="sr-only">Tenders from all portals, sorted by deadline, {filters.sort === "asc" ? "soonest first" : "latest first"}</caption>
            <thead role="rowgroup"><tr role="row">
              {["Tender", "Buyer", "Portal", "Deadline (portal time)", "Status", "Documents"].map((h) => <th key={h} role="columnheader" scope="col" className={th}>{h}</th>)}
            </tr></thead>
            <tbody role="rowgroup">
              {rows.slice(0, limit).map((r) => <Row key={`${r.portalId}:${r.tender.id}`} row={r} now={now} live={!!live} />)}
            </tbody>
          </table>
        )}
        {rows.length > limit && (
          <p className="mt-4 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
            Showing {limit} of {rows.length}.
            <button type="button" className="pill-ghost" onClick={() => setLimit((n) => n + PAGE_SIZE)}>Show {Math.min(PAGE_SIZE, rows.length - limit)} more</button>
          </p>
        )}
        {data && !live && all.length > 0 && <p className="mt-5 text-sm text-muted-foreground">Demo data: the document files are not on this server, so their names show without a link.</p>}
      </div>
    </PagesShell>
  );
}
