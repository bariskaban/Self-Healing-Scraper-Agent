import { FileCheck2, FileClock } from "lucide-react";
import { safeFileHref } from "@/data/api";
import { absTime, bytes, localTime } from "@/data/format";
import type { Tender } from "@/types";

function Docs({ docs, live }: { docs: Tender["documents"]; live: boolean }) {
  if (docs === null) return <span className="text-muted-foreground">Not collected</span>;
  if (!docs.length) return <span className="text-muted-foreground">None listed</span>;
  return (
    <ul className="flex flex-col gap-0.5">
      {docs.map((d, i) => {
        const href = live ? safeFileHref(d.path) : null;
        const meta = `${bytes(d.sizeBytes)}${d.sha256 ? ` · sha256 ${d.sha256.slice(0, 10)}…` : ""}`;
        return (
          <li key={`${d.fileName}-${i}`} className="flex items-start gap-1.5 text-label" title={meta}>
            {d.path ? <FileCheck2 aria-hidden className="mt-0.5 size-4 shrink-0 text-serving" /> : <FileClock aria-hidden className="mt-0.5 size-4 shrink-0 text-healing" />}
            <span className="min-w-0">
              {href ? <a href={href} className="break-words text-primary underline-offset-2 hover:underline">{d.fileName}</a> : <span className="break-words">{d.fileName}</span>}
              <span className="block text-micro text-muted-foreground">{d.path ? "Downloaded" : "File pending"} · {bytes(d.sizeBytes)}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

const STATUS = { open: "text-serving", closed: "text-muted-foreground", withdrawn: "text-failed" };

export function TenderTable({ tenders, timeZone, live }: { tenders: Tender[]; timeZone: string | null; live: boolean }) {
  if (!tenders.length) return <p className="text-secondary-text">No tenders delivered yet.</p>;
  const th = "px-3 py-2 text-left text-label font-medium text-secondary-text";
  return (
    <>
      <ul className="divide-y divide-divider border-y border-divider md:hidden" aria-label="Delivered tenders">
        {tenders.map((t) => <li key={t.id} className="py-4">
          <h3 className="text-body font-semibold">{t.title}</h3>
          <p className="mt-1 break-all text-micro text-muted-foreground">{t.referenceNumber ? `${t.referenceNumber} · ` : ""}{t.url}</p>
          <dl className="mt-3 grid grid-cols-[5rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-label">
            <dt className="text-muted-foreground">Buyer</dt><dd>{t.buyerName}</dd>
            <dt className="text-muted-foreground">Deadline</dt><dd><time dateTime={t.submissionDeadline}>{absTime(t.submissionDeadline, timeZone)}</time><p className="text-micro text-muted-foreground">Local: {localTime(t.submissionDeadline)}</p></dd>
            <dt className="text-muted-foreground">Status</dt><dd className={`font-medium capitalize ${STATUS[t.status]}`}>{t.status}</dd>
            <dt className="text-muted-foreground">Documents</dt><dd><Docs docs={t.documents} live={live} /></dd>
          </dl>
        </li>)}
      </ul>
    <div className="hidden overflow-x-auto rounded-lg border border-border bg-surface md:block">
      <table className="w-full min-w-[48rem] text-body">
        <caption className="sr-only">Delivered tenders</caption>
        <thead className="border-b border-divider bg-inset"><tr>
          <th scope="col" className={th}>Title</th><th scope="col" className={th}>Buyer</th>
          <th scope="col" className={th}>Deadline (portal time)</th><th scope="col" className={th}>Status</th><th scope="col" className={th}>Documents</th>
        </tr></thead>
        <tbody className="divide-y divide-divider">
          {tenders.map((t) => (
            <tr key={t.id} className="align-top">
              <td className="px-3 py-2"><p className="font-medium">{t.title}</p><p className="text-micro text-muted-foreground break-all">{t.referenceNumber ? `${t.referenceNumber} · ` : ""}{t.url}</p></td>
              <td className="px-3 py-2 text-label">{t.buyerName}</td>
              <td className="px-3 py-2 text-label whitespace-nowrap"><time dateTime={t.submissionDeadline}>{absTime(t.submissionDeadline, timeZone)}</time><p className="text-micro text-muted-foreground">Local: {localTime(t.submissionDeadline)}</p></td>
              <td className={`px-3 py-2 text-label font-medium capitalize ${STATUS[t.status]}`}>{t.status}</td>
              <td className="px-3 py-2"><Docs docs={t.documents} live={live} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}
