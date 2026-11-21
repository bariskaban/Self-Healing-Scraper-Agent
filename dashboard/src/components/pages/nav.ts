// Hash routes of the extra pages. The overview and the portal page keep their own parser (data/hooks).
export type Page = "tv" | "scale" | "tenders";

export const PAGE_HASH: Record<Page, string> = { tv: "#/tv", scale: "#/scale", tenders: "#/tenders" };
export const PAGE_TITLE: Record<Page, string> = { tv: "TV mode", scale: "Cost & scale", tenders: "Tender explorer" };

export function parsePage(hash: string): Page | null {
  const m = /^#\/(tv|scale|tenders)\/?$/.exec(hash);
  return m ? (m[1] as Page) : null;
}

/** `?tv=1` opens the wallboard directly, for a projector bookmark. */
export function tvParam(search: string): boolean {
  try { return new URLSearchParams(search).get("tv") === "1"; } catch { return false; }
}

/** Typing in a field must never trigger the "T" shortcut. */
export function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
}
