import { useId, useState, type ReactNode } from "react";
import { RotateCcw } from "lucide-react";
import { hostname } from "@/data/format";
import { portalHash } from "@/data/hooks";
import { SectionHead, Skel, StateBadge } from "@/components/ledger/primitives";
import { cn } from "@/lib/utils";
import type { Portal } from "@/types";
import { PageHero, PagesShell } from "./PagesShell";
import { useFleet } from "./pagesData";
import { TARGET_PORTALS, costBasis, eurFine, families, observedKnownShare, project, type CostSide, type Family } from "./scaleMath";

const NOT_RECORDED = "Not recorded";
const plural = (n: number, word: string) => `${n} ${n === 1 ? word : word === "family" ? "families" : `${word}s`}`;
const int = (n: number) => n.toLocaleString("en-GB");

function Tag({ kind }: { kind: "assumption" | "data" }) {
  return (
    <span className={cn("inline-block rounded-full px-2 py-0.5 text-[0.68rem] font-semibold tracking-[0.1em] whitespace-nowrap uppercase",
      kind === "assumption" ? "bg-healing-tint text-healing" : "bg-serving-tint text-serving")}>
      {kind === "assumption" ? "Assumption" : "From the data"}
    </span>
  );
}

function UnitCost({ label, side, caption, widest }: { label: string; side: CostSide; caption: ReactNode; widest: number }) {
  const v = side.averageEur;
  return (
    <div className="card flex min-h-[13rem] flex-col p-5 2xl:p-6">
      <dt className="text-sm font-medium text-muted-foreground">{label}</dt>
      <dd className="flex flex-1 flex-col pt-5">
        {v === null
          ? <p className="text-[2rem] leading-none font-light text-secondary-text">{NOT_RECORDED}</p>
          : <p className="flex flex-wrap items-baseline gap-x-2"><span className="silver tnum text-[clamp(2.5rem,3.6vw,3.6rem)] leading-none font-semibold tracking-[-0.035em]">{eurFine(v).replace(" EUR", "")}</span><span className="text-base font-medium text-muted-foreground">EUR</span></p>}
        {v !== null && widest > 0 && <div aria-hidden className="mt-4 h-2 rounded-full bg-inset"><div className="h-2 rounded-full bg-gradient-to-r from-[#6366f1] to-[var(--bar-top)]" style={{ width: `${Math.max(1.5, (v / widest) * 100)}%` }} /></div>}
        <p className="mt-auto pt-4 text-sm leading-snug text-secondary-text">{caption}</p>
      </dd>
    </div>
  );
}

function PortalLine({ p }: { p: Portal }) {
  const how = p.recipeVersion == null ? "No recipe yet" : p.reusedFrom ? `Recipe reused from ${p.reusedFrom}` : "Recipe learned here";
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-divider py-2.5 first:border-t-0">
      <span className="min-w-0">
        <a href={portalHash(p.id)} className="font-medium break-all underline-offset-4 hover:underline">{hostname(p.url)}</a>
        <span className="block text-xs text-muted-foreground">{how}</span>
      </span>
      <span className="flex items-center gap-3">
        <StateBadge state={p.state} className="!py-0.5 !text-xs" />
        <span className={cn("tnum w-24 text-right text-sm", p.usage ? "font-semibold" : "text-muted-foreground")}>{p.usage ? eurFine(p.usage.costEur) : NOT_RECORDED}</span>
      </span>
    </li>
  );
}

function FamilyCard({ title, sentence, portals, costEur, muted }: { title: string; sentence: string; portals: Portal[]; costEur: number | null; muted?: boolean }) {
  return (
    <li className="card flex flex-col p-5 2xl:p-6">
      <p className={cn("text-[1.35rem] leading-tight font-semibold tracking-tight break-words", muted && "font-normal text-secondary-text")}>{title}</p>
      <p className="mt-1.5 text-secondary-text">{sentence}.</p>
      <ul className="mt-4">{portals.map((p) => <PortalLine key={p.id} p={p} />)}</ul>
      <p className="mt-auto flex justify-between gap-4 border-t border-divider pt-3 text-sm text-muted-foreground">
        <span>Model cost to date</span>
        <span className={cn("tnum", costEur !== null && "font-semibold text-foreground")}>{costEur === null ? NOT_RECORDED : eurFine(costEur)}</span>
      </p>
    </li>
  );
}

const familyCard = (f: Family) => <FamilyCard key={f.fingerprint} title={f.fingerprint} sentence={f.sentence} portals={f.portals} costEur={f.costEur} />;

