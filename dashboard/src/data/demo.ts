import dashboardJson from "@/demo/dashboard.json";
import timelinesJson from "@/demo/timelines.json";
import tendersJson from "@/demo/tenders.json";
import { dashboardSchema, tendersSchema, timelineSchema } from "./schema";
import type { Dashboard, Tender, Timeline } from "@/types";

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
