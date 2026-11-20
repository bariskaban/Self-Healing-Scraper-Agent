
# Research: Watchtower real-portal test set (Patterno seed + candidates)

Date of research: 20 Nov 2026. Fetch budget used: 22 of 45 (max 3 per portal respected). Searches are not counted as fetches.

## Question

Which real European public-procurement portals make a test set for Watchtower (Patterno track): at least 8 portals, 4+ countries, 3+ software families, mixed rendering (server HTML, JS app + JSON API, multi-step document download), 1-2 login/captcha portals expected to fail, and 2 kept unseen?

## Answer

- 14 candidates recorded: 6 countries (NL, DE, AT, FR, ES, PL) plus one multi-country login platform (Mercell); at least 6 software families.
- Rendering: 1 JSON API (TenderNed), 6 server HTML verified (NRW VMPSatellite, tender24, Frankfurt, AT eProcurement, PLACSP detail, platformazakupowa), 1 JS app (ezamowienia mp-client), rest not confirmed.
- Best first end-to-end targets: (1) TenderNed JSON API (no key, documents via /documenten), (2) evergabe.nrw.de VMPSatellite (server HTML, per-notice document tab).
- Expected failed (login): Mercell (my.mercell.com / EU-Supply). Second login candidate: Deutsche eVergabe portal (ZIP download needs registration; not live-confirmed).
- Keep unseen: ausschreibungen.usp.gv.at (AT) and platformazakupowa.pl (PL, Open Nexus). PLACE (FR) returned a suspension notice on 20 Nov 2026, so use it as the "failed/unavailable" control, not for the success path.

## Evidence

Table (all rows; "verified" = seen in a fetch on 20 Nov 2026, "snippet" = search result only):

