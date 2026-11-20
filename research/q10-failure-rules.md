# Q10. Failure rules: which exact rules decide that a read failed?

Owner: Goktug · Researched 20 Nov 2026 · Status: **answered**

How each claim is known is marked: **read** (seen in the paper, standard, vendor page or source code itself), **measured** (we ran it today), **search** (seen only in a search result), **ours** (our own reasoning or choice; no source gives it).

## Question

Which exact rules decide that a read failed (portal -> healing)? The rules must not raise false alarms on portals that really have few or no open tenders.

Candidate checks: tender count drop versus the last good read, and versus the count the portal prints; null rate per required field; known open ids missing; value checks (dates parse, deadline after publication, CPV format); document download failures; page structure fingerprint; HTTP errors; login or captcha detection, which goes straight to failed.

Prior art to check: data-observability practice (volume, schema and freshness checks) and scraper monitoring.

Deliverable: the rule set with thresholds, and how each rule maps to a state and its reason text.

## Decision

**A read is judged by evidence that does not depend on how many tenders exist today, and no single statistic changes the state on its own.** Cheap checks mark a read *suspect*; a second, deterministic observation in the same run (a re-read, or a look at the detail pages of the tenders that went missing) confirms or clears it within seconds and without a model call. Only then does the portal change state.

We choose this for four reasons:

1. **Counts cannot tell a quiet portal from a broken one.** The best detector in the wrapper-verification literature ignored the count altogether, and comparing whole results fails on 81% of sites because content legitimately changes.
2. **Percentage thresholds are wrong at both ends.** A 30% rule fires on one withdrawn tender in a portal of three, and tolerates 150 missing tenders in a portal of 500.
3. **The tools that learn thresholds from history need 4 to 14 days of it.** The judges run us for hours, and those tools go blind when the history is constant.
4. **Waiting for repeated failures makes the reported state wrong for 10 to 15 minutes.** A second observation costs seconds and no tokens, so we buy certainty with evidence, not with time.

## The rule set

Every read runs these steps in order. Thresholds marked * are in the tables that follow.

### Step 1: did each request get an answer?

| Rule | Observation | What we do | Result if it persists |
| --- | --- | --- | --- |
| T1 | Timeout, DNS or TLS failure, connection reset, HTTP 408, 500, 502, 503, 504, 520 to 524 | Up to 3 tries in the read, with a randomised, growing pause (2 s, up to 30 s). A `Retry-After` of up to 60 s is obeyed in place. | **Outage** |
| T2 | HTTP 429. Or HTTP 403 or 503 that carries `Retry-After`, or that started when we were sending faster than the portal allows | Halve this portal's request rate (down to one request per 10 s), wait, go on. The slower rate is kept for the portal. | **Outage** only if it still happens at the slowest rate |
| T3 | Signs of a login or bot wall | Looked at only when Step 2 says the content did not arrive | see Step 2 |

### Step 2: did what we asked for arrive?

Presence of a captcha script, widget or cookie is never a reason. Only the outcome counts.

| Rule | The outcome is there when | If it is missing |
| --- | --- | --- |
| O1 list | The recipe's row locator matches at least one row. Or the list is provably empty: the portal prints a total of 0, the empty-state marker learned at attach is on the page, or a JSON API answers with its usual keys and an empty list. | With a block sign (table below): fetch once more, through the browser if plain HTTP was used. Still blocked: **Block**. A maintenance page: **Outage**. Neither: suspect, go to Step 4. |
| O2 file | Status 2xx; not an HTML page where a file was expected; the first bytes fit the type (`%PDF`, `PK`); size above 0 and equal to the announced size when one was given. | Same classification, per file. One file is not the portal: see D1. |

### Step 3: is what we extracted right? (no model)

