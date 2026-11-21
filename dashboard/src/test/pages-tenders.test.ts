import { describe, expect, it } from "vitest";
import { demoDashboard, demoTenderPage, demoTenders } from "@/data/demo";
import { demoFleet, loadFleet } from "@/components/pages/pagesData";
import { CSV_COLUMNS, NO_FILTERS, csvCell, externalHref, filterRows, flattenTenders, toCsv, toJson, type TenderRow } from "@/components/pages/tenderRows";
import type { Tender } from "@/types";

const NOW = Date.parse("2026-11-20T12:00:00+01:00");
const tender = (over: Partial<Tender>): Tender => ({
  id: "t", url: null, title: null, buyerName: null, publicationDate: null, submissionDeadline: null,
  status: "open", documents: null, lastChangedAt: "2026-11-20T10:00:00+01:00", ...over,
});
const row = (over: Partial<Tender>, portalId = "p1"): TenderRow => ({ tender: tender(over), portalId, portalUrl: `https://${portalId}.example`, timeZone: "Europe/Berlin" });

const rows: TenderRow[] = [
  row({ id: "a", title: "Wartung von Lüftungsanlagen", buyerName: "Stadt Aachen", submissionDeadline: "2026-11-25T10:00:00+01:00" }),
  row({ id: "b", title: "Road works", buyerName: "City of Ulm", submissionDeadline: "2026-12-15T10:00:00+01:00", status: "closed" }, "p2"),
  row({ id: "c", title: "Bridge repair", buyerName: "Stadt Neuss", submissionDeadline: "2026-11-01T10:00:00+01:00", status: "withdrawn" }),
  row({ id: "d", title: "Cleaning services", buyerName: null }),
  row({ id: "e", title: null, buyerName: "Gemeente Maastricht", submissionDeadline: "2027-03-01T10:00:00+01:00" }, "p2"),
];
const ids = (rs: TenderRow[]) => rs.map((r) => r.tender.id);

describe("explorer filtering", () => {
  it("sorts by deadline, soonest first, with undated tenders last", () => {
    expect(ids(filterRows(rows, NO_FILTERS, NOW))).toEqual(["c", "a", "b", "e", "d"]);
    expect(ids(filterRows(rows, { ...NO_FILTERS, sort: "desc" }, NOW))).toEqual(["e", "b", "a", "c", "d"]);
  });

  it("searches the title and the buyer, ignoring case and accents", () => {
    expect(ids(filterRows(rows, { ...NO_FILTERS, query: "luftung" }, NOW))).toEqual(["a"]);
    expect(ids(filterRows(rows, { ...NO_FILTERS, query: "STADT" }, NOW))).toEqual(["c", "a"]);
    expect(ids(filterRows(rows, { ...NO_FILTERS, query: "maastricht" }, NOW))).toEqual(["e"]);
    expect(ids(filterRows(rows, { ...NO_FILTERS, query: "stadt bridge" }, NOW))).toEqual(["c"]);
    expect(filterRows(rows, { ...NO_FILTERS, query: "p2.example" }, NOW)).toEqual([]);
  });

  it("filters by status", () => {
    expect(ids(filterRows(rows, { ...NO_FILTERS, status: "open" }, NOW))).toEqual(["a", "e", "d"]);
    expect(ids(filterRows(rows, { ...NO_FILTERS, status: "withdrawn" }, NOW))).toEqual(["c"]);
  });

  it("filters by deadline window against the given now", () => {
    expect(ids(filterRows(rows, { ...NO_FILTERS, window: "7d" }, NOW))).toEqual(["a"]);
    expect(ids(filterRows(rows, { ...NO_FILTERS, window: "30d" }, NOW))).toEqual(["a", "b"]);
    expect(ids(filterRows(rows, { ...NO_FILTERS, window: "past" }, NOW))).toEqual(["c"]);
    expect(ids(filterRows(rows, { ...NO_FILTERS, window: "none" }, NOW))).toEqual(["d"]);
  });

  it("combines search, status and window", () => {
    expect(ids(filterRows(rows, { query: "stadt", status: "open", window: "30d", sort: "asc" }, NOW))).toEqual(["a"]);
  });

  it("does not change the input rows", () => {
    const before = ids(rows);
    filterRows(rows, { ...NO_FILTERS, sort: "desc" }, NOW);
    expect(ids(rows)).toEqual(before);
  });

  it("flattens every portal's tenders and skips portals that could not be read", () => {
    const tenders = Object.fromEntries(demoDashboard.portals.map((p) => [p.id, p.id === "nrw" ? null : demoTenders(p.id)]));
    const flat = flattenTenders(demoDashboard.portals, tenders);
    expect(flat.some((r) => r.portalId === "nrw")).toBe(false);
    expect(flat.filter((r) => r.portalId === "tn")).toHaveLength(5);
    expect(flat[0]).toMatchObject({ portalId: "tn", portalUrl: "https://tenderned.nl", timeZone: "Europe/Amsterdam" });
  });
});

