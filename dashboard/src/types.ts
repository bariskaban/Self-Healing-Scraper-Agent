import type { z } from "zod";
import type * as S from "./data/schema";

export type Usage = z.infer<typeof S.usageSchema>;
export type Settings = z.infer<typeof S.settingsSchema>;
export type PortalState = z.infer<typeof S.portalStateSchema>;
export type Portal = z.infer<typeof S.portalSchema>;
export type Dashboard = z.infer<typeof S.dashboardSchema>;
export type Check = z.infer<typeof S.checkSchema>;
export type Step = z.infer<typeof S.stepSchema>;
export type Run = z.infer<typeof S.runSchema>;
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
  dashboard: Dashboard | null;
  detail: DetailView | null;
  /** ms epoch of last successful live commit */
  liveAt: number | null;
  everOnline: boolean;
  /** increments on each successful live poll, drives the single pulse */
  livePulse: number;
  /** the last poll failed: the data shown (if any) is the last live snapshot, not a current one */
  offline?: boolean;
}
