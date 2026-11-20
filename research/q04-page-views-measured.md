
# Q4 Page Views Measured (20 Nov 2026)

For David's Q4 ("what page view does the learning agent see"). Board: Agent Board. Tokens = tiktoken `o200k_base`. Budget: ~60K input tokens per request.

## Recommendation

The learner should see **trimmed HTML with row-cutting applied to list pages only** (about 4K tokens on a 50-row list versus 49K raw), because it is the only view that keeps the `data-*`/`href`/`id`/`class` hooks a recipe needs (vmstart rows have no href at all, only `data-oid`, which markdown, a11y and text all drop). The spot check can use the plain-text or markdown view of the same page (0.4K to 2K tokens after row cut) to confirm labels and values cheaply, but must not be used to find selectors. Do NOT apply "first 3 siblings" cutting on detail pages: it deleted the deadline label on vmstart.

## Pages fetched

| Key | URL | Result |
|---|---|---|
| vmstart_home | https://vergabe.vmstart.de/NetServer/ | 200, static HTML (cosinex VMP "NetServer") |
| vmstart_list | .../NetServer/PublicationSearchControllerServlet?function=SearchPublications&Gesetzesgrundlage=All&Category=InvitationToTender&thContext=publications | 200, 50 rows (linked from the home nav) |
| vmstart_detail | .../NetServer/PublicationControllerServlet?function=Detail&TOID=...&Category=InvitationToTender | 200; URL obtained via the portal's own anonymous POST to `DataProvider` (what a row click does) |
| tenderned_list_shell | https://www.tenderned.nl/aankondigingen/overzicht (plain HTTP GET) | 200 but an Angular app shell, zero rows in the HTML |
| tenderned_list_rendered | same URL, rendered with Playwright Chromium, DOM after load | 50 cards, a `Laad meer` button |
| tenderned_detail_rendered | https://www.tenderned.nl/aankondigingen/overzicht/450432 (id taken from the JSON), rendered | tender detail |
| tenderned_json | https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties?page=0&size=20 | 200, JSON, 20 items of 147,349 |
| nrw (evergabe.nrw.de) | https://evergabe.nrw.de/VMPSatellite/notice/ | FAILED: redirects to .../public/company/project//de/overview and returns 404 "unerwarteter Fehler". Only the error page was measured (nrw_404). |
| fr (marches-publics.gouv.fr) | the AllCons search URL | FAILED: HTTP 503, maintenance notice (access suspended until 20 Nov 19:00 because of a vulnerability). Only the notice was measured (fr_503). |

## Tokens: page x view

"Cut" = row cutting applied (first 3 of a repeated run plus a comment with the count). The median row uses the 5 real pages that loaded; the median page by raw size is vmstart_list.

| Page | raw HTML | trimmed (literal rule) | trimmed (record rule) | trimmed, no cutting | markdown (full) | a11y tree (full) | text (full) | markdown (cut) | a11y (cut) | text (cut) |
|---|---|---|---|---|---|---|---|---|---|---|
| vmstart_home | 12,135 | 3,042 | 3,498 | 8,367 | 4,498 | 7,412 | 1,830 | 1,582 | 2,848 | 728 |
| vmstart_list (50 rows) | 49,404 | 3,396 | 4,008 | 38,264 | 23,819 | 36,125 | 7,788 | 1,965 | 3,219 | 584 |
| vmstart_detail | 8,074 | 1,708 | 1,955 | 5,548 | 2,866 | 5,730 | 1,610 | 879 | 1,613 | 386 |
| tenderned_list (rendered, 50 cards) | 234,669 | 5,854 | 5,954 | 31,745 | 4,867 | 5,557 | 3,718 | 679 | 1,039 | 413 |
| tenderned_detail (rendered) | 167,353 | 3,616 | 3,675 | 4,946 | 797 | 1,160 | 474 | 659 | 962 | 427 |
| **median of the 5** | **49,404** | **3,396** | **3,675** | **8,367** | **4,498** | **5,730** | **1,830** | **879** | **1,613** | **427** |
| tenderned_list as plain GET (SPA shell) | 27,042 | 23 | 23 | 36 | 4 | 0 | 0 | 7 | 4 | 1 |
| nrw 404 page | 3,408 | 737 | 884 | 1,150 | 478 | 781 | 155 | 240 | 545 | 90 |
| fr 503 page | 2,972 | 403 | 403 | 566 | 128 | 180 | 106 | 129 | 165 | 106 |

Notes: raw HTML of both rendered TenderNed pages (235K, 167K) is 3 to 4 times over the 60K budget (Angular inline CSS and state). Raw vmstart_list (49K) just fits. Trimmed with no cutting still fits (38K and 32K for 50 rows). The accessibility tree is Playwright `aria_snapshot()` on the page DOM with JavaScript disabled. Playwright and a Chromium headless shell were already installed, so this was not skipped.

### JSON (tenderned_json, tokens)

| raw (as served) | pretty-printed (indent 2) | sampled, pretty (arrays cut to 3 + count) | sampled, compact |
|---|---|---|---|
| 8,311 | 10,357 | 1,544 | 1,227 |

Facts from the JSON: top-level keys `content, first, last, totalElements, totalPages, size, numberOfElements, number` (pagination is in the body). Each item has `publicatieId`, `publicatieDatum`, `aanbestedingNaam`, `opdrachtgeverNaam`, `link` but no deadline (Sluitingsdatum). Only `content` is an array, so sampling cuts 20 items to 3 (page size 20 already makes raw cheap).

