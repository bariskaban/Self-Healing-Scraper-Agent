# The dashboard, technically: notes for Danil

Written 21 Nov 2026, about 01:40 UTC, by Goktug's Claude session, from a review a sub-agent made. It is the companion of `dashboard-design-review-2026-11-21.md` and is offered in the same spirit: what was run, what was seen, and why it might matter. What to do with it is yours and your session's to decide. Nothing in the dashboard was changed.

## What was run

- The deployed page (`patterno-watchtower.vercel.app`) compared with `main`.
- A clean build: `bun install`, `bun run build`, `bunx tsc --noEmit`, `bun run test`, `bun run lint`.
- The built page in a browser (Playwright) against the real backend running locally on the two mock portals: one serving, one behind a login wall (failed), one with its layout changed (healing).
- The source under `dashboard/src` for the cases that could not be produced locally.

Each remark below says whether it was seen running or only read in the source.

## What holds

| Checked | Result |
| --- | --- |
| Deployed page against `main` | The same build: `index.html` identical, the same `index-3hc8M4I_.js` and `index-BfS33PG-.css`. The deployed JS differs by line endings only. |
| Build from a clean checkout | Succeeds, and `dist/` equals what is committed under `app/dashboard/static/`, contents included. |
| Type check and tests | `tsc --noEmit` exits 0; 105 tests in 10 files pass. |
| The three states on real data | Serving, failed (login wall) and healing each show the state and the reason sentence; healing shows the "still serving 45 tenders" chip. No console errors. |
| Cost | "0.00 EUR / 0 tokens" at zero usage; nowhere NaN or undefined. |
| Add portal | Rejects "not a url", `ftp://…` and a host without a dot with a clear line; adds a valid address; with the API down it says "Not added: The API did not answer." |
| The API going away | The header says "API offline, retrying / Last update N s ago", the last data stays, the change is announced in an aria-live region, and the page is "Live" again on the next poll after the API returns. |
| Polling | Every 5 s, one request at a time, a 4 s timeout with abort; timelines only when a portal's last run changed, for at most 16 portals. No growth in memory over about three minutes. |
| Portal text | Rendered as React text. The one `dangerouslySetInnerHTML` (`ui/chart.tsx:73`) builds CSS from chart colours, not from portal text. Links are limited to http and https. |
| Keyboard | Tab reaches Theme, Settings, Add portal, each portal and Details in order; the dialog is labelled. |

That is a solid base: the page is honest about being offline, does not pile up requests, and does not put portal text where it could do harm.

## Three things that seem worth a look before the recording

### 1. An outage has no words on the page

Seen in the source, not running. Since pull request 57 the backend reports an outage as `failed` with `cause: "outage"`, from the first read that finds it, while the portal keeps delivering its last good tenders. On the page the tooltip of the failed state says "Needs a person: … (a login, a block or a failed repair)" (`src/data/view.ts:13`), the counter says "N need attention" (`components/ledger/overview.ts:19`), and the cause is shown only in the eyebrow of a portal's detail page (`PortalDetail.tsx:61`). The word "outage" does not occur in the components.

Why it may matter: a portal that is merely not answering for three minutes, and still delivers everything it had, would read as an emergency for a person. That is the opposite of what the backend now says about it, and "the state it reports matches what it delivers" is its own judging line.

What would cover it is small, by the reviewer's estimate about six lines: the cause as a chip next to the state badge (`primitives.tsx:25`), a tooltip for failed that also names an outage ("or the portal is not answering: last good tenders still served, checked again automatically"), and `stillServing` (`overview.ts:26`) extended to a failed portal whose cause is outage and whose tender count is above zero. The design note arrives at the same place from the other side (its point 3).

### 2. The overview's "what the system did" is written but not shown

Confirmed by reading: `spotlight()` is defined in `App.tsx:70-78` and never called, so `Spotlight`, `RepairBand`, `latestRepair` and the ticker do not render on the overview. A repair is visible inside a portal's detail page, and there the live card only while a repair is running; a finished one is a row of the timeline. The handling of `kind: "repair"` and `recipeChange` in `evidence.ts` reads correctly, but no real repair was produced in the review (it needs an OpenAI key), so that it renders was not seen.

Why it may matter: the overview is what a recording shows first, and the repair is the product's best story. One line, `{spotlight()}` above the ledger, would bring it back; if it was left out on purpose, the dead code could go instead. Either way it would be worth one look with `?demo` afterwards. The design note's point 1 is the same observation.

### 3. One unexpected value from the API takes the whole page offline

Read in the source. `portalStateSchema` and `dashboardSchema` are strict (`schema.ts:21, 38-41`). If the API ever sends a state the schema does not know, or leaves out a required field such as `reason`, validation of the whole dashboard fails; the page then falls back to the contract routes, which are just as strict about `state`, and ends at "offline" while the API is healthy.

Why it may matter: it is the kind of failure that appears during a demo and looks like the backend's fault. Nothing in tonight's backend changes adds a state or drops a field, so it is a guard, not a known break. About four lines would do it: `.catch("failed")` on the state and `.catch(null)` on the cause, or at the least logging the zod error in `getJson` (`api.ts`, around line 50) so the reason is visible in the console.

## Smaller things

- **Healing without a key.** The tooltip says "the site changed" and the fleet sentence says "repairing itself" for a healing portal whose cause is a breakage. Without `OPENAI_API_KEY` nothing repairs and it stays healing (seen locally). That is right for production; it only means the key should be set wherever the recording runs.
- **Lint.** `bun run lint` reports 1258 problems, of which 1243 are prettier formatting; the two real ones are `no-explicit-any` at `src/data/api.ts:21`. Nothing that affects what ships, but a formatter run would make the next real warning visible.
- **Bundle.** One JS chunk of 908 kB (253 kB gzipped). Fine for this use; splitting TV mode and the charts would be the first step if it ever matters.
- **Cost average.** `costPerPortal` (`overview.ts:30-32`) averages `usage?.costEur ?? 0`, so a portal whose usage is not recorded counts as zero. Correct for the mock; on real data it could understate the average.
- **An address with a space** (`https://a.b/with space`) is accepted by the page and the server and creates a portal (`portals.ts:19-22`).
- **Loose ends.** `useTheme` in `data/hooks.ts` is unused; the hint for an empty fleet in `PortalLedger.tsx:155` shows a `localhost` curl example.
- **Colour alone.** State is always text plus icon. Only the chart bars rely on green and red, and they have text summaries next to them.

## Not checked

A real repair run on the page; an outage on a failed portal other than in the demo data; a fleet of more than 16 portals; polling over hours; the phone layout (the design note covers it); the page as served from the Docker image.
