import { useEffect, useId, useState, type ReactNode } from "react";
import { CirclePlus, Wrench, XCircle } from "lucide-react";
import { eur, relTime, tokens } from "@/data/format";
import { portalHash } from "@/data/hooks";
import type { FleetSummary } from "@/data/view";
import { cn } from "@/lib/utils";
import type { Portal, Run } from "@/types";
import { useWidth } from "./Charts";
import { TowerMark } from "./Header";
import { costBars, costSeries, deliverySeries, fleetEvents, fleetZone, readSeries, type FleetEvent } from "./overview";

const Panel = ({ title, note, children, className }: { title: string; note?: ReactNode; children: ReactNode; className?: string }) => (
  <section aria-label={title} className={cn("card flex min-w-0 flex-col p-5 2xl:p-6", className)}>
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h3 className="text-[1.15rem] font-semibold tracking-tight">{title}</h3>
      {note && <div className="text-sm text-muted-foreground">{note}</div>}
    </div>
    {children}
  </section>
);

const Empty = ({ children }: { children: ReactNode }) => (
  <p className="grid min-h-[6rem] flex-1 place-items-center rounded-xl border border-dashed border-border px-4 py-3 text-center text-secondary-text">{children}</p>
);

/** A wide sparkline that stretches with its tile; the stroke keeps its width. */
function Spark({ values, label }: { values: number[] | null; label: string }) {
  const id = useId();
  if (!values || values.length < 2) return <p className="flex h-12 items-center text-sm text-muted-foreground">{values === null ? "" : "Not enough history for a trend yet"}</p>;
  const max = Math.max(...values, 1), min = Math.min(...values, 0);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${27 - ((v - min) / span) * 23}`);
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label={`${label}: ${values.map((v) => Math.round(v * 100) / 100).join(", ")}`} className="h-12 w-full text-[var(--bar-top)]">
      <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="currentColor" stopOpacity="0.4" /><stop offset="1" stopColor="currentColor" stopOpacity="0" /></linearGradient></defs>
      <polygon points={`0,30 ${pts.join(" ")} 100,30`} fill={`url(#${id})`} />
      <polyline points={pts.join(" ")} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Big({ label, value, unit, prefix, spark, sparkLabel, note }: { label: string; value: string; unit?: string | undefined; prefix?: string | undefined; spark: number[] | null; sparkLabel: string; note?: string | undefined }) {
  return (
    <div className="flex min-w-0 flex-col">
      <dd className="order-1 flex items-baseline gap-x-2 whitespace-nowrap">
        {prefix && <span className="text-base text-muted-foreground">{prefix}</span>}
        <span className="silver tnum text-[clamp(3.2rem,4.5vw,4.9rem)] leading-[0.95] font-semibold tracking-[-0.04em]">{value}</span>
        {unit && <span className="text-[1.25rem] font-medium text-muted-foreground">{unit}</span>}
      </dd>
      <dt className="order-2 mt-2 text-[1.15rem] text-secondary-text">{label}</dt>
      <div className="order-3 mt-3"><Spark values={spark} label={sparkLabel} /></div>
      <p className="order-4 mt-1 min-h-[2.5rem] text-sm leading-snug text-muted-foreground">{note}</p>
    </div>
  );
}

/** Semicircle gauge from 0% to 100% with a needle, like a wall dashboard. */
function Gauge({ rate, passed, failed }: { rate: number | null; passed: number; failed: number }) {
  const id = useId();
  const r = 80, cx = 100, cy = 100, length = Math.PI * r;
  const share = rate ?? 0;
  const angle = Math.PI * (1 - share);
  const nx = cx + Math.cos(angle) * (r - 4), ny = cy - Math.sin(angle) * (r - 4);
  const text = rate === null ? "No finished reads yet" : `${Math.round(share * 100)}% of the last ${passed + failed} finished reads passed: ${passed} passed, ${failed} failed.`;
  return (
    <div className="flex min-w-0 flex-col items-center">
      <svg viewBox="0 0 200 122" role="img" aria-label={text} className="w-full max-w-[19rem]">
        <defs><linearGradient id={id} x1="0" x2="1" y1="0" y2="0"><stop offset="0" stopColor="#6366f1" /><stop offset="1" stopColor="var(--hl-from)" /></linearGradient></defs>
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="var(--inset)" strokeWidth="20" strokeLinecap="round" />
        {rate !== null && <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke={`url(#${id})`} strokeWidth="20" strokeLinecap="round" strokeDasharray={`${Math.max(0.01, share * length)} ${length}`} />}
        {rate !== null && <>
          <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="var(--foreground)" strokeWidth="3.5" strokeLinecap="round" />
          <circle cx={cx} cy={cy} r="7" fill="var(--foreground)" />
        </>}
        <text x={cx - r} y={cy + 19} textAnchor="middle" className="fill-muted-foreground text-[11px]">0%</text>
        <text x={cx + r} y={cy + 19} textAnchor="middle" className="fill-muted-foreground text-[11px]">100%</text>
      </svg>
      <p className="-mt-1 flex items-baseline gap-1">
        <span className="silver tnum text-[clamp(2.6rem,3.6vw,3.8rem)] leading-none font-semibold tracking-[-0.03em]">{rate === null ? "—" : Math.round(share * 100)}</span>
        {rate !== null && <span className="text-[1.4rem] font-medium text-muted-foreground">%</span>}
      </p>
      <p className="mt-1 text-[1.2rem] text-secondary-text">Reads passing</p>
      <p className="text-sm text-muted-foreground">{rate === null ? "No finished reads yet" : `${passed} of ${passed + failed} finished reads, last 30 slots`}</p>
    </div>
  );
}

interface Series { name: string; values: number[]; color: string; dashed?: boolean; fill?: boolean }

/** Lines over read slots, oldest to newest. Series differ by dash as well as colour. */
function LineChart({ series, summary, height = 200 }: { series: Series[]; summary: string; height?: number }) {
  const gid = useId();
  const [ref, W] = useWidth<HTMLDivElement>(640);
  const n = Math.max(...series.map((s) => s.values.length));
  const left = 38, right = 14, top = 14, base = height - 34;
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const ticks = max <= 4 ? Array.from({ length: max + 1 }, (_, i) => i) : [0, Math.round(max / 2), max];
  const x = (i: number) => (n <= 1 ? (left + W - right) / 2 : left + (i / (n - 1)) * (W - left - right));
  const y = (v: number) => base - (v / max) * (base - top);
  return (
    <div ref={ref} className="min-w-0 flex-1">
      <svg viewBox={`0 0 ${W} ${height}`} width={W} height={height} role="img" aria-label={summary} className="block max-w-full">
        <defs>{series.map((s, i) => s.fill && <linearGradient key={s.name} id={`${gid}-${i}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={s.color} stopOpacity="0.32" /><stop offset="1" stopColor={s.color} stopOpacity="0" /></linearGradient>)}</defs>
        {ticks.map((t) => <g key={t}>
          <line x1={left} x2={W - right} y1={y(t)} y2={y(t)} stroke="var(--grid-line)" strokeDasharray={t === 0 ? undefined : "2 6"} />
          <text x={left - 10} y={y(t) + 5} textAnchor="end" className="fill-muted-foreground text-[14px]">{t}</text>
        </g>)}
        {series.map((s, si) => {
          const pts = s.values.map((v, i) => `${x(n - s.values.length + i).toFixed(1)},${y(v).toFixed(1)}`);
          const first = x(n - s.values.length), last = x(n - 1);
          return <g key={s.name}>
            {s.fill && pts.length > 1 && <polygon points={`${first},${base} ${pts.join(" ")} ${last},${base}`} fill={`url(#${gid}-${si})`} />}
            <polyline points={pts.join(" ")} fill="none" stroke={s.color} strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? "7 6" : undefined} />
            {s.values.length <= 16 && s.values.map((v, i) => <circle key={i} cx={x(n - s.values.length + i)} cy={y(v)} r={s.dashed ? 3.5 : 4} fill={s.dashed ? "var(--surface)" : s.color} stroke={s.color} strokeWidth="2" />)}
          </g>;
        })}
        <text x={left} y={height - 8} className="fill-muted-foreground text-[14px]">oldest</text>
        <text x={W - right} y={height - 8} textAnchor="end" className="fill-muted-foreground text-[14px]">newest</text>
        <text x={(left + W - right) / 2} y={height - 8} textAnchor="middle" className="fill-muted-foreground text-[14px]">{n} read slot{n === 1 ? "" : "s"}</text>
      </svg>
    </div>
  );
}

const Key = ({ color, dashed, children }: { color: string; dashed?: boolean; children: ReactNode }) => (
  <span className="inline-flex items-center gap-2"><svg aria-hidden width="26" height="6"><line x1="1" x2="25" y1="3" y2="3" stroke={color} strokeWidth="3" strokeLinecap="round" strokeDasharray={dashed ? "6 5" : undefined} /></svg>{children}</span>
);

const EVENT_ICON = { repair: Wrench, failure: XCircle, attach: CirclePlus };
const PAGE = 3;

/** Recent events, a few per page, advancing by itself like the spotlight and pausing on hover or focus. */
function Events({ events, now, quiet }: { events: FleetEvent[]; now: number; quiet: string }) {
  const pages = Math.max(1, Math.ceil(events.length / PAGE));
  const [page, setPage] = useState(0);
  const [held, setHeld] = useState(false);
  useEffect(() => { if (page >= pages) setPage(0); }, [page, pages]);
  if (!events.length) return <Empty>{quiet}</Empty>;
  const shown = events.slice(page * PAGE, page * PAGE + PAGE);
  return (
    <div className="flex flex-1 flex-col" data-paused={held} onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)} onFocus={() => setHeld(true)} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setHeld(false); }}>
      <ul className="flex flex-1 flex-col divide-y divide-divider" aria-live="off">
        {shown.map((e) => {
          const Icon = EVENT_ICON[e.kind];
          const tone = e.result === null ? "text-integrating bg-integrating-tint" : e.kind === "failure" || e.result === "failed" ? "text-failed bg-failed-tint" : e.kind === "repair" ? "text-serving bg-serving-tint" : "text-integrating bg-integrating-tint";
          return (
            <li key={e.key} className="flex gap-3.5 py-2.5 first:pt-1">
              <span className={cn("mt-0.5 grid size-10 shrink-0 place-items-center rounded-full", tone)}><Icon aria-hidden className="size-5" /></span>
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-[1.05rem] leading-snug font-semibold">
                  <span>{e.title} <a href={portalHash(e.portalId)} className="font-medium text-primary underline-offset-4 hover:underline">{e.host}</a></span>
                  <span className="text-sm font-normal whitespace-nowrap text-muted-foreground">{e.at ? <time dateTime={e.at}>{relTime(e.at, now)}</time> : "Current state"}</span>
                </p>
                <p className="mt-0.5 line-clamp-2 leading-snug text-secondary-text">{e.text}</p>
              </div>
            </li>
          );
        })}
      </ul>
      {pages > 1 && (
        <ol className="mt-3 flex items-center justify-center gap-2" aria-label="Event pages">
          {Array.from({ length: pages }, (_, i) => (
            <li key={i} className="w-9">
              <button type="button" onClick={() => setPage(i)} aria-label={`Show events page ${i + 1} of ${pages}`} aria-current={i === page ? "page" : undefined} className="block w-full cursor-pointer rounded-md py-2">
                <span className="dot-track block"><span className="dot-fill" data-state={i < page ? "done" : i === page ? "active" : "idle"} style={{ ["--slide-ms" as string]: "7000ms" }} onAnimationEnd={i === page ? () => setPage((p) => (p + 1) % pages) : undefined} /></span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function wallClock(now: number, zone: string | null) {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short", ...(zone ? { timeZone: zone } : {}) }).formatToParts(new Date(now));
    const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
    return { time: `${pick("hour")}:${pick("minute")}`, zone: pick("timeZoneName") };
  } catch {
    return { time: new Date(now).toTimeString().slice(0, 5), zone: "" };
  }
}

/** A wall-dashboard section: everything on it is derived from the rows and runs already on screen. */
export function Analytics({ portals, summary, timelines, now, clockNow, eurPerUsd, basic }: {
  portals: Portal[]; summary: FleetSummary; timelines: Record<string, Run[]>; now: number; clockNow: number; eurPerUsd: number | null; basic: boolean;
}) {
  const reads = readSeries(portals);
  const delivery = deliverySeries(portals);
  const bars = costBars(portals);
  const maxEur = Math.max(0, ...bars.map((b) => b.eur ?? 0));
  const costTrend = costSeries(timelines);
  const events = fleetEvents(portals, timelines);
  const zone = fleetZone(portals);
  const clock = wallClock(clockNow, zone);
  const cost = summary.cost;
  const missing = basic ? "Not on the contract routes yet; it arrives with /api/dashboard." : "Not recorded.";
  const readsPerSlot = reads ? reads.passed.map((v, i) => v + (reads.failed[i] ?? 0) + (reads.running[i] ?? 0)) : null;
  return (
    <section id="analytics" aria-labelledby="analytics-h" className="scroll-mt-[5.1rem]">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <p className="eyebrow">Fleet analytics</p>
          <h2 id="analytics-h" className="display mt-2 text-[1.9rem]">The fleet at a glance, <span className="text-muted-foreground">from recorded reads</span></h2>
        </div>
        <p className="text-sm text-muted-foreground">Charts cover each portal's last 30 read slots</p>
      </div>
      <div className="grid gap-4 xl:grid-cols-12">
        <Panel title="Delivery now" className="xl:col-span-8">
          <div className="grid flex-1 items-center gap-x-8 gap-y-8 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1.1fr_minmax(13rem,1fr)]">
            <dl className="contents">
              <Big label="Tenders delivered" value={String(summary.tendersDelivered)} spark={delivery} sparkLabel="Tenders published per read, fleet total" note={delivery === null ? missing : undefined} />
              <Big label="Reads in the last hour" value={summary.readsLastHour === null ? "—" : String(summary.readsLastHour)} spark={readsPerSlot} sparkLabel="Reads per slot, fleet total" note={summary.readsLastHour === null ? missing : undefined} />
              {cost.kind === "known"
                ? <Big label="Model cost to date" prefix={cost.incomplete ? "At least" : undefined} value={eur(cost.eur).replace(" EUR", "")} unit="EUR" spark={costTrend} sparkLabel="Running total of model cost over runs"
                    note={`${tokens(cost.tokens)} tokens${eurPerUsd ? ` · 1 USD = ${eurPerUsd} EUR` : ""}`} />
                : <Big label="Model cost to date" value="—" spark={null} sparkLabel="Model cost" note={missing} />}
            </dl>
            <Gauge rate={reads?.passRate ?? null} passed={reads?.totalPassed ?? 0} failed={reads?.totalFailed ?? 0} />
          </div>
        </Panel>
        <Panel title="Recent events" note="Repairs, failures, attaches" className="xl:col-span-4">
          <Events events={events} now={now} quiet={basic ? "No repair or failed read is recorded. The contract routes do not say which read was an attach." : "Nothing to report: no repair, failed read or attach is recorded."} />
        </Panel>
        <Panel title="Passed and failed reads" className="xl:col-span-4" note={reads && reads.passRate !== null && <span className="flex flex-wrap gap-x-4 gap-y-1"><Key color="var(--serving)">Passed {reads.totalPassed}</Key><Key color="var(--failed)" dashed>Failed {reads.totalFailed}</Key></span>}>
          {!reads ? <Empty>{missing}</Empty> : reads.passed.length === 0 ? <Empty>No reads yet.</Empty> : reads.passRate === null ? <Empty>No read has finished yet{reads.totalRunning ? `; ${reads.totalRunning} running` : ""}.</Empty>
            : <LineChart summary={`Passed reads per slot: ${reads.passed.join(", ")}. Failed reads per slot: ${reads.failed.join(", ")}.`}
                series={[{ name: "Passed", values: reads.passed, color: "var(--serving)", fill: true }, { name: "Failed", values: reads.failed, color: "var(--failed)", dashed: true }]} />}
        </Panel>
        <Panel title="Delivery trend" note="Tenders published per read, all portals" className="xl:col-span-4">
          {!delivery ? <Empty>{missing}</Empty> : delivery.length === 0 ? <Empty>Nothing published yet.</Empty>
            : <LineChart summary={`Tenders published per read slot, summed over portals: ${delivery.join(", ")}.`} series={[{ name: "Published", values: delivery, color: "var(--bar-top)", fill: true }]} />}
        </Panel>
        <Panel title="Model cost per portal" note={eurPerUsd ? "LLM usage only" : undefined} className="xl:col-span-4">
          {bars.every((b) => b.eur === null) ? <Empty>{portals.length ? missing : "No portals yet."}</Empty> : (
            <ul className="flex flex-1 flex-col justify-center gap-[0.45rem]">
              {bars.slice(0, 7).map((b) => (
                <li key={b.id} className="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)_5.6rem] items-center gap-3">
                  <a href={portalHash(b.id)} className="truncate text-[0.98rem] font-medium underline-offset-4 hover:underline" title={b.host}>{b.host}</a>
                  <span aria-hidden className="h-3.5 rounded-full bg-inset">{b.eur !== null && b.eur > 0 && <span className="bar-llm block h-full rounded-full" style={{ width: `${Math.max(2, (b.eur / (maxEur || 1)) * 100)}%` }} />}</span>
                  <span className="tnum text-right text-[0.98rem] font-semibold whitespace-nowrap">{b.eur === null ? <span className="font-normal text-muted-foreground">Not recorded</span> : eur(b.eur)}</span>
                </li>
              ))}
              {bars.length > 7 && <li className="text-sm text-muted-foreground">and {bars.length - 7} more in the ledger, each at or below {eur(bars[6]?.eur ?? 0)}</li>}
            </ul>
          )}
        </Panel>
      </div>
      <footer className="glass mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-2xl px-5 py-3">
        <p className="flex items-center gap-3 text-[1.25rem] font-semibold tracking-tight"><TowerMark className="size-8 shrink-0" />Watchtower <span aria-hidden className="text-muted-foreground">·</span> <span className="font-normal text-secondary-text">Delivery Ledger</span></p>
        <p className="tnum flex items-baseline gap-2 text-[1.9rem] leading-none font-light tracking-tight" title={zone ? `Portal time, ${zone}` : "This device's time; no portal zone is recorded"}>
          <time>{clock.time}</time><span className="text-base font-normal text-muted-foreground">{clock.zone}</span>
        </p>
      </footer>
    </section>
  );
}
