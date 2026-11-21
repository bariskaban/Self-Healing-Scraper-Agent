# The learner and the repairer on the real test portals, and on altered clones of them

Run on 20 and 21 Nov 2026, 23:15 to 00:15 UTC, from one cloud session, on the development key. Model `gpt-6.2-sol`, reasoning `medium`. One run per portal: single runs, not averages. Every result, with its recipe and every step, is in `agent-on-real-portals.json` beside this file.

**This run sent requests to live portals.** `CLAUDE.md` forbids that for agent sessions. Goktug lifted the rule for this run, on the condition that nobody else was reading these portals at the time. The portals were read one request a second each, robots.txt obeyed, through `app/fetch`. `variants/real.py` refuses to start unless `FETCH_MODE=live` is set by hand. The rule in `CLAUDE.md` stands for everything else.

## What was run

All 18 portals of `bench/portals.toml` that are not held back and whose robots.txt does not forbid everything (`load_portals()`). For each: learn live, every fetched page kept in a clone on disk; then the learned recipe read over two list pages and five tenders as the baseline. No portal has gold labels, so "right" here means: the dry run passed, and after a break the repaired recipe gives the baseline's values again. Whether the baseline's values are the true ones was checked by nobody.

Three scenarios on each learned portal, one repair each:

- **list**: the clone is served with only its list pages altered (every class, id and `data-*` hook renamed; JSON keys renamed).
- **detail**: only the tenders' own pages altered.
- **lost**: nothing on the portal changes, but all we keep of its address is the domain: the stored address and the recipe's start address are replaced by one that answers 404 (the mentor: only the domain can be assumed to stay). The repairer has to find the list again from the real domain root.

## Learn: 11 of 18 learned