describe("CSV escaping", () => {
  it("leaves plain cells alone and empties null", () => {
    expect(csvCell("Road works")).toBe("Road works");
    expect(csvCell(null)).toBe("");
    expect(csvCell(undefined)).toBe("");
    expect(csvCell(1200)).toBe("1200");
    expect(csvCell(0)).toBe("0");
  });

  it("quotes commas, quotes and line breaks, doubling inner quotes", () => {
    expect(csvCell("Roads, bridges")).toBe('"Roads, bridges"');
    expect(csvCell('The "big" one')).toBe('"The ""big"" one"');
    expect(csvCell("line one\nline two")).toBe('"line one\nline two"');
    expect(csvCell("a\r\nb")).toBe('"a\r\nb"');
  });

  it("defuses cells a spreadsheet would run as a formula", () => {
    expect(csvCell("=SUM(A1:A9)")).toBe("'=SUM(A1:A9)");
    expect(csvCell("+49 30 1234")).toBe("'+49 30 1234");
    expect(csvCell("-cmd")).toBe("'-cmd");
    expect(csvCell("@import")).toBe("'@import");
    expect(csvCell('=HYPERLINK("http://x","y")')).toBe('"\'=HYPERLINK(""http://x"",""y"")"');
  });

  it("writes a header and one CRLF line per row with the same number of cells", () => {
    const csv = toCsv([
      row({ id: "x1", title: 'Sanierung, "Los 2"', buyerName: "Stadt Ulm", url: "https://p1.example/t/x1", referenceNumber: "R-1",
        submissionDeadline: "2026-12-09T10:00:00+01:00", publicationDate: "2026-11-20",
        documents: [{ fileName: "a.pdf", sizeBytes: 1000, sha256: null, path: "/files/a" }, { fileName: "b, c.pdf", sizeBytes: null, sha256: null, path: null }] }),
      row({ id: "x2" }),
    ]);
    const lines = csv.split("\r\n");
    expect(lines[0]).toBe(CSV_COLUMNS.join(","));
    expect(lines[1]).toBe('p1,https://p1.example,x1,R-1,"Sanierung, ""Los 2""",Stadt Ulm,open,,2026-11-20,2026-12-09T10:00:00+01:00,2026-11-20T10:00:00+01:00,https://p1.example/t/x1,2,1000,"a.pdf; b, c.pdf"');
    // documents null = not collected: count, bytes and names stay empty, never 0
    expect(lines[2]).toBe("p1,https://p1.example,x2,,,,open,,,,2026-11-20T10:00:00+01:00,,,,");
    expect(lines[3]).toBe("");
    expect(lines).toHaveLength(4);
  });

  it("exports JSON rows as sent, with their portal", () => {
    const out = JSON.parse(toJson([rows[1] as TenderRow])) as Record<string, unknown>[];
    expect(out[0]).toMatchObject({ portal: { id: "p2", url: "https://p2.example" }, id: "b", status: "closed", title: "Road works" });
  });
});

describe("links", () => {
  it("opens only http and https tender pages", () => {
    expect(externalHref("https://a.example/t/1")).toBe("https://a.example/t/1");
    expect(externalHref("javascript:alert(1)")).toBeNull();
    expect(externalHref("data:text/html,x")).toBeNull();
    expect(externalHref("not a url")).toBeNull();
    expect(externalHref(null)).toBeNull();
  });
});

describe("fleet loading", () => {
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  const dash = { ...demoDashboard, portals: demoDashboard.portals.filter((p) => p.id === "tn" || p.id === "nrw") };

  it("reads the first page (50) of each portal from the paged route and never mixes demo rows into live data", async () => {
    const seen: string[] = [];
    const data = await loadFleet(async (u) => {
      seen.push(u);
      if (u === "/api/dashboard") return json(dash);
      if (u === "/api/portals/tn/tenders?limit=50&offset=0") return json(demoTenderPage("tn", 50, 0));
      return new Response("no", { status: 500 });
    }, { timelines: false, tenders: true }, new AbortController().signal);
    expect([...seen].sort()).toEqual(["/api/dashboard", "/api/portals/nrw/tenders?limit=50&offset=0", "/api/portals/tn/tenders?limit=50&offset=0"]);
    expect(seen.some((u) => u.startsWith("/portals/"))).toBe(false);
    expect(data.source).toBe("live");
    expect(data.tenders["tn"]).toHaveLength(5);
    expect(data.tenders["nrw"]).toBeNull();
    expect(data.timelines).toEqual({});
  });

  it("stays live on the public contract routes when /api/dashboard is not there, using the runs as timelines", async () => {
    const seen: string[] = [];
    const runs = [
      { id: "r1", kind: "read", startedAt: "2026-11-20T20:00:00+01:00", finishedAt: "2026-11-20T20:00:05+01:00", result: "ok" },
      { id: "r2", kind: "read", startedAt: "2026-11-20T20:05:00+01:00", finishedAt: "2026-11-20T20:05:05+01:00", result: "failed" },
    ];
    const data = await loadFleet(async (u) => {
      seen.push(u);
      if (u === "/portals") return json([{ id: "tn", url: "https://tenderned.nl", state: "serving", reason: "ok", tenderCount: 5, lastSuccessAt: null }]);
      if (u === "/portals/tn/runs") return json(runs);
      if (u === "/portals/tn/tenders") return json(demoTenders("tn"));
      return new Response("no", { status: 404 });
    }, { timelines: true, tenders: true }, new AbortController().signal, undefined, undefined, new Map());
    expect(seen.filter((u) => u === "/portals/tn/tenders")).toHaveLength(1);
    expect(data).toMatchObject({ source: "live", basic: true });
    expect(seen).not.toContain("/api/portals/tn/timeline");
    expect(data.timelines["tn"]?.map((r) => r.id)).toEqual(["r1", "r2"]);
    expect(data.tenders["tn"]).toHaveLength(5);
    expect(data.dashboard.portals[0]).toMatchObject({ id: "tn", fingerprint: null, usage: null });
  });

  it("falls back to the whole demo snapshot when the dashboard cannot be read", async () => {
    const data = await loadFleet(async () => new Response("no", { status: 404 }), { timelines: true, tenders: true }, new AbortController().signal, undefined, true);
    expect(data).toEqual(demoFleet({ timelines: true, tenders: true }));
    expect(data.source).toBe("demo");
    expect(data.timelines["mock"]).toHaveLength(8);
  });
});
