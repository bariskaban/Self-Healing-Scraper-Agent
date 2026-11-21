import { useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Eye, Loader2, Plus, XCircle } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { portalHash } from "@/data/hooks";
import { addPortals, parseUrls, watchedIds, type AddResult } from "@/data/portals";

/**
 * Adds portals through the public contract route POST /portals, one address after another. It is the
 * only steering control on the page; nothing here removes, refreshes or repairs a portal.
 */
export function AddPortalSheet({ open, onOpenChange, knownIds, onAdded }: {
  open: boolean; onOpenChange: (open: boolean) => void; knownIds: string[]; onAdded: () => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<AddResult[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const lines = parseUrls(text);
  const valid = lines.filter((l) => l.valid);
  const invalid = lines.filter((l) => !l.valid);

  async function submit() {
    if (!valid.length || busy) return;
    setBusy(true); setResults([]);
    const fetchImpl = (u: string, i?: RequestInit) => window.fetch(u, i);
    const urls = valid.map((l) => l.url);
    setPending(urls[0] ?? null);
    const known = (await watchedIds(fetchImpl)) ?? new Set(knownIds);
    const done = await addPortals(fetchImpl, urls, known, (result, index) => {
      setResults((prev) => [...prev, result]);
      setPending(urls[index + 1] ?? null);
    });
    setBusy(false); setPending(null);
    // Keep what failed in the box so it can be corrected; clear what went through.
    const failed = new Set(done.filter((r) => r.status === "error").map((r) => r.url));
    setText([...invalid.map((l) => l.url), ...urls.filter((u) => failed.has(u))].join("\n"));
    onAdded();
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full max-w-full overflow-y-auto border-l-[var(--glass-border)] bg-[var(--panel)] p-5 backdrop-blur-2xl backdrop-saturate-150 sm:w-[38rem] sm:max-w-[97vw] sm:rounded-l-[1.75rem] sm:p-9">
        <SheetHeader className="space-y-0 pr-8 text-left">
          <p className="eyebrow">Add portal</p>
          <SheetTitle className="display mt-3 text-[2.2rem] font-light">Watch a new portal</SheetTitle>
          <SheetDescription className="!mt-3 text-base text-secondary-text">Paste the address of a public tender portal, or several, one per line. Watchtower starts reading each one in the background.</SheetDescription>
        </SheetHeader>
        <form className="mt-7 flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <label htmlFor="portal-urls" className="text-sm font-medium">Portal addresses</label>
          <textarea id="portal-urls" value={text} onChange={(e) => setText(e.target.value)} rows={5} spellCheck={false} autoComplete="off" disabled={busy}
            aria-describedby="portal-urls-help" aria-invalid={invalid.length > 0}
            placeholder={"https://www.tenderned.nl/aankondigingen/overzicht\nhttps://vergabe.vmstart.de/NetServer/"}
            className="-mt-2 w-full resize-y rounded-2xl border border-[var(--border-strong)] bg-inset px-4 py-3 font-mono text-sm leading-relaxed placeholder:text-muted-foreground/70 disabled:opacity-60" />
          <p id="portal-urls-help" className="-mt-1 text-sm text-muted-foreground">Each address must start with http:// or https://. The same address is never added twice.</p>
          {invalid.length > 0 && (
            <ul className="flex flex-col gap-1.5 rounded-2xl bg-failed-tint p-3.5 text-sm text-failed" aria-label="Addresses that cannot be sent">
              {invalid.map((l) => <li key={l.url} className="flex gap-2"><AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" /><span className="min-w-0"><span className="font-mono break-all">{l.url}</span> · {l.problem}</span></li>)}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" className="pill-cta disabled:cursor-not-allowed disabled:opacity-45" disabled={busy || valid.length === 0}>
              {busy ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <Plus aria-hidden className="size-4" />}
              {busy ? "Adding…" : valid.length > 1 ? `Add ${valid.length} portals` : "Add portal"}
            </button>
            {invalid.length > 0 && valid.length > 0 && <p className="text-sm text-muted-foreground">{invalid.length} address{invalid.length === 1 ? "" : "es"} will be skipped.</p>}
          </div>
        </form>
        {(results.length > 0 || pending) && (
          <section aria-label="Result" className="mt-8">
            <h3 className="eyebrow mb-3">Result</h3>
            <ul className="flex flex-col gap-2.5" role="status">
              {results.map((r) => (
                <li key={r.url} className="rounded-2xl border border-divider bg-inset p-4">
                  <p className="font-mono text-sm break-all">{r.url}</p>
                  {r.status === "error" ? (
                    <p className="mt-2 flex items-start gap-2 font-medium text-failed"><XCircle aria-hidden className="mt-0.5 size-[1.1rem] shrink-0" /><span>Not added: {r.message}</span></p>
                  ) : (
                    <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                      {r.status === "added"
                        ? <span className="inline-flex items-center gap-1.5 font-semibold text-serving"><CheckCircle2 aria-hidden className="size-[1.1rem]" />Added</span>
                        : <span className="inline-flex items-center gap-1.5 font-semibold text-integrating"><Eye aria-hidden className="size-[1.1rem]" />Already watched</span>}
                      <span className="text-sm text-muted-foreground">id <span className="font-mono text-foreground">{r.id}</span></span>
                      <a href={portalHash(r.id)} onClick={() => onOpenChange(false)} className="link-arrow ml-auto text-sm">Open portal <ArrowRight aria-hidden className="size-4" /></a>
                    </p>
                  )}
                </li>
              ))}
              {pending && <li className="flex items-center gap-2.5 rounded-2xl border border-dashed border-border p-4 text-secondary-text"><Loader2 aria-hidden className="size-4 shrink-0 animate-spin" /><span className="font-mono text-sm break-all">{pending}</span></li>}
            </ul>
          </section>
        )}
      </SheetContent>
    </Sheet>
  );
}
