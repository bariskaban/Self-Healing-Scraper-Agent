# Q8. Benchmark: how do we compare design options on equal terms, inside a 24-hour build?

Owner: Baris · Status: **answered** in [q05-q07-q08-framework-schemas-benchmark.md](q05-q07-q08-framework-schemas-benchmark.md)

## Question

The options to compare: Q1 recipe model, Q4 agent tools, Q9 models.

Starting proposal to refine
- 8+ real portals: at least 4 countries and 3 portal software packages; a mix of server-rendered pages, JS apps and multi-step downloads; 1-2 portals behind a login or captcha.
- A mock portal we change on purpose.
- Hand-checked expected tenders for a sample.
- Scored like the judges score:
  - per-field precision and recall
  - documents delivered
  - correct reported state
  - repair success after scripted changes
  - tokens and euros per portal
  - time to attach

Answer
- How do we snapshot dynamic portals for replay (HAR files, Playwright request routing)?
- How many hand-labelled tenders are enough?
- What do we automate, and what do we check by eye?
- Which changes do we script on the mock portal?

Deliverable: metric definitions, the benchmark harness design, and the hours it takes to build.

## Answer

**Two test beds**: a mock portal with 16 scripted changes for Notice and Repair, and 8 or more real portals replayed from recorded traffic for Attach, scored the way the judges score.

The full answer, its alternatives and sources are in [q05-q07-q08-framework-schemas-benchmark.md](q05-q07-q08-framework-schemas-benchmark.md), `docs/BENCHMARK.md` and [q08-test-portals.md](q08-test-portals.md). The end check is in [audit.md](audit.md).

## Inputs from answered questions

- **Q10:** one mock-portal switch per verdict row, plus: paging cut to one page, a 403 rate limit with `Retry-After`, a captcha widget that blocks nothing, a list emptied with and without the "no results" notice. See [q10-failure-rules.md](q10-failure-rules.md).
- **Q14:** three sequences: answer 503 for 3 minutes and recover; show a login wall and remove it; change the layout twice in a row. The model-call count must be 0, 0 and 2. See [q14-failed-retry.md](q14-failed-retry.md).
- **Q12:** the mock portal should come in a small size (finishes inside 10 minutes) and a large one (does not), to exercise both sides of the state rule. See [q12-large-portals.md](q12-large-portals.md).
- **Audit of Q9:** the cost per portal has to be measured here; the published estimate does not hold. See [audit.md](audit.md).
