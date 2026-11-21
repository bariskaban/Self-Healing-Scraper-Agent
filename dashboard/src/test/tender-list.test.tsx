import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { TenderList } from "@/components/ledger/TenderList";
import { LedgerController } from "@/data/controller";
import { demoDashboard, demoTenderPage, demoTenders } from "@/data/demo";
import { TenderPager } from "@/data/tenderPager";
import { TENDER_CAP, TENDER_PAGE_SIZE } from "@/data/tenderPaging";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const TOTAL = 4132;
const item = (i: number) => ({
  id: `t${i}`, url: null, title: `Tender ${i}`, buyerName: "Buyer", publicationDate: null, submissionDeadline: null,
  status: "open", lastChangedAt: "2026-11-20T10:00:00+01:00", documentCount: 60,
});
const pageOf = (offset: number, limit: number) => {
  const end = Math.min(offset + limit, TOTAL);
  return { total: TOTAL, offset, limit, next: end < TOTAL ? end : null, items: Array.from({ length: end - offset }, (_, k) => item(offset + k)) };
};
const query = (u: string) => { const q = new URL(u, "http://x").searchParams; return { limit: Number(q.get("limit")), offset: Number(q.get("offset")) }; };

/** A server for the paged route. `hold` keeps answers pending until released. */
function server(opts: { fail?: () => boolean; hold?: boolean } = {}) {
  const seen: string[] = [];
  const pending: (() => void)[] = [];
  const fetchImpl = async (u: string) => {
    seen.push(u);
    if (opts.hold) await new Promise<void>((r) => pending.push(r));
    if (opts.fail?.()) return new Response("x", { status: 500 });
    const { limit, offset } = query(u);
    return json(pageOf(offset, limit));
  };
  return { fetchImpl, seen, release: () => { pending.splice(0).forEach((r) => r()); } };
}

describe("TenderPager", () => {
  it("the first request has limit=50 and offset=0", async () => {
    const s = server();
    const p = new TenderPager(s.fetchImpl, "tn", "api");
    await p.loadMore();
    expect(s.seen).toEqual(["/api/portals/tn/tenders?limit=50&offset=0"]);
    expect(p.state.items).toHaveLength(50);
    expect(p.state.total).toBe(TOTAL);
  });

  it("two quick loads do not overlap", async () => {
    const s = server({ hold: true });
    const p = new TenderPager(s.fetchImpl, "tn", "api");
    const a = p.loadMore(), b = p.loadMore();
    expect(s.seen).toHaveLength(1);
    s.release();
    await Promise.all([a, b]);
    expect(p.state.items).toHaveLength(50);
    const c = p.loadMore();
    expect(s.seen).toHaveLength(2);
    expect(s.seen[1]).toBe("/api/portals/tn/tenders?limit=50&offset=50");
    s.release();
    await c;
  });

  it("sends no request when next is null", async () => {
    const seen: string[] = [];
    const p = new TenderPager(async (u) => { seen.push(u); return json({ total: 3, offset: 0, limit: 50, next: null, items: [item(0), item(1), item(2)] }); }, "tn", "api");
    await p.loadMore();
    await p.loadMore();
    await p.loadMore();
    expect(seen).toHaveLength(1);
    expect(p.state.next).toBeNull();
    expect(p.state.capped).toBe(false);
  });

  it("stops at 500 rows and sends nothing after", async () => {
    const s = server();
    const p = new TenderPager(s.fetchImpl, "tn", "api");
    for (let i = 0; i < 20; i++) await p.loadMore();
    expect(s.seen).toHaveLength(TENDER_CAP / TENDER_PAGE_SIZE);
    expect(p.state.items).toHaveLength(TENDER_CAP);
    expect(p.state.capped).toBe(true);
  });

  it("a failed page shows an error and the next call asks again once", async () => {
    let fail = true;
    const s = server({ fail: () => fail });
    const p = new TenderPager(s.fetchImpl, "tn", "api");
    await p.loadMore();
    expect(p.state.error).toBe(true);
    expect(s.seen).toHaveLength(1);
    fail = false;
    await p.loadMore();
    expect(s.seen).toHaveLength(2);
    expect(p.state.error).toBe(false);
    expect(p.state.items).toHaveLength(50);
  });

  it("demo mode slices the bundled tenders the same way, with no network", async () => {
    const seen: string[] = [];
    const p = new TenderPager(async (u) => { seen.push(u); throw new Error("no network"); }, "tn", "demo");
    await p.loadMore();
    const page = demoTenderPage("tn", 50, 0);
    expect(seen).toEqual([]);
    expect(page).toMatchObject({ total: demoTenders("tn")!.length, offset: 0, limit: 50, next: null });
    expect(p.state.items.map((t) => t.id)).toEqual(page!.items.map((t) => t.id));
    expect(demoTenderPage("tn", 2, 2)).toMatchObject({ offset: 2, limit: 2, next: 4 });
    expect(demoTenderPage("tn", 2, 4)).toMatchObject({ next: null });
    expect(demoTenderPage("tn", 2, 0)!.items[0]).toHaveProperty("documentCount");
  });

  it("basic live reads the contract route once and cuts it to 500", async () => {
    const seen: string[] = [];
    const all = Array.from({ length: 700 }, (_, i) => ({ ...item(i), documents: [] }));
    const p = new TenderPager(async (u) => { seen.push(u); return json(all); }, "tn", "basic");
    await p.loadMore();
    await p.loadMore();
    expect(seen).toEqual(["/portals/tn/tenders"]);
    expect(p.state.items).toHaveLength(500);
    expect(p.state.total).toBe(700);
    expect(p.state.cut).toBe(true);
  });

  it("opening a row fetches that one tender with its files", async () => {
    const seen: string[] = [];
    const { documentCount: _c, ...rest } = item(1);
    const full = { ...rest, documents: [{ fileName: "a.pdf", sizeBytes: 5, sha256: null, path: null }] };
    const p = new TenderPager(async (u) => { seen.push(u); return json(full); }, "tn", "api");
    await p.loadOne("t1");
    await p.loadOne("t1");
    expect(seen).toEqual(["/api/portals/tn/tenders/t1"]);
    expect(p.state.open["t1"]).toMatchObject({ status: "ok" });
  });
});

