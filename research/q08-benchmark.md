# Q8. Benchmark: how do we compare design options on equal terms, inside a 24-hour build?

Owner: teammate who took Q5, Q7 and Q8 · Status: **open, no answer in the repo yet**

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

None yet. When it is written, it follows the answer standard in [README.md](README.md).
