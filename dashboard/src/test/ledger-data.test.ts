import { describe, expect, it } from "vitest";
import { LedgerController } from "@/data/controller";
import { costText, eur, runCost, sumUsage, totalTokens } from "@/data/format";
import { publicationSeries, readSlots } from "@/data/view";
import { draftFrom, mergeServerSettings, saveSettings } from "@/data/settings";
import type { Dashboard, Run } from "@/types";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const portal = {
  id: "p1", url: "https://a.example/t", state: "serving", reason: "ok", tenderCount: 4,
  lastSuccessAt: null, cause: null, fingerprint: null, timezone: null, recipeVersion: null,
  nextReadAt: null, lastRun: null, recentReads: [], deliveryTrend: [], readsLastHour: 0, usage: null,
};
const dash = (portals: unknown[] = []): Dashboard =>
  ({ asOf: "2026-11-20T20:00:00Z", eurPerUsd: 0.9, settings: { attachTimeLimitMinutes: 20, ignoreRobotsTxt: false }, portals }) as Dashboard;

describe("ledger source selection", () => {
  it("cold 404 shows no data and says the API is offline, never the demo snapshot", async () => {
    const c = new LedgerController(async () => new Response("no", { status: 404 }), { name: "overview" });
    await c.cycle();
    expect(c.state.source).toBeNull();
    expect(c.state.dashboard).toBeNull();
    expect(c.state.offline).toBe(true);
    expect(c.state.everOnline).toBe(false);
  });

  it("with ?demo a cold 404 shows the demo snapshot", async () => {
    const c = new LedgerController(async () => new Response("no", { status: 404 }), { name: "overview" }, { allowDemo: true });
    await c.cycle();
    expect(c.state.source).toBe("demo");
  });

  it("live 200 with an empty fleet is live, not offline", async () => {
    const c = new LedgerController(async () => json(dash()), { name: "overview" });
    await c.cycle();
    expect(c.state.source).toBe("live");
    expect(c.state.dashboard?.portals).toEqual([]);
  });

  it("a JSON error body is not an empty success", async () => {
    const c = new LedgerController(async () => json({ error: "boom" }), { name: "overview" });
    await c.cycle();
    expect(c.state.source).toBeNull();
    expect(c.state.offline).toBe(true);
  });

  it("live → offline → live", async () => {
    let up = true;
    const c = new LedgerController(async () => { if (!up) throw new TypeError("down"); return json(dash()); }, { name: "overview" });
    await c.cycle();
    expect(c.state.source).toBe("live");
    up = false;
    await c.cycle();
    expect(c.state.source).toBe("live"); // the last live snapshot stays, marked offline
    expect(c.state.offline).toBe(true);
    expect(c.state.everOnline).toBe(true);
    up = true;
    await c.cycle();
    expect(c.state.source).toBe("live");
    expect(c.state.offline).toBe(false);
  });

  it("detail never mixes live dashboard with demo tenders", async () => {
    const c = new LedgerController(async (u) => (u.includes("tenders") ? new Response("x", { status: 500 }) : u.includes("timeline") ? json([]) : json(dash([portal]))), { name: "portal", id: "p1" });
    await c.cycle();
    expect(c.state.source).not.toBe("demo");
    expect(c.state.detail).toBeNull();
    expect(c.state.offline).toBe(true);
  });

  it("live dashboard without the id shows Portal not found", async () => {
    const c = new LedgerController(async (u) => (u.endsWith("dashboard") ? json(dash([portal])) : new Response("", { status: 404 })), { name: "portal", id: "gone" });
    await c.cycle();
    expect(c.state.source).toBe("live");
    expect(c.state.detail?.kind).toBe("notFound");
  });

  it("ignores a stale response after navigation", async () => {
    let release: (() => void) | undefined;
    const fetchImpl = async (u: string, init?: RequestInit) => {
      if (u.includes("/portals/slow/")) {
        await new Promise<void>((r) => { release = r; init?.signal?.addEventListener("abort", () => r()); });
      }
      return u.endsWith("dashboard") ? json(dash([{ ...portal, id: "slow" }])) : json([]);
    };
    const c = new LedgerController(fetchImpl, { name: "portal", id: "slow" });
    const first = c.cycle();
    c.setRoute({ name: "overview" });
    await c.cycle();
    release?.();
    await first;
    expect(c.state.route.name).toBe("overview");
    expect(c.state.detail).toBeNull();
  });
});

describe("usage and costs", () => {
  const u = { inputTokens: 1000, outputTokens: 200, cachedInputTokens: 800, reasoningTokens: 150, costUsd: 0.01, costEur: 0.009 };
  it("does not double-count cached or reasoning subsets", () => expect(totalTokens(u)).toBe(1200));
  it("formats zero and sub-cent euros", () => {
    expect(eur(0)).toBe("0.00 EUR");
    expect(eur(0.004)).toBe("< 0.01 EUR");
    expect(eur(1.234)).toBe("1.23 EUR");
  });
  it("unknown usage is not zero; modelCalls 0 is exact zero", () => {
    const run = { id: "r", kind: "read", trigger: "schedule", startedAt: "2026-11-20T10:00:00Z", finishedAt: "2026-11-20T10:01:00Z", result: "ok", summary: "", modelCalls: 0 } as Run;
    expect(costText(runCost(run))).toBe("0.00 EUR · no model call");
    expect(costText(runCost({ ...run, modelCalls: 2 }))).toBe("Not recorded");
  });
  it("incomplete fleet totals say At least", () => {
    expect(costText(sumUsage([u, null]))).toMatch(/^At least .* incomplete usage$/);
    expect(sumUsage([null]).kind).toBe("none");
  });
});

describe("history and series", () => {
  it("pads read history on the left to 30", () => {
    const s = readSlots(["ok", "failed", null]);
    expect(s).toHaveLength(30);
    expect(s.slice(-3)).toEqual(["ok", "failed", "running"]);
    expect(s[0]).toBe("empty");
  });
  it("a failed read without publishedCount is a gap, keeping the previous count", () => {
    const runs = [
      { id: "a", kind: "read", startedAt: "2026-11-20T10:00:00Z", result: "ok", publishedCount: 12 },
      { id: "b", kind: "read", startedAt: "2026-11-20T11:00:00Z", result: "failed" },
    ] as Run[];
    const s = publicationSeries(runs);
    expect(s[0]?.count).toBe(12);
    expect(s[1]?.count).toBeNull();
  });
});

describe("settings", () => {
  it("keeps dirty edits through polls and failed saves", async () => {
    let d = draftFrom({ attachTimeLimitMinutes: 20, ignoreRobotsTxt: false });
    d = { ...d, minutes: "45", dirtyMinutes: true };
    d = mergeServerSettings(d, { attachTimeLimitMinutes: 30, ignoreRobotsTxt: true });
    expect(d.minutes).toBe("45");
    expect(d.ignoreRobots).toBe(true);
    await expect(saveSettings(async () => new Response("x", { status: 500 }), { attachTimeLimitMinutes: 45, ignoreRobotsTxt: true })).rejects.toThrow();
    expect(d.minutes).toBe("45");
  });
  it("posts both fields and uses the acknowledged response", async () => {
    let body = "";
    const ack = await saveSettings(async (_u, init) => { body = String(init?.body); return json({ attachTimeLimitMinutes: 40, ignoreRobotsTxt: false }); }, { attachTimeLimitMinutes: 45, ignoreRobotsTxt: false });
    expect(JSON.parse(body)).toEqual({ attachTimeLimitMinutes: 45, ignoreRobotsTxt: false });
    expect(ack.attachTimeLimitMinutes).toBe(40);
  });
});
