# Q2. Field locators: what the recipe stores to find each field and link

Owner: Danil. Researched 20 Nov 2026 (web search, sources at the end; most read as search snippets, not full papers).

## Recommendation

For each field on each node, store **two or three independent locators plus a typed value spec**, and run all of them on every read with no early stop. Accept a value only when the hits agree after parsing **and** pass the field's value checks; when the locators disagree, send null and flag the read. Silently picking a hit is how wrong values get published.

## Format

Locators live on the recipe's nodes, so the format fits a fixed-stage recipe and a graph recipe (Q1) alike.

HTML node (detail page), one field:

```json
{"field": "submissionDeadline",
 "locators": [
   {"kind": "label", "labels": ["Angebotsfrist", "Abgabefrist"], "value": "same_row"},
   {"kind": "css", "selector": "div.frist > span.wert"},
   {"kind": "xpath", "xpath": "//dt[normalize-space()='Angebotsfrist']/following-sibling::dd[1]"}],
 "parse": {"type": "datetime", "zone": "Europe/Berlin", "formats": ["%d.%m.%Y %H:%M"]}}
```

JSON API node, one field:

```json
{"field": "submissionDeadline",
 "locators": [{"kind": "jsonpath", "path": "$.sluitingsDatum"}],
 "parse": {"type": "datetime", "zone": "Europe/Amsterdam"},
 "required_keys": ["sluitingsDatum", "publicatieDatum"]}
```

Order of preference when the learner writes them: JSON path (API) > label anchor > relative CSS or XPath using ids, attributes or text. Never absolute XPath, never `nth-child` positions, never a default value.

## Decision rule (every read, per field)

| Hits | Result |
|---|---|
| 2+ hits, equal after parsing | accept |
| 2+ hits, any differ | null, flag `conflict` |
| 1 hit, others miss | accept only if every value check passes; flag `single_witness` |
| 0 hits, optional field | leave the field out (the portal does not show it for this tender) |
| 0 hits, required field | null for this tender; when the page-level fill rate drops below the recipe's expectation, the read fails (portal to healing, see Q10) |

A label anchor counts only when the label and the value sit in the same row or cell. Agreement is necessary, not sufficient: a redesign can move two locators onto the same wrong row, which is why the value checks below are the second, independent line.

## Options compared

| Option | Survives small layout change | Risk of a silent wrong value | Easy for the LLM to write | Evidence |
|---|---|---|---|---|
| Absolute XPath | very low | high | easy | 871 of 1,110 broke vs 91 for ROBULA+ (Leotta 2016) |
| id / name attribute | high when unique | low | easy | ROBULA+ paper |
| CSS class or attribute | medium | medium (classes reused) | easy | Crawl4AI docs: avoid nth-child |
| Relative XPath with text or attribute predicates | high | low to medium | medium | ROBULA+ (Leotta 2016) |
| Label anchor | high to layout, low to wording | low for unique labels | easy | no benchmark found |
| Role + name (Playwright getByRole/getByLabel) | high | low, ambiguity throws | easy | Playwright docs; few form controls on list pages |
| JSON path | high | low when required keys are checked | easy | TenderNed API |
| Similarity healing (Healenium, Similo) | highest | **highest: always returns a best guess** | hard | Similo 91/801 failures vs 214/801 (Nass 2023). Use only to *propose* a locator to the repairer, never to accept one |

Wrapper-maintenance research supports checking values, not just selectors: Lerman, Minton and Knoblock (JAIR 2003) detected 35 of 37 real site changes from the statistics of extracted values alone, with 16 false alarms.

## Value checks per field

| Field | Check | Catches |
|---|---|---|
| id | matches the id shape learned at attach; unique within the read | neighbour row, row index used as id |
| title | non-empty, not equal to buyerName, length within bounds | title/buyer swap |
| buyerName | non-empty, not identical to the portal's own name on most tenders | header or footer text |
| publicationDate | parses, not in the future | wrong date row |
| submissionDeadline | parses with the portal's zone, after publicationDate; a date with no time is null (draft 2) | deadline/publication swap |
| status | enum after the word map; derived from the deadline when the portal shows none | constant column |
| cpvCodes | 8 digits **and present in the official CPV 2008 code list**, shipped in the image | wrong code column. The check digit is dropped from our output, so list membership is a stronger check than the check-digit formula, which the research could not confirm |
| placeOfPerformance | country code in ISO 3166-1; postal code fits the country's pattern | address line swap |
| any field | identical on 90%+ of tenders on a page of 5+ (starting threshold, tune on the test set) | header or footer hit |
| raw text fields | **grounding**: the raw value appears in the fetched page or JSON text after whitespace normalisation | invented or garbled values. It does not catch a neighbour value, which is also on the page, so it backs up the checks above and does not replace them |

EU deadlines run from the notice's dispatch date (eForms BT-05), not the publication date; when a dispatch date is shown, compare against it.

## Label anchors (sourced)

