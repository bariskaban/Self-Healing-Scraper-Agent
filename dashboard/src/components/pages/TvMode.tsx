import { Suspense, lazy, useEffect, useId, useState, type ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { costText, duration, eur, hostname, runCost, tokens } from "@/data/format";
import { useNow } from "@/data/hooks";
import { STATE_META, STATE_ORDER, fleetSummary, sortPortals } from "@/data/view";
import { hasActiveRepair } from "@/components/ledger/evidence";
import { TowerMark } from "@/components/ledger/Header";
import { clock, fleetSentence, stillServing } from "@/components/ledger/overview";
import { StateBadge, idx } from "@/components/ledger/primitives";
import { repairSlides } from "@/components/ledger/Spotlight";
import { cn } from "@/lib/utils";
import type { PortalState } from "@/types";
import { dataNow, knownTimelines, useFleet, type FleetData } from "./pagesData";
import { isEditable } from "./nav";
import { TV_SLIDES, TV_SLIDE_MS, costSeries, deliveredSeries, pickRepair, readBuckets, readHealth, readsHourSeries, useTvRotation, type ReadBuckets } from "./tv";

// The health board is the only user of the chart library: it loads with TV mode, not with the first page.
const HealthBoard = lazy(() => import("@/components/tv/HealthBoard").then((m) => ({ default: m.HealthBoard })));

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const hhmm = (t: number) => new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(t));

const LABEL = "text-[clamp(0.95rem,1.25vw,1.7rem)] font-medium text-muted-foreground";
const CAPTION = "text-[clamp(0.85rem,1.05vw,1.4rem)] leading-snug text-secondary-text";
const EYEBROW = "eyebrow !text-[clamp(0.75rem,0.95vw,1.25rem)] flex items-center gap-3";

/** A wide sparkline for a stat panel. The label says what the line is and gives its first and last value. */
function Spark({ values, label }: { values: number[]; label: string }) {
  const id = useId();
  if (values.length < 2) return <p className={cn(CAPTION, "text-muted-foreground")}>No trend yet</p>;
  const w = 240, h = 48;
  const max = Math.max(...values, 1e-9);
  const xy = values.map((v, i) => [(i / (values.length - 1)) * (w - 8) + 4, h - 5 - (v / max) * (h - 12)] as const);
  const line = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const last = xy[xy.length - 1] ?? [0, 0];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label} className="block h-auto w-full text-[var(--bar-top)]">
      <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="currentColor" stopOpacity="0.32" /><stop offset="1" stopColor="currentColor" stopOpacity="0" /></linearGradient></defs>
      <polygon points={`4,${h} ${line} ${w - 4},${h}`} fill={`url(#${id})`} />
      <polyline points={line} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="3.5" fill="currentColor" stroke="var(--surface)" strokeWidth="2" />
    </svg>
  );
}

function TvStat({ label, value, unit, prefix, caption, children, i }: { label: string; value: string; unit?: string; prefix?: string | undefined; caption: ReactNode; children?: ReactNode; i: number }) {
  return (
    <div className="card flex min-w-0 flex-col overflow-hidden p-[clamp(1rem,1.5vw,2.2rem)]" style={idx(i)}>
      <dt className={LABEL}>{label}</dt>
      <dd className="flex flex-1 flex-col">
        <p className="mt-[1.2vh] flex flex-wrap items-baseline gap-x-[0.6vw]">
          {prefix && <span className={LABEL}>{prefix}</span>}
          <span className="silver tnum text-[clamp(3rem,7.2vw,9.5rem)] leading-[0.95] font-semibold tracking-[-0.04em]">{value}</span>
          {unit && <span className="text-[clamp(1rem,1.6vw,2.2rem)] font-medium text-muted-foreground">{unit}</span>}
        </p>
        <div className="mt-[1.6vh]">{children}</div>
        <p className={cn(CAPTION, "mt-auto pt-[1.2vh]")}>{caption}</p>
      </dd>
    </div>
  );
}

const STATE_BG: Record<PortalState, string> = { serving: "bg-serving", healing: "bg-healing", integrating: "bg-integrating", failed: "bg-failed" };

