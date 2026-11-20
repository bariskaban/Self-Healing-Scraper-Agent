# End check: is every answer backed by research?

Checked 20 Nov 2026. Every answered question was tested against the answer standard in [README.md](README.md): is the decision stated with its reasons, were real alternatives compared, was each load-bearing claim read at its source, and are the numbers we chose ourselves marked as ours.

For Q2, Q9 and Q11 a separate pass opened the primary sources again and redid the arithmetic, without trusting the files. For Q6, Q10, Q12, Q13 and Q14 the quotes and numbers the decisions rest on were checked a second time against the saved documents, packages and live APIs.

## Summary

| Q | Reasons given | Alternatives compared | Claims read at source | Own numbers marked | Verdict |
| --- | --- | --- | --- | --- | --- |
| 2 Field locators | yes | partly | mostly; 4 corrections | no | **Fix before building.** The direction is sound; one rule is unsafe. |
| 6 Language | yes | yes (3) | yes, and measured | yes | Ready. One input not measurable: the team's own skills. |
| 9 Models and cost | yes | partly | yes for names and prices; the cost table is wrong | no | **Use the prices. Do not use the cost per portal** until it is measured. |
| 10 Failure rules | yes | yes (8) | yes | yes | Ready to prototype. Untested until it runs on the mock portal. |
| 11 Reuse | yes | no | API facts yes; family table has errors | no | **Fix before building.** The scoring rule cannot be computed as written. |
| 12 Large portals | yes | yes (10) | yes, and measured on one portal | yes | Ready. One rule waits on the mentors. |
| 13 Read schedule | yes | yes (5) | partly; the theory is from search results | yes | Ready. |
| 14 Failed retry | yes | yes (5) | yes for the shape; the steps are ours | yes | Ready. |
| 1, 3, 4, 5, 7, 8 | | | | | Open. No answer in the repo yet. |

## Q2 Field locators: what to fix first

Checked against the papers, Healenium's source and TenderNed's live API.

1. **"1 hit, others miss: accept if the value checks pass" is the weak point.** It fires exactly when the page has just changed, which is when the survivor is least trustworthy, and the neighbours it would pick (question deadline, opening date) pass every value check. Accept a single surviving locator only when its value equals the last good value for the same tender; otherwise null. Many single survivors in one read are a drift sign (Q10, rule C3).
2. **Several locators written by one model from one page are not independent witnesses.** In Similo's own data five locator kinds fail together on 24.4% of elements; independence would predict 3.5%. Agreement that means something comes from different sources: list row against detail page, page against the portal's API, this read against the last good one.
3. **The question asked about links, and the file does not answer it**: nothing on the detail link, the next-page link or document links, although links to summary pages are a named trap.
4. Corrections to citations:
   - Lerman et al.: 13 false alarms, not 16. Seven of the 37 changes were the authors' own edits to their wrappers.
   - Healenium does not always return a guess. Its default score floor is 0.6, below which it reports nothing found.
   - The same paper that supports ids also found that paths anchored on ids broke in 557 of 1,110 cases.
   - Similo is cited in two versions with different numbers (91 of 801 in the journal, seen only in a search result; 72 of 598 in the arXiv copy).
   - The TenderNed example with required keys fails on live data: award notices have no closing date.
5. Numbers without support: "identical on 90% of tenders" (misfires on a single-buyer portal, which a municipal or a test portal is likely to be), "two or three" locators.

## Q9 Models and cost: what to fix first

Checked against OpenAI's pricing page, all nine model pages and the batch, flex and rate-limit guides.

- **Confirmed at source:** every model name; the prices for `gpt-6.2-sol`, `gpt-6.1-terra`, `gpt-6-luna` and `gpt-5.4-mini`; the rule that a request over 272K input tokens is billed at twice the input and 1.5 times the output rate; context and output sizes; which models reject reasoning "none"; Batch at half price with a 24-hour window; the tier names.
- **The cost per portal does not hold.** The file warns that context grows about 30K tokens per call, and prices a learn as if it did not. With its own assumptions, one learn on Sol costs:

