import type { z } from "zod";
import type * as S from "./data/schema";

export type Usage = z.infer<typeof S.usageSchema>;
export type Settings = z.infer<typeof S.settingsSchema>;
export type PortalState = z.infer<typeof S.portalStateSchema>;
type WirePortal = z.infer<typeof S.portalSchema>;
type WireDashboard = z.infer<typeof S.dashboardSchema>;
type WireRun = z.infer<typeof S.runSchema>;

/**
 * The row model. The /api routes fill every field. Rows built from the public contract routes
 * ("basic" live) carry null wherever the contract has no value; null is shown as "Not recorded",
 * never as a zero or an empty list.
 */
export type Portal = Omit<WirePortal, "recentReads" | "deliveryTrend" | "readsLastHour"> & {
  recentReads: WirePortal["recentReads"] | null;
  deliveryTrend: number[] | null;
  readsLastHour: number | null;
};
export type Dashboard = Omit<WireDashboard, "portals" | "eurPerUsd" | "settings"> & {
  portals: Portal[];
  eurPerUsd: number | null;
  settings: Settings | null;
};
export type Check = z.infer<typeof S.checkSchema>;
export type Step = z.infer<typeof S.stepSchema>;
/** A run. Contract-only runs know their kind, times and result; the rest is null. */
export type Run = Omit<WireRun, "trigger" | "summary" | "modelCalls"> & {
  trigger: WireRun["trigger"] | null;
  summary: string | null;
  modelCalls: number | null;
};
export type Timeline = Run[];
export type TenderDocument = z.infer<typeof S.documentSchema>;
export type Tender = z.infer<typeof S.tenderSchema>;

export type Route = { name: "overview" } | { name: "portal"; id: string };
export type Source = "live" | "demo";

export type DetailView =
  | { kind: "ok"; portal: Portal; timeline: Timeline; tenders: Tender[] }
  | { kind: "notFound" } // live dashboard says id does not exist
  | { kind: "notInDemo" }; // fallback snapshot lacks id

export interface LedgerState {
  route: Route;
  /** null until the first cycle for this route committed */
  source: Source | null;
  /** true when live data comes from the public contract routes only (no /api/dashboard) */
  basic: boolean;
  dashboard: Dashboard | null;
  detail: DetailView | null;
  /** basic live overview only: each portal's runs from GET /portals/{id}/runs */
  fleetRuns: Record<string, Run[]> | null;
  /** ms epoch of last successful live commit */
  liveAt: number | null;
  everOnline: boolean;
  /** increments on each successful live poll, drives the single pulse */
  livePulse: number;
  /** the last poll failed: the data shown (if any) is the last live snapshot, not a current one */
  offline?: boolean;
}
