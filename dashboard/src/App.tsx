import { useEffect, useMemo, useRef, useState } from "react";
import { useHashRoute, useLedger, useNow, useTheme } from "@/data/hooks";
import { fleetSummary, STATE_META } from "@/data/view";
import { hostname } from "@/data/format";
import { Header } from "@/components/ledger/Header";
import { FleetStrip } from "@/components/ledger/FleetStrip";
import { EmptyFleet, LedgerSkeleton, PortalLedger } from "@/components/ledger/PortalLedger";
import { PortalDetail } from "@/components/ledger/PortalDetail";
import { SettingsSheet } from "@/components/ledger/SettingsSheet";
import { RepairBand } from "@/components/ledger/RepairBand";
import { hasActiveRepair } from "@/components/ledger/evidence";
import { sortPortals } from "@/data/view";
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
    else if (!p.offline && state.offline && state.source !== "demo") out.push("API offline, retrying. Showing the last update.");
    else if (p.offline && !state.offline && state.source === "live") out.push("Connected to live API.");
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

export default function App() {
  const route = useHashRoute();
  const { state, controller } = useLedger(route);
  const { pref, cycle } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const tick = useNow(true);
  const d = state.dashboard;
  const now = state.source === "demo" && d ? Date.parse(d.asOf) : tick;
  const summary = useMemo(() => (d && state.source ? fleetSummary(d) : null), [d, state.source]);
  const announce = useAnnouncements(state);
  const eurPerUsd = d?.eurPerUsd ?? 0;

  useEffect(() => {
    if (route.name === "overview") document.title = "Portal overview · Watchtower";
    else {
      const p = d?.portals.find((x) => x.id === route.id);
      document.title = `${p ? hostname(p.url) : "Portal"} · Watchtower`;
    }
  }, [route, d]);

  return (
    <div className="min-h-screen">
      <Header state={state} now={tick} theme={pref} onTheme={cycle} onSettings={() => setSettingsOpen(true)} />
      <div className="sr-only" aria-live="polite" role="status">{announce}</div>
      <main className="mx-auto flex max-w-[120rem] flex-col gap-4 px-4 py-4 lg:px-8 2xl:gap-6 2xl:py-6">
        {route.name === "overview" ? (
          <>
            <h1 className="sr-only">Portal overview</h1>
            <FleetStrip summary={summary} eurPerUsd={eurPerUsd} />
            {d && state.source && (() => { const repair = sortPortals(d.portals).find(hasActiveRepair); return repair ? <RepairBand portal={repair} /> : null; })()}
            {!d || !state.source ? <LedgerSkeleton /> : d.portals.length === 0 ? (
              state.source === "live" ? <EmptyFleet /> : <p className="rounded-lg border border-border bg-surface p-8 text-secondary-text">The demo snapshot contains no portals.</p>
            ) : <PortalLedger portals={d.portals} now={now} eurPerUsd={eurPerUsd} live={state.source === "live"} />}
            {d && state.source && <p className="text-micro text-muted-foreground">Model cost covers LLM usage only, at a fixed {d.eurPerUsd} EUR per USD as recorded; running work shows cost so far.</p>}
          </>
        ) : (
          <PortalDetail key={route.id} detail={state.detail} source={state.source} now={now} eurPerUsd={eurPerUsd} />
        )}
      </main>
      <SettingsSheet open={settingsOpen} onOpenChange={setSettingsOpen} settings={d?.settings ?? null}
        writable={state.source === "live" && !state.offline} onSaved={(s) => controller.acceptSettings(s)} />
    </div>
  );
}