| # | Country | Portal | Software family | List URL | Rendering | Open tenders visible | Pagination | Docs reachable without login (one tender) | Login/captcha | Why useful |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | NL | TenderNed | TenderNed own, public REST (papi/tenderned-rs-tns/v2) | https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties?page=0&size=20 (human list: https://www.tenderned.nl/announcements/overview) | JSON API (verified) | totalElements 1707 with publicatieDatumVanaf=2026-11-01 (verified) | Spring page/size; totalPages in JSON (verified) | Yes: publicatie 450411 -> /publicaties/450411/documenten lists 51 docs with /content download hrefs (verified) | None on public API. XML Notice API needs account (not used) | Cleanest JSON API; multi-step doc chain |
| 2 | DE | Vergabesatellit NRW (eVergabe NRW) | cosinex VMPSatellite | https://evergabe.nrw.de/VMPSatellite/company/announcements/categoryOverview.do?method=show (category page, verified); full list via "Alle Bekanntmachungen" | Server HTML (verified) | 1204 total entries (snippet, 19 Nov 2026) | "Seite 1 von 61" links (snippet) | Partly: notice CXPNYBBDWCE/documents lists 15 files with names and dates (verified); download href not confirmed | None seen | Server HTML, high volume, per-notice document tab |
| 3 | DE | tender24 (AI Vergabeplattform) | AI Vergabe@Net / NetServer | https://tender24.de/NetServer/PublicationSearchControllerServlet?function=SearchPublications&Category=InvitationToTender&Gesetzesgrundlage=All&Max=25&Start=0 | Server HTML (verified) | 25 rows per page (verified); total not shown | Start offset + Max=25 (verified) | Not checked (no tender detail URL fetched) | None on list | Offset pagination, NetServer family |
| 4 | DE | Vergabeplattform Frankfurt am Main | NetServer (vendor not named on page) | https://vergabe.stadt-frankfurt.de/NetServer/index.jsp?function=Search&OrderBy=Publishing&Order=desc | Server HTML (verified) | 10 rows (verified) | None visible (verified) | Not checked | None on list; registration only for bidder functions | Single-page list, small city portal |
| 5 | DE | Vergabemarktplatz Brandenburg (VMPCenter) | cosinex / NetServer (per Patterno list) | https://vergabemarktplatz.brandenburg.de/VMPCenter/company/announcements/categoryOverview.do?method=show | Not confirmed (.do servlet pattern) | about 20 (fetch estimate, not exact) | Not confirmed | Not checked | Not checked | Second VMP instance, same URL style as NRW |
| 6 | DE | DTVP Deutsches Vergabeportal | cosinex-based JV (per Patterno list) | https://dtvp.de/ausschreibungen | Not confirmed (fetch returned no rows) | Not confirmed | Not confirmed | Yes per BaFin guide (snippet 14 Nov 2026): download without registration; Q and A and bids need registration | Registration for bidder functions; no captcha seen | National platform; secondary-source only |
| 7 | DE | evergabe.de | evergabe.de / AI Bietercockpit | https://evergabe.de/unterlagen (direct search by tender number, per FAQ) | Not checked | Not checked | Not checked | Yes per evergabe.de FAQ (snippet, 23 May 2026): download without registration; participation needs free registration | Registration for participation | Login boundary test: docs open, participation gated |
| 8 | DE | Deutsche eVergabe portal | Healy Hudson (per Patterno list) | https://portal.deutsche-evergabe.de/dashboards/dashboard_off | Unclear (fetch showed no tender rows) | Not confirmed | Not confirmed | ZIP download needs registration (portal text, verified); single-file not checked | Registration wall for ZIP. EXPECTED FAILED candidate | Login-gated candidate |
| 9 | AT | eProcurement Austria (BMDW eproc-p) | BMDW own (eproc-p) | https://ausschreibungen.usp.gv.at/at.gv.bmdw.eproc-p/public/tenderlist?load=true | Server HTML (verified) | 25 rows per page (verified); 175140 results (verified) | start=offset parameter (verified) | Not confirmed: A14 notice page listed no documents (verified) | None seen | KEEP UNSEEN. Large volume, offset pagination |
| 10 | FR | PLACE (marches-publics.gouv.fr) | State platform PLACE | https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseAdvancedSearch&AllCons | Not checked: site returned a suspension notice (verified, 20 Nov 2026) | Not checked | Not checked | Per Expertise France guide (2025): DCE download via Publicite/Telechargement tab; not confirmed live | Suspension notice ("critical vulnerabilities"), not login | Failed/unavailable control. Retry later |
| 11 | ES | PLACSP (contrataciondelestado.es) | PLACSP own (CODICE / Atom) | https://contrataciondelestado.es/wps/portal/plataforma (search: Buscadores > Licitaciones) | Server HTML on detail page (verified) | Not counted | Result table; open Atom feeds with 500 entries per file, rel=next (snippet) | Yes: detail page lists pliego docs with GetDocumentByIdServlet download links (verified, no login). Example detail: https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=nC%2Bgi%2F3gfYY%2FbjW6njtWLw%3D%3D | None seen | Multi-doc server HTML plus open bulk feed (sindicacion_643) |
| 12 | PL | e-Zamowienia (ezamowienia.gov.pl) | UZP own (Angular mp-client; BZP) | BZP notice example: https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/2026%2FBZP%2000083126%2F01 ; search list: https://ezamowienia.gov.pl/mp-client/search/list | Mixed: notice = server HTML (verified); mp-client = JS app shell (verified) | Not counted | Not confirmed | Not confirmed: DCE page in mp-client is JS-only in fetch; notice links some docs to an external municipal BIP | None seen | Mixed rendering, external document hosts |
| 13 | PL | platformazakupowa.pl (Open Nexus) | Open Nexus | https://platformazakupowa.pl/all | Server HTML (verified) | 31 rows visible (verified) | Not shown | Not confirmed: detail /transakcja/1394941 showed no docs section (verified) | None seen | KEEP UNSEEN. Used by many PL buyers |
| 14 | multi (UK, SE, DK seen) | Mercell (my.mercell.com; EU-Supply / CTM) | Mercell CTM / EU-Supply | https://my.mercell.com/ | Login page (verified); JS not confirmed | Not checked (eu.eu-supply.com fetch gave no content) | Not checked | No: docs need account plus "Accept" / expression of interest (vendor support pages, snippets 1 Oct 2026 and 18 Feb 2025) | Login page seen. EXPECTED FAILED (login) | Login-gated test |

