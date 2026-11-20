import { settingsSchema } from "./schema";
import type { FetchLike } from "./api";
import type { Settings } from "@/types";

export interface SettingsDraft {
  minutes: string;
  ignoreRobots: boolean;
  dirtyMinutes: boolean;
  dirtyRobots: boolean;
}

export const draftFrom = (s: Settings): SettingsDraft => ({
  minutes: String(s.attachTimeLimitMinutes),
  ignoreRobots: s.ignoreRobotsTxt,
  dirtyMinutes: false,
  dirtyRobots: false,
});

/** Poll arrivals refresh only fields the operator has not touched. */
export function mergeServerSettings(d: SettingsDraft, s: Settings): SettingsDraft {
  return {
    ...d,
    minutes: d.dirtyMinutes ? d.minutes : String(s.attachTimeLimitMinutes),
    ignoreRobots: d.dirtyRobots ? d.ignoreRobots : s.ignoreRobotsTxt,
  };
}

export function parseMinutes(v: string): number | null {
  if (!/^\d+$/.test(v.trim())) return null;
  const n = Number(v.trim());
  return Number.isSafeInteger(n) && n > 0 ? n : null;
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
