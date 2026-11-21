# End check: is every answer backed by research?

Checked 20 Nov 2026. Every answered question was tested against the answer standard in [README.md](README.md): is the decision stated with its reasons, were real alternatives compared, was each load-bearing claim read at its source, and are the numbers we chose ourselves marked as ours.

For the questions answered by teammates (Q1 to Q5, Q7 to Q9, Q11) a separate pass opened the primary sources again, redid the arithmetic and ran what could be run, without trusting the files. For Q6, Q10, Q12, Q13 and Q14 the quotes and numbers the decisions rest on were checked a second time against the saved documents, packages and live APIs.

## Summary

| Q | Reasons given | Alternatives compared | Claims read at source | Own numbers marked | Verdict |
| --- | --- | --- | --- | --- | --- |
| 1 Recipe model | yes | no: not compared with the staged recipe | mostly; 4 corrections | no | **The direction holds; the draft recipe does not.** It cannot express three cases it has to. |
| 2 Field locators | yes | partly | mostly; 5 corrections | partly | **One rule to fix before building.** The direction is sound. |
| 3 Explore or map | yes | yes | partly | no | The headline holds. The probe checklist found nothing on four portals, and robots.txt is undecided. |
| 4 Agent tools | yes | yes, but three rejections rest on wrong reasons | partly; 4 corrections | no | **One claim to fix before building:** the rate limiter does not see redirect hops. The direction is sound. |
| 5 Agent framework | yes | yes; one alternative weighed on the wrong point | yes, from the package | partly | Usable. Output retry and the budget stop are not in the SDK and must be ours. |
| 6 Language | yes | yes (3) | yes, and measured | yes | Ready. One input not measurable: the team's own skills. |
| 7 Schemas | yes | not applicable | yes; tests pass | yes | The API layer is ready. The internal records need four additions for Q10, Q12 and Q14. |
| 8 Benchmark | yes | partly | partly | no | Sound design. Metric definitions and about nine scenarios to add before it can score anything. |
| 9 Models and cost | yes | partly | yes for names and prices | partly | **Use the prices. Do not quote the cost per portal** until it is measured: it holds only if the context is trimmed on every call. |
| 10 Failure rules | yes | yes (8) | yes | yes | Ready to prototype. Untested until it runs on the mock portal. |
| 11 Reuse | yes | partly | API facts yes; family table has errors | partly | Usable. One gap: a same-template test portal still gets no candidate. |
| 12 Large portals | yes | yes (10) | yes, and measured on one portal | yes | Ready. One rule waits on the mentors. |
| 13 Read schedule | yes | yes (5) | partly; the theory is from search results | yes | Ready. |
| 14 Failed retry | yes | yes (5) | yes for the shape; the steps are ours | yes | Ready. |

## Q1 Recipe model

Checked against the cited papers and OpenAI's rules for strict output, and by walking the draft recipe through five cases. The author has since revised the example recipe; this is the file's state now.

**Confirmed and worth keeping:** "learn once, run without a model, repair locally" is well supported by the cited work.

**Fixed since the first pass:** the publication date is a date, procedure type and contract nature are mapped to the contract's values, the place of performance is an object, and files over 250 MB are skipped (it was 5 GB).

**Still to fix:**

1. **The graph is compared with a fixed-stage recipe in general, not with the one already in `DESIGN.md`**, whose source is "a short series of GET or POST steps". That recipe already allows the extra hop the answer says fixed stages cannot express, so the comparison does not yet show the graph is needed.
2. **The draft recipe cannot express three cases it has to:** paging by form post with hidden state fields, a JSON API that takes its query in a POST body, and a multi-step document download. The `download` node kind named in the summary does not appear in the draft.
3. **The draft breaks its own rules for a strict schema:** maps with free keys, nested edges, node kinds outside its "closed set". Its CPV path returns nothing, `contains` is not JSONPath, and `nodes[id=list]` is not a JSON Patch path. JSONPath and JSON Patch are also packages nobody has declared.
4. Citations: AutoScraper's break-even of 19.5 pages is the paper's own figure and is measured in time; WebLists' replay can call a model per element; Crawl4AI's schema generation makes several model calls; Co-Scraper's 90.39% is per field (70.73% per page), and it generates code, the option this answer rejects.
5. Where it disagrees with other answers:
   - It keeps a 30% count rule and waits for two bad reads; Q10 replaced both. It has no place for what Q10's rules read (id shape, the printed total's locator, the empty-state marker).
   - Documents in round-robin against soonest deadline first; 3 files per tender against the measured 9 (Q12).
   - `integrating` with progress until the documents finish, against Q12's records gate.
   - It differs from `app/models.py`: status is computed there, version and fingerprint are duplicated, and there is no slot for the portal's time zone.