Coverage:
- Countries: NL 1, DE 7 (rows 2-8), AT 1, FR 1, ES 1, PL 2, multi 1. Six countries with portals.
- Software families: TenderNed, cosinex VMPSatellite, NetServer/AI (tender24, Frankfurt), Healy Hudson (Deutsche eVergabe), BMDW eproc-p, PLACE, PLACSP, UZP e-Zamowienia, Open Nexus, Mercell CTM, DTVP, evergabe.de. At least 6 platforms with different software.
- Rendering: JSON API (row 1); server HTML verified (rows 2, 3, 4, 9, 11 detail, 12 notice, 13); JS app (row 12 list); login-gated (rows 8, 14); unknown (rows 5, 6, 7, 10).
- Multi-step document download: row 1 (publication -> documenten -> content), row 11 (detail -> document servlet), row 2 (notice -> documents tab), row 12 (notice -> external BIP).
- Login/captcha: row 14 (expected failed), row 8 (expected failed candidate). No captcha seen on any page.
- Keep unseen: rows 9 and 13.

Sources (access date 20 Nov 2026 for fetches; snippet dates in brackets):
- https://patterno.de/de/vergabe-portale (seed list, 30 portals; fetched via www.patterno.de/de/vergabe-portale, 20 Nov 2026). Sub-pages not visited (budget).
- https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties?page=0&size=3&publicatieDatumVanaf=2026-11-01 (fetched 20 Nov 2026)
- https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties/450411/documenten (fetched 20 Nov 2026)
- https://opendataindex.nl/bron/tenderned (snippet, 18 Nov 2026; endpoint list and 146,559 publications)
- https://data.europa.eu/data/datasets/aankondigingen-van-overheidsopdrachten-tenderned?locale=en (snippet, 14 Sep 2026; API and RSS)
- https://evergabe.nrw.de/VMPSatellite/company/announcements/categoryOverview.do?method=show (fetched 20 Nov 2026)
- https://www.evergabe.nrw.de/VMPSatellite/public/company/project/CXPNYBBDWCE/de/documents (fetched 20 Nov 2026); https://evergabe.nrw.de/VMPSatellite/notice/CXPNYBBDWCE/documents (snippet 14 Nov 2026)
- https://evergabe.nrw.de/VMPSatellite (snippet, 19 Nov 2026; 1204 entries)
- https://tender24.de/NetServer/PublicationSearchControllerServlet?function=SearchPublications&Category=InvitationToTender&Gesetzesgrundlage=All&Max=25&Start=0 (fetched 20 Nov 2026)
- https://vergabe.stadt-frankfurt.de/NetServer/index.jsp?function=Search&OrderBy=Publishing&Order=desc (fetched 20 Nov 2026); https://vergabe.stadt-frankfurt.de/NetServer/index.jsp (fetched 20 Nov 2026)
- https://vergabemarktplatz.brandenburg.de/VMPCenter/company/welcome.do (fetched 20 Nov 2026)
- https://dtvp.de/ausschreibungen (fetched 20 Nov 2026, no rows); https://www.bafin.de/SharedDocs/Downloads/DE/Vergabeunterlagen/Hilfestellung_DTVP.pdf (snippet, 14 Nov 2026); https://vergabekompass.com/glossar/dtvp (snippet, 19 Nov 2026)
- https://evergabe.de/faq/auftragssuche-angebotsabgaben-bietercockpit/vergabeunterlagen-herunterladen-teilnahme-ausschreibung (snippet, 23 May 2026); https://evergabe.de/faq/administration/bieterkonto-vergabeteilnahme (snippet, 14 Nov 2026)
- https://portal.deutsche-evergabe.de/dashboards/dashboard_off (fetched 20 Nov 2026; snippet 19 Nov 2026)
- https://ausschreibungen.usp.gv.at/at.gv.bmdw.eproc-p/public/tenderlist?load=true (fetched 20 Nov 2026: 25 rows, 175140 results)
- https://ausschreibungen.usp.gv.at/at.gv.bmdw.eproc-p/public/notice-detail?backlink=L2F0Lmd2LmJtZHcuZXByb2MtcC9wdWJsaWMvdGVuZGVybGlzdD9sb2FkPXRydWU%3D&object=41a809d9-0b61-4991-86b8-74dc07973af3-8346779d-07fc-46a8-be02-02873917b41e&orderColumn=2&orderDir=desc&start=0 (fetched 20 Nov 2026)
- https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseAdvancedSearch&AllCons and https://www.marches-publics.gouv.fr/?page=Entreprise.AccueilEntreprise (both fetched 20 Nov 2026: suspension notice)
- https://expertisefrance.fr/sites/expertise/files/2025-07/daj_gu006eng_v01-place-user-guide-for-companies-1.pdf (snippet, 5 Nov 2026)
- https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=nC%2Bgi%2F3gfYY%2FbjW6njtWLw%3D%3D (fetched 20 Nov 2026); https://boe.es/diario_boe/txt.php?id=BOE-B-2026-34324 (snippet, 20 Nov 2026)
- https://contratacionabierta.com/fuentes/placsp-licitaciones (snippet, 10 Nov 2026); https://contratacionabierta.com/descargas (snippet, 19 Nov 2026); https://licitaciones365.es/blog/plataforma-contratacion-sector-publico-placsp (snippet, 18 Nov 2026)
- https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/2026%2FBZP%2000083126%2F01 (fetched 20 Nov 2026); https://ezamowienia.gov.pl/mp-client/search/list/ocds-148610-dce04c19-2f6d-4a73-b639-92715c8200da (fetched 20 Nov 2026)
- https://platformazakupowa.pl/all (fetched 20 Nov 2026); https://platformazakupowa.pl/transakcja/1394941 (fetched 20 Nov 2026)
- https://my.mercell.com/ (fetched 20 Nov 2026); https://eu.eu-supply.com/ (fetched 20 Nov 2026, no content); https://support.mercell.com/space/MKB/198312034305/Understanding+the+Free+Version+of+Mercell+Bidding (snippet, 1 Oct 2026); https://community.mercell.com/uk-ireland-155/how-to-search-for-or-participate-in-tenders-in-eu-supply-245 (snippet, 18 Feb 2025)
- Excluded: https://service.bund.de/Content/DE/Ausschreibungen/Suche/Formular.html (aggregator, not a procurement portal); https://tendigo.de and https://zertlotse.de (aggregators).

## Open points

- PLACE (row 10) returned a suspension notice on 20 Nov 2026. Retest before using it; until then it is a "failed/unavailable" control only.
- Not checked live: tender24 document download (row 3), Frankfurt documents (row 4), Brandenburg rendering and docs (row 5), evergabe.de (row 7), Mercell live login (row 14, eu-supply.com returned no content).
- Deutsche eVergabe (row 8): login wall for ZIP confirmed from portal text only. Single-file download and the tender list were not confirmed.
- DTVP (row 6): docs-without-login rests on BaFin guide and a glossary page, not a live check.
- NRW VMPSatellite (row 2): download href for document files not confirmed; list total (1204) from search snippet.
- Vendor conflict: Patterno lists tender24 as AI AG (Vergabe@Net); the page is titled "AI VERGABEPLATTFORM". Frankfurt page does not name its vendor.
- Patterno sub-pages (e.g. subreport-elvis) not fetched (budget). Vendor data comes from the main list only.
- Expected-failed (login) portal count is 1 confirmed (Mercell) plus 1 candidate (Deutsche eVergabe). Captcha: none seen on any visited page.
