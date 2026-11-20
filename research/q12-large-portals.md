# Q12. Large portals: every open tender with its documents, at 1 request per second

Owner: Goktug · Researched 20 Nov 2026 · Status: **answered, with one rule that waits on the mentors**

How each claim is known is marked: **measured** (we ran it today), **read** (seen in the document, API answer or source code itself), **search** (seen only in a search result), **ours** (our own reasoning or choice).

## Question

How do we deliver every open tender with its documents from a large portal, at 1 request/s?

Rough math: 1,000 tenders x (1 detail page + ~3 files) = ~4,000 requests = ~67 minutes, before paging.

Options
- Read the list first, then details, then documents, publishing as we go.
- Incremental reads: later reads fetch only new or changed tenders.
- Prefer bulk sources: a JSON API with large page sizes, feeds, all-documents ZIPs.
- Prioritise tenders by deadline.

Also answer: what state do we report during a long attach? Integrating until the attach completes, or serving once the first validated batch is out?

Deliverable: the recommended read order and state rule, with the request math for 100, 1,000 and 5,000 open tenders.

## Decision

**Read order.** Take the cheapest source the portal itself offers, then read in three phases: the whole list, then every tender's record, then the documents with the soonest deadline first. After the first attach, read incrementally.

**State rule.** Stay `integrating` and publish nothing until every open tender's record is read and validated. At that point, if the documents can be finished within 10 minutes, finish them and only then report `serving`. If they cannot, publish every tender now and report `serving`, with `documents` null on the tenders whose files are not in yet and the progress in `reason`.

We choose this for four reasons:

1. **The first attach is the only expensive part, and requests are what it costs.** A bulk source cuts it by a factor of 5 on the one portal we measured; nothing else comes close.
2. **Phases reach "every tender known and correct" 4 times sooner than finishing one tender at a time**, and they test the recipe on every detail page before most of the budget goes to files.
3. **The state rule never contradicts the organisers' definitions.** Nothing is delivered while `integrating`; nothing wrong or knowingly partial in the tender list is delivered while `serving`.
4. **Small portals lose nothing.** They finish inside the 10 minutes and go to `serving` complete. Only portals that cannot finish quickly use the early gate.

## Request math

All from `research/tools/q12_request_math.py` (**measured**: computed; run it to reproduce). One request may start per second.

### First attach

