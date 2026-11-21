// Adding portals through the public contract route POST /portals. This is the page's only write
// besides the two settings; it removes, refreshes and repairs nothing.
import { contractPortalsSchema, createdIdSchema } from "./schema";
import { TIMEOUT_MS, type FetchLike } from "./api";

export interface UrlLine { url: string; valid: boolean; problem: string | null }

/** One address per line. Blank lines and repeats are dropped; each line must be an http(s) address with a host. */
export function parseUrls(text: string): UrlLine[] {
  const seen = new Set<string>();
  const out: UrlLine[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const url = raw.trim();
    if (!url || seen.has(url)) continue;
    seen.add(url);
    let problem: string | null = null;
    try {
      const u = new URL(url);
      if (u.protocol !== "http:" && u.protocol !== "https:") problem = "Not an http or https address.";
      else if (!u.hostname.includes(".") && u.hostname !== "localhost") problem = "The address has no host name.";
    } catch {
      problem = /^https?:\/\//i.test(url) ? "Not a complete address." : "Start the address with http:// or https://.";
    }
    out.push({ url, valid: problem === null, problem });
  }
  return out;
}

export type AddResult =
  | { url: string; status: "added" | "already"; id: string }
  | { url: string; status: "error"; message: string };

/** The server's own words when it has some: FastAPI puts them in `detail`. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail)) {
      const msgs = detail.map((d) => (d as { msg?: unknown } | null)?.msg).filter((m): m is string => typeof m === "string");
      if (msgs.length) return msgs.join(" ");
    }
  } catch { /* no JSON body */ }
  return `The API answered ${res.status}.`;
}

async function postPortal(fetchImpl: FetchLike, url: string, timeoutMs: number): Promise<{ id: string } | { error: string }> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetchImpl("/portals", {
      method: "POST", cache: "no-store", signal: ac.signal,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!res.ok) return { error: await errorMessage(res) };
    const parsed = createdIdSchema.safeParse(await res.json().catch(() => null));
    return parsed.success ? { id: parsed.data.id } : { error: "The API answered without a portal id." };
  } catch {
    return { error: "The API did not answer." };
  } finally {
    clearTimeout(timer);
  }
}

/** Ids the server already watches, so a repeat can be told apart from a new portal. Null when the list cannot be read. */
export async function watchedIds(fetchImpl: FetchLike, timeoutMs = TIMEOUT_MS): Promise<Set<string> | null> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetchImpl("/portals", { cache: "no-store", headers: { Accept: "application/json" }, signal: ac.signal });
    if (!res.ok) return null;
    const parsed = contractPortalsSchema.safeParse(await res.json().catch(() => null));
    return parsed.success ? new Set(parsed.data.map((p) => p.id)) : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Posts the addresses one after another, never in parallel. The same address always gets the same
 * id, so an id that was already watched (before this batch, or earlier in it) reads "already".
 */
export async function addPortals(
  fetchImpl: FetchLike,
  urls: string[],
  known: Iterable<string>,
  onResult?: (result: AddResult, index: number) => void,
  timeoutMs = 8000,
): Promise<AddResult[]> {
  const seen = new Set(known);
  const out: AddResult[] = [];
  for (const [index, url] of urls.entries()) {
    const answer = await postPortal(fetchImpl, url, timeoutMs);
    const result: AddResult = "id" in answer
      ? { url, id: answer.id, status: seen.has(answer.id) ? "already" : "added" }
      : { url, status: "error", message: answer.error };
    if ("id" in answer) seen.add(answer.id);
    out.push(result);
    onResult?.(result, index);
  }
  return out;
}
