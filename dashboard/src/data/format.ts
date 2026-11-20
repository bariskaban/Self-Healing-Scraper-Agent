import type { Portal, Run, Usage } from "@/types";

export function relTime(iso: string, now: number): string {
  const diff = Math.round((now - Date.parse(iso)) / 1000);
  const future = diff < 0;
  const a = Math.abs(diff);
  let v: string;
  if (a < 60) v = `${a} s`;
  else if (a < 3600) v = `${Math.floor(a / 60)} min`;
  else if (a < 86400) v = `${Math.floor(a / 3600)} h`;
  else v = `${Math.floor(a / 86400)} d`;
  return future ? `in ${v}` : `${v} ago`;
}

/** Original offset as written in the ISO string (e.g. +01:00), or Z. */
export function isoOffset(iso: string): string {
  const m = /([+-]\d{2}:?\d{2}|Z)$/.exec(iso);
  return m?.[1] === "Z" ? "+00:00" : (m?.[1] ?? "");
}

/** Absolute time with numeric offset; in a zone when given, otherwise as written. */
export function absTime(iso: string, timeZone?: string | null): string {
  if (timeZone) {
    try {
      const f = new Intl.DateTimeFormat("en-GB", {
        timeZone,
        year: "numeric", month: "short", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hourCycle: "h23",
        timeZoneName: "longOffset",
      });
      return f.format(new Date(iso)).replace("GMT", "UTC");
    } catch {
      /* unknown zone: fall through */
    }
  }
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!m) return iso;
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${m[3]} ${months[Number(m[2]) - 1]} ${m[1]}, ${m[4]}:${m[5]} UTC${isoOffset(iso)}`;
}

export function localTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  }).format(new Date(iso));
}

export function eur(v: number): string {
  if (v === 0) return "0.00 EUR";
  if (v > 0 && v < 0.005) return "< 0.01 EUR";
  return `${v.toFixed(2)} EUR`;
}

export function tokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0).replace(/\.0$/, "")}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

/** Cached ⊂ input, reasoning ⊂ output: never add subsets. */
export const totalTokens = (u: Usage) => u.inputTokens + u.outputTokens;

export function bytes(n: number | null): string {
  if (n == null) return "size unknown";
  if (n < 1000) return `${n} B`;
  const units = ["kB", "MB", "GB", "TB"];
  let v = n / 1000;
  let i = 0;
  while (v >= 1000 && i < units.length - 1) { v /= 1000; i++; }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
}

export function hostname(url: string): string {
  try { return new URL(url).hostname; } catch { return url; }
}

export type CostSummary =
  | { kind: "none" }
  | { kind: "zero" }
  | { kind: "known"; eur: number; tokens: number; incomplete: boolean; running?: boolean };

export function sumUsage(items: (Usage | null | undefined)[]): CostSummary {
  let eurSum = 0, tok = 0, known = 0, unknown = 0;
  for (const u of items) {
    if (u) { eurSum += u.costEur; tok += totalTokens(u); known++; } else unknown++;
  }
  if (known === 0) return { kind: "none" };
  return { kind: "known", eur: eurSum, tokens: tok, incomplete: unknown > 0 };
}

export function portalCost(p: Portal): CostSummary {
  return p.usage ? { kind: "known", eur: p.usage.costEur, tokens: totalTokens(p.usage), incomplete: false } : { kind: "none" };
}

export function runCost(r: Run): CostSummary {
  const running = r.finishedAt === null;
  if (r.usage) return { kind: "known", eur: r.usage.costEur, tokens: totalTokens(r.usage), incomplete: false, running };
  if (r.modelCalls === 0) return { kind: "zero" };
  return { kind: "none" };
}

export function costText(c: CostSummary): string {
  if (c.kind === "none") return "Not recorded";
  if (c.kind === "zero") return "0.00 EUR · no model call";
  const base = `${eur(c.eur)} · ${tokens(c.tokens)} tokens`;
  if (c.incomplete) return `At least ${base} · incomplete usage`;
  if (c.running) return `${base} so far`;
  return base;
}

export function duration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60000)} min ${Math.round((ms % 60000) / 1000)} s`;
}