6. Numbers without support: 6 interpreters, 11 hours, plus or minus 30%, 100K to 300K tokens.

## Q3 Explore or map first

Checked against the cited paper and by trying the proposed probes on four public portals.

**Confirmed and worth keeping:** do not map the site first. TenderNed's sitemap alone lists about 95,000 historical notice addresses, stronger support than anything in the file.

**Still to fix:**

1. **Guessing feed and API paths found nothing:** 0 hits in 32 requests on four portals (`/feed`, `/rss`, `/api`, `/ocds`, `/swagger` and the like). What works is the page's own network calls and the links the pages themselves offer. Guessed paths should come last or go.
2. **robots.txt is read third and nothing says whether we obey it.** Spain's national portal answers `Disallow: /` for every robot, its feed path included. The team has to decide and say so; it is now a question for the mentors.
3. It delivers tender records while `integrating`, which contradicts the organisers' definition (Q12).
4. "Catches most JavaScript portals in one page load" has no support: TenderNed's entry page is not its list. And the agents in the cited "Beyond Browsing" paper were handed documented APIs; they did not find them.
5. Numbers without support: 10 to 25 probes, 60 pages, 300 to 3,000 addresses, 3 files per tender.

## Q2 Field locators

Checked against the papers, Healenium's source and TenderNed's live API. The author revised the file after a review of his own; this is its state now.

**Fixed since the first pass:** links, paging and identity are now covered; an optional field that stops being found counts against its fill rate; values are grounded before they are normalised.

**Still to fix:**

1. **A single surviving locator is still accepted when its value checks pass.** That rule fires exactly when the page has just changed, which is when the survivor is least trustworthy, and the neighbours it would pick (question deadline, opening date) pass every value check. Accept a single survivor only when its value equals the last good value for the same tender; otherwise null. Many single survivors in one read are a drift sign (Q10, rule C3).
2. **Several locators written by one model from one page are not independent witnesses**, though the file still calls them that. In Similo's own data five locator kinds fail together on 24.4% of elements; independence would predict 3.5%. Agreement that means something comes from different sources: list row against detail page, page against the portal's API, this read against the last good one.
3. Citations:
   - Lerman et al.: 13 false alarms, not 16. The paper's body counts 15 mistakes, 13 of them false alarms; seven of the 37 changes were the authors' own edits to their wrappers.
   - Healenium does not always return a guess. Its default score floor is 0.6, below which it reports nothing found.
   - The paper that supports ids also found that paths anchored on ids broke in 557 of 1,110 cases.
   - Similo is cited in two versions with different numbers (91 of 801 in the journal, seen only in a search result; 72 of 598 in the arXiv copy).
   - The TenderNed example with required keys fails on live data: award notices have no closing date.
4. Numbers without support: "identical on 90% of tenders" misfires on a single-buyer portal, which a municipal or a test portal is likely to be.
5. Added in the revision and not checked here: "29.5% fewer broken locators" for the multi-locator method.

## Q9 Models and cost

Checked against OpenAI's pricing page, all nine model pages and the batch, flex and rate-limit guides.

**Confirmed at source:** every model name; the prices for `gpt-6.2-sol`, `gpt-6.1-terra`, `gpt-6-luna` and `gpt-5.4-mini`; the rule that a request over 272K input tokens is billed at twice the input and 1.5 times the output rate; context and output sizes; which models reject reasoning "none"; Batch at half price with a 24-hour window; the tier names.

**Fixed since the first pass:** the attach total ($1.68), the cost range (its inputs are now stated, and it reproduces), and the prototype cost ($5.04).

**Still to fix:**

1. **The cost per learn assumes the context does not grow, and the file's own warning says it does.** With its own assumptions, one learn costs:

| Assumption | `gpt-6.2-sol` | `gpt-6.1-terra` |
| --- | --- | --- |
| 30K input on every call (what the file prices) | $1.68 | $0.84 |
| Context grows 30K per call, no cache | $7.74 | $3.87 |
| Context grows, prefix cached | $2.27 | $1.13 |

   The $1.68 holds only if the learner trims its context on every call. That is a requirement on Q5's loop, not a given.
