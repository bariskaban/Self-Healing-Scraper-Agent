import { Monitor, Moon, Plus, Settings as Gear, Sun, WifiOff } from "lucide-react";
import type { LedgerState } from "@/types";
import type { ThemePref } from "./viewState";
import { PagesNav } from "../pages/PagesNav";

/** Our own mark: a small watchtower on an indigo tile. */
export function TowerMark({ className }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 32 32" className={className}>
      <defs><linearGradient id="wt-mark" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#818cf8" /><stop offset="1" stopColor="#4f46e5" /></linearGradient></defs>
      <rect width="32" height="32" rx="9.5" fill="url(#wt-mark)" />
      <path d="M10 8.5h2.6v2.1h2.1V8.5h2.6v2.1h2.1V8.5H22v5.2l-1.6 1.6V23h-8.8v-7.7L10 13.7z" fill="#fff" />
      <path d="M14.6 23v-3.2a1.4 1.4 0 0 1 2.8 0V23z" fill="#4f46e5" />
      <rect x="8.4" y="23" width="15.2" height="1.9" rx="0.95" fill="#fff" fillOpacity="0.72" />
    </svg>
  );
}

const snapshotTime = (iso: string) =>
  new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short" }).format(new Date(iso));

export const ADD_OFF_REASON = "Adding a portal needs the live API. The API is unreachable, so this page shows the demo snapshot.";

export function Header(props: {
  state: LedgerState; now: number; theme: ThemePref;
  onTheme: () => void; onSettings: () => void; onAddPortal: () => void; onAnalytics: (() => void) | null;
}) {
  const { state, now } = props;
  const ThemeIcon = props.theme === "system" ? Monitor : props.theme === "light" ? Sun : Moon;
  const themeLabel = props.theme === "system" ? "System" : props.theme === "light" ? "Light" : "Dark";
  const canAdd = state.source === "live";
  return (
    <header className="pointer-events-none sticky top-3 z-40 px-3 lg:px-8">
      <div className="glass pointer-events-auto mx-auto flex max-w-[100rem] flex-wrap items-center gap-x-4 gap-y-2 rounded-[1.6rem] px-3 py-2 shadow-[0_10px_40px_-18px_rgb(0_0_0/0.55)] sm:rounded-full sm:pl-3 sm:pr-2">
        <a href="#/" className="flex items-center gap-2.5 rounded-full pr-1 text-foreground">
          <TowerMark className="size-9 shrink-0" />
          <span className="text-[1.12rem] font-semibold tracking-tight">Watchtower</span>
        </a>
        <nav aria-label="Sections" className="hidden items-center gap-3 text-sm text-muted-foreground md:flex">
          <span aria-hidden className="h-4 w-px bg-[var(--border-strong)]" />
          {state.route.name === "overview"
            ? <><span className="text-secondary-text">Portal overview</span>{props.onAnalytics && <button type="button" onClick={props.onAnalytics} className="cursor-pointer rounded-md hover:text-foreground">Analytics</button>}</>
            : <><a href="#/" className="hover:text-foreground">Portal overview</a><span aria-hidden>/</span><span className="text-secondary-text">Portal detail</span></>}
        </nav>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2 text-sm">
          <PagesNav />
          <SourceStatus state={state} now={now} />
          <button type="button" className="pill-ghost !px-2.5 xl:!px-3.5" onClick={props.onTheme} aria-label={`Theme: ${themeLabel}. Switch theme`} title={`Theme: ${themeLabel}`}>
            <ThemeIcon aria-hidden className="size-4" /> <span className="hidden xl:inline">{themeLabel}</span>
          </button>
          <button type="button" className="pill-ghost !px-2.5 xl:!px-3.5" onClick={props.onSettings} aria-label="Settings" title="Settings">
            <Gear aria-hidden className="size-4" /> <span className="hidden xl:inline">Settings</span>
          </button>
          <button type="button" className="pill-cta disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:transform-none" onClick={props.onAddPortal}
            disabled={!canAdd} title={canAdd ? "Add a portal by its address" : ADD_OFF_REASON} aria-describedby={canAdd ? undefined : "add-off"}>
            <Plus aria-hidden className="size-4" /> <span className="max-sm:sr-only">Add portal</span>
          </button>
          {!canAdd && state.source === "demo" && <span id="add-off" className="sr-only">{ADD_OFF_REASON}</span>}
        </div>
      </div>
    </header>
  );
}

function SourceStatus({ state, now }: { state: LedgerState; now: number }) {
  if (state.source === null) return <span className="px-2 text-muted-foreground">Connecting…</span>;
  if (state.source === "live") {
    const age = state.liveAt ? Math.max(0, Math.round((now - state.liveAt) / 1000)) : 0;
    return (
      <span className="chip chip-plain tnum text-secondary-text" title={state.basic ? "Live from the public contract routes. Fields those routes do not carry show as not recorded." : "Live from the /api routes."}>
        <span aria-hidden className="live-dot text-serving" />
        <span><span className="font-semibold text-foreground">{state.basic ? "Live · basic" : "Live"}</span><span className="max-sm:hidden"> · updated {age} s ago</span></span>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-2">
      {state.everOnline && (
        <span className="chip chip-plain bg-failed-tint text-failed">
          <WifiOff aria-hidden className="size-[1em]" /> API offline, retrying
        </span>
      )}
      <span className="chip chip-plain font-semibold">Demo data</span>
      {state.dashboard && <span className="hidden text-muted-foreground lg:inline">Snapshot · <time dateTime={state.dashboard.asOf}>{snapshotTime(state.dashboard.asOf)}</time></span>}
    </span>
  );
}
