import { describe, expect, it } from "vitest";
import { LedgerController } from "@/data/controller";
import { externalHref } from "@/data/api";
import { demoDashboard } from "@/data/demo";
import { addPortals, parseUrls } from "@/data/portals";
import { fleetSummary } from "@/data/view";
import { costBars, deliverySeries, fleetEvents, readSeries } from "@/components/ledger/overview";
import type { Portal, Run } from "@/types";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const notFound = () => json({ detail: "Not Found" }, 404);

const NOW = Date.parse("2026-11-20T21:00:00+00:00");
const contractPortals = [
  { id: "a1", url: "https://www.tenderned.nl/aankondigingen/overzicht", state: "integrating", reason: "Attaching: nothing delivered yet.", tenderCount: 0, lastSuccessAt: null, cause: null },
  { id: "b2", url: "https://vergabe.vmstart.de/NetServer/", state: "serving", reason: "Read at 20:55 found 1 open tender.", tenderCount: 1, lastSuccessAt: "2026-11-20T20:55:00+00:00", cause: null },
];
const runsA = [{ id: "ra1", kind: "read", startedAt: "2026-11-20T20:50:00+00:00", finishedAt: null, result: null }];
const runsB = [
  { id: "rb1", kind: "read", startedAt: "2026-11-20T19:30:00+00:00", finishedAt: "2026-11-20T19:30:08+00:00", result: "failed" },
  { id: "rb2", kind: "repair", startedAt: "2026-11-20T19:31:00+00:00", finishedAt: "2026-11-20T19:33:00+00:00", result: "ok" },
  { id: "rb3", kind: "read", startedAt: "2026-11-20T20:55:00+00:00", finishedAt: "2026-11-20T20:55:09+00:00", result: "ok" },
];

/** A server with the public contract routes and no /api routes, like the build before /api/dashboard exists. */
function contractServer(overrides: Record<string, () => Response> = {}) {
  const seen: string[] = [];
  const routes: Record<string, () => Response> = {
    "/portals": () => json(contractPortals),
    "/portals/a1/runs": () => json(runsA),
    "/portals/b2/runs": () => json(runsB),
    "/portals/b2/tenders": () => json([]),
    ...overrides,
  };
  const fetchImpl = async (u: string) => { seen.push(u); return (routes[u] ?? notFound)(); };
  return { fetchImpl, seen };
}