## Survival: do the learner's must-haves survive?

Y = present in that view, n = lost. "literal" and "record" are the two trimmed variants (rules below). Markdown, a11y and text are the full (uncut) views.

| Page | Needed thing | raw | trimmed literal | trimmed record | trimmed no-cut | markdown | a11y | text |
|---|---|---|---|---|---|---|---|---|
| vmstart_list | row identifier/link (`data-oid`; no href exists) | Y | Y | Y | Y | n | n | n |
| vmstart_list | deadline label "Abgabefrist" | Y | **n** | Y | Y | Y | Y | Y |
| vmstart_list | pagination links (`Start=50`) | Y | Y | Y | Y | Y | Y | n |
| tenderned_list | row link `/aankondigingen/overzicht/<id>` | Y | Y | Y | Y | Y | Y | n |
| tenderned_list | deadline label "Sluitingsdatum" | Y | Y | Y | Y | Y | Y | Y |
| tenderned_list | pagination control "Laad meer" (JS button, no href anywhere) | Y | Y | Y | Y | Y | Y | Y (label only) |
| vmstart_detail | deadline label "Ablauf der Frist fuer die Einreichung der Angebote" | Y | **n** | **n** | Y | Y | Y | Y |
| vmstart_detail | document link (`TenderingProcedureDetails`, "Unterlagen zur Ansicht herunterladen") | Y | Y | Y | Y | Y | Y | n as a link (the URL appears only as prose in one sentence) |
| tenderned_detail | "Sluitingsdatum" and "Aanvang opdracht" | Y | Y | Y | Y | Y | Y | Y |
| tenderned_detail | document links | n | n | n | n | n | n | n |

Findings behind the table:
- The "cut after the first 3 siblings" rule is dangerous when the repeated siblings are label/value rows, not records. On vmstart the 5 field rows inside each record share one class, so the literal rule kept only 3 of 5 and dropped "Abgabefrist" on the list page; on the detail page it dropped the whole "Ablauf der Frist" block. The record rule (cut only the outermost run, never inside kept records) fixed the list page but NOT the detail page. No cutting on detail pages is the only variant that keeps the deadline there.
- vmstart list rows have no `href`. A click handler (`script_net.js`) POSTs `OID` to `DataProvider` and navigates to the URL it returns. Only `data-oid` and `data-category` carry the link, so `data-*` must be kept, and markdown, a11y and text all lose it. The recipe needs a rule "detail URL = POST DataProvider" that no view shows by itself; the learner must also see the JS or be told.
- TenderNed list is client-rendered: a plain GET gives 27K raw tokens of shell and zero rows (a11y and text views of it are empty). This portal needs a rendered DOM (Playwright).
- TenderNed "Documenten" is a separate JS tab: its links are not in the detail DOM (label only), so no view can show document links without another interaction or the API.
- TenderNed pagination is "Laad meer" (load more), no page links. vmstart pagination is real `Start=` links.

## Exact trimming rules used (`scripts/views.py`)

1. Parse with BeautifulSoup and lxml. Remove HTML comments.
2. `<head>` emptied except `<title>`.
3. Delete tags: `script, style, svg, noscript, link, meta, iframe, template`.
4. Keep only the attributes `id, class, href, src, name, role, aria-label` and any `data-*`; delete all others (inline `style`, Angular `_ngcontent-*`, etc.). `class` list joined into one string. `href`/`src` starting with `data:` replaced by `data:...`.
5. Collapse every whitespace run inside text nodes to one space; remove whitespace between tags.
6. Row cutting: for each parent, drop child elements that have no text and no data-*/href/src (spacer elements such as empty `<tbody>`), then find runs of consecutive siblings with identical tag + class string; if a run is longer than 3, keep the first 3, delete the rest and insert `<!-- N more similar <tag> siblings omitted (T total) -->`.
   - literal: applied recursively everywhere (inside kept rows too).
   - record: applied only to the outermost run, not descending into kept rows.
   - no-cut: step 6 skipped.
7. Other views: markdown = markdownify (ATX headings) on the page with script/style/svg/noscript removed; a11y = Playwright `locator("body").aria_snapshot()` (JavaScript disabled, page loaded with `set_content`); text = `document.body.innerText`. The "cut" columns run these conversions on the trimmed-record HTML.

Files: `C:\Users\danil\AppData\Local\Temp\claude\6fe8190b17a30685\e91a31c0-f598-40e9-8332-82cb3f0318a2\scratchpad\q4\` with `pages\` (downloads), `scripts\` (fetch and measurement), `views\` (every view as text), `results.json`, `survival.json`.

## What failed or is uncertain

- evergabe.nrw.de list URL: redirect to a 404 error page (I did not search for another working NRW list URL). marches-publics.gouv.fr: 503 maintenance notice. Neither list was measured.
- Only 5 real pages on 2 portals (vmstart/cosinex and TenderNed), so the median is an order of magnitude only. Other vendors (big JS tables, DTVP, Bund.de) may be bigger.
- The TenderNed pages were rendered in Chromium, whose SPA makes its own API calls, possibly more than 1 request per second for the first seconds. Every explicit request I sent was at least 2 seconds apart, no logins.
- tiktoken `o200k_base` is a proxy; the real gpt-6.2-sol tokenizer may differ by a few percent.
- The first 3 rows are not a statistical sample; pages with varied row shapes (withdrawn or corrected notices) could be misrepresented.
- Pagination and label checks are regex tests on specific strings (`scripts/survive.py`), not a model reading the page.