| Rule | Check | Threshold | Outcome |
| --- | --- | --- | --- |
| C1 complete | Paging reached its end; no id twice; when the portal prints a total, we extracted exactly that many | exact, after one re-read of the list (lists change while we page) | fail: **Breakage** |
| C2 shape | Every record validates: required values parse, the id has the shape learned at attach, the deadline is after publication, enum and code formats hold, and **no value contains markup** | per value | The value is sent as null or left out, never published wrong. It counts as lost in C3. |
| C3 known tenders reproduce | For tenders in this read and in the last good one: how many **lost** a required value, how many **changed** a value, per field | lost: 2, 3, 5, 14 tenders for 3, 10, 50, 500 known*; changed: 3, 3, 6, 22* | lost: suspect, Step 4. changed: **spot check** by the model. |
| C4 known open tenders still listed | Tenders that were open, have a deadline still ahead, and are absent now | any | Look at the detail page of up to 5 of them. One still open: **Breakage**. All gone or withdrawn: accept, set `closed` or `withdrawn`. If the number missing reaches 3, 5, 9, 42 for 3, 10, 50, 500 known*, also require that the list's structure is intact or the printed total agrees; if not, **Breakage**. |
| C5 new tenders are as complete as before | Nulls per required field among tenders first seen in this read, against all rows of earlier good reads | exact test, 1 in 1,000* | suspect, Step 4 |
| C6 canary | Two known detail pages and one known file are fetched again on every read and must give the same id and title, and a valid file | exact | fail twice: **Breakage** |
| C7 structure | The list or detail page's structure differs from the stored one by more than this portal normally varies | per portal, measured at attach | **spot check** by the model; never a failure alone |
| D1 files | Files that fail O2 in this read, against the failure share of earlier good reads | exact test, 1 in 1,000*; and always when every file fails (2 or more) | Failed files are tried once more at the end. Then by cause: **Outage**, **Block** or **Breakage**. Below the threshold: publish the rest, log the failures on the run. |
| F1 age | The portal says `serving` and the last read that passed is older than 3 read intervals | fixed | `healing`, "no successful read since ..." |

### Step 4: confirm

A suspect read is repeated at once for the part that failed (the list, or the affected detail pages), and C4's detail-page look is run. If the second observation is clean, the read passes and the first result is logged. If it repeats, the read has failed. This costs a handful of requests and no tokens.

A spot check (C3 changed, C7) is one small model call that must quote the page for each value, as in draft 2. If it fails, the read is **Breakage**.

### Step 5: verdict, state and reason

| Verdict | State | Model tokens | Example reason |
| --- | --- | --- | --- |
| Pass | `serving` | none | "Read at 14:02 found 23 open tenders, 2 new and 1 closed. Every check passed." |
| Pass, empty | `serving` | none | "The portal lists no open tenders at 14:02. Its own 'no results' notice is shown, and the 4 tenders we knew are closed." |
| Outage | `healing` at once; `failed` after 60 minutes without an answer | none | "The portal has not answered since 14:07 (HTTP 503, three tries). Still delivering the 23 tenders read at 14:02. Next try 14:09. The recipe is unchanged." |
| Outage, long | `failed` | none | "The portal has been unreachable for 3 hours (DNS failure). This is not a login block. We check again every 6 hours and on every refresh." |
| Block | `failed` at once, after one confirming fetch | none | "Login required: the tender list redirects to /anmelden and shows a password field. We do not log in." or "Bot protection blocks the list (Cloudflare challenge). We do not solve captchas." |
| Breakage | `healing`, repair starts | yes | "The list reads 9 tenders but the portal prints 23, also on a second read. Repairing; still delivering the 23 tenders read at 14:02." |
| Breakage, repair budget used | `failed` | none after | "The layout changed at 14:07. Three repair attempts failed (list locator, paging, full re-learn). A person is needed." |
| Stale | `healing` | none | "No read has passed since 13:20. Reads are not completing." |

Going back to `serving` takes one full read that passes every check and reproduces the last good records, as draft 2 already requires for a repair.

## Thresholds, and where each comes from

**The significance level, 1 in 1,000.** Lerman, Minton and Knoblock made their wrapper-change decision "at a high significance level (corresponding to α = 0.001)" (**read**), and Soda's forecast check ships with an interval width of 0.999 (**read**: source). We use the same level everywhere.

**C4, missing known tenders.** Model: each open tender with its deadline ahead disappears between two reads with probability q; the number missing follows a binomial law. Smallest number missing that has a chance of at most 1 in 1,000 (**measured**: computed today):