/** One segment per portal state, as wide as its share of the fleet. The caption names every count. */
function StateBar({ counts, total }: { counts: Record<PortalState, number>; total: number }) {
  const order = [...STATE_ORDER].reverse();
  const text = order.filter((s) => counts[s] > 0).map((s) => `${counts[s]} ${STATE_META[s].label.toLowerCase()}`).join(", ");
  return (
    <div role="img" aria-label={`Portals by state: ${text}.`} className="flex h-[clamp(0.6rem,1.1vh,1rem)] w-full gap-[2px]">
      {order.filter((s) => counts[s] > 0).map((s) => <span key={s} className={cn("rounded-full", STATE_BG[s])} style={{ width: `${(counts[s] / total) * 100}%` }} />)}
    </div>
  );
}

function FleetSlide({ data, now }: { data: FleetData; now: number }) {
  const d = data.dashboard;
  const portals = d.portals;
  const summary = fleetSummary(d);
  const { total, parts } = fleetSentence(portals);
  const tl = knownTimelines(data.timelines);
  const hasTl = Object.keys(tl).length > 0;
  const delivered = deliveredSeries(tl), readsHour = readsHourSeries(tl, now), spend = costSeries(tl);
  const reads: number | null = summary.readsLastHour;
  const cost = summary.cost;
  const delivering = portals.filter((p) => p.tenderCount > 0).length;
  const others = [...STATE_ORDER].reverse().filter((s) => s !== "serving" && summary.counts[s] > 0).map((s) => `${summary.counts[s]} ${STATE_META[s].label.toLowerCase()}`);
  const repairing = sortPortals(portals).find(hasActiveRepair);
  const sub = repairing && repairing.tenderCount > 0
    ? `${hostname(repairing.url)} is still serving ${plural(repairing.tenderCount, "tender")} from its last correct read while the agent repairs it.`
    : `${plural(summary.tendersDelivered, "tender")} available across the fleet.`;
  if (total === 0) return <Empty label="Fleet status" title="No portal is attached yet.">Add a portal on the overview; it appears here as soon as it is being learned.</Empty>;
  return (
    <div className="flex h-full flex-col gap-[2.5vh]">
      <div>
        <p className={EYEBROW}>Fleet status</p>
        <h2 className="display mt-[1.6vh] text-[clamp(2.1rem,5vw,6.4rem)]">
          <span className="whitespace-nowrap">{plural(total, "portal")}.</span>{" "}
          {parts.map((part, i) => (
            <span key={`${part.state}-${part.text}`}><span className="whitespace-nowrap"><span className={part.highlight ? "highlight font-normal" : undefined}>{part.count} {part.text}</span>{i < parts.length - 1 ? "," : "."}</span>{" "}</span>
          ))}
        </h2>
        <p className="mt-[2.2vh] max-w-[70vw] text-[clamp(1.05rem,1.7vw,2.3rem)] leading-snug font-light text-secondary-text">{sub}</p>
      </div>
      <dl aria-label="Fleet numbers" className="mt-auto grid grid-cols-2 gap-[clamp(0.75rem,1.2vw,1.75rem)] xl:grid-cols-4">
        <TvStat i={0} label="Tenders delivered" value={String(summary.tendersDelivered)} caption={`Available now from ${plural(delivering, "portal")}.`}>
          {hasTl ? <Spark values={delivered} label={`Fleet total of published tenders after each publishing read, from ${delivered[0] ?? 0} to ${delivered[delivered.length - 1] ?? 0}.`} /> : null}
        </TvStat>
        <TvStat i={1} label="Portals serving" value={String(summary.counts.serving)} unit={`of ${total}`} caption={others.length ? `${others.join(", ")}.` : "Every portal is serving."}>
          <StateBar counts={summary.counts} total={total} />
        </TvStat>
        <TvStat i={2} label="Reads in the last hour" value={reads === null ? "—" : String(reads)} caption={reads === null ? "Not recorded." : "Read runs started, repairs excluded."}>
          {hasTl ? <Spark values={readsHour} label={`Reads started per 5 minutes over the last hour: ${readsHour.join(", ")}.`} /> : null}
        </TvStat>
        {cost.kind === "known"
          ? <TvStat i={3} label="Model cost to date" prefix={cost.incomplete ? "At least" : undefined} value={eur(cost.eur).replace(" EUR", "")} unit="EUR"
              caption={`${tokens(cost.tokens)} tokens${cost.incomplete ? ", incomplete usage" : ""}. Model usage only${d.eurPerUsd ? `, 1\u00a0USD\u00a0=\u00a0${d.eurPerUsd}\u00a0EUR fixed` : ""}.`}>
              {hasTl ? <Spark values={spend} label={`Running total of recorded model cost, ${spend.length} runs, ending at ${eur(spend[spend.length - 1] ?? 0)}.`} /> : null}
            </TvStat>
          : <TvStat i={3} label="Model cost to date" value="—" caption="Not recorded." />}
      </dl>
    </div>
  );
}

