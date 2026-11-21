import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { draftFrom, mergeServerSettings, parseMinutes, parseTenderLimit, saveSettings, tenderLimitNote, type SettingsDraft } from "@/data/settings";
import type { Settings } from "@/types";

export function SettingsSheet(props: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  settings: Settings | null;
  writable: boolean;
  onSaved: (s: Settings) => void;
  /** why the form is read-only, when it is not the demo snapshot */
  readOnlyReason?: string;
}) {
  const { settings } = props;
  const [draft, setDraft] = useState<SettingsDraft>(() => draftFrom(settings ?? { attachTimeLimitMinutes: 20, ignoreRobotsTxt: false }));
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => { if (settings) setDraft((d) => mergeServerSettings(d, settings)); }, [settings]);

  const minutes = parseMinutes(draft.minutes);
  // The limit is shown only when the backend sends it; without it the form is the two older settings.
  const hasLimit = settings?.maxTendersPerPortal !== undefined;
  const tenders = hasLimit ? parseTenderLimit(draft.tenders) : 0;
  const limitNote = hasLimit && tenders !== null ? tenderLimitNote(tenders) : null;
  const dirty = draft.dirtyMinutes || draft.dirtyRobots || draft.dirtyTenders;

  async function save() {
    if (minutes === null || tenders === null || !props.writable) return;
    setSaving(true); setMsg(null);
    try {
      const ack = await saveSettings((u, i) => window.fetch(u, i), { attachTimeLimitMinutes: minutes, ignoreRobotsTxt: draft.ignoreRobots, ...(hasLimit ? { maxTendersPerPortal: tenders } : {}) });
      setDraft(draftFrom(ack));
      props.onSaved(ack);
      setMsg({ ok: true, text: "Settings saved." });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Save failed. Your edits are kept." });
    } finally { setSaving(false); }
  }

  return (
    <Sheet open={props.open} onOpenChange={props.onOpenChange}>
      <SheetContent className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle className="text-section">Settings</SheetTitle>
          <SheetDescription>{props.writable ? "Applies to all portals." : props.readOnlyReason ?? "Read-only while showing demo data or while the API is offline."}</SheetDescription>
        </SheetHeader>
        <form className="mt-6 flex flex-col gap-6" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <div className="flex flex-col gap-2">
            <Label htmlFor="limit" className="text-label">Attach time limit (minutes)</Label>
            <Input id="limit" inputMode="numeric" value={draft.minutes} disabled={!props.writable}
              aria-invalid={minutes === null} aria-describedby="limit-help"
              onChange={(e) => setDraft({ ...draft, minutes: e.target.value, dirtyMinutes: true })} />
            <p id="limit-help" className="text-label text-muted-foreground">Publish validated records when the limit is reached.</p>
            {minutes === null && <p className="text-label text-failed">Enter a positive whole number.</p>}
          </div>
          {hasLimit && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="tender-limit" className="text-label">Most tenders per portal (0 = no limit)</Label>
              <Input id="tender-limit" inputMode="numeric" value={draft.tenders} disabled={!props.writable}
                aria-invalid={tenders === null} aria-describedby="tender-limit-help"
                onChange={(e) => setDraft({ ...draft, tenders: e.target.value, dirtyTenders: true })} />
              {limitNote && (
                <p id="tender-limit-help" className={limitNote.warn ? "flex gap-2 rounded-md bg-healing-tint p-3 text-label text-healing" : "text-label text-muted-foreground"}>
                  {limitNote.warn && <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />}
                  {limitNote.text}
                </p>
              )}
              {tenders === null && <p className="text-label text-failed">Enter a whole number from 0 to 100,000.</p>}
            </div>
          )}
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="robots" className="text-label">Ignore robots.txt (testing only)</Label>
              <Switch id="robots" checked={draft.ignoreRobots} disabled={!props.writable}
                onCheckedChange={(v) => setDraft({ ...draft, ignoreRobots: v, dirtyRobots: true })} />
            </div>
            <p className="flex gap-2 rounded-md bg-healing-tint p-3 text-label text-healing">
              <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
              Use only on portals you have permission to test. Login and CAPTCHA blocks are never bypassed.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={!props.writable || saving || minutes === null || tenders === null || !dirty}>{saving ? "Saving…" : "Save settings"}</Button>
            <p role="status" className={msg?.ok ? "text-label text-serving" : "text-label text-failed"}>{msg?.text}</p>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}