| Field | DE | FR | ES | NL | PL | IT |
|---|---|---|---|---|---|---|
| Deadline | Angebotsfrist | Date limite de réception des offres | Fecha límite de presentación de ofertas | Sluitingsdatum | Termin składania ofert | Termine per il ricevimento delle offerte |
| Publication / dispatch | not found | Date d'envoi de l'avis | not found | Publicatiedatum | Data publikacji | Data di spedizione |
| Buyer | not found | not found | not found | Aanbestedende dienst | not found | not found |

Buyer, reference number, CPV and procedure labels were not sourced in most languages. The learner reads them off the live page anyway; this table seeds its synonym lists. TED shows the offset explicitly ("05/05/2026 13:00:00 (UTC+02:00)"); the TenderNed JSON deadline ("2026-10-12T10:00:00") has none, so the offset comes from the portal's country zone.

## Prototype first (about 5 hours)

1. 1.5 h: save 6 pages (DE, FR, ES, NL, PL, IT detail pages) and 1 JSON response; hand-label 6 fields each.
2. 1.5 h: a field resolver that runs all locators, parses, applies the decision rule and the value checks, and returns value, null or a flag.
3. 2 h: mutate the saved pages (rename a class, wrap in a div, swap two date rows, change a label's wording, rename a JSON key) and count. **Target: zero wrong values accepted.** Also report the null rate and how many breaks were flagged.

This doubles as the engine's field resolver, so the hours are not wasted.

## Effect on other questions

- Q1 recipe: each node stores fields as locator list + label synonyms + value spec. Learn the id shape and date format from the first read's examples.
- Q4 agent tools: give the agent a dry-run tool that shows every locator's hit with its row text. It must never pick one silently.
- Q7 schemas: output fields nullable, with per-field flags on the run (conflict, single_witness), not on the tender record.
- Q10 failure rules: required-field fill rate below expectation means the read fails. A conflict nulls one value. A healed locator is never auto-accepted.
- Q11 reuse: a reused recipe is checked by these same rules on the canary read.

## Open points

- CPV check-digit formula not confirmed (moot if we check list membership).
- Lerman 2003 and Similo numbers come from abstracts and web-app studies, not procurement portals.
- Postal-code patterns per country not sourced; use a small library or the learner's examples.

## Sources

- Leotta et al., ROBULA+, JSEP 2016: https://onlinelibrary.wiley.com/doi/10.1002/smr.1771
- Leotta et al., ROBULA, ISSREW 2014: https://sepl.dibris.unige.it/publications/2014-leotta-ISSREW.pdf
- Nass et al., Similo, TOSEM 2023: https://dl.acm.org/doi/pdf/10.1145/3571855 and https://arxiv.org/abs/2208.00677
- VON Similo: https://arxiv.org/pdf/2301.03863v2
- Lerman, Minton, Knoblock, Wrapper Maintenance, JAIR 18:149-181 (2003): https://jair.org/index.php/jair/article/view/10325
- Kushmerick, RAPTURE (AAAI 1999): https://cdn.aaai.org/AAAI/1999/AAAI99-011.pdf; Wrapper verification (WWW 2000): https://link.springer.com/article/10.1023/A:1019229612909
- Healenium: https://healenium.io/docs/how_healenium_works
- Crawl4AI no-LLM extraction: https://docs.crawl4ai.com/extraction/no-llm-strategies
- Firecrawl JSON extraction: https://docs.firecrawl.dev/features/llm-extract
- ScrapeGraphAI: https://github.com/ScrapeGraphAI/Scrapegraph-ai
- Playwright locators: https://playwright.dev/docs/locators
- Grounding prior art: HALO https://arxiv.org/pdf/2607.17883; RefLens (AAAI 2026) https://ojs.aaai.org/index.php/AAAI/article/view/42361/46322
- CPV structure: https://en.wikipedia.org/wiki/Common_Procurement_Vocabulary; Reg. 213/2008 annex: http://legislation.gov.uk/eur/2008/213/annex/I/adopted
- TED-XML v2.0: https://docs.ted.europa.eu/ODS/latest/reuse/_attachments/TED-XML_general_description_v2.0_20160219.pdf; notice example: https://ted.europa.eu/en/notice/172939-2026/html
- eForms BT-05: https://duke.yt/learn/concepts/notice
- Labels: documedia.at (Angebotsfrist) https://documedia.at/wissenswertes/glossar/angebotsfrist; BOAMP https://boamp.fr/telechargements/FILES/PDF/2026/11/26-111095.pdf; Aragón https://gd.aragon.es/cgi-bin/ACTA/BRSCGI?CMD=VEROBJ&MLKOB=1406741575454; TenderNed https://tenderned.nl/papi/tenderned-rs-tns/v2/publicaties/433492; e-Zamówienia https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/2026%2FS%20110-398672; difesa.it notice https://difesa.it/assets/allegati/SGD-DNA/Staff/DG/COMMISERVIZI/Bandi/Documents/gara%201_2023/20230619_069%20(1).pdf

All accessed 20 Nov 2026.