| q per read | 3 known | 10 known | 50 known | 500 known |
| --- | --- | --- | --- | --- |
| 0.01 | 2 | 3 | 5 | 14 |
| 0.02 | 3 | 3 | 6 | 22 |
| **0.05** (used for C4) | **3** | **5** | **9** | **42** |

Why q = 0.05 and not a measured rate: we found no figure for tenders removed before their deadline. The nearest are cancellation rates before award, about 5 to 10% across the EU and up to 25% for Danish local government (**search** only). Spread over a tender's open weeks, that gives q far below 0.001 per read at our interval, so a single missing tender would already count as significant. A real base rate therefore cannot be the alarm threshold. That is exactly why C4 looks at the detail pages for any missing tender, and why the statistical threshold only adds the structure check for a mass disappearance. q = 0.05 leaves room for removals that come together, such as all lots of one cancelled procedure, and stays valid for gaps of up to a day. After a longer gap it is recomputed: 0.056 after three days, 0.126 after a week (**ours**).

What a fixed percentage does instead, as false alarms per read at q = 0.05 (**measured**): a 30% rule fires on 14% of reads with 3 known tenders; a 50% rule on 0.7%. At 500 known tenders a 30% rule waits for 150 missing where 42 is already a 1-in-1,000 event.

**C3, lost and changed values.** The same tender is read twice, so this is a paired comparison, far stronger than comparing rates. With a 1% chance per read that a required value truly disappears from a tender, the 1-in-1,000 thresholds are the q = 0.01 row above; with 2% for a true change, the q = 0.02 row (**ours** for the two rates). With a single known tender, one lost value is not significant; it is confirmed by a re-read and then sent to the spot check.

**C5 and D1, rates among new rows or files.** Two samples are compared, so the test is Fisher's exact test, one-sided. Fewest nulls among the new rows that are significant at 1 in 1,000 (**measured**):

| Earlier good rows (nulls / rows) | 3 new | 10 new | 50 new |
| --- | --- | --- | --- |
| 0 / 5 | never | 10 | 40 |
| 0 / 20 | 3 | 6 | 18 |
| 0 / 200 | 2 | 3 | 5 |
| 10 / 200 | 3 | 5 | 11 |

The test has little power on a small portal, and that is correct: five rows do not establish a rate. Small portals are covered by C2, C3 and C4, which do not need one.

