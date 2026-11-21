import { ExternalLink, FileCheck2, FileClock } from "lucide-react";
import { externalHref, safeFileHref } from "@/data/api";
import { absTime, bytes, localTime } from "@/data/format";
import type { OpenTender } from "@/data/tenderPager";
import type { Tender, TenderItem } from "@/types";

function Docs({ docs, live }: { docs: Tender["documents"]; live: boolean }) {
  if (docs === null) return <span className="text-muted-foreground">Not collected</span>;
  if (!docs.length) return <span className="text-muted-foreground">None listed</span>;
  return (
    <ul className="flex flex-col gap-1">
      {docs.map((d, i) => {
        const href = live ? safeFileHref(d.path) : null;
        const meta = `${bytes(d.sizeBytes)}${d.sha256 ? ` · sha256 ${d.sha256.slice(0, 10)}…` : ""}`;
        return (
          <li key={`${d.fileName}-${i}`} className="flex items-start gap-2 text-sm" title={meta}>
            {d.path ? <FileCheck2 aria-hidden className="mt-0.5 size-4 shrink-0 text-serving" /> : <FileClock aria-hidden className="mt-0.5 size-4 shrink-0 text-healing" />}
            <span className="min-w-0">
              {href ? <a href={href} className="break-words text-primary underline-offset-4 hover:underline">{d.fileName}</a> : <span className="break-words">{d.fileName}</span>}
              <span className="block text-xs text-muted-foreground">{d.path ? "Downloaded" : "File pending"} · {bytes(d.sizeBytes)}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

const missing = <span className="font-normal text-muted-foreground">Not stated</span>;

function Deadline({ at, timeZone }: { at: string | null; timeZone: string | null }) {
  if (at === null) return missing;
  return <><time dateTime={at}>{absTime(at, timeZone)}</time><p className="text-xs text-muted-foreground">Local: {localTime(at)}</p></>;
}

/** The title opens the tender's own page on the portal, in a new tab, when the portal gave an http(s) address. */
function Title({ t }: { t: TenderItem }) {
  const href = externalHref(t.url);
  if (t.title === null) return missing;
  if (!href) return <>{t.title}</>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" title={`Open ${href} in a new tab`} className="group/t underline-offset-4 hover:underline">
      {t.title}<ExternalLink aria-hidden className="ml-1.5 inline size-[0.85em] -translate-y-px text-muted-foreground group-hover/t:text-primary" /><span className="sr-only"> (opens the tender's page in a new tab)</span>
    </a>
  );
}

/** Reference number and page address, whichever of the two the portal shows. */
const subline = (t: TenderItem) => [t.referenceNumber, t.url].filter(Boolean).join(" · ");

const STATUS = { open: "text-serving bg-serving-tint", closed: "text-muted-foreground bg-inset", withdrawn: "text-failed bg-failed-tint" };
const Status = ({ status }: { status: Tender["status"] }) => <span className={`inline-block rounded-full px-2.5 py-0.5 text-sm font-medium capitalize ${STATUS[status]}`}>{status}</span>;

/** What the closed row says about the files; the files themselves come when the row is opened. */
function Count({ n }: { n: number | null }) {
  if (n === null) return <span className="text-muted-foreground">Not collected</span>;
  if (n === 0) return <span className="text-muted-foreground">None listed</span>;
  return <span className="text-secondary-text">{n} {n === 1 ? "file" : "files"}</span>;
}

function Open({ o, live }: { o: OpenTender | undefined; live: boolean }) {
  if (!o || o.status === "loading") return <span className="text-sm text-muted-foreground" aria-busy="true">Loading files…</span>;
  if (o.status === "error") return <span className="text-sm text-failed">The files could not be loaded. Close the row and open it again.</span>;
  return <Docs docs={o.tender.documents} live={live} />;
}

interface TableProps {
  tenders: TenderItem[];
  timeZone: string | null;
  live: boolean;
  /** Ids of the opened rows and their fetched tenders. A closed row shows only the file count. */
  opened?: ReadonlySet<string>;
  detail?: Record<string, OpenTender>;
  onToggle?: (id: string) => void;
}

export function TenderTable({ tenders, timeZone, live, opened, detail, onToggle }: TableProps) {
  if (!tenders.length) return <p className="card p-6 text-secondary-text">No tenders delivered yet.</p>;
  const th = "sticky top-0 z-10 bg-background px-4 pb-1 pt-1 text-left text-[0.7rem] font-semibold tracking-[0.14em] text-muted-foreground uppercase 2xl:px-5";
  const td = "px-4 py-3.5 2xl:px-5";
  const isOpen = (id: string) => !!opened?.has(id);
  const toggle = (id: string) => onToggle?.(id);
  /** A click on the row opens it; links inside it keep their own click. */
  const onRow = (id: string) => (e: React.MouseEvent) => { if (!(e.target as HTMLElement).closest("a")) toggle(id); };
  const onKey = (id: string) => (e: React.KeyboardEvent) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggle(id); } };
  return (
    <>
      <ul className="flex flex-col gap-3 lg:hidden" aria-label="Delivered tenders">
        {tenders.map((t) => <li key={t.id} className="card cursor-pointer p-4 sm:p-5" tabIndex={0} aria-expanded={isOpen(t.id)} onClick={onRow(t.id)} onKeyDown={onKey(t.id)}>
          <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="text-[1.05rem] font-semibold"><Title t={t} /></h3><Status status={t.status} /></div>
          <p className="mt-1 break-all text-xs text-muted-foreground">{subline(t)}</p>
          <dl className="mt-3 grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Buyer</dt><dd>{t.buyerName ?? missing}</dd>
            <dt className="text-muted-foreground">Deadline</dt><dd><Deadline at={t.submissionDeadline} timeZone={timeZone} /></dd>
            <dt className="text-muted-foreground">Documents</dt><dd>{isOpen(t.id) ? <Open o={detail?.[t.id]} live={live} /> : <Count n={t.documentCount} />}</dd>
          </dl>
        </li>)}
      </ul>
      <div className="hidden lg:block">
        <table className="ledger-table w-full text-[0.95rem]">
          <caption className="sr-only">Delivered tenders. Select a row to load its files.</caption>
          <thead><tr>
            <th scope="col" className={th}>Title</th><th scope="col" className={th}>Buyer</th>
            <th scope="col" className={th}>Deadline (portal time)</th><th scope="col" className={th}>Status</th><th scope="col" className={th}>Documents</th>
          </tr></thead>
          <tbody>
            {tenders.map((t) => (
              <tr key={t.id} className="cursor-pointer align-top" tabIndex={0} aria-expanded={isOpen(t.id)} onClick={onRow(t.id)} onKeyDown={onKey(t.id)}>
                <td className={td}><p className="text-[1.05rem] font-semibold tracking-tight"><Title t={t} /></p><p className="mt-0.5 text-xs break-all text-muted-foreground">{subline(t)}</p></td>
                <td className={`${td} text-secondary-text`}>{t.buyerName ?? missing}</td>
                <td className={`${td} whitespace-nowrap`}><Deadline at={t.submissionDeadline} timeZone={timeZone} /></td>
                <td className={td}><Status status={t.status} /></td>
                <td className={td}>{isOpen(t.id) ? <Open o={detail?.[t.id]} live={live} /> : <Count n={t.documentCount} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
