import { useEffect, useMemo, useRef, useState } from "react";
import { useHashRoute, useLedger, useNow } from "@/data/hooks";
import { fleetSummary, sortPortals, STATE_META } from "@/data/view";
import { hostname } from "@/data/format";
import { Header } from "@/components/ledger/Header";
import { FleetHero, StatCards } from "@/components/ledger/FleetStrip";
import { EmptyFleet, LedgerSkeleton, PortalLedger } from "@/components/ledger/PortalLedger";
import { PortalDetail } from "@/components/ledger/PortalDetail";
import { SettingsSheet } from "@/components/ledger/SettingsSheet";
import { Spotlight, SpotlightEmpty } from "@/components/ledger/Spotlight";
import { Ticker } from "@/components/ledger/Ticker";
import { SectionHead } from "@/components/ledger/primitives";
import { hasActiveRepair, repairRuns } from "@/components/ledger/evidence";
import { latestRepair, tickerItems } from "@/components/ledger/overview";
import { useOverviewTimelines, useTheme } from "@/components/ledger/viewState";
import type { LedgerState } from "@/types";

function useAnnouncements(state: LedgerState) {
  const [msg, setMsg] = useState("");
  const prev = useRef<LedgerState | null>(null);
  useEffect(() => {
    const p = prev.current;
    prev.current = state;
    if (!p) return;
    const out: string[] = [];
    if (p.source !== state.source && state.source) out.push(state.source === "live" ? "Connected to live API." : state.everOnline ? "API offline, showing demo data. Retrying." : "Showing demo data.");
    if (p.dashboard && state.dashboard) {
      const before = new Map(p.dashboard.portals.map((x) => [x.id, x.state]));
      for (const x of state.dashboard.portals) {
        const b = before.get(x.id);
        if (b && b !== x.state) out.push(`${hostname(x.url)} is now ${STATE_META[x.state].label}.`);
      }
    }
    if (out.length) setMsg(out.join(" "));
  }, [state]);
  return msg;
}

const SHELL = "mx-auto w-full max-w-[100rem] px-4 lg:px-8";

export default function App() {
  const route = useHashRoute();
  const { state, controller } = useLedger(route);
  const { pref, cycle } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const tick = useNow(true);
  const d = state.dashboard;
  const ready = !!d && !!state.source;
  const now = state.source === "demo" && d ? Date.parse(d.asOf) : tick;
  const summary = useMemo(() => (d && state.source ? fleetSummary(d) : null), [d, state.source]);
  const announce = useAnnouncements(state);
  const eurPerUsd = d?.eurPerUsd ?? 0;
  const overview = route.name === "overview";
  const timelines = useOverviewTimelines(d, state.source, overview);
  const ticker = useMemo(() => (d && state.source ? tickerItems(d.portals, timelines) : []), [d, state.source, timelines]);

  useEffect(() => {
    if (route.name === "overview") document.title = "Portal overview · Watchtower";
    else {
      const p = d?.portals.find((x) => x.id === route.id);
      document.title = `${p ? hostname(p.url) : "Portal"} · Watchtower`;
    }
  }, [route, d]);

  const spotlight = () => {
    if (!ready || !d) return <SpotlightEmpty loading />;
    const repairing = sortPortals(d.portals).find(hasActiveRepair);
    const timeline = repairing ? timelines[repairing.id] : undefined;
    if (repairing && timeline) {
      const { active, earlier } = repairRuns(repairing, timeline);
      if (active) return <Spotlight portal={repairing} run={active} timeline={timeline} earlier={earlier} live eurPerUsd={eurPerUsd} />;
    }
    if (repairing) return <SpotlightEmpty loading />;
    const last = latestRepair(d.portals, timelines);
    return last ? <Spotlight portal={last.portal} run={last.run} timeline={timelines[last.portal.id] ?? []} earlier={null} live={false} eurPerUsd={eurPerUsd} /> : <SpotlightEmpty />;
  };

  return (
    <div className="relative isolate min-h-screen overflow-x-clip">
      <div className="glow-field" aria-hidden><div className="glow glow-1" /><div className="glow glow-2" /><div className="glow glow-3" /></div>
      <Header state={state} now={tick} theme={pref} onTheme={cycle} onSettings={() => setSettingsOpen(true)} />
      <div className="sr-only" aria-live="polite" role="status">{announce}</div>
      <main>
        {overview ? (
          <>
            <div className={SHELL}>
              <h1 className="sr-only">Portal overview</h1>
              <Ticker items={ticker} />
              <FleetHero portals={ready && d ? d.portals : null} summary={summary} />
              <div className="mt-9 grid gap-4 pb-12 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] 2xl:mt-11 2xl:pb-14">
                {spotlight()}
                <StatCards portals={ready && d ? d.portals : null} summary={summary} eurPerUsd={eurPerUsd} />
              </div>
            </div>
            <div className="band">
              <section aria-labelledby="ledger-h" className={`${SHELL} py-10 2xl:py-12`}>
                <SectionHead id="ledger-h" label="Portal ledger" title={ready && d ? <>Every portal, <span className="text-muted-foreground">exceptions first</span></> : "Portals"}>
                  <p className="text-sm text-muted-foreground">Read history runs oldest to newest</p>
                </SectionHead>
                {!ready || !d ? <LedgerSkeleton /> : d.portals.length === 0 ? (
                  state.source === "live" ? <EmptyFleet /> : <p className="card p-8 text-secondary-text">The demo snapshot contains no portals.</p>
                ) : <PortalLedger portals={d.portals} now={now} eurPerUsd={eurPerUsd} live={state.source === "live"} />}
                {ready && d && <p className="mt-6 text-sm text-muted-foreground">Model cost covers LLM usage only, at a fixed {d.eurPerUsd} EUR per USD as recorded; running work shows cost so far.</p>}
              </section>
            </div>
          </>
        ) : (
          <div className={`${SHELL} pb-16`}>
            <PortalDetail key={route.id} detail={state.detail} source={state.source} now={now} eurPerUsd={eurPerUsd} />
          </div>
        )}
      </main>
      <SettingsSheet open={settingsOpen} onOpenChange={setSettingsOpen} settings={d?.settings ?? null}
        writable={state.source === "live"} onSaved={(s) => controller.acceptSettings(s)} />
    </div>
  );
}