| Portal | Kind | Calls | Cost | Cached | Requests | Seconds | Tenders on two list pages (portal's own count) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `deutsche-evergabe` | unknown | 22 | $0.37 | 84% | 12 | 146 | 947 |
| `dtvp` | unknown | 22 | $0.48 | 77% | 23 | 162 | 8 |
| `eb2b-gddkia` | unknown | 40 | $0.69 | 81% | 29 | 200 | 2000 (5300) |
| `ezamawiajacy-inneko` | server_html | 31 | $0.64 | 81% | 15 | 243 | 39 (39) |
| `ezamawiajacy-nfz` | server_html | 34 | $0.54 | 83% | 10 | 156 | 5 (5) |
| `ezamowienia` | mixed | 37 | $0.67 | 82% | 36 | 233 | 200 |
| `frankfurt` | server_html | 28 | $0.64 | 79% | 19 | 307 | 50 |
| `tender24` | server_html | 17 | $0.40 | 77% | 16 | 144 | 121 |
| `tenderned` | json_api | 30 | $0.62 | 79% | 26 | 208 | 200 (147,353) |
| `vergabe-niedersachsen` | unknown | 39 | $0.86 | 79% | 19 | 306 | 40 (2020) |
| `vmstart` | server_html | 20 | $0.45 | 79% | 14 | 164 | 110 (110) |

A learn cost $0.37 to $0.86, median $0.62, and took 10 to 36 requests to the portal. The cached share of input is 77% to 84% on every portal: the cache misses that cost 72% of the first NFZ learn (pull request 53) did not come back after pull request 54.

Not learned, 7:

| Portal | Calls | Cost | Why |
| --- | --- | --- | --- |
| `mercell`, `subreport-elvis`, `vmp-brandenburg` | 2 each | $0.04 each | robots.txt disallows the address we were given. Correct: we obey it. |
| `evergabe-de` | 4 | $0.05 | HTTP 418 "Access Denied" after a redirect to `www.evergabe.de`: a bot wall. |
| `evergabe-nrw` | 2 | $0.04 | Its robots.txt redirects to `www.evergabe.nrw.de`, a host this session's network did not allow. A fault of this run's setup, not of the portal or the product. Not tried again. |
| `evergabe-online` | 33 | $0.70 | The first page reads (10 of 989 tenders). Its next-page links are session links and answer 403 when fetched on their own. |
| `place` | 39 | $0.88 | The first page reads (10 tenders). The request for the next page answers 400. |

The last two are the expensive failures: a list whose paging lives in the server's session cannot be read by the executor's plain requests, and the learner spends its whole budget finding that out.

`deutsche-evergabe` was listed as "expect a login wall"; its public list was learned (947 tenders on two pages).

## One node broken on the clone

| Portal | list pages altered | tender pages altered |
| --- | --- | --- |
| `deutsche-evergabe` | repaired, same values; changed list, documents ($0.09) | repaired, same values; changed detail ($0.12) |
| `dtvp` | repaired, same values; changed list, detail ($0.19) | recipe unaffected |
| `eb2b-gddkia` | recipe unaffected | recipe unaffected |
| `ezamawiajacy-inneko` | repaired, same values; changed list ($0.23) | **repaired, but the five tenders lost their documents**; changed list ($0.14) |
| `ezamawiajacy-nfz` | repaired, same values; changed list ($0.16) | repaired, same values; changed detail ($0.09) |
| `ezamowienia` | repaired, same values; changed list, a step node, documents ($0.10) | recipe unaffected |
| `frankfurt` | repaired, same values; changed list ($0.15) | repaired, same values; changed documents ($0.17) |
| `tender24` | repaired, same values; changed list ($0.15) | repaired, same values; changed detail, documents ($0.16) |
| `tenderned` | repaired, same values; changed list ($0.08) | repaired, same values; changed detail ($0.07) |
| `vergabe-niedersachsen` | recipe unaffected | recipe unaffected |
| `vmstart` | repaired, same values; changed list ($0.13) | repaired, same values; changed detail, documents ($0.12) |

Of 22 scenarios, 7 did not break the recipe (it reads those pages by label, by JSON path or by address, none of which the alteration touches). Of the 15 that did, 14 were repaired to the baseline's values and one was repaired wrongly (`ezamawiajacy-inneko`, tender pages: the values came back, the document links did not, and the dry run accepted it because documents are not compared with the last good read).

"Only the broken node changes" held in 10 of the 14: the repair changed the node that reads the altered pages, or that node and the documents node on the same pages. In 3 it changed one more node than was broken (`dtvp`, `ezamowienia`, `deutsche-evergabe`, list scenario). Why was not looked into; the values were right in all three.

## Only the domain left ("lost")

| Portal | Result | Calls | Cost | Requests to the portal | Where the recipe starts now |
| --- | --- | --- | --- | --- | --- |
| `vmstart` | found again, same values | 4 | $0.07 | 2 | `/` |
| `tender24` | found again, same values | 8 | $0.11 | 5 | `/NetServer/PublicationSearchControllerServlet` |
| `tenderned` | found again, same values | 18 | $0.25 | 7 | `/papi/tenderned-rs-tns/v2/publicaties` (used `portal_hints`) |
| `dtvp` | found again, same values | 6 | $0.10 | 3 | `/ausschreibungen/` |
| `ezamowienia` | found again, same values | 6 | $0.09 | 2 | `/mp-client/search/list` |
| `frankfurt` | found again, same values | 8 | $0.09 | 3 | `/NetServer/` |
| `ezamawiajacy-nfz` | found again, same values | 9 | $0.12 | 3 | `/pn/nfz/demand/notice/publicpzp/current/list` |
| `ezamawiajacy-inneko` | found again, same values | 11 | $0.13 | 3 | its list address |
| `vergabe-niedersachsen` | found again, same values | 8 | $0.12 | 2 | `/Satellite/company/welcome.do` |
| `eb2b-gddkia` | **not found** | 19 | $0.21 | 1 | The list is loaded by the portal's JavaScript; the repairer searched the script for the call and did not find it within its 20 calls. |
| `deutsche-evergabe` | recipe unaffected | | | | The recipe's list request does not start from the corrupted address. |

9 of 10 found the list again from the domain root, for $0.07 to $0.25.

This scenario leaves the portal as it is and loses our address. It does not show a portal that really moved its pages: no real portal can be moved. That case was run on the made-up portals (`variants/portals.py`, `moved`: every page, API call and file under a new prefix, old addresses 404): 6 of 6 repaired with every tender, field and document count right, $0.08 to $0.13 each (`agent-on-made-up-portals-moved.json`). And once in the app on the mock portal (`paths_moved`): repaired in a scheduled-style read in 26 seconds for $0.09, and because the tenders' addresses differ from the last good read the reader asked for the spot check, which confirmed 15 values on 3 pages before anything was published. That was also the first live spot check.

## What the run found, and what was changed for it

| Found | Change (this pull request) |
| --- | --- |
| Four learns at once used the key's 1M tokens a minute; each run died of its first 429. | `app/agent/runner.py`: a rate limit is waited out (the API's own wait, at most 60 s) and tried again, five times at most. |
| On `ezamowienia` a repair of the list was accepted although the tenders' pages no longer gave reference numbers. | `app/agent/tools.py`: a repair's dry run must give the last good read's tenders again, same ids and values, or it is refused with what differs. |
| The repair prompt had no step for a page that answers 404. | Repair prompt 2: only the domain can be relied on; go to the root, follow the portal's links, keep the ids; the task names the root. |
| No sitemap help. | `portal_hints`: the sitemaps robots.txt names, as address patterns with counts and samples, never whole; through `app/fetch`, inside the request budget. |
| No way to move the mock portal's paths. | `mock_portal`: `paths_moved` (and a sitemap), `POST /demo/move` in the demo. |

## Open, not fixed

- **Paging that lives in the server's session** (`evergabe-online`, `place`): not readable today. The learner should stop early and say so; today it spends $0.70 to $0.88 first.
- **Documents are not compared after a repair** (`ezamawiajacy-inneko`): a repaired recipe can lose every document link and still be accepted by the dry run. The reader's checks after the trial read were not run here.
- **A list loaded by a script's own call** can be learned (`eb2b-gddkia` was) but was not found again from the root within a repair's budget.
- **The network layer does not use `HTTPS_PROXY`**: behind a proxy it connects directly. That only matters in a session like this one; the benchmark script hands it a proxy transport.
- **Coverage**: `eb2b-gddkia` read a deadline on 405 of 2000 rows and `vergabe-niedersachsen` on 19 of 40; nobody checked whether the rest have none.
- The repairs here ran through `repair()`, without the reader's trial read, except the one in-app run named above.

## Cost of this run

About $10.30 for the learns and the one-node repairs, $1.28 for the lost-address repairs, $0.80 for the moved made-up portals, and about $3 on runs that failed for the rate limit or the proxy before the fixes: about $15 on the development key.
