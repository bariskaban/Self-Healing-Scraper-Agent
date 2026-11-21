import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import "./pages.css";
import { PAGE_TITLE, isEditable, parsePage, tvParam } from "./nav";
import { ScalePage } from "./ScalePage";
import { TendersPage } from "./TendersPage";
import { TvMode } from "./TvMode";

/**
 * Routes `#/tv`, `#/scale` and `#/tenders` to the extra pages and hands everything else to the
 * overview app (`children`), which is not mounted while an extra page shows, so only one page polls.
 * Also owns the wallboard shortcuts: "T" toggles TV mode, Escape leaves it, `?tv=1` starts in it.
 */
export function PagesRoot({ children }: { children: ReactNode }) {
  const [hash, setHash] = useState(() => window.location.hash);
  const [tvQuery, setTvQuery] = useState(() => tvParam(window.location.search));
  const returnTo = useRef("#/");

  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const hashPage = parsePage(hash);
  const page = tvQuery ? "tv" : hashPage;
  useEffect(() => { if (hashPage !== "tv") returnTo.current = hash || "#/"; }, [hash, hashPage]);
  useEffect(() => { if (page) document.title = `${PAGE_TITLE[page]} · Watchtower`; }, [page]);

  const leaveTv = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen?.().catch(() => { /* already left */ });
    if (tvParam(window.location.search)) {
      const u = new URL(window.location.href);
      u.searchParams.delete("tv");
      window.history.replaceState(null, "", u.pathname + u.search + u.hash);
    }
    setTvQuery(false);
    if (parsePage(window.location.hash) === "tv") window.location.hash = "#/";
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.repeat || isEditable(e.target)) return;
      const t = e.key === "t" || e.key === "T";
      if (page === "tv") {
        if (t || e.key === "Escape") { e.preventDefault(); leaveTv(); }
      } else if (t && !document.querySelector('[role="dialog"]')) {
        e.preventDefault();
        window.location.hash = "#/tv";
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [page, leaveTv]);

  if (page === "tv") return <TvMode onLeave={leaveTv} />;
  if (page === "scale") return <ScalePage />;
  if (page === "tenders") return <TendersPage />;
  return <>{children}</>;
}
