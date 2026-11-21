import dashboardJson from "@/demo/dashboard.json";
import timelinesJson from "@/demo/timelines.json";
import tendersJson from "@/demo/tenders.json";
import { dashboardSchema, tendersSchema, timelineSchema } from "./schema";
import type { Dashboard, Tender, TenderItem, TenderPage, Timeline } from "@/types";

/** The bundled snapshot. Validated once with the same schemas as live data. */
export const demoDashboard: Dashboard = dashboardSchema.parse(dashboardJson);

const timelines = timelinesJson as Record<string, unknown>;
const tenders = tendersJson as Record<string, unknown>;

export function demoTimeline(id: string): Timeline | null {
  if (!Object.prototype.hasOwnProperty.call(timelines, id)) return null;
  const r = timelineSchema.safeParse(timelines[id]);
  return r.success ? r.data : null;
}

export function demoTenders(id: string): Tender[] | null {
  if (!Object.prototype.hasOwnProperty.call(tenders, id)) return null;
  const r = tendersSchema.safeParse(tenders[id]);
  return r.success ? r.data : null;
}

/** A list row from a full tender: the files stay on it (demo has no server), plus their count. */
export const toTenderItem = (t: Tender): TenderItem => ({ ...t, documentCount: t.documents === null ? null : t.documents.length });

/** The same shape as GET /api/portals/{id}/tenders?limit&offset, sliced in the browser from the bundled tenders. */
export function demoTenderPage(id: string, limit: number, offset: number): TenderPage | null {
  const all = demoTenders(id);
  if (!all) return null;
  const end = Math.min(offset + limit, all.length);
  return { total: all.length, offset, limit, next: end < all.length ? end : null, items: all.slice(offset, end).map(toTenderItem) };
}