function Row({ kind, term, children }: { kind: "assumption" | "data"; term: string; children: ReactNode }) {
  return (
    <div className="grid gap-x-6 gap-y-1.5 border-t border-divider py-4 first:border-t-0 first:pt-0 sm:grid-cols-[13rem_minmax(0,1fr)]">
      <dt className="flex flex-col items-start gap-1.5 font-medium"><Tag kind={kind} />{term}</dt>
      <dd className="text-secondary-text">{children}</dd>
    </div>
  );
}

function Bar({ label, value, widest }: { label: string; value: number | null; widest: number }) {
  return (
    <div>
      <p className="flex justify-between gap-4 text-sm"><span className="text-secondary-text">{label}</span><span className="tnum font-semibold">{value === null ? NOT_RECORDED : eurFine(value)}</span></p>
      <div aria-hidden className="mt-1.5 h-2.5 rounded-full bg-inset">{value !== null && widest > 0 && <div className="h-2.5 rounded-full bg-gradient-to-r from-[#6366f1] to-[var(--bar-top)]" style={{ width: `${Math.max(0.8, (value / widest) * 100)}%` }} />}</div>
    </div>
  );
}

function Projection({ portals }: { portals: Portal[] }) {
  const sliderId = useId();
  const basis = costBasis(portals);
  const known = observedKnownShare(portals);
  const observedPct = known.share === null ? null : Math.round(known.share * 100);
  const [chosen, setChosen] = useState<number | null>(null);
  const pct = chosen ?? observedPct ?? 0;
  const cL = basis.learned.averageEur, cR = basis.reused.averageEur;
  const out = project({ portals: TARGET_PORTALS, knownShare: pct / 100, costPerLearnEur: cL, costPerReuseEur: cR });
  const widest = Math.max(out.totalEur ?? 0, out.allLearnedEur ?? 0);
  const missing = [cL === null && out.learns > 0 ? "no portal learned from scratch has recorded usage" : null, cR === null && out.reuses > 0 ? "no portal has reused a recipe with recorded usage" : null].filter(Boolean);
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      <section aria-label="Assumptions and inputs" className="card p-5 2xl:p-7">
        <h3 className="eyebrow mb-5">What the projection rests on</h3>
        <dl>
          <Row kind="assumption" term="Fleet size">
            <span className="tnum font-semibold text-foreground">{int(TARGET_PORTALS)} portals.</span> The target fleet, not a measurement.
          </Row>
          <Row kind="assumption" term="Share on known software">
            <label htmlFor={sliderId} className="sr-only">Share of the {int(TARGET_PORTALS)} portals that run software we have already learned, in percent</label>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <input id={sliderId} type="range" min={0} max={100} step={1} value={pct} onChange={(e) => setChosen(Number(e.target.value))}
                aria-valuetext={`${pct} percent`} className="h-2 min-w-40 flex-1 cursor-pointer accent-[#6366f1]" />
              <output htmlFor={sliderId} className="tnum w-16 text-right text-[1.35rem] font-semibold text-foreground">{pct}%</output>
              {chosen !== null && observedPct !== null && chosen !== observedPct && (
                <button type="button" onClick={() => setChosen(null)} className="pill-ghost !px-3 !py-1.5 !text-xs"><RotateCcw aria-hidden className="size-3.5" /> Back to observed {observedPct}%</button>
              )}
            </div>
            <p className="mt-2">
              {known.share === null
                ? "Not recorded: no portal has a software fingerprint yet, so the slider starts at 0%."
                : <>Starts at the share observed in this fleet: {plural(known.fingerprinted, "fingerprinted portal")} in {plural(known.distinct, "family")}, so {known.fingerprinted - known.distinct} of {known.fingerprinted} ({observedPct}%) run software another portal already uses.</>}
              {" "}How this share develops across {int(TARGET_PORTALS)} portals is not measured; move the slider to test other values.
            </p>
          </Row>
          <Row kind="data" term="Cost per learn">
            <span className="tnum font-semibold text-foreground">{cL === null ? NOT_RECORDED : eurFine(cL)}</span>
            {cL !== null && <> per portal: the average recorded model cost to date of {plural(basis.learned.recorded, "portal")} learned from scratch, repairs so far included.</>}
            <span className="mt-1 block"><Tag kind="assumption" /> A portal on new software will cost what these cost on average.</span>
          </Row>
          <Row kind="data" term="Cost per reuse">
            <span className="tnum font-semibold text-foreground">{cR === null ? NOT_RECORDED : eurFine(cR)}</span>
            {cR !== null && <> per portal: the average recorded model cost to date of {plural(basis.reused.recorded, "portal")} running on a reused recipe.</>}
            <span className="mt-1 block"><Tag kind="assumption" /> A portal on known software will cost what these cost on average.</span>
          </Row>
          <Row kind="assumption" term="Left out">
            Model usage only. Regular reads make no model call by design, so they add nothing here. Future repairs, hosting, storage and download traffic are not projected.
          </Row>
        </dl>
      </section>

      <section aria-label="Projected model cost" aria-live="polite" className="card flex flex-col overflow-hidden p-5 2xl:p-7">
        <div aria-hidden className="pointer-events-none absolute -top-24 -right-16 size-72 rounded-full bg-[radial-gradient(closest-side,rgb(99_102_241/0.22),transparent)]" />
        <h3 className="eyebrow">Projected model cost, {int(TARGET_PORTALS)} portals</h3>
        {out.totalEur === null ? (
          <>
            <p className="display mt-5 text-[2.4rem]">{NOT_RECORDED}</p>
            <p className="mt-3 text-secondary-text">The projection needs a cost that the data does not hold yet: {missing.join(", and ")}. Nothing is estimated in its place.</p>
          </>
        ) : (
          <>
            <p className="mt-5 flex flex-wrap items-baseline gap-x-3">
              <span className="silver tnum text-[clamp(3rem,5.4vw,5.5rem)] leading-none font-semibold tracking-[-0.04em]">{eurFine(out.totalEur).replace(" EUR", "")}</span>
              <span className="text-xl font-medium text-muted-foreground">EUR</span>
            </p>
            <p className="mt-2 text-secondary-text">One-off model cost to attach {int(TARGET_PORTALS)} portals with {pct}% of them on known software.</p>
          </>
        )}
        <dl className="tnum mt-6 grid grid-cols-[auto_minmax(0,1fr)_auto] gap-x-4 gap-y-2 border-t border-divider pt-5 text-[0.95rem]">
          <dt className="font-semibold">{int(out.learns)}</dt><dd className="text-secondary-text">learned from scratch × {cL === null ? NOT_RECORDED.toLowerCase() : eurFine(cL)}</dd><dd className="text-right font-semibold">{out.learnCostEur === null ? NOT_RECORDED : eurFine(out.learnCostEur)}</dd>
          <dt className="font-semibold">{int(out.reuses)}</dt><dd className="text-secondary-text">on a reused recipe × {cR === null ? NOT_RECORDED.toLowerCase() : eurFine(cR)}</dd><dd className="text-right font-semibold">{out.reuseCostEur === null ? NOT_RECORDED : eurFine(out.reuseCostEur)}</dd>
        </dl>
        <div className="mt-6 flex flex-col gap-4 border-t border-divider pt-5">
          <Bar label={`With ${pct}% on known software`} value={out.totalEur} widest={widest} />
          <Bar label="Every portal learned from scratch" value={out.allLearnedEur} widest={widest} />
        </div>
        {out.savingEur !== null && out.allLearnedEur !== null && out.allLearnedEur > 0 && (
          <p className="mt-5 text-secondary-text">Reuse saves <span className="font-semibold text-foreground">{eurFine(out.savingEur)}</span> ({Math.round((out.savingEur / out.allLearnedEur) * 100)}%) against learning every portal from scratch.</p>
        )}
      </section>
    </div>
  );
}

