// Tender explorer: pure helpers for the rows, the filters and the two exports.
import type { Portal, Tender } from "@/types";

export interface TenderRow { tender: Tender; portalId: string; portalUrl: string; timeZone: string | null }

/** Every tender of every portal whose tenders were read; portal order is the dashboard's. */
export function flattenTenders(portals: Portal[], tenders: Record<string, Tender[] | null>): TenderRow[] {
  return portals.flatMap((p) => (tenders[p.id] ?? []).map((tender) => ({ tender, portalId: p.id, portalUrl: p.url, timeZone: p.timezone })));
}

export type StatusFilter = "all" | Tender["status"];
export type DeadlineWindow = "any" | "7d" | "30d" | "past" | "none";
export type DeadlineSort = "asc" | "desc";
export interface Filters { query: string; status: StatusFilter; window: DeadlineWindow; sort: DeadlineSort }

export const NO_FILTERS: Filters = { query: "", status: "all", window: "any", sort: "asc" };
export const WINDOW_LABEL: Record<DeadlineWindow, string> = {
  any: "Any deadline", "7d": "Due in the next 7 days", "30d": "Due in the next 30 days", past: "Deadline passed", none: "No deadline stated",
};

const DAY = 86_400_000;
/** Case and accent insensitive, so "luftung" finds "Lüftung". */
const fold = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

function inWindow(deadline: string | null, window: DeadlineWindow, now: number): boolean {
  if (window === "any") return true;
  if (deadline === null) return window === "none";
  const t = Date.parse(deadline);
  if (window === "none") return false;
  if (window === "past") return t < now;
  return t >= now && t <= now + (window === "7d" ? 7 : 30) * DAY;
}

/**
 * Search matches every typed word against the title and the buyer. Sorting is by deadline; tenders
 * without one always come last, and equal deadlines keep a stable order by title.
 */
export function filterRows(rows: TenderRow[], f: Filters, now: number): TenderRow[] {
  const words = fold(f.query).split(/\s+/).filter(Boolean);
  const kept = rows.filter(({ tender: t }) => {
    if (f.status !== "all" && t.status !== f.status) return false;
    if (!inWindow(t.submissionDeadline, f.window, now)) return false;
    if (!words.length) return true;
    const hay = fold(`${t.title ?? ""} ${t.buyerName ?? ""}`);
    return words.every((w) => hay.includes(w));
  });
  const dir = f.sort === "asc" ? 1 : -1;
  return kept.sort((a, b) => {
    const ta = a.tender.submissionDeadline, tb = b.tender.submissionDeadline;
    if (ta === null || tb === null) return ta === tb ? byTitle(a, b) : ta === null ? 1 : -1;
    return (Date.parse(ta) - Date.parse(tb)) * dir || byTitle(a, b);
  });
}

const byTitle = (a: TenderRow, b: TenderRow) => (a.tender.title ?? "").localeCompare(b.tender.title ?? "") || a.tender.id.localeCompare(b.tender.id);

/** An address the browser may open in a new tab: http or https only, never javascript: or data:. */
export function externalHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

/**
 * One CSV cell (RFC 4180): a cell with a comma, a quote or a line break is wrapped in quotes, with
 * inner quotes doubled. A text cell that starts with = + - @, tab or CR gets a leading apostrophe,
 * so a spreadsheet shows it as text instead of running it as a formula. Numbers are never altered.
 */
export function csvCell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export const CSV_COLUMNS = [
  "portalId", "portalUrl", "tenderId", "referenceNumber", "title", "buyerName", "status", "procedureType",
  "publicationDate", "submissionDeadline", "lastChangedAt", "tenderUrl", "documentCount", "documentBytes", "documentNames",
] as const;

/** Header plus one line per row, CRLF line ends. Document sizes are summed only over the sizes that are known. */
export function toCsv(rows: TenderRow[]): string {
  const lines = rows.map(({ tender: t, portalId, portalUrl }) => {
    const docs = t.documents;
    const sizes = (docs ?? []).map((d) => d.sizeBytes).filter((n): n is number => n !== null);
    return [
      portalId, portalUrl, t.id, t.referenceNumber, t.title, t.buyerName, t.status, t.procedureType,
      t.publicationDate, t.submissionDeadline, t.lastChangedAt, t.url,
      docs === null ? null : docs.length, sizes.length ? sizes.reduce((s, n) => s + n, 0) : null,
      docs === null ? null : docs.map((d) => d.fileName).join("; "),
    ].map(csvCell).join(",");
  });
  return [CSV_COLUMNS.join(","), ...lines].join("\r\n") + "\r\n";
}

/** The filtered rows as the API sent them, each with the portal it came from. */
export function toJson(rows: TenderRow[]): string {
  return JSON.stringify(rows.map(({ tender, portalId, portalUrl }) => ({ portal: { id: portalId, url: portalUrl }, ...tender })), null, 2);
}

/** Saves text as a file from memory. No request leaves the page. */
export function downloadText(fileName: string, mime: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** watchtower-tenders-20261120-2058 */
export function exportName(now: number): string {
  const d = new Date(now);
  const two = (n: number) => String(n).padStart(2, "0");
  return `watchtower-tenders-${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}-${two(d.getHours())}${two(d.getMinutes())}`;
}
