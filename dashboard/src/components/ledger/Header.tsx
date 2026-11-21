import { Monitor, Moon, Plus, Settings as Gear, Sun, WifiOff } from "lucide-react";
import type { LedgerState } from "@/types";
import type { ThemePref } from "./viewState";
import { PAGE_HASH } from "../pages/nav";

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

const wallClock = (ms: number) => new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(ms);

/** Portals and Repairs are sections of the overview: go there first, then scroll. */
function jump(id: string) {
  const go = () => document.getElementById(id)?.scrollIntoView({ block: "start" });
  if (/^#\/?$|^$/.test(window.location.hash)) go();
  else { window.location.hash = "#/"; window.setTimeout(go, 120); }
}

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
      <div className="glass pointer-events-auto mx-auto flex max-w-[100rem] flex-wrap items-center gap-x-4 gap-y-2 rounded-[1.6rem] px-3 py-2 shadow-[0_14px_40px_-22px_rgb(60_50_120/0.45)] sm:rounded-full sm:pl-3 sm:pr-2">
        <a href="#/" className="flex items-center gap-2.5 rounded-full pr-1 text-foreground">
          <TowerMark className="size-9 shrink-0" />
          <span className="text-[1.12rem] font-semibold tracking-tight">Watchtower</span>
        </a>
        <nav aria-label="Sections" className="flex flex-wrap items-center gap-0.5">
          <a href="#/" className="nav-link" aria-current={state.route.name === "overview" ? "page" : undefined}>Overview</a>
          <button type="button" className="nav-link" onClick={() => jump("portals")}>Portals</button>
          <a href={PAGE_HASH.tenders} className="nav-link" title="Every tender from every portal">Tenders</a>
          <button type="button" className="nav-link" onClick={() => jump("repairs")}>Repairs</button>
          <a href={PAGE_HASH.scale} className="nav-link" title="Cost per portal and the projection to 4,500 portals">Cost &amp; scale</a>
          <a href={PAGE_HASH.tv} className="nav-link" title="Full-screen wallboard (shortcut: T)">TV mode</a>
        </nav>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2 text-sm">
          <SourceStatus state={state} now={now} />
          <time className="tnum hidden px-1 text-[0.95rem] font-semibold text-foreground lg:inline" dateTime={new Date(now).toISOString()}>{wallClock(now)}</time>
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
      <span className="chip chip-plain font-semibold">Demo snapshot · not live</span>
      {state.dashboard && <span className="hidden text-muted-foreground lg:inline">Snapshot · <time dateTime={state.dashboard.asOf}>{snapshotTime(state.dashboard.asOf)}</time></span>}
    </span>
  );
}
