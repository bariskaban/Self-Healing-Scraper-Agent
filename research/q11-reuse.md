# Q11. Reuse across portals: detect known software, trust a reused recipe

Owner: Danil. Researched 20 Nov 2026 (web search, sources at the end). Vendor numbers are vendor claims.

## Recommendation

Fingerprint the software family with a cheap probe and no model call (host, URL path, page title, one structural check), then **trust a reused recipe only after a canary read on the new host passes every deterministic check**; the model spot check comes after, on the first full read. A fingerprint is a hint, never a key: the same `/NetServer/` path runs under two vendor brands.

## Families worth knowing

| Family | Countries | Size (cited) | Seen at | Public list without login | Signals |
|---|---|---|---|---|---|
| cosinex VMP / BMS / DTVP | DE | ">5,000 contracting authorities" (cosinex, Sep 2026) | evergabe.nrw.de/VMPSatellite, evergabe.blb.nrw.de | partly | path `/VMPSatellite/`, `projectForwarding.do?pid=` |
| AI Vergabeplattform (Administration Intelligence) | DE | not found | vergabe.vmstart.de/NetServer, tender24.de/NetServer | yes | path `/NetServer/`, title "AI Vergabeplattform", "AI BIETERCOCKPIT" |
| Healy Hudson NetServer (Vergabe24) | DE | not verified | vergabe24.de | not verified | same `/NetServer/` path as AI |
| subreport ELViS | DE | not verified | subreport-elvis.de, evergabemv.de | not verified | host |
| evergabe.de (runs AI software) | DE | "about 290,000 procedures a year" (vendor) | evergabe.de | yes (free, no registration) | host |
| Deutsche eVergabe | DE | not found | portal.deutsche-evergabe.de | partly | host |
| PLACE (French state) | FR | ~40,000 consultations in 2025 | marches-publics.gouv.fr | yes (anonymous DCE download) | `?page=Entreprise.` |
| Atexo buyer profiles | FR | ">50,000 buyers" (vendor) | not verified | not checked | not verified |
| Maximilien, Megalis, AWS-Achat, achatpublic, marches-securises | FR | not counted | host names only | not checked | host |
| PLACSP | ES | national platform | contrataciondelestado.es | yes | Atom feed `sindicacion_643` |
| Mercell (Negometrix, EU-Supply/CTM, TendSign) | NL, Nordics, EU | ~3,300 buyers (2022) | my.mercell.com, eu.eu-supply.com | not checked | host |
| Vortal | PT, ES, DE, AT, FR, IT and more | ">10,000 buyers" (vendor, 2022) | not verified | not checked | not verified |
| TenderNed | NL | 146,513 publications (Oct 2026) | tenderned.nl | yes | public REST `/papi/tenderned-rs-tns/` |
| platformazakupowa.pl (Open Nexus) | PL | 3,200 to 32,700 clients (sources conflict) | platformazakupowa.pl | not checked | host |
| e-Zamówienia (BZP) | PL | national | ezamowienia.gov.pl | yes | public REST `/mo-board/api/v1/`, 30 requests/min per IP |
| Italian certified platforms | IT | 60 platforms, 22,013 authorities (SDA Bocconi, Apr 2025) | not verified | partly | not verified |

**Patterno publishes its own portal list** with software families: https://patterno.de/de/vergabe-portale. That is the best seed for our test set (Q8) and the family table, since it is the judges' own view of the landscape.

## Fingerprint method

1. **Host and path** (from the address and the first response): known hosts and paths from the table above. Weak alone.
2. **Brand text**: page title, footer, "powered by", product names.
3. **Structure**: run the candidate recipe's list locators on the list page. This is the strongest signal, and it is already part of the canary.

