import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { FetchLike } from "@/data/api";
import { TenderPager, type PagerMode } from "@/data/tenderPager";
import { TENDER_CAP } from "@/data/tenderPaging";
import { Skel } from "./primitives";
import { TenderTable } from "./TenderTable";

const n = (v: number) => v.toLocaleString("en-US");

/**
 * The portal's tenders in their own scroll box. The first page loads when the page opens, the next
 * one when the sentinel under the rows comes within 300px of the visible end. No buttons. The 5 s
 * poll never touches this list; it lives until the portal id changes.
 */
export function TenderList({ portalId, mode, timeZone, live, fetchImpl }: {
  portalId: string; mode: PagerMode; timeZone: string | null; live: boolean; fetchImpl?: FetchLike;
}) {
  const [pager] = useState(() => new TenderPager(fetchImpl ?? ((u, i) => window.fetch(u, i)), portalId, mode));
  const s = useSyncExternalStore(pager.subscribe, pager.getSnapshot, pager.getSnapshot);
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const box = useRef<HTMLDivElement>(null);
  const [sentinel, setSentinel] = useState<HTMLDivElement | null>(null);

  useEffect(() => { void pager.loadMore(); return () => pager.dispose(); }, [pager]);

  const hasSentinel = s.items.length > 0 && s.next !== null && !s.capped;
  useEffect(() => {
    if (!sentinel || !box.current || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => { if (entries.some((e) => e.isIntersecting)) void pager.loadMore(); },
      { root: box.current, rootMargin: "0px 0px 300px 0px" },
    );
    io.observe(sentinel);
    return () => io.disconnect();
  }, [sentinel, pager]);

  const toggle = useCallback((id: string) => {
    setOpened((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else { next.add(id); void pager.loadOne(id); }
      return next;
    });
  }, [pager]);

  return (
    <div>
      <p className="mb-3 text-sm text-muted-foreground" role="status" aria-live="polite">
        {s.total === null ? (s.error ? "Could not load the tenders." : "Loading tenders…") : `Showing ${n(s.items.length)} of ${n(s.total)}`}
        {s.cut && " · Basic live: the public route answers every tender at once. It was read once and is cut to the first 500 rows here."}
      </p>
      {s.total === 0 && !s.error ? <p className="card p-6 text-secondary-text">No tenders delivered yet.</p> : (
        <div ref={box} onScroll={() => { if (s.error) void pager.loadMore(); }} aria-label="Delivered tenders, scrolling list" tabIndex={-1}
          className="max-h-[70vh] overflow-y-auto overscroll-contain rounded-2xl">
          <TenderTable tenders={s.items} timeZone={timeZone} live={live} opened={opened} detail={s.open} onToggle={toggle} />
          {hasSentinel && <div ref={setSentinel} aria-hidden className="h-px" />}
          {s.loading && <div className="mt-3 flex flex-col gap-2" aria-busy="true" aria-label="Loading more tenders">{[0, 1, 2].map((i) => <Skel key={i} className="h-16 rounded-2xl" />)}</div>}
          {s.error && !s.loading && <p className="mt-3 px-2 py-3 text-sm text-muted-foreground" role="alert">The next tenders could not be loaded. Scroll again to try once more.</p>}
          {s.capped && <p className="px-2 py-4 text-sm text-muted-foreground">Showing the first {n(TENDER_CAP)} of {n(s.total ?? 0)} tenders.</p>}
        </div>
      )}
    </div>
  );
}
