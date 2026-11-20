# Q3. Explore or map first?

Research date: 2026-11-20. Hackathon: Patterno track.

**Summary:**
Probe structured sources first: an XHR/JSON API, OCDS, a TED or national feed, ATOM/RSS, then sitemaps. If none exists, explore toward the goal with a page budget. Do not map the site first. At 1 req/s, enumerating every tender and document takes most of the request budget whichever option you choose. Mapping first only adds hundreds to thousands of requests before any tender is delivered.

---

## Q3. Explore or map first?

### Recommendation

**Probe structured sources first** with roughly 10-25 requests. **Then explore toward the goal** from the entry URL with a hard budget of about 60 pages. **Never crawl the whole site to map it.** Read the sitemap only if it is small, and only as a hint for the explorer.

### Why

- **APIs beat browsing.** In ["Beyond Browsing: API-Based Web Agents"](https://arxiv.org/pdf/2410.16464), an API-based agent scored **29.2%** on WebArena against **14.8%** for a browsing agent. A **hybrid** agent scored **38.9%**. So the agent should look for the JSON behind JS apps before it parses rendered HTML.
- **The real cost is enumeration, not learning.** Delivering every open tender with its documents costs about 1 list request per page, 1 detail request per tender (unless the list or API already carries the fields) and 1+ request per document. That cost is the same under either strategy. Mapping first adds a classification crawl on top, and sitemaps on procurement portals often list *historical* notices, which can run to hundreds of thousands.

### Requests attach needs (worked example: 300 open tenders, 20 per list page, 3 files per tender)

| Phase | Explore-first (recommended) | Map-first |
|---|---|---|
| Structured probe (robots.txt, sitemap index, /feed, /rss, /atom, /api, /ocds, well-known paths) | 10-25 | 10-25 |
| Learning (find list, detail, files) | 20-60 page visits, with their JSON calls | Sitemap fetch, then crawl and cluster 300-3,000 URLs to label page types |
| Enumerate list | 15 | 15 |
| Detail pages | 300 (0 if the API carries the fields) | 300 |
| Documents | ~900 | ~900 |
| **Total** | **~1,250-1,300 = ~21 min** | **~1,500-4,300 = ~25-72 min** |
| Via OCDS/JSON API instead of HTML | **list ~3-5 + docs ~900 -> ~16 min** | n/a |

At 1 req/s you get at most 3,600 requests an hour. "Minutes" is only achievable for tender metadata, so **document downloads must be streamed after metadata**, and the dashboard should show the portal as `integrating` until they finish. Recommended ordering:

1. Deliver all tender records first.
2. Then fetch documents round-robin across tenders.
3. Fetch large ZIPs last. A ZIP over 1 GB is a single request, so it uses only one rate-limit token, but it holds a connection open for a long time.

### Structured sources: how common?

- **OCDS.** The [OCP Data Registry](https://data.open-contracting.org/en/search/) lists **136 datasets** and states "over 100 publishers" ([registry home](https://data.open-contracting.org/)). The European entries include UK Find a Tender, Croatia (Narodne Novine) and Slovenia via TheyBuyForYou. They also include OpenTender (GTI), which republishes data from **35 jurisdictions**: the 27 EU member states plus EU institutions, Georgia, Iceland, North Macedonia, Norway, Serbia, Switzerland and the UK, drawn from TED and national portals. OCDS is common for national portals in some countries, but most regional and municipal portals don't publish it.
- **TED.** Every above-threshold EU notice is on TED, and the [TED Search API v3](https://api.ted.europa.eu/api-v3.yaml) needs **no key for search**. It is a single `POST /v3/notices/search` with an expert query, `scope: ACTIVE` for currently open notices, up to 250 results per page and iteration tokens. The TED OpenAPI spec caps the PAGE_NUMBER pagination mode at 15,000 notices per query ("To retrieve more notices, you can use the ITERATION mode"). The iteration-token mode we use has no such cap. The TED HTML detail page loads the notice body with JavaScript. Our fetch got only navigation chrome, about 2.2k tokens of noise, so **never** use TED HTML.
  - TED is a **cross-check, not a source**. Below-threshold tenders aren't on it, and the judges want the *portal's* own ids and document links. Its main use is in the validator. If TED lists a notice whose buyer-profile URL is this portal, and our crawl missed it, attach is incomplete.
- **National ATOM feeds.** Spain's PLACSP publishes CODICE-in-ATOM syndication. Feed `sindicacion_643` holds about 500 entries per file, chained with `next` links, and comes with monthly ZIP archives ([Hacienda open data](https://www.hacienda.gob.es/es-ES/GobiernoAbierto/Datos%20Abiertos/Paginas/LicitacionesContratante.aspx); [syndication spec](https://contrataciondelsectorpublico.gob.es/datosabiertos/especificacion-sindicacion.pdf)).
- **Hidden JSON APIs.** Hidden JSON APIs are the norm for SPA portals. Find them by capturing XHR/fetch traffic during the first few page loads (Q4).

### Ordered probe checklist (run before any HTML crawl, all through the limiter)

1. **Entry page in a browser with network capture.** Record same-origin `xhr`/`fetch` responses with JSON content type. If list-like arrays appear (objects with title/date/id), promote them to an `http_json` node. This step catches most SPA portals in one page load.
2. **Platform fingerprint.** Check generator meta tags, script paths, cookie names and footer text. Match against the template library (Q11). If it matches, try the known recipe first.
3. **`/robots.txt`.** Read Sitemap lines and disallow rules.
4. **Feed discovery.** Look for `<link rel="alternate" type="application/atom+xml|rss+xml">` on the entry page. Probe `/feed`, `/rss`, `/atom` and `*.atom`, and `sindicacion` paths on Spanish portals.
5. **OCDS endpoints.** Probe `/api/*/ocds*`, `/ocds`, and `releasePackages`/`recordPackages`. Check the OCP Data Registry offline beforehand by hostname, which costs no portal requests.
6. **Documented APIs.** Probe `/api`, `/swagger`, `/openapi.json` and `/api-docs`.
7. **Sitemap (index only).** If a child sitemap's URLs match a tender-detail pattern and carry `lastmod`, use it as a change hint for repair, not for enumeration.
8. **TED cross-check (off-portal, separate rate budget).** Query TED for notices from this buyer-profile domain to estimate how many open tenders to expect.

### Prototype first (Q3)

- **Probe sequence plus XHR JSON detector. ~4 h.** Run it on FTS, PLACSP and 2 SPA portals, and log the request count.
- **Goal-directed explorer with a 60-page budget. ~4 h**, using Q4's tools.

---

## Changes to other open questions (from the Q1, Q3 and Q4 research together)

- **Q2 (field locators):** Each field should be a *locator bundle*: primary selector, fallbacks, label-text anchor and a value regex or type. This follows Co-Scraper's fallback wrappers and SG-WRAM's preserved features. Prefer JSONPath whenever an API exists.
- **Q5 (agent framework):** You probably need none. A plain OpenAI tool-calling loop over ~8 tools is enough. Avoid browser-use, because its own planner loop overlaps this question.
- **Q6 (language):** Python 3.12 works. Playwright Python, httpx and asyncio cover everything, and there is no need to run Node for Playwright MCP.
- **Q7 (schemas):** Write the recipe schema in the OpenAI strict subset: flat `nodes`/`edges` arrays, every field required, optional fields as `null`-unions, no root `anyOf`.
- **Q8 (benchmark):** Use FTS OCDS, TED `scope: ACTIVE` and the PLACSP ATOM feed as ground truth to score our HTML attach on the matching portals, and model choice with it.
- **Q9 (models and cost):** Budget about 100-300K tokens for learning and much less for each repair. HTML views favour stronger models, so a cheaper model may work for navigation and a stronger one for locator writing.
- **Q10 (failure rules):** "Bot detection on HTML but the API works" means `serving`, not `failed`. Mark the portal `failed` only when every route needs login or a captcha. Use the JAIR result (verification recall 0.95, precision 0.73) as a reason to require two consecutive bad reads before entering `healing`.
- **Q11 (reuse across portals):** Platform fingerprints plus `subrecipe_ref` nodes, such as the external e-sourcing portals linked from FTS, are the reuse mechanism.
- **Q12 (large portals):** Use watermark-based incremental reads (`updatedFrom` with overlap, cursors). Load metadata first, then documents round-robin. Report progress during `integrating`, because full document sets won't fit in minutes at 1 req/s.

## Caveats

- Several token figures come from vendor or tutorial blogs (TestDino, RenderScreenshot, DeepWiki), not peer-reviewed papers. Treat them as order-of-magnitude figures.
- The AutoScraper break-even of about 10-30 pages per domain is our own calculation from the paper's Table 6 (GPT-4-Turbo timings), not a figure the paper states.
- Our subagent could not fetch raw HTML byte counts, the PLACSP feed, or a live FTS tender-stage release. The FTS `tenderPeriod.endDate` path and offset are inferred from the docs and must be checked first.
- Co-Scraper (June 2026) and several other cited works are recent preprints that have not been peer reviewed.

---

## Caveats

- Several token figures come from vendor or tutorial blogs (TestDino, RenderScreenshot, DeepWiki), not peer-reviewed papers. Treat them as order-of-magnitude figures.
- The AutoScraper break-even of about 10-30 pages per domain is our own calculation from the paper's Table 6 (GPT-4-Turbo timings), not a figure the paper states.
- Our subagent could not fetch raw HTML byte counts, the PLACSP feed, or a live FTS tender-stage release. The FTS `tenderPeriod.endDate` path and offset are inferred from the docs and must be checked first.
- Co-Scraper (June 2026) and several other cited works are recent preprints that have not been peer reviewed.

---

## Addendum: German portals (accounts and deadlines)

Added 2026-11-20 from a separate web search. The main report above does not cover Germany. Treat this as a lead to verify, not a tested result.

### Do you need an account?

Usually not for reading. Germany has no single portal, so the answer depends on the platform a tender sits on.

- **Where tenders are listed (no account):** [service.bund.de](https://www.service.bund.de) lists national tenders and [oeffentlichevergabe.de](https://oeffentlichevergabe.de) lists EU-wide ones ([Lower Saxony platform overview, 2 Dec 2025](https://www.mw.niedersachsen.de/download/223791/Uebersicht_Vergabeplattformen.pdf)). Bremen's guidance says the central notice service can be used [without authentication](https://www.service.bremen.de/dienstleistungen/vorinformationen-zu-auftragsbekanntmachungen-einsehen-179541). The OCP registry lists it as an OCDS publisher, reviewed Jan 2024 ([OCP](https://data.open-contracting.org/en/publication/136)). Probe this first, following the Q3 checklist.
- **Where the documents live:** Notices link out to many platforms, including evergabe-online.de, DTVP, vergabe.fraunhofer.de and meinauftrag.rib.de ([TED example 1](https://ted.europa.eu/en/notice/301973-2026/pdf), [example 2](https://ted.europa.eu/en/notice/234211-2026/pdf), [example 3](https://ted.europa.eu/en/notice/369917-2026/pdf)).
- **Federal evergabe-online.de:** One notice says documents can be downloaded free of charge without registration ([TED 149260-2025](https://ted.europa.eu/de/notice/149260-2025/pdf)). Another says there is no obligation to register, but updates reach you automatically only if you registered beforehand ([TED 285266-2024](https://ted.europa.eu/de/notice/285266-2024/pdf)).
- **DTVP:** A DTVP guide says registration is not always required to download tender documents ([guide](https://www.einbeck.de/downloads/datei/NzA4MGZjN2I3YTM0ZGZlMG9MRXprOVp1VmVqSXNyR2dJRHgyem1kd3B4QVJZR1IxaUx1T0FpRTZEZXhGMml1d1NRTFdDSDMydW9HZzBDRDBoa1JkVVM0dlExaXJpaU5Uc3crZVVBYllGL2dsQk04NWpob2k5b1BRdU43VWhjUCsweTh1b09KNjhwVUhUMkNUdUNyYkkrUWtGMnNRaHZ5amNtbVFBR3JQRDA2K29EQmh1RUtsZkNQYU10Zz0)). "Not always" means some buyers do require it.
- **Not confirmed:** The rules for other platforms, such as Bavaria's [auftraege.bayern.de](https://www.bayernportal.de/dokumente/leistung/2894921985168?locale=en), which offers searching, viewing notices and downloading documents but does not say whether that needs an account.

### Design consequences

- Registration is optional for reading but needed for updates, bidder questions and bidding. The "no logins" rule therefore doesn't block Attach on most German tenders.
- **Notice and Q10:** If a particular buyer requires login for the files, that portal reports `failed` with the reason. If metadata is readable and only some documents are gated, mark those documents as unresolved. Don't mark the whole portal `failed`, and don't output guessed values.
- **Q11:** Each German platform (evergabe-online, DTVP, and so on) is a separate platform fingerprint with its own recipe. The `subrecipe_ref` mechanism fits this, because the notice portal links to them.

### Deadlines

- German tenders carry submission deadlines, so `submissionDeadline` should be filled. TED shows them with an explicit offset, for example `04/03/2026 23:59:59 (UTC+01:00)` ([TED 86983-2026](https://ted.europa.eu/en/notice/86983-2026/pdf)). Use TED as a cross-check for the portal's own value.
- **Which deadline:** Notices often list several dates, such as the deadline for requesting additional information. The recipe must map the tender-submission date specifically, and the validator should check it is later than the publication date.
- **Local time:** Portals usually show German local time without an offset, so the engine has to add one. Use the Europe/Berlin zone, which switches between +01:00 and +02:00 with daylight saving. Don't hardcode +01:00.
- **Not verified:** Whether the deadline is visible without an account on each German platform. It sits in the notice itself, so it is probably public.

### Verify first (~1 h)

Open one evergabe-online tender and one DTVP tender in a clean browser session with no cookies. Check that the documents download and the deadline is visible.