Verified signatures to seed the table (fact-checked 20 Nov 2026 from published notices and docs):
- cosinex: `/Satellite/notice/` (dtvp.de) and `/VMPSatellite/notice/` (NRW and other VMP installations).
- PLACE: `?page=Entreprise.AccueilEntreprise` and `?page=Entreprise.EntrepriseAdvancedSearch`.
- PLACSP: tender deep links `/wps/poc?uri=deeplink:detalle_licitacion`, plus Atom/CODICE feeds.
- TenderNed: RSS `/papi/tenderned-rs-tns/rss/last-publication.rss`. The v2 public-xml API needs a username and password, so it is off limits.
- e-Zamówienia: notice pages `/mo-client-board/bzp/notice-details/`. The BZP API is public but allows only 30 requests/min per IP (HTTP 403 above that), and its page size drops to 100.
- BOAMP: open data API on boamp-datadila.opendatasoft.com.

Before fingerprinting HTML, the prober looks for structured sources **the portal itself exposes**, in this order:
1. JSON calls in the page's own network traffic.
2. `<link rel="alternate">` RSS/Atom.
3. `__NEXT_DATA__` or similar embedded app state.
4. `application/ld+json`.

In Playwright, cache the portal's own static scripts in memory per portal (inside `page.route()`), so a JS app does not spend its 1 request/s budget reloading the same bundle on every page.

Candidates are ordered by exact matches: host, then path, then brand text. The structural canary is the trust boundary. Add numeric scoring only if the team sees mis-ranking. Not yet checked: generator meta tags, script and style names, cookies. The research tool only saw rendered text, so the prototype checks these on raw HTML.

## How much installations differ

- Same vendor, different tenants: cosinex runs the NRW satellite, a sister instance and a separate federal instance, each with its own configuration.
- Same path, different vendors: `/NetServer/` (AI and Healy Hudson).
- No evidence found on template or version drift between installations.

So reuse the family's **navigation and locators**, and treat per-host settings (page size, filters, language, document format, login walls) as parameters to check on every new host.

## Trust rule

String-matched quotes prove the text is on the page, not that the locator took it from the right field; validators can pass a well-formed wrong value. So:

1. A host, path or brand match makes the family recipe a candidate: load it with this host's base URL.
2. **Canary** (about 6 requests, 6 seconds at 1 request/s): 1 list page and 5 detail pages. Required fields reach their learned fill rates (null is allowed where the portal shows nothing), every value check from Q2 passes, and the count on the fetched list page or API page matches what that page itself shows. On the full read the total must match the portal's printed count exactly (DESIGN.md).
3. Pass: run the full first read, then **one model spot check** where each quote must sit inside the node the locator read from. Only then serving.
4. Fail: triage first (an outage or a login wall means no learning, see Q10); then try the other family candidates; then cold learn with the rejected recipe handed to the learner as a draft (cheaper than starting blank).
5. Keep it honest after: draft 2's drift signals and continuity checks apply to reused recipes like any other.

What to ship and measure:
- Seed recipes are committed to the repo and copied into the image; a fresh container knows nothing otherwise.
- Measure the family-hit rate, wrong-family rejections, canary requests and time, and the cold-learn fallback rate.
- Honour stricter limits than 1 request/s where a portal or API states them (the BZP API's 30 requests/min means one request every 2 seconds).

Cost: a reused attach is the canary plus one Luna spot check, about $0.003 (see Q9), against about $1.70 for a cold learn.

## Two cautions

- **A national feed is not the portal.** BOAMP, PLACSP, TED and the PL BZP API are great for discovery, but the brief wants each tender's id, URL and documents *from the portal we were given*. Use a feed or API as the source only when it belongs to that portal (TenderNed's own REST API for tenderned.nl, yes; BOAMP for a buyer profile, no: ids and documents differ). This bears on Q3.
- **The judges' private portals will not match real software.** Reuse there pays only if the judges built several portals from one template, which is likely; the fingerprint then lands on our own recipe learned from their first portal. Recipes learned at run time join the library (draft 2 already says so).

## Prototype first (about 3 hours)

