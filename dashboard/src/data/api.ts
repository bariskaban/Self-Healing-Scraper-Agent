import type { ZodType } from "zod";

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly kind: "network" | "status" | "content" | "invalid" | "aborted",
    public readonly status?: number,
  ) {
    super(message);
  }
}

export const TIMEOUT_MS = 4000;

/** Relative, no-store JSON GET with timeout + validation. Never returns an unvalidated body. */
export async function getJson<T>(
  fetchImpl: FetchLike,
  path: string,
  schema: ZodType<T, any, any>,
  outer: AbortSignal,
  timeoutMs = TIMEOUT_MS,
): Promise<T> {
  const ac = new AbortController();
  const onAbort = () => ac.abort();
  outer.addEventListener("abort", onAbort);
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try {
    let res: Response;
    try {
      res = await fetchImpl(path, {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: ac.signal,
      });
    } catch {
      throw new ApiError(`network error for ${path}`, outer.aborted ? "aborted" : "network");
    }
    if (!res.ok) throw new ApiError(`HTTP ${res.status} for ${path}`, "status", res.status);
    const ct = res.headers.get("content-type") ?? "";
    if (!ct.includes("application/json")) throw new ApiError(`not JSON: ${path}`, "content");
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      throw new ApiError(`malformed JSON: ${path}`, outer.aborted ? "aborted" : "content");
    }
    const parsed = schema.safeParse(body);
    if (!parsed.success) throw new ApiError(`invalid payload: ${path}`, "invalid");
    return parsed.data;
  } finally {
    clearTimeout(timer);
    outer.removeEventListener("abort", onAbort);
  }
}

export const portalPath = (id: string, part: "timeline" | "tenders") =>
  `/api/portals/${encodeURIComponent(id)}/${part}`;

/** Only same-origin /files/{id} paths with a safe id are linkable. */
export function safeFileHref(path: string | null): string | null {
  if (!path) return null;
  return /^\/files\/[A-Za-z0-9._~-]+$/.test(path) && !path.includes("..") ? path : null;
}
