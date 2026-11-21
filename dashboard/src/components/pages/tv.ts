// TV mode helpers: the slide rotation and the series the wallboard draws. Every series is derived
// from the dashboard snapshot or the run timelines; nothing is interpolated or invented.
import { useEffect, useState } from "react";
import { sortPortals } from "@/data/view";
import { hasActiveRepair, repairRuns } from "@/components/ledger/evidence";
import { latestRepair } from "@/components/ledger/overview";
import type { Portal, Run } from "@/types";

export const TV_SLIDE_MS = 12_000;
export const TV_SLIDES = ["Fleet", "Repair", "Health"] as const;

const REDUCED = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia(REDUCED).matches);
  useEffect(() => {
    const mq = window.matchMedia(REDUCED);
    const on = () => setReduced(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

/**
 * The slide on screen. It advances every `ms` and wraps. Under reduced motion there is no rotation at
 * all: `stacked` is true, no timer runs, and the wallboard shows every slide one under the other.
 */
export function useTvRotation(count: number, ms = TV_SLIDE_MS): { index: number; stacked: boolean } {
  const stacked = useReducedMotion();
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (stacked || count < 2) return;
    const t = setInterval(() => setIndex((i) => (i + 1) % count), ms);
    return () => clearInterval(t);
  }, [stacked, count, ms]);
  return { index: stacked ? 0 : index % Math.max(1, count), stacked };
}

export interface RepairPick { portal: Portal; run: Run; timeline: Run[]; live: boolean }

/** The repair in flight when its timeline is known, otherwise the newest finished, passing repair. */
export function pickRepair(portals: Portal[], timelines: Record<string, Run[]>): RepairPick | null {
  const repairing = sortPortals(portals).find(hasActiveRepair);
  const timeline = repairing ? timelines[repairing.id] : undefined;
  if (repairing && timeline) {
    const { active } = repairRuns(repairing, timeline);
    if (active) return { portal: repairing, run: active, timeline, live: true };
  }
  const last = latestRepair(portals, timelines);
  return last ? { portal: last.portal, run: last.run, timeline: timelines[last.portal.id] ?? [], live: false } : null;
}

export interface ReadHealth { passed: number; failed: number; running: number; share: number | null }

/** Share of finished reads that passed, over each portal's recent reads (the last 30 at most). */
export function readHealth(portals: Portal[]): ReadHealth {
  let passed = 0, failed = 0, running = 0;
  for (const p of portals) {
    for (const r of p.recentReads ?? []) {
      if (r === "ok") passed++; else if (r === "failed") failed++; else running++;
    }
  }
  const finished = passed + failed;
  return { passed, failed, running, share: finished ? passed / finished : null };
}

const MIN = 60_000;
const STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440].map((m) => m * MIN);

export interface ReadBuckets { stepMs: number; buckets: { t: number; passed: number; failed: number }[] }

/**
 * Finished reads counted per time bucket, by start time. The bucket width is the smallest step that
 * covers the first recorded read up to `now` in at most `max` buckets; a longer history keeps its
 * newest `max` buckets. Empty buckets are real zeros: no read started in them.
 */
export function readBuckets(timelines: Record<string, Run[]>, now: number, max = 12): ReadBuckets | null {
  const reads = Object.values(timelines).flat()
    .filter((r) => r.kind === "read" && r.result !== null)
    .map((r) => ({ t: Date.parse(r.startedAt), ok: r.result === "ok" }))
    .filter((r) => Number.isFinite(r.t) && r.t <= now);
  if (!reads.length) return null;
  const first = Math.min(...reads.map((r) => r.t));
  const count = (step: number) => Math.floor((now - Math.floor(first / step) * step) / step) + 1;
  const stepMs = STEPS.find((s) => count(s) <= max) ?? (STEPS[STEPS.length - 1] as number);
  const n = Math.min(max, count(stepMs));
  const start = Math.floor(now / stepMs) * stepMs - (n - 1) * stepMs;
  const buckets = Array.from({ length: n }, (_, i) => ({ t: start + i * stepMs, passed: 0, failed: 0 }));
  for (const r of reads) {
    const b = buckets[Math.floor((r.t - start) / stepMs)];
    if (b) { if (r.ok) b.passed++; else b.failed++; }
  }
  return { stepMs, buckets };
}

const tail = (xs: number[], n = 60) => xs.slice(-n);

/** Fleet total of published tenders after each run that published, oldest first. */
export function deliveredSeries(timelines: Record<string, Run[]>): number[] {
  const events = Object.entries(timelines)
    .flatMap(([id, runs]) => runs.filter((r) => r.publishedCount !== undefined).map((r) => ({ id, t: Date.parse(r.startedAt), n: r.publishedCount as number })))
    .sort((a, b) => a.t - b.t);
  const latest = new Map<string, number>();
  const out: number[] = [];
  for (const e of events) {
    latest.set(e.id, e.n);
    let sum = 0;
    for (const v of latest.values()) sum += v;
    out.push(sum);
  }
  return tail(out);
}

/** Read runs started in each of the last twelve 5-minute windows, oldest first. */
export function readsHourSeries(timelines: Record<string, Run[]>, now: number): number[] {
  const step = 5 * MIN;
  const out = Array<number>(12).fill(0);
  for (const r of Object.values(timelines).flat()) {
    if (r.kind !== "read") continue;
    const age = now - Date.parse(r.startedAt);
    if (age < 0 || age >= 12 * step) continue;
    const i = 11 - Math.floor(age / step);
    out[i] = (out[i] ?? 0) + 1;
  }
  return out;
}

/** Running total of recorded model cost in EUR, one point per run that recorded usage, oldest first. */
export function costSeries(timelines: Record<string, Run[]>): number[] {
  const runs = Object.values(timelines).flat().filter((r) => r.usage).sort((a, b) => Date.parse(a.startedAt) - Date.parse(b.startedAt));
  let sum = 0;
  return tail(runs.map((r) => (sum += r.usage?.costEur ?? 0)));
}
