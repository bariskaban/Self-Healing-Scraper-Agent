import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TenderTable } from "@/components/ledger/TenderTable";
import { portalPath } from "@/data/api";
import { LedgerController } from "@/data/controller";
import { costText, runCost } from "@/data/format";
import { runSchema, stepSchema, tenderSchema, tendersSchema, timelineSchema } from "@/data/schema";

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

// What TenderOut.to_api() sends when the portal shows nothing but the id:
// required fields null, optional fields left out.
const bareTender = {
  id: "t-bare", url: null, title: null, buyerName: null, publicationDate: null,
  submissionDeadline: null, status: "open", documents: null, lastChangedAt: "2026-11-20T10:00:00+01:00",
};
const fullTender = {
  id: "t-full", url: "https://a.example/t/1", title: "Road works", buyerName: "City of A",
  publicationDate: "2026-12-09", submissionDeadline: "2027-01-15T12:00:00+01:00", status: "open",
  documents: [
    { fileName: "spec.pdf", sizeBytes: 1200, sha256: "a".repeat(64), path: "/files/ab12" },
    { fileName: "later.pdf", sizeBytes: null, sha256: null, path: null },
  ],
  lastChangedAt: "2026-11-20T10:00:00+01:00",
  referenceNumber: "REF-1", description: "Resurfacing", procedureType: "open",
  contractNature: "works", cpvCodes: ["45233120"], placeOfPerformance: { postalCode: null, city: "A", countryCode: "DE" },
};
const step = { seq: 1, at: "2026-11-20T10:00:01Z", kind: "llm", name: "plan", summary: "s", durationMs: 10, usage: null };
const run = {
  id: "r1", kind: "repair", trigger: "heal", startedAt: "2026-11-20T10:00:00Z", finishedAt: "2026-11-20T10:01:00Z",
  result: "ok", summary: "done", modelCalls: 2, usage: null, steps: [step],
};
const portal = {
  id: "p1", url: "https://a.example/t", state: "serving", reason: "ok", tenderCount: 2,
  lastSuccessAt: null, cause: null, fingerprint: null, timezone: null, recipeVersion: null,
  nextReadAt: null, lastRun: null, recentReads: [], deliveryTrend: [], readsLastHour: 0, usage: null,
};
const dash = { asOf: "2026-11-20T20:00:00Z", eurPerUsd: 0.9, settings: { attachTimeLimitMinutes: 20, ignoreRobotsTxt: false }, portals: [portal] };

describe("request paths", () => {
  it("reads tenders from the public contract route and the timeline from /api", () => {
    expect(portalPath("p1", "tenders")).toBe("/portals/p1/tenders");
    expect(portalPath("p1", "timeline")).toBe("/api/portals/p1/timeline");
    expect(portalPath("a/b c", "tenders")).toBe("/portals/a%2Fb%20c/tenders");
  });

  it("a detail cycle requests exactly the documented routes and stays live", async () => {
    const seen: string[] = [];
    const routes: Record<string, unknown> = {
      "/api/dashboard": dash,
      "/api/portals/p1/timeline": [run],
      "/portals/p1/tenders": [bareTender, fullTender],
    };
    const c = new LedgerController(async (u) => {
      seen.push(u);
      return u in routes ? json(routes[u]) : new Response("no", { status: 404 });
    }, { name: "portal", id: "p1" });
    await c.cycle();
    expect([...seen].sort()).toEqual(["/api/dashboard", "/api/portals/p1/timeline", "/portals/p1/tenders"]);
    expect(c.state.source).toBe("live");
    expect(c.state.detail?.kind).toBe("ok");
  });
});

describe("tender wire shape (TenderOut)", () => {
  it("accepts a tender whose five nullable fields are null and whose optional fields are left out", () => {
    const r = tenderSchema.safeParse(bareTender);
    expect(r.success).toBe(true);
    expect(r.data).toMatchObject({ url: null, title: null, buyerName: null, publicationDate: null, submissionDeadline: null });
  });
  it("accepts a plain publication date and the optional keys the page does not show", () => {
    const r = tendersSchema.safeParse([fullTender, bareTender]);
    expect(r.success).toBe(true);
    expect(r.data?.[0]?.publicationDate).toBe("2026-12-09");
  });
  it("still rejects a tender without an id or with a broken date", () => {
    expect(tenderSchema.safeParse({ ...bareTender, id: undefined }).success).toBe(false);
    expect(tenderSchema.safeParse({ ...bareTender, publicationDate: "soon" }).success).toBe(false);
    expect(tenderSchema.safeParse({ ...bareTender, lastChangedAt: null }).success).toBe(false);
  });
  it("renders missing values as Not stated instead of failing", () => {
    render(<TenderTable tenders={tendersSchema.parse([bareTender, fullTender])} timeZone={null} live />);
    // title, buyer and deadline, in the phone list and in the table
    expect(screen.getAllByText("Not stated")).toHaveLength(6);
    expect(screen.getAllByText("Road works")).toHaveLength(2);
    expect(screen.getAllByText("REF-1 · https://a.example/t/1")).toHaveLength(2);
    expect(screen.queryByText(/Invalid Date|null/)).toBeNull();
  });
});

describe("usage: null", () => {
  it("is accepted on a run and on a step, like a missing usage", () => {
    expect(stepSchema.safeParse(step).success).toBe(true);
    expect(runSchema.safeParse(run).success).toBe(true);
    const { usage: _s, ...stepWithout } = step;
    const { usage: _r, ...runWithout } = run;
    expect(stepSchema.safeParse(stepWithout).success).toBe(true);
    expect(runSchema.safeParse(runWithout).success).toBe(true);
    expect(timelineSchema.safeParse([run]).success).toBe(true);
  });
  it("means unknown cost for a paid run, not zero", () => {
    expect(costText(runCost(runSchema.parse(run)))).toBe("Not recorded");
  });
});
