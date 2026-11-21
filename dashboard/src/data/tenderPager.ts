import { ApiError, contractPath, getJson, tenderPagePath, tenderPath, type FetchLike } from "./api";
import { demoTenderPage, demoTenders, toTenderItem } from "./demo";
import { singleTenderSchema, tendersSchema, tenderPageSchema } from "./schema";
import { TENDER_CAP, TENDER_PAGE_SIZE } from "./tenderPaging";
import type { Tender, TenderItem } from "@/types";

/** api: paged dashboard route. demo: sliced from the bundle. basic: the contract route, read once, cut. */
export type PagerMode = "api" | "demo" | "basic";
export type OpenTender = { status: "loading" } | { status: "ok"; tender: Tender } | { status: "error" };

export interface PagerState {
  items: TenderItem[];
  /** All delivered tenders on the server; null before the first page. */
  total: number | null;
  /** Offset of the next page; null when there is none (or the cap was reached). */
  next: number | null;
  started: boolean;
  loading: boolean;
  /** The last page request failed; the next scroll asks again. */
  error: boolean;
  /** 500 rows are in and more exist: no more requests. */
  capped: boolean;
  /** Basic live only: the whole route was read once and cut in the browser. */
  cut: boolean;
  /** Per tender id, the full tender fetched when its row was opened. */
  open: Record<string, OpenTender>;
}

const PAGE_TIMEOUT_MS = 15_000;

/**
 * Holds the loaded pages of one portal's tender list. One request at a time, never more than
 * TENDER_CAP rows, no request when `next` is null. The poll never touches it: it lives as long as
 * the portal page is open.
 */
export class TenderPager {
  state: PagerState = { items: [], total: null, next: 0, started: false, loading: false, error: false, capped: false, cut: false, open: {} };
  private listeners = new Set<() => void>();
  private ac: AbortController | null = null;
  private seq = 0;

  constructor(private fetchImpl: FetchLike, private portalId: string, private mode: PagerMode) {}

  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  getSnapshot = () => this.state;
  private set(patch: Partial<PagerState>) { this.state = { ...this.state, ...patch }; this.listeners.forEach((l) => l()); }

  /** Stops what is in flight (the page closed or the portal changed). */
  dispose() {
    this.seq++;
    this.ac?.abort();
    this.ac = null;
    if (this.state.loading) this.state = { ...this.state, loading: false };
  }

  /** Loads the next page when allowed. Safe to call from every scroll event. */
  async loadMore(): Promise<void> {
    const s = this.state;
    if (s.loading || s.next === null || s.capped || s.items.length >= TENDER_CAP) return;
    const seq = ++this.seq;
    const ac = (this.ac = new AbortController());
    this.set({ loading: true, error: false, started: true });
    try {
      if (this.mode === "demo") {
        const page = demoTenderPage(this.portalId, TENDER_PAGE_SIZE, s.next);
        this.apply(page ? page.items : [], page ? page.total : 0, page ? page.next : null);
      } else if (this.mode === "basic") {
        const all = await getJson(this.fetchImpl, contractPath(this.portalId, "tenders"), tendersSchema, ac.signal, PAGE_TIMEOUT_MS);
        if (seq !== this.seq) return;
        this.apply(all.slice(0, TENDER_CAP).map(toTenderItem), all.length, null, all.length > TENDER_CAP);
      } else {
        const page = await getJson(this.fetchImpl, tenderPagePath(this.portalId, TENDER_PAGE_SIZE, s.next), tenderPageSchema, ac.signal, PAGE_TIMEOUT_MS);
        if (seq !== this.seq) return;
        this.apply(page.items, page.total, page.next);
      }
    } catch (e) {
      if (seq !== this.seq || (e instanceof ApiError && e.kind === "aborted")) return;
      this.set({ loading: false, error: true });
    }
  }

  private apply(page: TenderItem[], total: number, next: number | null, cut = false) {
    const items = [...this.state.items, ...page].slice(0, TENDER_CAP);
    const done = next === null || items.length >= TENDER_CAP;
    this.set({ items, total, next: done ? null : next, loading: false, error: false, capped: items.length >= TENDER_CAP && total > TENDER_CAP, cut });
  }

  /** A row was opened: fetch that one tender with its files. Demo and basic rows already carry them. */
  async loadOne(tenderId: string): Promise<void> {
    const have = this.state.open[tenderId];
    if (have && have.status !== "error") return;
    const setOpen = (o: OpenTender) => this.set({ open: { ...this.state.open, [tenderId]: o } });
    if (this.mode !== "api") {
      const t = this.mode === "demo" ? demoTenders(this.portalId)?.find((x) => x.id === tenderId) : undefined;
      const row = this.state.items.find((x) => x.id === tenderId);
      const tender = t ?? (row ? { ...row, documents: row.documents ?? null } : undefined);
      setOpen(tender ? { status: "ok", tender } : { status: "error" });
      return;
    }
    setOpen({ status: "loading" });
    try {
      const tender = await getJson(this.fetchImpl, tenderPath(this.portalId, tenderId), singleTenderSchema, new AbortController().signal, PAGE_TIMEOUT_MS);
      setOpen({ status: "ok", tender });
    } catch {
      setOpen({ status: "error" });
    }
  }
}