| Portal | Tenders | Requests | Every record known | Everything in | Disk |
| --- | --- | --- | --- | --- | --- |
| HTML list of 20, 3 files each (the question's guess) | 100 | 405 | 2 min | 7 min | 2 GB |
| | 1,000 | 4,050 | 18 min | 68 min | 20 GB |
| | 5,000 | 20,250 | 88 min | 5.6 h | 100 GB |
| HTML list of 20, **9 files each (measured mean)** | 100 | 1,005 | 2 min | 17 min | 2 GB |
| | 1,000 | 10,050 | 18 min | 2.8 h | 20 GB |
| | 5,000 | 50,250 | 88 min | 14 h | 100 GB |
| **API list of 100 and one all-documents ZIP per tender (measured: TenderNed)** | 100 | 201 | 1 s | 3 min | 2 GB |
| | 1,000 | 2,010 | 10 s | 34 min | 20 GB |
| | 5,000 | 10,050 | 50 s | 2.8 h | 100 GB |

**A real case, measured today:** TenderNed lists 1,551 open tenders. With its API and ZIP link that is 3,179 requests, 53 minutes. File by file it is about 15,600 requests, 4.3 hours. Either way it is about 35 GB of documents.

Three things the question's rough math missed:

- **Files per tender are about 9, not 3**, on the portal we measured (mean 8.7 over 40 open tenders; median 7.5). Read file by file, 1,000 tenders take 2.8 hours, not 67 minutes.
- **Disk is a limit of its own.** At about 20 MB per tender, 1,000 tenders are 20 GB.
- **A bulk source changes the picture more than any ordering does.** With TenderNed's API and its ZIP link, the same 1,000 tenders take 34 minutes, and every record is known after 10 seconds, because the list already carries the required fields.
- **Some portals allow less than 1 request per second.** Poland's national portal allows 30 a minute and answers 403 beyond that. There, every time above doubles.

### After the first attach

HTML list of 20 per page; a new tender costs 10 requests; re-reading the detail pages of known tenders may use a fifth of the request budget.

| Tenders | List pages | List read every | Requests per hour | Share of the budget | Longest time a broken portal can read `serving` | Every detail page re-read within |
| --- | --- | --- | --- | --- | --- | --- |
| 100 | 5 | 2 min | about 1,110 | 31% | 2 min | 8 min |
| 1,000 | 50 | 8 min | 1,150 to 1,190 | 32 to 33% | 9 min | 83 min |
| 5,000 | 250 | 30 min | 1,280 to 1,500 | 35 to 42% | 34 min | 6.9 h |

The range is for tenders that stay open 50 days (measured median, TenderNed) down to 8 days (measured median, Polish notices below the EU threshold). Steady state stays under half of what the limit allows at every size. The interval rule is in Q13.

## The read, step by step

1. **Look for a bulk source that belongs to the portal** (Q3 owns the checklist): a JSON API behind the page, a feed, an all-documents ZIP. For an API, raise the page size until the API refuses; TenderNed's refusal names its own maximum ("must be less than or equal to 100").
2. **List phase.** Read every list page. This gives the count for progress and, when the list shows deadlines, the order for step 4.
3. **Record phase.** Read every detail page the recipe needs (none when the list carries all required fields). Validate each record (Q10). This is the gate.
4. **Document phase.** Soonest deadline first, smallest tender first among equals. One ZIP per tender where the portal offers it; we have to unpack ZIPs anyway. A file over 250 MB is left out, as the brief allows: of 9 tenders measured, one held 376 MB.
5. **From then on, incremental.** Each read takes the list again; reads detail and documents for tenders that are new or whose list row changed; and follows the portal's own change marks where they exist. A file is fetched again only when its entry in the tender's document list changed (name, size or date).
6. **Known tenders' detail pages are re-read in an even rotation that may use a fifth of the request budget**, tenders closing within 48 hours first. That is 24 detail pages in a 2-minute read. A portal of 24 tenders has every detail page re-read on every read; one of 100 within 8 minutes; one of 1,000 within 83 minutes. So a moved deadline or an added document on a small portal, which is what the private test portals are likely to be, is seen within minutes.

Portal-stated limits win over our own: the limiter starts at one request per second and slows down when the portal says so (Q10, rule T2).

## State during a long attach

| Phase | State | `GET /tenders` | `reason` |
| --- | --- | --- | --- |
| List and record phases | `integrating` | `[]` | "Reading tender 420 of 1,000." |
| Gate reached, documents need 10 minutes or less | `integrating` | `[]` | "All 38 tenders read. Fetching documents: 12 of 38." |
| Gate reached, documents need longer | `serving` | every tender; `documents` null where files are not in yet | "All 1,000 open tenders are delivered. Documents are in for 140 of them, soonest deadlines first; the rest follow by 16:40." |
| Everything in | `serving` | complete | "Read at 14:02 found 1,000 open tenders. Every check passed." |

Why null and not an empty list: an empty list says the tender has no documents, which is wrong. Null is the contract's word for a value we cannot give, and "a wrong value is worse than a missing one".

The 10 minutes is **ours**, and so is the fifth of the budget for re-reading detail pages. The 10 minutes is the one number here that should come from the mentors (question 1 below). Both are settings.

**Known limit:** a 5,000-tender HTML portal needs 88 minutes to reach the gate, and shows nothing until then. Publishing a partial tender list sooner would mean reporting `serving` on a list we know is incomplete, so we do not.

## The alternatives, and why they lose here

| Alternative | Why it loses, or what we kept |
| --- | --- |
| Publish tenders as they are read, while still `integrating` (the question's first option, as worded) | Contradicts the organisers' definition, "Nothing is delivered yet." The reported state would not match what we deliver, which is what the Notice criterion checks. We keep the order, not the publishing. |
| `serving` once a first validated batch is out | The tender list is then knowingly incomplete, and only the reason text says so. Our early gate delivers strictly more at every moment: all records, not some. |
| `integrating` until the last document, always | Correct, and what we do for portals that finish in 10 minutes. For a 1,000-tender portal it means 3.6 hours with nothing delivered, and zero for Attach if the harness stops waiting. |
| Finish one tender completely before starting the next | Mean time to a complete tender is better by about N/2 seconds (2,052 s against 2,552 s for 1,000 tenders with 3 files). But every record is known only at the very end (4,050 s against 1,050 s), and a wrong recipe is found late. |
| Newest tenders first | The newest tenders have the most time left. A tender closing tomorrow without its documents is the worst case, so soonest deadline first. |
| Re-read tenders more often the more often they change | Research on crawler refresh policies found that visiting all pages equally often gives better average freshness than visiting in proportion to their change rate (**search**; the paper was not opened). We refresh evenly and add only the deadline weighting. |
| Re-read every open tender's detail page once a day | Enough for freshness: with about 3 changes in a tender's life it is fresh 95% of the time (**measured**: computed). Too slow for noticing: a detail page that broke, or a deadline the judges moved, could go unseen for a day. A fifth of the budget buys minutes on small portals. |
| Conditional requests and HEAD to save budget | Each is still a request. They save bytes, not requests (**read**: RFC 9110). Worth sending on files, not a way around the limit. |
| Trust a sitemap's `lastmod` or a list's "changed" column blindly | Google uses `lastmod` only "if it's consistently and verifiably accurate" (**read**). Change marks are noisy in both directions (**read**: Busa-Fekete et al. 2025), hence the rotation as a backstop. |
| Never revisit a page that already gave a tender (the scrapy-deltafetch pattern) | It would miss extended deadlines and added documents (**read**: its source skips any request whose page produced an item). |
| Keep only hash and size, fetch the bytes from the portal when someone downloads | The file could have changed since we hashed it, so our published hash would be wrong; downloads would spend the portal's request budget; and while `healing` we promise the last good data. Package mirrors keep copies for the same reasons (**search**). |

## Evidence

### Measured on real portals today

All with plain requests to public, documented interfaces, at most one per second.

- **TenderNed (Netherlands), public REST API, no login.** Page size defaults to 10 and is capped at 100: a request for 101 answers "must be less than or equal to 100" (checked twice). A list entry carries id, title, buyer, publication date, closing time in local time with no offset, procedure, type and description. There is no last-modified field: a change appears as a separate rectification row, and the detail call points to the latest one.
- **TenderNed's open stock.** Reading every publication since 15 August (7,630 rows in 77 pages of 100: 2,691 contract notices, 2,494 awards, 1,208 rectifications, the rest other types) gives 1,933 rows with a deadline still ahead, which are **1,551 distinct open tenders**. Tenders published earlier and still open are not counted, so the true figure is slightly higher.
- **TenderNed documents.** The document list and one all-documents ZIP per tender both answer without login (one ZIP fetched: 6.9 MB). In a random sample of 40 of those open tenders: 7.5 files at the median, 8.7 on average, 29 at most, and 9 tenders with none. Size per tender: 2.8 MB at the median, 22.7 MB on average, 127 MB at the 90th percentile, 300 MB at most. One file was over 250 MB. A first sample of 10 had given a median of 12 files; the larger sample replaces it.
- **TenderNed lifetimes.** Across the 1,551 open tenders: 50 days at the median from publication to deadline, 26 at the 10th percentile, 89 at the 90th. One row in six is a rectification.
- **e-Zamówienia (Poland), public notice API.** At most 30 requests a minute from one address, then HTTP 403 (**read**; checked twice). A page of 500 notices is accepted and weighs 17 MB. 500 notices below the EU threshold: median 8 days from publication to deadline, 15 days at the 90th percentile.
- **Spain's national feed.** One Atom file held 210 entries with a per-entry update time and a link to the next file. The same portal's HTML pages answered "Request Rejected" to a plain request.

This is one portal for documents and two for lifetimes, on one day. It replaces a guess with a measurement; it does not show how portals differ.

### Read

- TED's search API: 250 notices per page; 15,000 in page mode, no cap with a continuation token.
- RFC 9110: a 304 or a HEAD answer is still a response to a request; a 206 answers only a range the client asked for.
- Google on sitemaps: "Google uses the `<lastmod>` value if it's consistently and verifiably ... accurate."
- Web Almanac 2021, all responses: 70.5% send `Last-Modified`, 46.5% an `ETag`, 24.5% neither.
- Kubernetes: a container is not ready while it does "time-consuming initial tasks, such as establishing network connections, loading files, and warming caches". Elasticsearch: a cluster is red when primary data is missing. Both treat "data not all there yet" as not ready, which is our `integrating`.
- Debezium, Fivetran, Airbyte: one backfill that saves its progress, then incremental reads; Airbyte's first incremental sync "is equivalent to a Full Refresh". Scrapy's cache policy sends both validators and treats 304 as unchanged.
- Busa-Fekete et al. 2025: change signals are "noisy with false positive events and with missing change events".

### Search results only

- Cho and Garcia-Molina, "Effective page refresh policies for Web crawlers" (TODS 2003): the uniform policy gives better freshness than the proportional one.
- Earliest-due-date order minimises the largest lateness on one machine (Jackson's rule).
- Directive 2014/24/EU time limits (35 days for an open procedure); the EU's legal site did not answer our requests.

## What would change the decision

- **The mentors' answer on how long the harness waits and how large the test portals are.** A long wait: raise the 10 minutes. A very short one: lower it.
- **A mentor ruling that `serving` requires every document.** Then the early gate goes, and large portals stay `integrating` with progress in `reason`.
- **A ruling that only one request may be in flight at a time.** Then a large file blocks the portal while it downloads, and the times above grow with file size.

## For the mentors

1. How long does the harness wait after `POST /portals` before it scores Attach, and how many tenders and documents do the test portals hold?
2. Is a portal `serving` when every open tender is delivered with a correct record while some tenders' documents are still being fetched, shown as null?
3. Does "1 request per second" limit request starts, so that a large download may still be running when the next request starts, or the number in flight?
4. How much disk does the container have?

## Disk

Files are kept on local disk under their SHA-256, so the same file in two tenders is stored once. From the measured sizes, plan for about 20 MB per tender: 20 GB for 1,000 tenders and 100 GB for 5,000. The average is carried by a few large tenders; the median is under 3 MB (40 tenders, one portal). When free space runs low, stop fetching new documents, leave those tenders' `documents` null, say so in `reason`, and remove the files of closed tenders first (**ours**).

## Prototype first (about 4 hours)

1. 1 h: the scheduler's three phases against the mock portal, with the gate and the 10-minute rule; check `GET /tenders` is empty until the gate.
2. 1.5 h: the incremental read: list difference, new and changed tenders, the rotation, the per-file "entry changed" test.
3. 1 h: one real bulk portal end to end (TenderNed's API and ZIP): count requests against the table above.
4. 0.5 h: the limiter slowing down on a 429 and on a 403 with `Retry-After` from the mock portal.

## Effect on other questions

- **Q1 recipe model:** the recipe says whether the list alone carries the required fields, what the page-size parameter and its maximum are, whether an all-documents ZIP exists, and which change mark the portal has.
- **Q3 explore or map:** probing for an API, a feed or a ZIP link is worth up to a few dozen requests at attach: on a 1,000-tender portal it saves about 8,000.
- **Q7 schemas:** a tender needs read bookkeeping (last seen in the list, last detail read, hash of its list row), and a document entry must be able to exist before its bytes do.
- **Q9 cost:** portal size does not change model cost; it changes time and disk.
- **Q10 failure rules:** the checks add at most 8 requests per read. A 403 at a rate-limited portal is not a block.
- **Q13:** the read interval follows from the list length.
- **DESIGN.md:** replace "publish only after a full first read" with the gate and the 10-minute rule; replace "a portal that reads in full within two minutes is read in full every time" and "within the hour" with the rotation on a fifth of the budget; drop "3 times the last read's duration".

## Sources

Read or measured on 20 Nov 2026.

- TenderNed public API: https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties and its description at https://www.tenderned.nl/info/swagger/public-aankondiging-api.yaml
- e-Zamówienia, integration and traffic control: https://ezamowienia.gov.pl/pl/integracja/ and https://ezamowienia.gov.pl/pl/mechanizm-kontroli-ruchu-dla-endpointow-w-ramach-api-bzp/
- Spain, public feed: https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom
- TED search API: https://docs.ted.europa.eu/api/latest/search.html
- RFC 9110: https://www.rfc-editor.org/rfc/rfc9110.txt
- Google, build and submit a sitemap: https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap
- Web Almanac 2021, caching chapter (source text): https://github.com/HTTPArchive/almanac.httparchive.org
- Kubernetes probes (documentation source): https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/pods/probes.md
- Elasticsearch cluster status (documentation source): https://raw.githubusercontent.com/elastic/docs-content/main/troubleshoot/elasticsearch/red-yellow-cluster-status.md
- Busa-Fekete et al., "A Scalable Crawling Algorithm Utilizing Noisy Change-Indicating Signals" (2025): https://arxiv.org/abs/2502.02430
- Scrapy 2.20.0, scrapy-deltafetch 2.1.0, airbyte-cdk 7.49.0, singer-python 6.9.0: package sources from PyPI; Debezium PostgreSQL connector documentation source on GitHub
- Search only: Cho and Garcia-Molina, TODS 28(4), 2003, https://doi.org/10.1145/958942.958945 ; Jackson's rule, lecture notes at https://www.columbia.edu/~cs2035/courses/ieor8100.F16/lec5.pdf

Not found: open-tender counts for any portal but TenderNed, HTML list page sizes, and how often tenders are withdrawn. Patterno's own portal list is counted in [patterno-landscape.md](patterno-landscape.md): most of its 4,657 portals are one buyer's space on a shared platform, so small lists are the common case.