function Empty({ label, title, children }: { label: string; title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full flex-col justify-center">
      <p className={EYEBROW}>{label}</p>
      <p className="display mt-[1.6vh] text-[clamp(2.1rem,5vw,6.4rem)]">{title}</p>
      {children && <p className="mt-[2vh] max-w-[60rem] text-[clamp(1rem,1.5vw,2rem)] leading-relaxed text-secondary-text">{children}</p>}
    </div>
  );
}

function RepairSlide({ data }: { data: FleetData }) {
  const pick = pickRepair(data.dashboard.portals, knownTimelines(data.timelines));
  if (!pick) {
    return <Empty label="Repair" title="No repair recorded.">No portal has a repair in flight, and the recorded runs hold no finished repair. When a portal's layout changes, the repair shows here: what broke, what the agent did, what changed and how it was verified.</Empty>;
  }
  const { portal, run, timeline, live } = pick;
  const stops = repairSlides(run, timeline, portal.timezone);
  const cost = runCost(run);
  const span = run.finishedAt === null ? null : Date.parse(run.finishedAt) - Date.parse(run.startedAt);
  return (
    <div className="flex h-full flex-col gap-[2.2vh]">
      <div className="flex flex-wrap items-end justify-between gap-x-[3vw] gap-y-[1.5vh]">
        <div className="min-w-0">
          <p className={EYEBROW}>{live && <span aria-hidden className="live-dot text-healing" />}{live ? "Live repair" : "Latest repair"}</p>
          <h2 className="display mt-[1.2vh] text-[clamp(2rem,4.4vw,5.6rem)] break-all">{hostname(portal.url)}</h2>
          <p className="mt-[1.2vh] flex flex-wrap items-center gap-x-4 gap-y-2 text-[clamp(0.95rem,1.25vw,1.7rem)] text-secondary-text">
            <StateBadge state={portal.state} portal={portal} note={stillServing(portal)} className="!text-[1em]" />
            <span>{run.finishedAt === null ? `Started ${clock(run.startedAt, portal.timezone)}, not finished` : `${clock(run.startedAt, portal.timezone)} to ${clock(run.finishedAt, portal.timezone)}${span !== null && span >= 0 ? `, ${duration(span)}` : ""}`}</span>
          </p>
        </div>
        <div className="text-right">
          <p className={LABEL}>Model cost of this repair</p>
          {cost.kind === "known"
            ? <><p className="mt-[0.6vh] flex items-baseline justify-end gap-x-[0.5vw]"><span className="silver tnum text-[clamp(2.2rem,4.6vw,6rem)] leading-none font-semibold tracking-[-0.035em]">{eur(cost.eur).replace(" EUR", "")}</span><span className="text-[clamp(1rem,1.5vw,2rem)] font-medium text-muted-foreground">EUR</span></p>
                <p className={cn(CAPTION, "mt-[0.6vh]")}>{tokens(cost.tokens)} tokens{cost.running ? " so far" : ""}</p></>
            : <p className="mt-[0.6vh] text-[clamp(1.4rem,2.4vw,3.2rem)] font-light text-secondary-text">{costText(cost)}</p>}
        </div>
      </div>
      <ol aria-label="Repair, step by step" className="grid min-h-0 flex-1 grid-cols-1 gap-[clamp(0.75rem,1.1vw,1.6rem)] sm:grid-cols-2 xl:grid-cols-4">
        {stops.map((s, i) => (
          <li key={s.label} className="card relative flex min-h-0 flex-col p-[clamp(1rem,1.4vw,2rem)]" style={idx(i)}>
            {i < stops.length - 1 && <ArrowRight aria-hidden className="absolute top-[clamp(1.2rem,1.7vw,2.4rem)] -right-[clamp(0.9rem,1.25vw,1.75rem)] z-10 hidden size-[clamp(1rem,1.4vw,1.9rem)] rounded-full bg-background text-muted-foreground xl:block" />}
            <p className="flex items-center gap-[0.7vw]">
              <span className={cn("grid size-[clamp(2.2rem,2.9vw,3.8rem)] shrink-0 place-items-center rounded-full", s.tone)}><s.Icon aria-hidden className="size-[50%]" /></span>
              <span className="text-[clamp(0.8rem,1.05vw,1.4rem)] font-semibold tracking-[0.16em] uppercase">{String(i + 1).padStart(2, "0")} · {s.label}</span>
            </p>
            <p className={cn(CAPTION, "mt-[1.4vh] text-muted-foreground")}>{s.meta}</p>
            <p className="mt-[1.6vh] line-clamp-[7] text-[clamp(1.15rem,1.85vw,2.6rem)] leading-[1.3] font-light tracking-[-0.01em]">{s.text}</p>
            {s.tags.length > 0 && <ul className="mt-auto flex flex-wrap gap-2 pt-[1.4vh]">{s.tags.slice(0, 3).map((t) => <li key={t} className="chip chip-plain !text-[clamp(0.72rem,0.9vw,1.15rem)] text-secondary-text">{t}</li>)}</ul>}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Share of passing reads on a half circle from 0 to 100 %. The number is the reading; the arc is its picture. */
function Gauge({ share }: { share: number | null }) {
  const id = useId();
  const r = 92, len = Math.PI * r;
  const arc = `M 18 112 A ${r} ${r} 0 0 1 202 112`;
  const pct = share === null ? null : Math.round(share * 100);
  return (
    <div className="relative mx-auto w-full max-w-[min(100%,62vh)]">
      <svg viewBox="0 0 220 128" role="img" aria-label={pct === null ? "No finished reads recorded." : `${pct} percent of finished reads passed.`} className="block h-auto w-full">
        <defs><linearGradient id={id} x1="0" x2="1" y1="0" y2="0"><stop offset="0" stopColor="#6366f1" /><stop offset="1" stopColor="var(--bar-top)" /></linearGradient></defs>
        <path d={arc} fill="none" stroke="var(--inset)" strokeWidth="16" strokeLinecap="round" />
        {share !== null && share > 0 && <path d={arc} fill="none" stroke={`url(#${id})`} strokeWidth="16" strokeLinecap="round" strokeDasharray={`${(len * share).toFixed(2)} ${(len + 20).toFixed(2)}`} />}
        <text x="18" y="127" textAnchor="middle" className="fill-muted-foreground text-[9px]">0%</text>
        <text x="202" y="127" textAnchor="middle" className="fill-muted-foreground text-[9px]">100%</text>
      </svg>
      <p aria-hidden className="absolute inset-x-0 bottom-[4%] text-center">
        <span className="silver tnum text-[clamp(3rem,7vw,9rem)] leading-none font-semibold tracking-[-0.04em]">{pct === null ? "—" : pct}</span>
        {pct !== null && <span className="text-[clamp(1.2rem,2.2vw,3rem)] font-medium text-muted-foreground">%</span>}
      </p>
    </div>
  );
}

const stepWord = (ms: number) => (ms < 3_600_000 ? `${ms / 60_000} min` : ms < 86_400_000 ? `${ms / 3_600_000} h` : "day");

/** Passed and failed reads per time bucket: two lines on one count axis, told apart by colour, dash and marker. */
function ReadsChart({ series }: { series: ReadBuckets }) {
  const { buckets, stepMs } = series;
  const W = 720, H = 330, left = 44, right = 118, top = 18, base = 276;
  const max = Math.max(1, ...buckets.map((b) => Math.max(b.passed, b.failed)));
  const x = (i: number) => (buckets.length === 1 ? (left + W - right) / 2 : left + (i / (buckets.length - 1)) * (W - left - right));
  const y = (v: number) => base - (v / max) * (base - top);
  const ticks = max <= 5 ? Array.from({ length: max + 1 }, (_, i) => i) : [0, Math.round(max / 2), max];
  const every = Math.max(1, Math.ceil(buckets.length / 6));
  const points = (key: "passed" | "failed") => buckets.map((b, i) => `${x(i).toFixed(1)},${y(b[key]).toFixed(1)}`).join(" ");
  const last = buckets[buckets.length - 1] ?? { t: 0, passed: 0, failed: 0 };
  let yp = y(last.passed), yf = y(last.failed);
  if (Math.abs(yp - yf) < 20) { const mid = (yp + yf) / 2, up = last.passed >= last.failed ? -10 : 10; yp = mid + up; yf = mid - up; }
  const summary = buckets.map((b) => `${hhmm(b.t)}: ${b.passed} passed, ${b.failed} failed`).join("; ");
  return (
    <figure className="flex min-h-0 flex-1 flex-col">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Finished reads per ${stepWord(stepMs)}. ${summary}.`} className="min-h-0 w-full flex-1">
        {ticks.map((t) => <g key={t}>
          <line x1={left} x2={W - right} y1={y(t)} y2={y(t)} stroke="var(--grid-line)" strokeDasharray={t === 0 ? undefined : "2 5"} />
          <text x={left - 10} y={y(t) + 5} textAnchor="end" className="fill-muted-foreground text-[14px]">{t}</text>
        </g>)}
        {buckets.map((b, i) => i % every === 0 && <text key={b.t} x={x(i)} y={base + 26} textAnchor="middle" className="fill-muted-foreground text-[14px]">{hhmm(b.t)}</text>)}
        <polyline points={points("passed")} fill="none" stroke="var(--serving)" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
        <polyline points={points("failed")} fill="none" stroke="var(--failed)" strokeWidth="2.5" strokeLinejoin="round" strokeDasharray="7 6" />
        {buckets.map((b, i) => <g key={b.t}>
          <circle cx={x(i)} cy={y(b.passed)} r="4.5" fill="var(--serving)" stroke="var(--surface)" strokeWidth="2" />
          <rect x={x(i) - 4} y={y(b.failed) - 4} width="8" height="8" rx="1.5" fill="var(--failed)" stroke="var(--surface)" strokeWidth="2" transform={`rotate(45 ${x(i)} ${y(b.failed)})`} />
        </g>)}
        <text x={W - right + 16} y={yp + 5} className="fill-foreground text-[15px] font-semibold">Passed {last.passed}</text>
        <text x={W - right + 16} y={yf + 5} className="fill-foreground text-[15px] font-semibold">Failed {last.failed}</text>
      </svg>
      <figcaption className={cn(CAPTION, "mt-[1vh] flex flex-wrap gap-x-[2vw] gap-y-1")}>
        <span className="inline-flex items-center gap-2"><svg aria-hidden width="30" height="10"><line x1="0" x2="30" y1="5" y2="5" stroke="var(--serving)" strokeWidth="2.5" /><circle cx="15" cy="5" r="4" fill="var(--serving)" /></svg>Passed reads</span>
        <span className="inline-flex items-center gap-2"><svg aria-hidden width="30" height="10"><line x1="0" x2="30" y1="5" y2="5" stroke="var(--failed)" strokeWidth="2.5" strokeDasharray="7 6" /><rect x="11.5" y="1.5" width="7" height="7" fill="var(--failed)" transform="rotate(45 15 5)" /></svg>Failed reads</span>
        <span className="text-muted-foreground">Per {stepWord(stepMs)}, by start time, browser clock.</span>
      </figcaption>
    </figure>
  );
}

function HealthSlide({ data, now }: { data: FleetData; now: number }) {
  const portals = data.dashboard.portals;
  const health = readHealth(portals);
  const tl = knownTimelines(data.timelines);
  const series = readBuckets(tl, now);
  const finished = health.passed + health.failed;
  const missing = portals.length - Object.keys(tl).length;
  return (
    <div className="flex h-full flex-col gap-[2.2vh]">
      <div>
        <p className={EYEBROW}>Read health</p>
        <h2 className="display mt-[1.2vh] text-[clamp(1.9rem,3.6vw,4.6rem)]">
          {health.share === null ? "No finished reads yet." : <><span className="highlight font-normal">{health.passed} of {finished}</span> recent reads passed every check.</>}
        </h2>
      </div>
      <div className="grid min-h-0 flex-1 gap-[clamp(0.75rem,1.2vw,1.75rem)] xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <section aria-label="Share of passing reads" className="card flex min-h-0 flex-col justify-between p-[clamp(1rem,1.5vw,2.2rem)]">
          <p className={LABEL}>Share of passing reads</p>
          <Gauge share={health.share} />
          <p className={CAPTION}>
            {health.share === null ? "No finished reads recorded." : `${health.passed} passed, ${health.failed} failed${health.running ? `, ${health.running} running` : ""}.`} Each portal's last 30 reads at most; a failed read publishes nothing, the last correct tenders stay available.
          </p>
        </section>
        <section aria-label="Passed and failed reads over time" className="card flex min-h-0 flex-col p-[clamp(1rem,1.5vw,2.2rem)]">
          <p className={LABEL}>Passed and failed reads over time</p>
          {series ? <ReadsChart series={series} /> : <p className="my-auto text-[clamp(1.1rem,1.7vw,2.2rem)] font-light text-secondary-text">Not recorded: no finished read is in the run timelines.</p>}
          {series && missing > 0 && <p className={cn(CAPTION, "mt-1 text-muted-foreground")}>Timelines read for {portals.length - missing} of {plural(portals.length, "portal")}.</p>}
        </section>
      </div>
    </div>
  );
}

/**
 * Full-screen, passive wallboard. Three slides rotate every 12 s (Fleet, Repair, Health); under
 * reduced motion they do not rotate and stand one under the other. No controls: Escape or T leaves.
 */
export function TvMode({ onLeave }: { onLeave: () => void }) {
  const fleet = useFleet(true, false, 10_000);
  const { index, stacked, paused, epoch, go, next, prev, toggle } = useTvRotation(TV_SLIDES.length);
  const wall = useNow(true);
  const data = fleet.data;
  const now = dataNow(data, wall);

  // Keys: Right or Space next, Left previous, 1-9 jump, P pause. Escape and T are the router's.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || isEditable(e.target)) return;
      if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
      else if (e.key === "p" || e.key === "P") { e.preventDefault(); toggle(); }
      else if (/^[1-9]$/.test(e.key)) { e.preventDefault(); go(Number(e.key) - 1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, prev, toggle, go]);

  // Ask for the browser's full screen; it is allowed only right after a key press or click, so a
  // refusal is normal and ignored. Leaving the browser's full screen leaves TV mode too.
  useEffect(() => {
    let entered = !!document.fullscreenElement;
    try { void Promise.resolve(document.documentElement.requestFullscreen?.()).catch(() => { /* not allowed now */ }); } catch { /* unsupported */ }
    const on = () => { if (document.fullscreenElement) entered = true; else if (entered) onLeave(); };
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, [onLeave]);

  const slides = data ? [<Suspense key="b" fallback={null}><HealthBoard portals={data.dashboard.portals} summary={fleetSummary(data.dashboard)} basic={data.basic} /></Suspense>, <FleetSlide key="f" data={data} now={now} />, <RepairSlide key="r" data={data} />, <HealthSlide key="h" data={data} now={now} />] : [];
  const pad = "px-[clamp(1rem,3.2vw,5rem)]";
  return (
    <div className={cn("relative isolate flex flex-col bg-background", stacked ? "min-h-dvh" : "h-dvh overflow-hidden")}>
      <div className="glow-field" aria-hidden><div className="glow glow-1" /><div className="glow glow-2" /><div className="glow glow-3" /></div>
      <h1 className="sr-only">Watchtower TV mode</h1>
      <p className="sr-only">Wallboard. Right arrow or Space: next slide. Left arrow: previous. 1 to 4: jump. P: pause. Escape: back to Portals.</p>
      <main className={cn("flex min-h-0 flex-1 flex-col pt-[clamp(1rem,3.4vh,3rem)]", pad)}>
        {!data ? (
          <Empty label="Watchtower" title="Reading the fleet…" />
        ) : stacked ? (
          <div className="flex flex-col gap-[clamp(3rem,9vh,7rem)] pb-[4vh]">
            {slides.map((s, i) => <section key={TV_SLIDES[i]} aria-label={TV_SLIDES[i]}>{s}</section>)}
          </div>
        ) : (
          <div className="slides min-h-0 flex-1">
            {slides.map((s, i) => (
              <section key={TV_SLIDES[i]} role="group" aria-roledescription="slide" aria-label={`${i + 1} of ${slides.length}: ${TV_SLIDES[i]}`} aria-hidden={i !== index} data-active={i === index} className="slide tv-slide min-h-0">{s}</section>
            ))}
          </div>
        )}
      </main>
      <footer className={cn("flex flex-wrap items-center gap-x-[2vw] gap-y-2 py-[clamp(0.75rem,2.2vh,2rem)] text-[clamp(1rem,1.45vw,2rem)]", pad)}>
        <p className="flex items-center gap-[0.8vw]">
          <TowerMark className="size-[1.9em] shrink-0" />
          <span className="font-semibold tracking-tight">Watchtower</span>
          <span className="text-muted-foreground">· Delivery Ledger</span>
        </p>
        {data && (data.source === "live"
          ? <span className="chip chip-plain !text-[0.62em] text-secondary-text"><span aria-hidden className="live-dot text-serving" />{data.basic ? "Live · basic" : "Live"}</span>
          : <span className="chip chip-plain !text-[0.62em] font-semibold">Demo data · snapshot {hhmm(Date.parse(data.dashboard.asOf))}</span>)}
        <span className="text-[0.55em] text-muted-foreground">{stacked ? "Esc: exit" : `← → Space: slide · 1-${TV_SLIDES.length}: jump · P: ${paused ? "resume" : "pause"} · Esc: exit`}</span>
        {!stacked && data && (
          <ol className="ml-auto flex items-center gap-2">
            {TV_SLIDES.map((name, i) => (
              <li key={name} className="flex">
                <button type="button" className="tv-dot" data-active={i === index} data-paused={paused} onClick={() => go(i)} aria-label={`Slide ${i + 1}: ${name}`} aria-current={i === index ? "true" : undefined} title={name}>
                  {i === index && <span key={`${index}-${epoch}`} className="tv-dot-fill" style={{ ["--slide-ms" as string]: `${TV_SLIDE_MS}ms` }} />}
                </button>
              </li>
            ))}
          </ol>
        )}
        {!stacked && paused && <span className="text-[0.62em] font-semibold text-healing">Paused</span>}
        {!stacked && data && <p className="sr-only">Slide {index + 1} of {TV_SLIDES.length}: {TV_SLIDES[index]}</p>}
        <time dateTime={new Date(wall).toISOString()} className={cn("tnum font-medium tracking-tight", (stacked || !data) && "ml-auto")}>
          {hhmm(wall)}<span className="text-muted-foreground">:{String(new Date(wall).getSeconds()).padStart(2, "0")}</span>
        </time>
        <button type="button" className="pill-ghost !text-[0.6em]" onClick={onLeave}>Exit TV</button>
      </footer>
    </div>
  );
}
