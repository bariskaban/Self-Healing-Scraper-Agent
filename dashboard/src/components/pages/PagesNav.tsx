import { Coins, MonitorPlay, ScrollText, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { PAGE_HASH, type Page } from "./nav";

const LINKS: { page: Page; label: string; Icon: LucideIcon; title: string }[] = [
  { page: "tenders", label: "Tenders", Icon: ScrollText, title: "Tender explorer: every tender from every portal" },
  { page: "scale", label: "Cost & scale", Icon: Coins, title: "Cost per portal and the projection to 4,500 portals" },
  { page: "tv", label: "TV", Icon: MonitorPlay, title: "TV mode: full-screen wallboard (shortcut: T)" },
];

/** Links to the extra pages. Icon only on small screens, with the name kept for screen readers. */
export function PagesNav({ current = null }: { current?: Page | null }) {
  return (
    <nav aria-label="Pages" className="flex items-center gap-0.5">
      {LINKS.map(({ page, label, Icon, title }) => (
        <a key={page} href={PAGE_HASH[page]} title={title} aria-current={current === page ? "page" : undefined}
          className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-2 text-sm font-medium whitespace-nowrap transition-colors",
            current === page ? "bg-inset text-foreground" : "text-muted-foreground hover:bg-inset hover:text-foreground")}>
          <Icon aria-hidden className="size-4" />
          <span className="max-xl:sr-only">{label}</span>
        </a>
      ))}
    </nav>
  );
}