describe("a poll cycle", () => {
  it("sends no request to any tenders route", async () => {
    const seen: string[] = [];
    const portal = demoDashboard.portals[0]!;
    const c = new LedgerController(async (u) => {
      seen.push(u);
      return u === "/api/dashboard" ? json(demoDashboard) : u.endsWith("/timeline") ? json([]) : new Response("no", { status: 404 });
    }, { name: "portal", id: portal.id });
    await c.cycle();
    await c.cycle();
    expect(c.state.detail?.kind).toBe("ok");
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.some((u) => u.includes("/tenders"))).toBe(false);
  });
});

describe("TenderList scrolling", () => {
  let observers: { cb: IntersectionObserverCallback; el: Element | null }[] = [];
  const original = globalThis.IntersectionObserver;
  beforeEach(() => {
    observers = [];
    globalThis.IntersectionObserver = class {
      private rec: { cb: IntersectionObserverCallback; el: Element | null };
      constructor(cb: IntersectionObserverCallback) { this.rec = { cb, el: null }; observers.push(this.rec); }
      observe(el: Element) { this.rec.el = el; }
      disconnect() { this.rec.el = null; }
      unobserve() {}
      takeRecords() { return []; }
    } as unknown as typeof IntersectionObserver;
  });
  afterEach(() => { globalThis.IntersectionObserver = original; });
  const scrollToEnd = () => act(() => { observers.filter((o) => o.el).forEach((o) => o.cb([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver)); });

  it("loads 50 first, then exactly one page per scroll, never overlapping", async () => {
    const s = server({ hold: true });
    render(<TenderList portalId="tn" mode="api" timeZone={null} live fetchImpl={s.fetchImpl} />);
    expect(s.seen).toEqual(["/api/portals/tn/tenders?limit=50&offset=0"]);
    await act(async () => { s.release(); });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Showing 50 of 4,132"));
    scrollToEnd();
    scrollToEnd();
    expect(s.seen).toHaveLength(2);
    expect(s.seen[1]).toBe("/api/portals/tn/tenders?limit=50&offset=50");
    await act(async () => { s.release(); });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Showing 100 of 4,132"));
  });

  it("shows an error row after a failed page and asks again on the next scroll", async () => {
    let fail = false;
    const s = server({ fail: () => fail });
    render(<TenderList portalId="tn" mode="api" timeZone={null} live fetchImpl={s.fetchImpl} />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Showing 50 of 4,132"));
    fail = true;
    scrollToEnd();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Scroll again/));
    expect(s.seen).toHaveLength(2);
    fail = false;
    fireEvent.scroll(screen.getByLabelText("Delivered tenders, scrolling list"));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Showing 100 of 4,132"));
    expect(s.seen).toHaveLength(3);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("stops at 500 with the one-line note and sends nothing more", async () => {
    const s = server();
    render(<TenderList portalId="tn" mode="api" timeZone={null} live fetchImpl={s.fetchImpl} />);
    for (let i = 0; i < 12; i++) {
      await waitFor(() => expect(screen.getByRole("status")).not.toHaveTextContent("Loading"));
      scrollToEnd();
      await act(async () => {});
    }
    await waitFor(() => expect(screen.getByText("Showing the first 500 of 4,132 tenders.")).toBeInTheDocument());
    expect(s.seen).toHaveLength(10);
    scrollToEnd();
    expect(s.seen).toHaveLength(10);
  });
});
