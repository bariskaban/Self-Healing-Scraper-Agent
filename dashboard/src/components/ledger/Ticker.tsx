import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { portalHash } from "@/data/hooks";
import { runResultWord } from "@/data/view";
import type { TickerItem } from "./overview";

function Item({ item, hidden }: { item: TickerItem; hidden?: boolean }) {
  const Icon = item.result === null ? Loader2 : item.result === "ok" ? CheckCircle2 : XCircle;
  const ink = item.result === null ? "text-integrating" : item.result === "ok" ? "text-serving" : "text-failed";
  return (
    <li className="flex shrink-0 items-center gap-2.5 whitespace-nowrap pr-10 text-sm">
      <Icon aria-hidden className={`size-4 shrink-0 ${ink}`} />
      {item.time && <time className="text-muted-foreground">{item.time}</time>}
      <a href={portalHash(item.portalId)} tabIndex={hidden ? -1 : undefined} className="font-medium text-foreground hover:underline">{item.host}</a>
      {item.kind && <span className={ink}>{item.kind === "repair" ? "Repair" : "Read"} {runResultWord(item.result).toLowerCase()}</span>}
      <span className="text-secondary-text">{item.text}</span>
    </li>
  );
}

/** A slow marquee of real run summaries. It pauses on hover and focus and stands still under reduced motion. */
export function Ticker({ items }: { items: TickerItem[] }) {
  if (!items.length) return null;
  return (
    <section aria-label="Latest runs" className="mt-5 flex items-center gap-4">
      <p className="eyebrow hidden shrink-0 sm:block">Latest runs</p>
      <div className="ticker min-w-0 flex-1 py-1.5">
        <div className="ticker-track" style={{ ["--ticker-duration" as string]: `${Math.max(40, items.length * 11)}s` }}>
          <ul className="flex">{items.map((item) => <Item key={item.key} item={item} />)}</ul>
          <ul className="ticker-copy flex" aria-hidden>{items.map((item) => <Item key={item.key} item={item} hidden />)}</ul>
        </div>
      </div>
    </section>
  );
}