export function ScalePage() {
  const fleet = useFleet(false, false, 10_000);
  const d = fleet.data?.dashboard ?? null;
  const portals = d?.portals ?? [];
  const basis = costBasis(portals);
  const fam = families(portals);
  const cL = basis.learned.averageEur, cR = basis.reused.averageEur;
  const ratio = cL !== null && cR !== null && cR > 0 && cL > cR ? cL / cR : null;
  const shared = fam.families.filter((f) => f.reused > 0);
  return (
    <PagesShell page="scale" fleet={fleet}>
      <PageHero label="Cost & scale"
        title={ratio !== null
          ? <>A portal on software we already know costs <span className="highlight font-normal">{ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)}× less</span> to attach than a new one.</>
          : <>Learn a software family once, <span className="highlight font-normal">reuse the recipe</span> for every portal on it.</>}>
        The agent writes a recipe the first time it meets a piece of portal software. Every further portal on that software takes the recipe over instead of paying for the learning again. All amounts are recorded model usage{d?.eurPerUsd ? `, converted at a fixed ${d.eurPerUsd} EUR per USD` : ""}.
      </PageHero>

      {!d ? (
        <div className="mt-10 grid gap-4 md:grid-cols-3" aria-busy="true">{[0, 1, 2].map((i) => <Skel key={i} className="min-h-[13rem] rounded-[1.25rem]" />)}</div>
      ) : portals.length === 0 ? (
        <p className="card mt-10 p-8 text-secondary-text">No portal is attached yet, so there is no cost to show. Add a portal on the <a href="#/" className="text-primary underline-offset-4 hover:underline">overview</a>.</p>
      ) : (
        <>
          {fleet.data?.basic && (
            <p className="mt-8 rounded-2xl bg-healing-tint px-4 py-3 text-sm text-healing">
              Live from the public contract routes. Software fingerprint, recipe reuse and model cost are not on those routes, so the numbers below read "Not recorded" until the /api routes answer. Nothing is filled in from demo data.
            </p>
          )}
          <section aria-labelledby="unit-h" className="mt-12">
            <SectionHead id="unit-h" label="Per portal" title={<>What one portal costs, <span className="text-muted-foreground">by how it got its recipe</span></>} />
            <dl className="grid gap-4 md:grid-cols-3">
              <UnitCost label="New portal, learned from scratch" side={basis.learned} widest={Math.max(cL ?? 0, cR ?? 0)}
                caption={basis.learned.portals === 0 ? "Not recorded: no portal has a recipe of its own yet." : <>Average recorded model cost to date of {plural(basis.learned.recorded, "portal")} with a recipe of {basis.learned.recorded === 1 ? "its" : "their"} own, repairs included.{basis.learned.recorded < basis.learned.portals && ` ${basis.learned.portals - basis.learned.recorded} more without recorded usage.`}</>} />
              <UnitCost label="Portal on software we already know" side={basis.reused} widest={Math.max(cL ?? 0, cR ?? 0)}
                caption={basis.reused.portals === 0 ? "Not recorded: no portal has taken over a recipe yet." : <>Average recorded model cost to date of {plural(basis.reused.recorded, "portal")} running on a recipe taken over from the same software.{basis.reused.recorded < basis.reused.portals && ` ${basis.reused.portals - basis.reused.recorded} more without recorded usage.`}</>} />
              <div className="card flex min-h-[13rem] flex-col p-5 2xl:p-6">
                <dt className="text-sm font-medium text-muted-foreground">Recipes shared today</dt>
                <dd className="flex flex-1 flex-col pt-5">
                  <p className="flex flex-wrap items-baseline gap-x-2"><span className="silver tnum text-[clamp(2.5rem,3.6vw,3.6rem)] leading-none font-semibold tracking-[-0.035em]">{basis.reused.portals}</span><span className="text-base font-medium text-muted-foreground">of {plural(basis.learned.portals + basis.reused.portals, "portal")} with a recipe</span></p>
                  <p className="mt-auto pt-4 text-sm leading-snug text-secondary-text">
                    {shared.length ? `${shared.map((f) => f.sentence).join(". ")}.` : "No recipe is shared between portals yet."}
                    {basis.withoutRecipe > 0 && ` ${plural(basis.withoutRecipe, "portal")} without a working recipe ${basis.withoutRecipe === 1 ? "is" : "are"} in neither average.`}
                  </p>
                </dd>
              </div>
            </dl>
          </section>

          <section aria-labelledby="fam-h" className="mt-14">
            <SectionHead id="fam-h" label="Software families" title={<>{plural(fam.families.length, "family")} <span className="text-muted-foreground">across {plural(portals.length, "portal")}</span></>}>
              <p className="text-sm text-muted-foreground">Grouped by the software fingerprint each portal reports</p>
            </SectionHead>
            {fam.families.length === 0 && fam.unknown.length === 0 ? <p className="card p-6 text-secondary-text">No families recorded.</p> : (
              <ul className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
                {fam.families.map(familyCard)}
                {fam.unknown.length > 0 && <FamilyCard muted title="Fingerprint not recorded" sentence={`${plural(fam.unknown.length, "portal")} without a recognised software family; ${fam.unknown.length === 1 ? "it counts" : "they count"} in no family`} portals={fam.unknown}
                  costEur={fam.unknown.some((p) => p.usage) ? fam.unknown.reduce((s, p) => s + (p.usage?.costEur ?? 0), 0) : null} />}
              </ul>
            )}
          </section>

          <section aria-labelledby="proj-h" className="mt-14">
            <SectionHead id="proj-h" label="Projection" title={<>From {plural(portals.length, "portal")} to <span className="highlight font-normal">{int(TARGET_PORTALS)}</span></>}>
              <p className="text-sm text-muted-foreground">Inputs are measured; every assumption is marked</p>
            </SectionHead>
            <Projection portals={portals} />
          </section>
        </>
      )}
    </PagesShell>
  );
}
