import { Monitor, Moon, Settings as Gear, Sun, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ThemePref } from "@/data/hooks";
import type { LedgerState } from "@/types";

export function Header(props: {
  state: LedgerState;
  now: number;
  theme: ThemePref;
  onTheme: () => void;
  onSettings: () => void;
}) {
  const { state, now } = props;
  const demoZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const ThemeIcon = props.theme === "system" ? Monitor : props.theme === "light" ? Sun : Moon;
  const themeLabel = props.theme === "system" ? "System" : props.theme === "light" ? "Light" : "Dark";
  return (
    <header className="flex min-h-16 flex-wrap items-center gap-x-6 gap-y-2 border-b border-divider bg-surface px-4 py-2 lg:px-8">
      <a href="#/" className="flex items-center gap-2 rounded-sm text-foreground">
        <svg aria-hidden viewBox="0 0 32 32" className="size-8 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"><path d="M9 24V11L7 9V3h4v4h3V3h4v4h3V3h4v6l-2 2v13M9 11h14M14 24v-7h4v7M6 25h20M9 29h14" /></svg>
        <span className="flex flex-col"><span className="text-[22px] leading-6 font-semibold">Watchtower</span><span className="text-xs text-secondary-text">Delivery Ledger</span></span>
      </a>
      <span className="hidden text-label text-secondary-text md:inline">{state.route.name === "overview" ? "Portal overview" : "Portal detail"}</span>
      <div className="masthead-tools ml-auto flex flex-wrap items-center justify-end gap-2 text-label">
        <SourceStatus state={state} now={now} demoZone={demoZone} />
        <Button variant="ghost" size="sm" onClick={props.onTheme} aria-label={`Theme: ${themeLabel}. Switch theme`} title={`Theme: ${themeLabel}`}>
          <ThemeIcon aria-hidden /> <span className="hidden md:inline">{themeLabel}</span>
        </Button>
        <Button variant="outline" size="sm" onClick={props.onSettings}>
          <Gear aria-hidden /> Settings
        </Button>
      </div>
    </header>
  );
}

function SourceStatus({ state, now, demoZone }: { state: LedgerState; now: number; demoZone: string }) {
  if (state.offline && state.source !== "demo") {
    const age = state.liveAt ? Math.max(0, Math.round((now - state.liveAt) / 1000)) : null;
    return (
      <span className="inline-flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-sm bg-failed-tint px-2 py-0.5 text-failed">
          <WifiOff aria-hidden className="size-[1em]" /> API offline, retrying
        </span>
        <span className="text-muted-foreground">{age === null ? "No data yet" : `Last update ${age} s ago`}</span>
      </span>
    );
  }
  if (state.source === null) return <span className="text-muted-foreground">Connecting…</span>;
  if (state.source === "live") {
    const age = state.liveAt ? Math.max(0, Math.round((now - state.liveAt) / 1000)) : 0;
    return (
      <span className="inline-flex items-center gap-2 text-secondary-text">
        <span aria-hidden className="size-2 rounded-full bg-serving animate-live-pulse" />
        Live · updated {age} s ago
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {state.everOnline && (
        <span className="inline-flex items-center gap-1 rounded-sm bg-failed-tint px-2 py-0.5 text-failed">
          <WifiOff aria-hidden className="size-[1em]" /> API offline, retrying
        </span>
      )}
      <span className="rounded-sm border border-border bg-inset px-2 py-0.5 font-medium">Demo data</span>
      <span className="text-muted-foreground">Snapshot · {demoZone}</span>
    </span>
  );
}
