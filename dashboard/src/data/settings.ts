import { settingsSchema } from "./schema";
import type { FetchLike } from "./api";
import type { Settings } from "@/types";

export interface SettingsDraft {
  minutes: string;
  ignoreRobots: boolean;
  dirtyMinutes: boolean;
  dirtyRobots: boolean;
  /** "" when the backend does not send the limit: the field is then not shown. */
  tenders: string;
  dirtyTenders: boolean;
}

export const draftFrom = (s: Settings): SettingsDraft => ({
  minutes: String(s.attachTimeLimitMinutes),
  ignoreRobots: s.ignoreRobotsTxt,
  dirtyMinutes: false,
  dirtyRobots: false,
  tenders: s.maxTendersPerPortal === undefined ? "" : String(s.maxTendersPerPortal),
  dirtyTenders: false,
});

/** Poll arrivals refresh only fields the operator has not touched. */
export function mergeServerSettings(d: SettingsDraft, s: Settings): SettingsDraft {
  return {
    ...d,
    minutes: d.dirtyMinutes ? d.minutes : String(s.attachTimeLimitMinutes),
    ignoreRobots: d.dirtyRobots ? d.ignoreRobots : s.ignoreRobotsTxt,
    tenders: d.dirtyTenders ? d.tenders : s.maxTendersPerPortal === undefined ? "" : String(s.maxTendersPerPortal),
  };
}

export function parseMinutes(v: string): number | null {
  if (!/^\d+$/.test(v.trim())) return null;
  const n = Number(v.trim());
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}

/** The tender limit as typed: a whole number from 0 (no limit) to 100,000, else null. */
export function parseTenderLimit(v: string): number | null {
  if (!/^\d+$/.test(v.trim())) return null;
  const n = Number(v.trim());
  return Number.isSafeInteger(n) && n <= 100_000 ? n : null;
}

/** What a limit means for the wait: each tender costs at least one request, at one request a second. */
export function tenderLimitNote(n: number): { warn: boolean; text: string } {
  if (n === 0)
    return { warn: true, text: "No limit. A portal with thousands of tenders stays integrating for an hour or more before it delivers anything, and one whose own search stops early delivers nothing." };
  const minutes = Math.max(1, Math.ceil(n / 60));
  const wait = minutes >= 90 ? `about ${Math.round(minutes / 60)} hours` : `about ${minutes} minute${minutes === 1 ? "" : "s"}`;
  return {
    warn: n > 1000,
    text: `A portal that lists more delivers its first ${n.toLocaleString("en-US")} tenders. Reading that many takes ${wait} at one request a second, before documents.`,
  };
}

export async function saveSettings(fetchImpl: FetchLike, s: Settings): Promise<Settings> {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), 8000);
  try {
    const res = await fetchImpl("/api/settings", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        attachTimeLimitMinutes: s.attachTimeLimitMinutes,
        ignoreRobotsTxt: s.ignoreRobotsTxt,
        ...(s.maxTendersPerPortal === undefined ? {} : { maxTendersPerPortal: s.maxTendersPerPortal }),
      }),
      signal: ac.signal,
    });
    if (!res.ok) throw new Error(`The server refused the change (HTTP ${res.status}).`);
    if (!(res.headers.get("content-type") ?? "").includes("application/json"))
      throw new Error("The server did not acknowledge the change.");
    const parsed = settingsSchema.safeParse(await res.json().catch(() => null));
    if (!parsed.success) throw new Error("The server did not acknowledge the change.");
    return parsed.data;
  } catch (e) {
    if (e instanceof Error && e.name !== "AbortError" && !(e instanceof TypeError)) throw e;
    throw new Error("Could not reach the API. Your edits are kept.");
  } finally {
    clearTimeout(t);
  }
}