describe("live without /api/dashboard", () => {
  it("404 on /api/dashboard with GET /portals 200 is basic live, not demo", async () => {
    const { fetchImpl, seen } = contractServer();
    const c = new LedgerController(fetchImpl, { name: "overview" }, { now: () => NOW, allowDemo: true });
    await c.cycle();
    expect(c.state.source).toBe("live");
    expect(c.state.basic).toBe(true);
    expect(seen[0]).toBe("/api/dashboard");
    expect(c.state.dashboard?.portals.map((p) => p.id)).toEqual(["a1", "b2"]);
    expect(c.state.dashboard?.portals.some((p) => demoDashboard.portals.some((x) => x.id === p.id))).toBe(false);
  });

  it("maps PortalOut into the row model and leaves what the contract lacks null", async () => {
    const { fetchImpl } = contractServer();
    const c = new LedgerController(fetchImpl, { name: "overview" }, { now: () => NOW, allowDemo: true });
    await c.cycle();
    const [a, b] = c.state.dashboard?.portals ?? [];
    expect(a).toMatchObject({ state: "integrating", tenderCount: 0, lastSuccessAt: null, cause: null });
    expect(b).toMatchObject({ fingerprint: null, timezone: null, recipeVersion: null, nextReadAt: null, usage: null, deliveryTrend: null });
    expect(c.state.dashboard?.eurPerUsd).toBeNull();
    expect(c.state.dashboard?.settings).toBeNull();
    // From the public runs route, nothing invented: the last run, the read results, reads within the hour.
    expect(b?.lastRun).toEqual({ id: "rb3", kind: "read", result: "ok" });
    expect(b?.recentReads).toEqual(["failed", "ok"]);
    expect(b?.readsLastHour).toBe(1);
    expect(a?.recentReads).toEqual([null]);
    expect(c.state.fleetRuns?.["b2"]?.[1]).toMatchObject({ kind: "repair", trigger: null, summary: null, modelCalls: null });
  });

  it("a portal whose runs cannot be read keeps null history instead of an empty one", async () => {
    const { fetchImpl } = contractServer({ "/portals/a1/runs": () => new Response("x", { status: 500 }) });
    const c = new LedgerController(fetchImpl, { name: "overview" }, { now: () => NOW, allowDemo: true });
    await c.cycle();
    const a = c.state.dashboard?.portals[0];
    expect(c.state.basic).toBe(true);
    expect(a?.recentReads).toBeNull();
    expect(a?.readsLastHour).toBeNull();
    expect(a?.lastRun).toBeNull();
  });

  it("the portal page poll uses /portals/{id}/runs as a basic timeline and never reads the tenders route", async () => {
    const { fetchImpl, seen } = contractServer();
    const c = new LedgerController(fetchImpl, { name: "portal", id: "b2" }, { now: () => NOW, allowDemo: true });
    await c.cycle();
    expect(c.state.source).toBe("live");
    expect(c.state.basic).toBe(true);
    expect(c.state.detail?.kind).toBe("ok");
    if (c.state.detail?.kind !== "ok") throw new Error("no detail");
    expect(c.state.detail.timeline.map((r) => r.id)).toEqual(["rb1", "rb2", "rb3"]);
    expect(seen).toContain("/portals/b2/runs");
    expect(seen).not.toContain("/portals/b2/tenders");
  });

  it("never mixes: basic live with a failing runs route falls back to demo as a whole", async () => {
    const { fetchImpl } = contractServer({ "/portals/b2/runs": () => new Response("x", { status: 500 }) });
    const c = new LedgerController(fetchImpl, { name: "portal", id: "b2" }, { now: () => NOW, allowDemo: true });
    await c.cycle();
    expect(c.state.source).toBe("demo");
    expect(c.state.basic).toBe(false);
    expect(c.state.detail?.kind).toBe("notInDemo");
  });

  it("an id the contract list does not have is Portal not found, still live", async () => {
    const { fetchImpl } = contractServer();
    const c = new LedgerController(fetchImpl, { name: "portal", id: "gone" }, { now: () => NOW, allowDemo: true });
    await c.cycle();
    expect(c.state.source).toBe("live");
    expect(c.state.detail?.kind).toBe("notFound");
  });

  it("both unreachable is the demo snapshot", async () => {
    const c = new LedgerController(async () => { throw new TypeError("down"); }, { name: "overview" }, { allowDemo: true });
    await c.cycle();
    expect(c.state.source).toBe("demo");
    expect(c.state.basic).toBe(false);
    expect(c.state.everOnline).toBe(false);
    expect(c.state.dashboard).toBe(demoDashboard);
  });

  it("the full /api routes win when they exist; basic to full to demo and back", async () => {
    let mode: "basic" | "full" | "down" = "basic";
    const full = { asOf: "2026-11-20T21:00:00Z", eurPerUsd: 0.9, settings: { attachTimeLimitMinutes: 20, ignoreRobotsTxt: false }, portals: [] };
    const { fetchImpl: contract } = contractServer();
    const c = new LedgerController(async (u) => {
      if (mode === "down") throw new TypeError("down");
      if (mode === "full" && u === "/api/dashboard") return json(full);
      return contract(u);
    }, { name: "overview" }, { now: () => NOW, allowDemo: true });
    await c.cycle();
    expect([c.state.source, c.state.basic]).toEqual(["live", true]);
    mode = "full";
    await c.cycle();
    expect([c.state.source, c.state.basic]).toEqual(["live", false]);
    expect(c.state.fleetRuns).toBeNull();
    mode = "down";
    await c.cycle();
    expect([c.state.source, c.state.everOnline]).toEqual(["demo", true]);
    mode = "basic";
    await c.refresh();
    expect([c.state.source, c.state.basic]).toEqual(["live", true]);
  });

  it("unknown reads and cost stay unknown in the fleet numbers and the analytics", () => {
    const rows = (demoDashboard.portals as Portal[]).map((p) => ({ ...p, recentReads: null, deliveryTrend: null, readsLastHour: null, usage: null }));
    const summary = fleetSummary({ ...demoDashboard, portals: rows });
    expect(summary.readsLastHour).toBeNull();
    expect(summary.cost.kind).toBe("none");
    expect(summary.tendersDelivered).toBe(13);
    expect(readSeries(rows)).toBeNull();
    expect(deliverySeries(rows)).toBeNull();
    expect(costBars(rows).every((b) => b.eur === null)).toBe(true);
  });
});

