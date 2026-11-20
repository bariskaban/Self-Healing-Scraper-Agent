import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { LedgerController } from "./controller";
import type { LedgerState, Route } from "@/types";

export function parseHash(hash: string): Route {
  const m = /^#\/portal\/([^/?#]+)\/?$/.exec(hash);
  if (m?.[1]) {
    try { return { name: "portal", id: decodeURIComponent(m[1]) }; } catch { /* bad escape */ }
  }
  return { name: "overview" };
}

export const portalHash = (id: string) => `#/portal/${encodeURIComponent(id)}`;

export function useHashRoute(): Route {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return useMemo(() => parseHash(hash), [hash]);
}

export function useLedger(route: Route): { state: LedgerState; controller: LedgerController } {
  const controller = useMemo(
    () =>
      new LedgerController((u, i) => window.fetch(u, i), route, {
        allowDemo: new URLSearchParams(window.location.search).has("demo"),
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  useEffect(() => {
    controller.start();
    return () => controller.stop();
  }, [controller]);
  useEffect(() => controller.setRoute(route), [controller, route]);
  const state = useSyncExternalStore(
    (cb) => { const un = controller.subscribe(cb); return () => { un(); }; },
    () => controller.state,
    () => controller.state,
  );
  return { state, controller };
}

/** Ticks once a second; returns null to signal "frozen" when not needed. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

export type ThemePref = "system" | "light" | "dark";
const KEY = "watchtower.theme";

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(() => {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  });
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = pref === "dark" || (pref === "system" && mq.matches);
      document.documentElement.classList.toggle("dark", dark);
    };
    apply();
    mq.addEventListener("change", apply);
    if (pref === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, pref);
    return () => mq.removeEventListener("change", apply);
  }, [pref]);
  const cycle = () => setPref((p) => (p === "system" ? "light" : p === "light" ? "dark" : "system"));
  return { pref, cycle };
}