**C7, structure.** No published, evaluated threshold exists for detecting extractor breakage from page structure (see Evidence). So the fingerprint (the set of tag-and-class paths, plus whether each of the recipe's anchor locators still resolves) is compared by similarity against a floor measured on this portal: the lowest similarity among the pages fetched at attach, minus 0.1 (**ours**). It only ever triggers a spot check.

**T1, retries.** Three attempts per request and randomised growing pauses are sourced (see Evidence). The 2 s base, 30 s cap and 60 s inline limit are **ours**.

**Outage to `failed` after 60 minutes.** No source gives a number; Google's own guidance speaks only of "multiple days". Our rule ties the word to our behaviour: `healing` while we retry at a pace someone watching would call active (the first hour of the ladder in Q14), `failed` once we have fallen back to slow checks (**ours**). See the question for the mentors below.

## Block signs

Looked at only when the outcome is missing (O1, O2).

| Sign | Where | How we know |
| --- | --- | --- |
| HTTP 401 with `WWW-Authenticate` | status, header | read: RFC 9110 |
| Redirect to a login or single-sign-on address; a password field where a list was expected | final URL, page | ours |
| `cf-mitigated: challenge` | response header. Set for every kind of Cloudflare challenge page; "challenge is the only valid value" | read: Cloudflare docs |
| AWS WAF: HTTP 202 (challenge) or 405 (captcha) on a request that is not a page load, such as a file download | status | read: AWS blog |
| "Request Rejected ... Your support ID is" | body. Seen today from Spain's national portal on a plain request. | measured; the wording as an F5 sign is search only |
| Imperva: `_Incapsula_Resource` frame or script | page | read: Crawlee source treats it as blocked |
| reCAPTCHA, hCaptcha, Turnstile, Friendly Captcha (`frc-captcha`), ALTCHA, DataDome, PerimeterX markers | page, cookies | read: open fingerprint list. These prove the product is present, not that we were blocked. |
| HTTP 403 with none of the above, also on a slow second try through the browser | status | read: RFC 9110, "understood the request but refuses to fulfill it" |

## The alternatives, and why they lose here

| Alternative | Who does it | Why it loses for this project |
| --- | --- | --- |
| Fixed percentage drop in the count (draft 2 had 30% and "halves") | Spidermon's comparison with earlier jobs is a plain fraction of their mean, off by default | Fires on one tender in a small portal; blind in a large one. Numbers above. |
| Thresholds learned from the portal's own history | Elementary (3 standard deviations, 14 days of training, at least 7 points), dbt-expectations (3 sigma, 14 periods), Deequ (3.0; first 10% of points ignored), Soda (at least 4 points) | Needs days of history we will not have, and scores a constant history as "no anomaly", so a stable small portal dropping to zero is missed. |
| Wait for N failures in a row before changing state | Kubernetes probes default to 3 consecutive failures; Prometheus `for:` | At our interval that is 10 to 15 minutes of reporting `serving` while broken. Google's SRE workbook rates duration-based alerts "poor recall and poor detection time". A second observation gives the same certainty in seconds. |
| Decide "blocked" from status codes alone | Crawlee treats 401, 403 and 429 as blocked | 429 means slow down. And Poland's national portal answers **403** when a client passes 30 requests a minute, so a 403 can be a rate limit. A system that reports `failed` there is wrong and stays wrong. |
| Decide "blocked" from a captcha being on the page | Crawlee's three selectors | The organisers' own trap. reCAPTCHA v3 "will never interrupt your users"; a widget on a contact form blocks nothing. |
| Learn value patterns per field and test their statistics | Lerman et al. 2003 | Caught 35 of 37 real changes, but 13 false alarms in 438 checks (precision 0.73), 10 of them artefacts of the learned patterns. We keep the cheap part (C2) and get the rest from paired comparison of known tenders, which needs no learned patterns. |
| Compare the whole result with the last one | Kushmerick's baseline | "Performs perfectly for only 19% of the sites", because content changes. We compare only the tenders present in both reads, which should not change. |
| Structure fingerprint as the main alarm | proposed in draft 2 as one of four checks | No evaluated threshold exists anywhere we looked. Kept as a trigger for the spot check only. |

## Evidence

### Wrapper verification research

- **Lerman, Minton, Knoblock, JAIR 2003** (**read**; numbers checked twice against the paper text). 27 wrappers on 23 sources, May 1999 to March 2000. "A manual check of the 438 comparisons revealed 37 wrapper changes ... correctly discovered 35 of these changes and made 15 mistakes. Of these mistakes, 13 were false positives". Numeric features alone: precision 0.92, recall 0.55. Causes of the 13 false alarms: 5 from splitting URLs with session keys, 5 from over-specific learned patterns, 3 from real data or format changes.
- **Kushmerick, AAAI 1999** (**read**; checked twice). 27 sites, 6 months, 23,416 pages. 56% of sites never changed; 23 changes in all, 0.85 per site. The best detector used only the share of markup characters inside extracted values, with the number of tuples ignored: 3 mistakes over 23,416 predictions. Exact-match comparison with the previous result "performs perfectly for only 19% of the sites". Lerman later found markup share alone missed 17 changes on their data, so it is a strong check, not a sufficient one.
- **Parameswaran et al., VLDB 2011** (**read**): at Yahoo, wrappers "had an average life of 2 months, with 1 out of every 50 wrappers breaking every day on average". An anecdote, with no method given.
- **How often sites break extractors:** the two measured studies both give about 0.14 changes per site per month. So a real portal changing by chance during a day of judging is unlikely (**ours**, from those rates), and false alarms are the larger risk on real portals. The private portals will be changed on purpose.
- **Zhang 2026, arXiv 2611.00884** (**read**): 20.9% of pages a plain client receives with status 200 lack the page's main content; 13.1% of sites answer a random missing path with 200. Simple checks (text length, a random-path probe, redirect to the home page) recover 86% of unusable responses at about 5% false alarms. This is why O1 tests the outcome and never trusts a 200.
- **AutoScraper, EMNLP 2024** (**read**): verifies a generated scraper only when it is generated; no runtime monitoring. We found no peer-reviewed study from 2023 to 2026 that measures breakage detection for model-written scrapers.
- **Not read:** McCann et al. 2005 (the publisher refuses downloads), Vertex's monitoring method, and all fingerprint thresholds. Nothing above depends on them.

### Data-observability and scraper-monitoring tools (**read** from the shipped source code)

- Spidermon 1.27: item count, error count, validation and field coverage have **no default threshold**; the only active defaults are 10 responses per unwanted HTTP code (400, 407, 429, 500, 502, 503, 504, 523, 540, 541) and a finish reason of "finished". Comparison with earlier jobs is off by default.
- Great Expectations: `mostly = 1`, every row must pass. Soda 4: row count above 0, missing count 0, no default for freshness. dbt: any failing row fails.
- Elementary: sensitivity 3, 14 days of training, minimum 7 points. dbt-expectations: 3 sigma, 14 test periods. Deequ (Schelter et al., VLDB 2018): 3.0 standard deviations, first 10% of points ignored. Soda 3: at least 4 points, interval 0.999.
- No tool we found compares the count with a total the portal prints, or checks that known items are still listed. Those two rules are ours, and they are the ones that answer the question's "few or no open tenders" condition.

### HTTP and blocking (**read**; the quoted sentences were checked a second time against the saved documents)

- RFC 9110: 503 means "currently unable to handle the request due to a temporary overload or scheduled maintenance"; `Retry-After = HTTP-date / delay-seconds`; 403 means the server "understood the request but refuses to fulfill it"; 401 means the request "lacks valid authentication credentials". RFC 6585: 429 "MAY include a Retry-After header".
- Cloudflare: a challenge page "will have the cf-mitigated header present and set to challenge". The status code of a challenge page is not documented; do not rely on 403.
- Google reCAPTCHA v3 "will never interrupt your users".
- Google's crawlers: "5xx and 429 server errors prompt Google's crawlers to temporarily slow down", and "Don't use 401 and 403 status codes for limiting the crawl rate". No fixed time to give up is stated.
- e-Zamówienia, Poland (**read** and checked twice): "z jednego adresu IP można wysłać maksymalnie 30 zapytań w ciągu minuty, po przekroczeniu tego limitu system zwróci odpowiedź HTTP 403 (Forbidden)". 30 requests a minute is half of what our own rule allows.
- Retries: Google SRE book, "per-request retry budget of up to three attempts" and "Always use randomized exponential backoff when scheduling retries"; AWS, "the no-jitter exponential backoff approach is the clear loser". The SRE numbers are for internal services, so they are precedent by analogy. Scrapy retries 408, 429, 500, 502, 503, 504, 522, 524 twice, with no pause; Crawlee three times.
- Crawlee's "blocked" codes are 401, 403 and 429, and it checks three page selectors; Scrapy has no block detection.

### Alerting practice (**read**)

- Google SRE workbook, on alerts that wait for a duration: "Poor recall and poor detection time: Because the duration does not scale with the severity of the incident".
- Kubernetes probes: 3 consecutive failures by default, 10 s apart (from the client library's field documentation).

## What would change the decision

- A measured rate of tenders removed before their deadline, from our own reads over a few weeks, would replace q = 0.05.
- If the mentors say a long outage must read `healing`, or a short one `failed`, the 60-minute line moves. The rules do not.
- If the judges' private portals print totals, C1 does most of the work and C4 rarely runs.

## For the mentors

1. A portal that is down, not changed: should it read `healing` or `failed`, and after how long?
2. When a portal answers 403 or shows a challenge to a plain HTTP client but serves a normal browser, may we read it with the headless browser? We assume yes: it is a real browser and we solve nothing.

## Prototype first (about 5 hours)

1. 1.5 h: the verdict function. Input: this read's records, the last good read, per-request outcomes. Output: verdict, the rules that fired, the reason sentence. Pure code, tested with made-up reads.
2. 1.5 h: the confirm step (re-read, detail-page look for missing tenders) and the canary.
3. 2 h: run it against the mock portal's switches (Q8). Each row of the verdict table must be produced by at least one switch, and "list emptied with the no-results notice" must stay `serving`. **Target: no false `healing` on the empty and the small portal, and no missed change.**

## Effect on other questions

- **Q1 recipe model:** the recipe carries what these rules read: the id shape, the locator of the printed total and whether it counts closed tenders, the empty-state marker, the anchor locators, and the structure fingerprint with its floor.
- **Q2 locators:** a locator conflict or a single-witness value feeds C2 and C3 as a lost value. The "identical on 90% of tenders" check there is a C3-style rule and should use the same test.
- **Q4 agent tools:** the learner needs one extra step, a search that returns nothing, to record the empty state.
- **Q7 schemas:** a check result is rule id, verdict (pass, suspect, cleared, failed), the counts and the evidence; a run stores them and the reason sentence.
- **Q8 benchmark:** one mock switch per verdict row, plus: paging cut to one page, a 403 rate limit with `Retry-After`, a captcha widget that blocks nothing, a list emptied with and without the notice.
- **Q11 reuse:** the canary for a reused recipe is these same rules.
- **Q12 large portals:** the checks cost at most 8 extra requests per read (5 detail looks, 2 canary pages, 1 file).
- **Q13, Q14:** the read interval sets F1; the outage ladder is in Q14.
- **DESIGN.md:** replace the 30% and "halves" continuity rule, the 10% run rule and the 30-minute outage line with the rules above; add rate-limit handling (T2) and the outcome test (O1, O2) to triage.

## Sources

Read on 20 Nov 2026.

- Lerman, Minton, Knoblock, "Wrapper Maintenance: A Machine Learning Approach", JAIR 18 (2003): https://arxiv.org/abs/1106.4872
- Kushmerick, "Regression testing for wrapper maintenance", AAAI 1999: https://cdn.aaai.org/AAAI/1999/AAAI99-011.pdf
- Parameswaran, Dalvi, Garcia-Molina, Rastogi, "Optimal schemes for robust web extraction", PVLDB 4 (2011): http://www.vldb.org/pvldb/vol4/p980-parameswaran.pdf
- Zhang, arXiv 2611.00884 (31 Oct 2026): https://arxiv.org/abs/2611.00884
- Huang et al., AutoScraper, EMNLP 2024: https://arxiv.org/abs/2404.12753
- Schelter et al., "Automating Large-Scale Data Quality Verification", PVLDB 11 (2018): https://www.vldb.org/pvldb/vol11/p1781-schelter.pdf
- Spidermon 1.27.0, `spidermon/contrib/scrapy/monitors/monitors.py` (package from PyPI); Scrapy 2.20.0, `scrapy/settings/default_settings.py`; Crawlee 3.18.2, `session_pool/consts.js` and `utils/internals/blocked.js` (packages from npm)
- Elementary, dbt-expectations, Great Expectations 1.25, Soda and Deequ defaults: their source files on GitHub and PyPI
- RFC 9110: https://www.rfc-editor.org/rfc/rfc9110.txt ; RFC 6585: https://www.rfc-editor.org/rfc/rfc6585.txt
- Cloudflare, detecting a challenge page response: https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/
- Google reCAPTCHA v3: https://developers.google.com/recaptcha/docs/v3
- Google, how HTTP status codes affect its crawlers: https://developers.google.com/crawling/docs/troubleshooting/http-status-codes
- AWS WAF Challenge and CAPTCHA actions: https://aws.amazon.com/blogs/networking-and-content-delivery/protect-against-bots-with-aws-waf-challenge-and-captcha-actions/
- AWS, "Exponential Backoff And Jitter": https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
- Google SRE book, "Handling Overload" and "Addressing Cascading Failures": https://sre.google/sre-book/handling-overload/ , https://sre.google/sre-book/addressing-cascading-failures/
- Google SRE workbook, "Alerting on SLOs": https://sre.google/workbook/alerting-on-slos/
- e-Zamówienia traffic control for the notice API (6 Oct 2026): https://ezamowienia.gov.pl/pl/mechanizm-kontroli-ruchu-dla-endpointow-w-ramach-api-bzp/

Seen only in search results, and used only where marked: cancellation rates (Public Management Review 2023; a European Commission country profile for Denmark), the F5 "Request Rejected" wording, the `x-amzn-waf-action` header.