A signature table and canary for 2 installations of one family (for example AI/NetServer: vergabe.vmstart.de, tender24.de) plus 2 mock portals built from one template. Build the probe and table, run the canary on the Q2 field resolver, then run all four hosts.

## Effect on other questions

- Q1 recipe: add a `family` key, a per-host parameter block, and the canary spec.
- Q3 explore vs map: probe the portal's own JSON API or feed first, but only when it belongs to the portal (see the caution above).
- Q8 benchmark: at least 2 installations per family, plus one same-family host with a different configuration, plus a held-out host. Start from Patterno's portal list.
- Q12 large portals: multi-tenant platforms (Mercell, Atexo, Open Nexus) are where reuse pays most.

## Sources (accessed 20 Nov 2026)

- Patterno portal list: https://patterno.de/de/vergabe-portale; subreport page: https://patterno.de/de/vergabe-portale/subreport-elvis
- cosinex: https://cosinex.de/produkte/beschaffungsmanagementsystem (17 Sep 2026); https://blog.cosinex.de/2026/07/09/cosinex-vergabeplattform-bundesverkehrsressort
- NRW satellite: https://evergabe.nrw.de/VMPSatellite
- AI NetServer: https://vergabe.vmstart.de/NetServer; https://tender24.de/NetServer/index.jsp
- evergabe.de: https://evergabe.de/glossar/ai-vergabemanager; https://evergabe.de/faq/auftragssuche-angebotsabgaben-bietercockpit/vergabeunterlagen-herunterladen-teilnahme-ausschreibung
- Deutsche eVergabe: https://portal.deutsche-evergabe.de/dashboards/dashboard_off
- subreport: https://subreport.de/blog/mecklenburg-vorpommern-setzt-bei-der-evergabe-auf-subreport-elvis
- §41 VgV (free access to documents): https://gesetze-im-internet.de/vgv_2016/__41.html
- PLACE: https://economie.gouv.fr/dae/les-projets-achats-les-consultations/place-la-plateforme-des-achats-de-letat; https://www.marches-publics.gouv.fr/?page=Entreprise.AccueilEntreprise; https://semagora.com/guides/plateformes-marches-publics-dce
- Atexo: https://atexo.com/solutions/solutions-achats-et-marches-publics
- BOAMP API: https://data.gouv.fr/dataservices/api-bulletin-officiel-des-annonces-des-marches-publics-boamp
- PLACSP feeds: https://contratacionabierta.com/fuentes/placsp-licitaciones; https://docs.licitaradar.oriolj.com/fuentes
- Mercell: https://info.mercell.com/en/login; https://bearingpoint.com/en-nl/insights-events/blog/bearingpoint-helps-mercell-with-post-acquisition-crm-integration
- Vortal: https://vortal.biz/interproc-improves-interoperability-and-eprocurement-across-europe
- TenderNed: https://www.tenderned.nl/cms/nl/aanbesteden-in-cijfers/datasets-aanbestedingen; https://opendataindex.nl/bron/tenderned
- Open Nexus: https://paperless.asseco.com/case-studies-en/secure-and-intuitive-procurement-platform; https://parametry.pl/blog/open-nexus-platforma-zakupowa-alternatywa
- e-Zamówienia API: https://ezamowienia.gov.pl/pl/integracja; https://www.gov.pl/web/uzp/planowane-zmiany-w-api-bzp
- Italy: https://sdabocconi.it/en/sda-bocconi-insight/opinioni/centralized-procurement-should-different-models-be-applied-to-large-and-small-public-entities
- TED search API: https://tenderapi.eu/en/blog/ted-search-api-guide
- OCDS publishers: https://data.open-contracting.org/en

Conflicts and gaps: cosinex size (5,000 vs 2,000 authorities), Open Nexus clients (3,200 vs 32,700), whether AI and Healy Hudson NetServer share code, no Jaggaer data, no Italian platform URLs, meta tags and cookies unchecked.
