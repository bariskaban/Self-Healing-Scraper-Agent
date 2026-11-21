import type { ReactNode } from "react";
import { Monitor, Moon, Sun, WifiOff } from "lucide-react";
import { useNow } from "@/data/hooks";
import { TopBar } from "@/components/ledger/Header";
import { useTheme } from "@/components/ledger/viewState";
import { PagesNav } from "./PagesNav";
import { PAGE_TITLE, type Page } from "./nav";
import type { FleetState } from "./pagesData";

export const SHELL = "mx-auto w-full max-w-[100rem] px-4 lg:px-8";

const snapshotTime = (iso: string) =>
  new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short" }).format(new Date(iso));

/** Where the numbers on the page come from: the live API, or the bundled demo snapshot. */
export function SourceChip({ fleet }: { fleet: FleetState }) {
  const now = useNow(fleet.data?.source === "live");
  const data = fleet.data;
  if (!data) return <span className="px-2 text-muted-foreground">Connecting…</span>;
  if (data.source === "live") {
    const age = fleet.liveAt ? Math.max(0, Math.round((now - fleet.liveAt) / 1000)) : 0;
    return (
      <span className="chip chip-plain tnum text-secondary-text" title={data.basic ? "Live from the public contract routes. Fields those routes do not carry show as not recorded." : "Live from the /api routes."}>
        <span aria-hidden className="live-dot text-serving" />
        <span><span className="font-semibold text-foreground">{data.basic ? "Live · basic" : "Live"}</span><span className="max-sm:hidden"> · updated {age} s ago</span></span>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-2">
      {fleet.everOnline && <span className="chip chip-plain bg-failed-tint text-failed"><WifiOff aria-hidden className="size-[1em]" /> API offline, retrying</span>}
      <span className="chip chip-plain font-semibold">Demo snapshot · not live</span>
      <span className="hidden text-muted-foreground xl:inline">Snapshot · <time dateTime={data.dashboard.asOf}>{snapshotTime(data.dashboard.asOf)}</time></span>
    </span>
  );
}

/** The frame of the extra pages: the same glow, glass header and width as the overview. */
export function PagesShell({ page, fleet, children }: { page: Page; fleet: FleetState; children: ReactNode }) {
  const { pref, cycle } = useTheme();
  const ThemeIcon = pref === "system" ? Monitor : pref === "light" ? Sun : Moon;
  const themeLabel = pref === "system" ? "System" : pref === "light" ? "Light" : "Dark";
  return (
    <div className="relative isolate min-h-screen overflow-x-clip">
      <TopBar current={page === "tv" ? null : page} status={<SourceChip fleet={fleet} />} />
      <main className={`${SHELL} pb-16`}>{children}</main>
    </div>
  );
}

/** Uppercase label over a large light headline and one supporting sentence. */
export function PageHero({ label, title, children }: { label: string; title: ReactNode; children?: ReactNode }) {
  return (
    <section className="pt-10 2xl:pt-14">
      <p className="eyebrow">{label}</p>
      <h1 className="display mt-4 max-w-[62rem] text-[clamp(2rem,3.9vw,3.5rem)]">{title}</h1>
      {children && <p className="mt-5 max-w-[52rem] text-[1.1rem] leading-relaxed text-secondary-text">{children}</p>}
    </section>
  );
}