| Assumption | `gpt-6.2-sol` | `gpt-6.1-terra` |
| --- | --- | --- |
| 30K input on every call (what the file prices) | $1.68 | $0.84 |
| Context grows 30K per call, no cache | $7.74 | $3.87 |
| Context grows, prefix cached | $2.27 | $1.13 |

- Arithmetic: "attach $1.69" is $1.68; "6 learns under $3" is $5.21 at the file's own prices; the range "$0.48 to $3.30" cannot be reproduced.
- "Sol and Luna only accept tool calls on Chat Completions at reasoning none" is documented for `gpt-6-sol` and `gpt-6-luna`. The `gpt-6.1` pages say tool calling requires the Responses API. The `gpt-6.2-sol` page says nothing. The practical advice, use the Responses API, stands.
- Unsupported: the token counts themselves (12 calls of 30K in and 8K out), and the choice of Sol over Terra, which has no quality evidence and whose stated reason (cheapest cached input) is contradicted by the file's own table.
- Could not be checked from here: which tier our key is on, and whether the judges' key can use `gpt-6.2-sol`.

## Q11 Reuse: what to fix first

Checked against the live TenderNed, e-Zamówienia and Spanish feed APIs, and vendor pages where they opened.

1. **The scoring rule is circular.** The strongest signal, "structure", is defined as running a candidate recipe's locators, so it cannot be scored before a candidate is chosen. Without it a new host scores at most 4, below the threshold of 5. A judge-built portal that shares only its template with an earlier one scores 3 and is learned from scratch, the very case the file says reuse will pay for. Given that trying a recipe costs one or two requests and a missed match costs a full learn, any single specific match should make a candidate; scores should only order them.
2. **The canary cannot run its own check.** One list page cannot test "count within 10% of the printed total", and 10% is the wrong tolerance: the two numbers are the same quantity and should be equal (Q10, rule C1).
3. Family table: PLACE and Atexo are one family (PLACE runs Atexo's software). "No drift between installations" is wrong: cosinex hosts differ in their first path segment, and Atexo hosts expose three URL forms. The second vendor behind `/NetServer/` could not be found.
4. Sizes: cosinex's 5,000 are awarding offices, not contracting authorities; Vortal's 10,000 are public and private buyers together; PLACE's operator reports 36,101 consultations in 2025, not 40,000. The argument needs hosts per family, not buyers.
5. Numbers without support: the weights 3, 2, 2, 3 and the threshold 5; five detail pages (five clean pages only bound the failure rate below 45%); the two cost figures, which come from Q9's assumptions.
6. Confirmed and worth keeping: TenderNed's public API needs no login; e-Zamówienia allows 30 requests a minute and answers 403 beyond that; the Spanish feed.

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

- Q12: documents per tender and megabytes per tender come from 9 tenders on one portal on one day. No open-tender count was found for any portal.
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
| Repair accepted when 90% of ids and 90% of values reproduce | Still our default. Q10's paired test (rule C3) would be the better-founded rule. |
| Three repair attempts per incident | Still our default |
| Four model calls at a time | Still our default; Q9 confirms it is far under the rate limit |
| Spot check by quoted passages | Q2's audit: a quote proves the text is on the page, not that the locator read the right node. Needs Q2's fix. |
| Recipe as the main path, generated code as fallback | Open: Q1 |
| Portal id derived from the URL; 201 on repeat | Still our default; not a research question |

## Limits of this check

- The research machine could not open every site. Patterno's own portal list, DTVP, the ACM and Wiley libraries and OpenAI's older docs host never answered or refused. TED and the EU's legal site answered with a bot challenge, which we did not try to pass.
- Portal measurements are from one day and small samples.
- Nothing here has been run against a real judge. The rules in Q10 and Q12 are designs until the prototypes pass on the mock portal.