describe("fleet analytics from the snapshot", () => {
  const portals = demoDashboard.portals as Portal[];
  it("counts passed and failed reads per slot and the share that passed", () => {
    const s = readSeries(portals);
    if (!s) throw new Error("no series");
    expect([s.totalPassed, s.totalFailed, s.totalRunning]).toEqual([18, 7, 1]);
    expect(s.passRate).toBeCloseTo(18 / 25, 5);
    expect(s.passed).toHaveLength(6);
    expect(s.passed.at(-1)).toBe(4);
    expect(s.failed.at(-1)).toBe(3);
  });
  it("sums published tenders per read over portals and ranks cost per portal", () => {
    expect(deliverySeries(portals)).toEqual([7, 9, 9, 10, 11, 13]);
    const bars = costBars(portals);
    expect(bars[0]?.eur).toBeCloseTo(0.036, 5);
    expect(bars.at(-1)?.eur).toBe(0);
  });
  it("lists repairs, failures and attaches from runs, and current states without runs", () => {
    const run = (r: Partial<Run>): Run => ({ id: "x", kind: "read", trigger: "schedule", startedAt: "2026-11-20T20:00:00Z", finishedAt: null, result: "ok", summary: "s", modelCalls: 0, ...r });
    const first = portals[0];
    if (!first) throw new Error("no portal");
    const events = fleetEvents([first], { [first.id]: [run({ id: "1" }), run({ id: "2", result: "failed", startedAt: "2026-11-20T20:10:00Z" }), run({ id: "3", kind: "repair", trigger: "heal", result: null, startedAt: "2026-11-20T20:11:00Z" }), run({ id: "4", trigger: "attach", startedAt: "2026-11-20T19:00:00Z" })] });
    expect(events.map((e) => e.title)).toEqual(["Repair running", "Read failed", "Portal attached"]);
    expect(fleetEvents(portals, null).map((e) => e.title)).toEqual(["Failed", "Failed", "Healing"]);
  });
});

describe("adding portals", () => {
  it("keeps http(s) addresses, one per line, and says what is wrong with the rest", () => {
    const lines = parseUrls(" https://www.tenderned.nl/aankondigingen/overzicht \n\nftp://x.example/a\nvergabe.vmstart.de\nhttps://vergabe.vmstart.de/NetServer/\nhttps://www.tenderned.nl/aankondigingen/overzicht\njavascript:alert(1)");
    expect(lines.map((l) => [l.url, l.valid])).toEqual([
      ["https://www.tenderned.nl/aankondigingen/overzicht", true],
      ["ftp://x.example/a", false],
      ["vergabe.vmstart.de", false],
      ["https://vergabe.vmstart.de/NetServer/", true],
      ["javascript:alert(1)", false],
    ]);
    expect(lines[2]?.problem).toMatch(/http/);
  });

  it("posts one after another and reports added, already watched and the server's error", async () => {
    const order: string[] = [];
    let open = 0, maxOpen = 0;
    const fetchImpl = async (u: string, init?: RequestInit) => {
      const { url } = JSON.parse(String(init?.body)) as { url: string };
      order.push(`${init?.method} ${u} ${url}`);
      open++; maxOpen = Math.max(maxOpen, open);
      await new Promise((r) => setTimeout(r, 1));
      open--;
      if (url.includes("bad")) return json({ detail: "url must be an http or https address." }, 400);
      return json({ id: url.includes("tenderned") ? "a1" : "new9" }, 201);
    };
    const seenResults: string[] = [];
    const results = await addPortals(fetchImpl, ["https://www.tenderned.nl/x", "https://new.example/", "https://bad.example/", "https://new.example/again"], ["a1"], (r) => seenResults.push(r.status));
    expect(maxOpen).toBe(1);
    expect(order).toHaveLength(4);
    expect(order[0]).toBe("POST /portals https://www.tenderned.nl/x");
    expect(results.map((r) => r.status)).toEqual(["already", "added", "error", "already"]);
    expect(results[1]).toMatchObject({ id: "new9" });
    expect(results[2]).toMatchObject({ message: "url must be an http or https address." });
    expect(seenResults).toEqual(["already", "added", "error", "already"]);
  });

  it("an unreachable API is an error per address, not a crash", async () => {
    const results = await addPortals(async () => { throw new TypeError("down"); }, ["https://a.example/"], []);
    expect(results).toEqual([{ url: "https://a.example/", status: "error", message: "The API did not answer." }]);
  });
});

describe("outbound links", () => {
  it("opens only http(s) addresses", () => {
    expect(externalHref("https://www.tenderned.nl/aankondigingen/overzicht")).toBe("https://www.tenderned.nl/aankondigingen/overzicht");
    expect(externalHref("http://mock.watchtower.test")).toBe("http://mock.watchtower.test/");
    expect(externalHref("javascript:alert(1)")).toBeNull();
    expect(externalHref("not a url")).toBeNull();
    expect(externalHref(null)).toBeNull();
  });
});