2. The token counts themselves (12 calls of 30K in and 8K out) are unmeasured. Q8 has to measure them before the hand-in README states a cost.
3. "Sol and Luna only accept tool calls on Chat Completions at reasoning none" is documented for `gpt-6-sol` and `gpt-6-luna`. The `gpt-6.1` pages say tool calling requires the Responses API. The `gpt-6.2-sol` page says nothing. The practical advice, use the Responses API, stands.
4. The choice of Sol over Terra has no quality evidence, and its stated reason (cheapest cached input) is contradicted by the file's own table.
5. Could not be checked from here: which tier our key is on, and whether the judges' key can use `gpt-6.2-sol`.

## Q11 Reuse

Checked against the live TenderNed, e-Zamówienia and Spanish feed APIs, and vendor pages where they opened. The author revised the file after a review of his own; this is its state now.

**Fixed since the first pass:** the numeric score is gone, and any host, path or brand match now makes a candidate; the printed total must match exactly on the full read; cosinex's two path forms are listed; the 30-requests-a-minute limit is honoured; seed recipes ship in the image.

**Still to fix:**

1. **A test portal built from the same template as an earlier one still gets no candidate.** It shares no host, path or brand text with anything, so it is learned from scratch, the very case the file says reuse will pay for. The only signal such a portal carries is its page structure. Matching the new portal's structure fingerprint (Q10, rule C7) against those of stored recipes would catch it; trying a recipe costs one or two requests, a missed match costs a full learn.
2. Family table: PLACE and Atexo are one family (PLACE runs Atexo's software). The second vendor behind `/NetServer/` could not be found.
3. Sizes: cosinex's 5,000 are awarding offices, not contracting authorities; Vortal's 10,000 are public and private buyers together; PLACE's operator reports 36,101 consultations in 2025, not 40,000. The argument for the Approach criterion needs hosts per family, not buyers.
4. Five detail pages for the canary: five clean pages only bound the failure rate below 45%. It is acceptable because the full read that follows does the real check; the text should say so.
5. "Its page size drops to 100" for Poland's API: a page of 500 was still accepted today. The lower cap is announced, not live.
6. The two cost figures come from Q9's unmeasured assumptions.

**Confirmed and worth keeping:** TenderNed's public API needs no login (only its XML endpoint does); e-Zamówienia allows 30 requests a minute and answers 403 beyond that; the Spanish feed.

## Q4 Agent tools

Checked against the Playwright, Playwright MCP and browser-use packages, the cited papers, and a local test server.

**Confirmed and worth keeping:** the direction. Our own tools on Playwright for Python and httpx, one rate limiter, trimmed HTML for writing locators.

**Still to fix:**

1. **`page.route` does not see every request, so the limiter built on it does not hold the 1 request per second rule by itself.** Redirect hops and WebSockets get past it. Measured twice on a local server, by two separate scripts: a page behind two redirects sent three requests within 10 milliseconds; the route handler saw only the first. Playwright's documentation says the handler is called once, for the original request. This also corrects draft 2 of `DESIGN.md`, which says every browser request passes through the limiter. Ways to close it: walk redirects ourselves in the HTTP client, one hop per second, and send the browser to the final address; store final addresses in the recipe at attach so reads skip the hop; block WebSockets with `route_web_socket` unless a recipe needs one.
2. **A page load in a JavaScript app can cost about 90 requests.** One cold render of TenderNed's site asked for 84 script files before its first data call. So Q10's "try once through the browser" is expensive there. It is done once per incident, and the script cache this answer already proposes is what makes it affordable.
3. Reasons given against the alternatives that do not hold:
   - Playwright MCP can be rate-limited: it accepts a browser context we create. Its real costs are that the limiter would run in Node, that version 0.0.86 pins a pre-release of Playwright 1.66, and that it needs Node on the path (Q6).
   - browser-use is described as it was before version 1.0. Since 10 November 2026 it is a coding agent on the raw browser protocol, and it ships a hook for captcha solving, which we may not use.
   - "Own tools are Python only": Playwright for Python ships a Node binary (Q6).
4. Facts to correct:
   - The Playwright version (1.64, taken from Wikipedia) is stale; 1.65.2 was released on 14 November.
   - The cost of a screenshot uses another provider's formula; OpenAI's gives about 1,100 tokens for 1280 by 720.
   - "TenderNed's JSON has no deadline": 15 of 20 list entries carry one.
   - In the notes file, the figures +13.3 and +20.9 are listed as "not in either paper"; both are in Table 2 of arXiv 2604.01535.
5. Where it disagrees with other answers:
   - It moves a portal to `healing` after two bad reads in a row; Q10 confirms with one immediate re-read. Q10 owns that rule.
   - Its limiter is keyed by host; `DESIGN.md` and Q12 key it by portal. The brief says "per portal", and a portal's files often sit on a second host, so per portal is the safe reading.
6. Numbers without support: 100K to 300K tokens per learn, about 8 tools, 4K tokens per page view, the 0.9 requests per second margin, the hour estimates. The tool definitions of Playwright MCP measure 4,864 tokens, not about 3,919.

## Q5 Agent framework

Checked against the `openai-agents` 0.25.0 package source, and by running it against a local stand-in for OpenAI's API.

**Confirmed and worth keeping:** the SDK uses the Responses API by default. Only `/v1/responses` was called in the test run. That settles the worry from Q9. If no model is named it picks its own default, so always name one.

**Still to fix:** two things the answer relies on are not in the SDK.

1. **With `output_type` set, the SDK does not keep going until the answer is valid.** Invalid JSON raises an error after one request. "Validated output or retry" (`CONVENTIONS.md`, rule 10) has to be our code.
2. **A tool that raises when the budget is used up does not stop the run.** The SDK hands the error to the model and carries on to `max_turns`: 8 more requests in the test. The budget has to stop the run from outside the tool.
3. The default `max_turns` is 10, not "permissive" (checked twice in the source). Setting it explicitly is still right.
4. PydanticAI was set aside because its portability buys little. But the answer itself says its usage limits cap requests, tool calls and tokens per run, which is items 1 and 2. The comparison should weigh that against one more thing to learn.
5. Numbers without support: the 150-line fallback loop, the 1-hour spike.

## Q7 Schemas

Checked by running the tests on a copy (19 pass on Python 3.12 and 3.13) and by comparing the models with the contract, the tables, and the answers to Q10, Q12 and Q14.

**Confirmed and worth keeping:** the API models produce the contract's answers; the tables match the models field for field.

**Still to fix, so the models can carry the other answers:**

1. **An outage.** A failed check sends a portal to `healing`, which today implies a repair. Q10 needs `healing` without one (see "Names for `CheckResult`" in [q10-failure-rules.md](q10-failure-rules.md)).
2. **A tender whose documents are not in yet.** `documents` cannot be null in the API model, though the contract allows null for a required field, and a file's id is the hash of its bytes, so a file not yet fetched has none. Q12's early gate needs both.
3. **What a failed portal remembers** (Q14): the page structure we gave up on, the time of the next check, today's repair count. `Portal.fingerprint` is the software, not the page structure. There is also no per-portal request rate for portals that state their own limit.
4. **Read bookkeeping** (Q12): no hash of a tender's list row, and nowhere to hold records before the gate.
5. Smaller: internal times without a zone are accepted; a partly known place of performance sends nested nulls; the same file twice in one tender breaks the table's key; one row per run and check name cannot hold a first observation and its confirmation.
6. eForms references: `publicationDate` cites BT-05, which is the notice's dispatch date (checked in `app/models.py`); the procedure-type map misses two codes; the link to SDK 1.12 is dead, the current one is 1.16.0.
7. **There is no `pyproject.toml`**, though `app/models.py` needs pydantic. The repo's own rule is that every package is declared there.
8. `CONVENTIONS.md` rule 2, no model call in a regular read, needs one exception: Q10 makes one small spot-check call when a portal's structure has changed.

## Q8 Benchmark

Checked against the judging criteria, the failure rules in Q10 and the sequences in Q14, and a few of the listed portals.

**Confirmed and worth keeping:** the two test beds, a mock portal plus real portals replayed from recordings, and recording at our own fetch layer.

**Still to fix:**

1. **Several metrics would not come out the same for two people.** State accuracy does not say what the right state is at each moment after a change. Time to notice has no defined start (the change, the refresh, or our next read) and no meaning for scenarios that should end `failed` or stay `serving`. Field scores do not say when two values count as equal (whitespace, the same instant in two offsets, lists). False alarms have no unchanged control portal to be counted on.
2. **The 16 scenarios miss cases the other answers need:** an outage that lasts past the retries and then ends; a rate limit (429, and 403 with `Retry-After`); a list emptied without its notice; paging cut to one page; a repair budget used up; the three sequences in Q14 with their model-call counts; one tender's detail changed only on its detail page; a large portal for Q12's state rule; and a measure of our own request rate at the mock portal.
3. **"The open-id list is cheap" does not hold for large portals.** The file's own Austrian portal shows 175,140 results. And the 1,707 given for TenderNed is every publication since 1 November, of which about a third are contract notices.
4. **Five labelled tenders per portal cannot show a per-portal error rate**: with five clean tenders the rate is only known to be under about 60%. Forty across all portals bound it at about 7.5% overall. Two minutes per tender is also short when a tender has 8 or 9 files to hash.
5. Spain's HTML pages refuse a plain client (seen twice today), so that row of the portal list will not behave as described.
6. Numbers without support: 8 to 10 person-hours, recall 0.95, 15 minutes, the weight of 2 on errors.

## Q6, Q10, Q12, Q13, Q14: our own check

**Checked a second time, by a separate run or against the saved source:**

- Q6: the Node binary inside Playwright's Python package (present, runs, version 26.13.1); no XPath anywhere in cheerio; no Polish in chrono-node and all six languages in dateparser; the HTML parsing benchmark, re-run.
- Q10: the quoted sentences from RFC 9110, Cloudflare, Google (reCAPTCHA and crawler pages), the AWS posts and both SRE books; Lerman's and Kushmerick's numbers in the papers' text; Scrapy's, Crawlee's and Spidermon's defaults in their source; the Polish 403 rate-limit notice on the portal's own page.
- Q12: TenderNed's page-size cap, from the live API's own error message.

**Our own choices, with no source behind the number:**

- Q10: the removal rates 0.05, 0.01 and 0.02 per read; five detail-page looks; the per-portal structure floor; 60 minutes from outage to `failed`.
- Q12: the 10-minute rule for finishing documents before `serving`; a fifth of the budget for re-reading detail pages.
- Q13: the 2-minute floor, the 10% share, the 30-minute cap.
- Q14: every step of both retry ladders.

Each is one setting, and each file says what would change it.

**Weak evidence the decisions still lean on:**

- Q12: documents per tender and megabytes per tender come from 40 tenders on one portal on one day, and the one open-tender count (1,551) is for the same portal.
- Q10: no measured rate exists for tenders removed before their deadline. The rule set is designed so that this rate does not decide anything alone.
- Q12 and Q13: "refresh evenly, not in proportion to change rate" was seen only in search results; the paper sits behind a publisher wall.
- Q6: the team's own skills were not measured; Playwright's list of features missing in Python was not readable.

## Decisions in DESIGN.md that still have no research behind them

| Decision in draft 2 | Status |
| --- | --- |
| Continuity thresholds (30%, "halves"), the 10% run rule, 30 minutes to `failed` | Replaced by Q10 |
| Read interval, 3 times the last read | Replaced by Q13 |
| Failed portals checked hourly | Replaced by Q14 |
| Publish only after a full first read | Replaced by Q12 |
| Two browser pages at a time | Now supported: two tabs measured at 592 MB (Q6) |
| Every browser request passes through the rate limiter | **Not true as written.** Redirect hops and WebSockets get past `page.route` (measured twice). See Q4 above for the fix. |
| Repair accepted when 90% of ids and 90% of values reproduce | Still our default. Q10's paired test (rule C3) would be the better-founded rule. |
| Three repair attempts per incident | Still our default |
| Four model calls at a time | Still our default; Q9 confirms it is far under the rate limit |
| Spot check by quoted passages | Q2's audit: a quote proves the text is on the page, not that the locator read the right node. Needs Q2's fix. |
| Recipe as the main path, generated code as fallback | Open: Q1 |
| Portal id derived from the URL; 201 on repeat | Still our default; not a research question |

## Limits of this check

- The research machine could not open every site. The ACM and Wiley libraries and OpenAI's older docs host refused. TED and the EU's legal site answered with a bot challenge, which we did not try to pass. Patterno's portal list opened once its second address was allowed, and is counted in [patterno-landscape.md](patterno-landscape.md).
- Portal measurements are from one day and small samples.
- Nothing here has been run against a real judge. The rules in Q10 and Q12 are designs until the prototypes pass on the mock portal.

## Decisions of a person after this check

- **20 Nov 2026: an outage is `failed`, not `healing`.** Q10 reports a portal that stops answering as `healing` (then `failed` after 60 minutes). The brief defines `healing` as "Broken. A repair is running", and an outage has no repair (this audit already noted it: Q7, "An outage"). Decided by David: an outage is `failed` with the cause `outage` from the first read that finds it; the cause says whether a person can help (`block` and a spent repair budget need one, an `outage` does not). `healing` is kept for a repair that is running. The retries stay on the outage ladder (Q14), then the failed schedule. This overrides Q10's state for an outage; the rest of Q10 stands. `DESIGN.md` is changed to match.
