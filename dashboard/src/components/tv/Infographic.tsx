import type { ReactNode } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Portal, PortalState } from "@/types";
import { eur, hostname, tokens } from "@/data/format";
import { STATE_META, STATE_ORDER, type FleetSummary } from "@/data/view";
import { costBars, deliverySeries, readSeries } from "@/components/ledger/overview";

/** The light infographic cards of the overview: one clear chart per card, drawn from the same data as the ledger. */

const INDIGO = "#6366f1";
const LAVENDER = "#c4b5fd";
const GREEN = "#22c55e";
const STATE_COLOR: Record<PortalState, string> = { serving: "#22c55e", healing: "#f59e0b", integrating: "#6366f1", failed: "#ef4444" };
const TICK = { fill: "var(--muted-text)", fontSize: 13 };
const TOOLTIP = { borderRadius: 12, border: "1px solid var(--border)", background: "var(--raised)", color: "var(--foreground)", fontSize: 13 };

export function InfoCard({ title, note, children, className = "" }: { title: string; note?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`info-card flex min-w-0 flex-col ${className}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-[1.05rem] font-semibold tracking-tight text-foreground">{title}</h3>
        {note && <p className="text-sm text-muted-foreground">{note}</p>}
      </header>
      <div className="mt-4 flex min-h-0 flex-1 flex-col">{children}</div>
    </section>
  );
}

/** One calm sentence on a light placeholder instead of an empty box. */
export const Calm = ({ children }: { children: ReactNode }) => (
  <div className="info-calm flex flex-1 items-center justify-center rounded-2xl px-6 py-8 text-center text-[0.95rem] leading-relaxed text-secondary-text">{children}</div>
);

function MiniBars({ values, color }: { values: number[] | null; color: string }) {
  const shown = (values ?? []).slice(-12);
  if (shown.length < 2) return <div aria-hidden className="flex h-12 items-end gap-1 opacity-40">{[5, 8, 6, 10, 7, 9, 6, 11].map((h, i) => <span key={i} className="w-2 rounded-sm bg-[var(--inset)]" style={{ height: h * 4 }} />)}</div>;
  const max = Math.max(1, ...shown);
  return (
    <div aria-hidden className="flex h-12 items-end gap-1">
      {shown.map((v, i) => <span key={i} className="w-2 rounded-sm" style={{ height: `${Math.max(8, (v / max) * 100)}%`, background: color, opacity: 0.45 + 0.55 * ((i + 1) / shown.length) }} />)}
    </div>
  );
}

function Kpi({ label, value, unit, caption, spark, color }: { label: string; value: string; unit?: string | undefined; caption: string; spark: number[] | null; color: string }) {
  return (
    <div className="info-card flex min-w-0 items-end justify-between gap-4">
      <div className="min-w-0">
        <dt className="text-sm font-medium text-muted-foreground">{label}</dt>
        <dd className="mt-2 flex items-baseline gap-2">
          <span className="tnum text-[clamp(2.1rem,2.6vw,3rem)] leading-none font-semibold tracking-[-0.03em] text-foreground">{value}</span>
          {unit && <span className="text-base font-medium text-muted-foreground">{unit}</span>}
        </dd>
        <p className="mt-2 text-sm leading-snug text-secondary-text">{caption}</p>
      </div>
      <MiniBars values={spark} color={color} />
    </div>
  );
}

export function KpiRow({ portals, summary, basic }: { portals: Portal[]; summary: FleetSummary; basic: boolean }) {
  const missing = basic ? "Arrives with /api/dashboard." : "Not recorded.";
  const reads = readSeries(portals);
  const delivery = deliverySeries(portals);
  const cost = summary.cost;
  const perSlot = reads ? reads.passed.map((v, i) => v + (reads.failed[i] ?? 0) + (reads.running[i] ?? 0)) : null;
  const costs = portals.map((p) => p.usage?.costEur ?? 0).filter((v) => v > 0);
  return (
    <dl aria-label="Fleet numbers" className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
      <Kpi label="Portals serving" value={String(summary.counts.serving)} unit={`of ${portals.length}`} color={GREEN} spark={reads ? reads.passed : null}
        caption={portals.length === 0 ? "No portal is attached yet." : `${summary.counts.healing} repairing, ${summary.counts.integrating} being learned, ${summary.counts.failed} failed.`} />
      <Kpi label="Tenders delivered" value={String(summary.tendersDelivered)} color={INDIGO} spark={delivery}
        caption={`Available now from ${portals.filter((p) => p.tenderCount > 0).length} portal(s).`} />
      <Kpi label="Reads in the last hour" value={summary.readsLastHour === null ? "—" : String(summary.readsLastHour)} color={LAVENDER} spark={perSlot}
        caption={summary.readsLastHour === null ? missing : "Read runs started in the last 60 minutes."} />
      <Kpi label="Model cost" value={cost.kind === "known" ? eur(cost.eur).replace(" EUR", "") : "—"} unit={cost.kind === "known" ? "EUR" : undefined} color={INDIGO} spark={costs.length >= 2 ? costs : null}
        caption={cost.kind === "known" ? `${cost.incomplete ? "At least. " : ""}${tokens(cost.tokens)} tokens, model only.` : missing} />
    </dl>
  );
}

export function DeliveryCard({ portals, basic }: { portals: Portal[]; basic: boolean }) {
  const series = deliverySeries(portals);
  const data = (series ?? []).map((v, i) => ({ read: i + 1, tenders: v }));
  return (
    <InfoCard title="Delivery" note="Tenders published per read, fleet-wide" className="xl:col-span-2">
      {data.length < 2
        ? <Calm>{basic ? "Published counts arrive with the /api/dashboard route." : data.length === 1 ? `One read has published so far: ${data[0]!.tenders} tenders. The curve starts with the second read.` : "No read has published tenders yet. The curve starts with the first one."}</Calm>
        : (
          <div className="h-[var(--chart-h,260px)]" role="img" aria-label={`Tenders published per read over the last ${data.length} reads, from ${data[0]!.tenders} to ${data[data.length - 1]!.tenders}.`}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
                <defs><linearGradient id="delivery-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={INDIGO} stopOpacity={0.35} /><stop offset="1" stopColor={INDIGO} stopOpacity={0.02} /></linearGradient></defs>
                <CartesianGrid stroke="var(--grid-line)" vertical={false} />
                <XAxis dataKey="read" tick={TICK} tickLine={false} axisLine={false} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} allowDecimals={false} width={48} />
                <Tooltip contentStyle={TOOLTIP} labelFormatter={(l) => `Read ${l}`} />
                <Area type="monotone" dataKey="tenders" name="Tenders published" stroke={INDIGO} strokeWidth={2.5} fill="url(#delivery-fill)" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
    </InfoCard>
  );
}

export function HealthCard({ portals, basic }: { portals: Portal[]; basic: boolean }) {
  const reads = readSeries(portals);
  const rate = reads?.passRate ?? null;
  const data = reads ? [{ name: "Passed", value: reads.totalPassed, color: GREEN }, { name: "Failed", value: reads.totalFailed, color: "#ef4444" }] : [];
  return (
    <InfoCard title="Read health" note="Share of reads passing, last 30">
      {rate === null
        ? <Calm>{basic ? "Read results arrive with the /api/dashboard route." : "No read has finished yet. The share appears after the first one."}</Calm>
        : (
          <>
            <div className="relative h-[var(--donut-h,200px)]" role="img" aria-label={`${Math.round(rate * 100)} percent of finished reads passed: ${reads!.totalPassed} passed, ${reads!.totalFailed} failed.`}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data} dataKey="value" innerRadius="68%" outerRadius="94%" startAngle={90} endAngle={-270} stroke="none" isAnimationActive={false}>
                    {data.map((d) => <Cell key={d.name} fill={d.color} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <p className="pointer-events-none absolute inset-0 grid place-items-center text-[2.4rem] font-semibold tracking-tight text-foreground tnum">{Math.round(rate * 100)}%</p>
            </div>
            <p className="mt-3 flex flex-wrap justify-center gap-x-5 gap-y-1 text-sm text-secondary-text">
              <span><span aria-hidden className="mr-1.5 inline-block size-2.5 rounded-full" style={{ background: GREEN }} />{reads!.totalPassed} passed</span>
              <span><span aria-hidden className="mr-1.5 inline-block size-2.5 rounded-full bg-[#ef4444]" />{reads!.totalFailed} failed</span>
            </p>
          </>
        )}
    </InfoCard>
  );
}

export function StatesCard({ summary, total }: { summary: FleetSummary; total: number }) {
  const data = STATE_ORDER.map((s) => ({ name: STATE_META[s].label, value: summary.counts[s], color: STATE_COLOR[s] })).filter((d) => d.value > 0);
  return (
    <InfoCard title="Portals by state" note={`${total} in all`}>
      {total === 0 ? <Calm>No portal yet. Add one with the purple button.</Calm> : (
        <>
          <div className="h-[var(--donut-h,200px)]" role="img" aria-label={`Portals by state: ${data.map((d) => `${d.value} ${d.name.toLowerCase()}`).join(", ")}.`}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={data} dataKey="value" outerRadius="94%" stroke="var(--surface)" strokeWidth={3} isAnimationActive={false}>
                  {data.map((d) => <Cell key={d.name} fill={d.color} />)}
                </Pie>
                <Tooltip contentStyle={TOOLTIP} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-3 flex flex-wrap justify-center gap-x-5 gap-y-1 text-sm text-secondary-text">
            {data.map((d) => <span key={d.name}><span aria-hidden className="mr-1.5 inline-block size-2.5 rounded-full" style={{ background: d.color }} />{d.value} {d.name.toLowerCase()}</span>)}
          </p>
        </>
      )}
    </InfoCard>
  );
}

export function CostCard({ portals, basic }: { portals: Portal[]; basic: boolean }) {
  const bars = costBars(portals).filter((b) => b.eur !== null).slice(0, 7);
  const max = Math.max(0, ...bars.map((b) => b.eur ?? 0));
  const palette = [INDIGO, "#818cf8", LAVENDER, GREEN, "#86efac", "#f59e0b", "#f9a8d4"];
  return (
    <InfoCard title="Model cost per portal" note="EUR, to date">
      {bars.length === 0 || max === 0
        ? <Calm>{basic ? "Model cost arrives with the /api/dashboard route." : bars.length ? "No portal has spent anything on the model yet." : "No model cost is recorded yet."}</Calm>
        : (
          <ul className="flex flex-1 flex-col justify-center gap-3.5">
            {bars.map((b, i) => (
              <li key={b.id}>
                <p className="flex items-baseline justify-between gap-3 text-sm"><span className="truncate font-medium text-foreground">{b.host}</span><span className="tnum shrink-0 text-secondary-text">{eur(b.eur!)}</span></p>
                <div className="mt-1.5 h-2.5 rounded-full bg-[var(--inset)]"><div className="h-full rounded-full" style={{ width: `${Math.max(2, (b.eur! / max) * 100)}%`, background: palette[i % palette.length] }} /></div>
              </li>
            ))}
          </ul>
        )}
    </InfoCard>
  );
}

export function ReadsCard({ portals, basic }: { portals: Portal[]; basic: boolean }) {
  const rows = portals.filter((p) => p.recentReads && p.recentReads.length > 0).slice(0, 8).map((p) => ({
    host: hostname(p.url).replace(/^www\./, "").slice(0, 16),
    Passed: p.recentReads!.filter((r) => r === "ok").length,
    Failed: p.recentReads!.filter((r) => r === "failed").length,
  }));
  return (
    <InfoCard title="Reads: passed vs failed" note="Per portal, last 30 reads">
      {rows.length === 0
        ? <Calm>{basic ? "Read results arrive with the /api/dashboard route." : "No read is recorded yet. Bars appear after the first read."}</Calm>
        : (
          <div className="h-[var(--chart-h,260px)]" role="img" aria-label={`Reads per portal: ${rows.map((r) => `${r.host} ${r.Passed} passed, ${r.Failed} failed`).join("; ")}.`}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barGap={4}>
                <CartesianGrid stroke="var(--grid-line)" vertical={false} />
                <XAxis dataKey="host" tick={TICK} tickLine={false} axisLine={false} interval={0} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} allowDecimals={false} width={44} />
                <Tooltip contentStyle={TOOLTIP} cursor={{ fill: "var(--inset)" }} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 13, color: "var(--secondary-text)" }} />
                <Bar dataKey="Passed" fill={GREEN} radius={[6, 6, 0, 0]} maxBarSize={26} isAnimationActive={false} />
                <Bar dataKey="Failed" fill={INDIGO} radius={[6, 6, 0, 0]} maxBarSize={26} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
    </InfoCard>
  );
}
