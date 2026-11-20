# Research register

One file per question, so every decision in this project can be traced to its research. A decision is not finished until it can be said like this: "we chose X because of A, B and C; the other ways to solve it were Y and Z, and they lose here because ...".

The end check of every answered question is in [audit.md](audit.md).

## Register

| Q | Question | Owner | Status | Decision in one line | File |
| --- | --- | --- | --- | --- | --- |
| 1 | Recipe model | David | answered | A navigation graph with a closed set of node kinds and actions; generated Python only as a sandboxed escape hatch | [q01-recipe-model.md](q01-recipe-model.md) |
| 2 | Field locators | Danil | answered, revised | Several locators plus value checks per field | [q02-locators.md](q02-locators.md) |
| 3 | Explore or map first | David | answered | Probe structured sources first, then explore toward the list with a page budget; do not map the site | [q03-explore-or-map.md](q03-explore-or-map.md) |
| 4 | Agent tools | David | answered | About 8 own tools on Playwright for Python and httpx; one rate limiter per host inside `page.route` | [q04-agent-tools.md](q04-agent-tools.md), [q04-page-views-measured.md](q04-page-views-measured.md), [q04-q10-notes.md](q04-q10-notes.md) |
| 5 | Agent framework and conventions | Baris | answered | OpenAI Agents SDK; own loop as fallback | [q05-agent-framework.md](q05-agent-framework.md), answer in [q05-q07-q08-framework-schemas-benchmark.md](q05-q07-q08-framework-schemas-benchmark.md) |
| 6 | Language | Goktug | answered | Python for the whole system; no TypeScript part | [q06-language.md](q06-language.md) |
| 7 | Schemas | Baris | answered, built | API models and internal records in `app/models.py`, tables in `app/schema.sql` | [q07-schemas.md](q07-schemas.md), answer in [q05-q07-q08-framework-schemas-benchmark.md](q05-q07-q08-framework-schemas-benchmark.md) |
| 8 | Benchmark | Baris | answered | A mock portal with 16 scripted changes, and 8 or more real portals replayed from recordings | [q08-benchmark.md](q08-benchmark.md), [q08-test-portals.md](q08-test-portals.md), answer in [q05-q07-q08-framework-schemas-benchmark.md](q05-q07-q08-framework-schemas-benchmark.md) |
| 9 | OpenAI models and cost | Danil | answered, revised | Learn and repair on `gpt-6.2-sol`, spot checks on `gpt-6-luna` | [q09-models-cost.md](q09-models-cost.md) |
| 10 | Failure rules | Goktug | answered | Suspect on cheap checks, confirm with a second observation, then change state | [q10-failure-rules.md](q10-failure-rules.md) |
| 11 | Reuse across portals | Danil | answered, revised | Any host, path or brand match makes a candidate; a canary read before trust | [q11-reuse.md](q11-reuse.md) |
| 12 | Large portals | Goktug | answered; one rule waits on the mentors | Bulk source first; list, records, then documents by deadline; `serving` at the records gate when documents take over 10 minutes | [q12-large-portals.md](q12-large-portals.md) |
| 13 | Read schedule | Goktug | answered; replaces the proposal | Every 2 minutes, or 10 times the list's read time, at most 30 minutes | [q13-read-schedule.md](q13-read-schedule.md) |
| 14 | Retrying failed portals | Goktug | answered; replaces the proposal | Check on every refresh, and at 5 min, 15 min, 1 h, then every 6 h; repair only on a page not seen before | [q14-failed-retry.md](q14-failed-retry.md) |

The verdict of the end check for each answer is in [audit.md](audit.md).

Beside the questions: [patterno-landscape.md](patterno-landscape.md) counts Patterno's own list of 4,657 portals by country and platform. Four countries hold 83% of them, and ten platforms hold half of all portal addresses. Q8, Q11 and Q12 lean on it.

## Answer standard

Every answer file has, in this order:

1. **Question**, as it was asked.
2. **Decision** in one or two sentences, with its reasons.
3. **Alternatives** that would also solve the problem, and why each loses for this project.
4. **Evidence**, every claim linked and marked by how we know it: **read** at the source, **measured** by us, seen only in a **search** result, or **ours** (our own reasoning or choice).
5. **What would change the decision.**
6. **Prototype first**, with hours.
7. **Effect on other questions**, by number.

## Plan for Q6, Q10, Q12, Q13 and Q14

About 12 hours of building, in this order. Each step is the prototype named in its file.

| Step | From | Work | Hours | Needs first |
| --- | --- | --- | --- | --- |
| 1 | Q6 | Dockerfile on Playwright's Python image with the version pinned; build on linux/amd64 in CI; one page load through the rate limiter | 1 | |
| 2 | Q10 | The verdict function: this read, the last good read and the request outcomes in; verdict, rules fired and reason sentence out. Pure code with tests. | 1.5 | Q7's tender record |
| 3 | Q12 | The three read phases with the records gate and the 10-minute rule | 1 | Q1's recipe, the mock portal |
| 4 | Q10 | The confirm step (re-read, detail-page look for missing tenders) and the two-page canary | 1.5 | step 2 |
| 5 | Q12, Q13 | Incremental read: list difference, new and changed tenders, the rotation on a fifth of the budget; the interval rule | 2 | step 3 |
| 6 | Q10, Q12 | The limiter slows down on 429 and on 403 with `Retry-After` | 0.5 | |
| 7 | Q14 | The check ladder for failed portals and the check on refresh | 1.5 | step 2 |
| 8 | Q10, Q14 | Run every mock-portal switch; each verdict row must be produced at least once | 2 | Q8's mock portal |
| 9 | Q12 | One real bulk portal end to end (TenderNed's API and ZIP); compare the request count with the table | 1 | steps 3 and 5 |

## Questions for the mentors

A mentor answered most of them on 20 Nov. The answers, and what they change, are in [mentor-answers.md](mentor-answers.md); they rank with the track description. Still open: whether tender ids stay the same when a portal changes, whether a page's sub-requests count, whether the judges call refresh after restoring a portal, ZIP entries in place of the ZIP or beside it, what `tenderCount` counts, and which of two identifiers is `id`.

## Tools

- `tools/q12_request_math.py` prints every number in Q12 and Q13. Change a parameter, run it, paste the tables.
- `tools/probe_portals.py` records what a plain client sees on a list of public portals. Run it from a laptop: the research machine cannot reach several of them. It writes `sources/portal-probe.json`.
- `tools/patterno_coverage.py` reads Patterno's public coverage pages, one request per second, and writes the counts per country and platform to `sources/patterno-coverage.json`.

## Shared context

Paste this first, then one question block, into a fresh research session.

```
# Context: Patterno "Watchtower" hackathon

We are a team of 3-4 in a 24-hour hackathon (Patterno track). We must hand in one
Docker container (linux/amd64, quick to build) that serves a JSON API and an operator
dashboard on port 8080. Given only the URL of a European public-procurement portal it
has never seen, the system must:

1. Attach: deliver every open tender the portal lists, with each tender's documents.
2. Notice: report the portal's state truthfully, with a reason. The states are
   integrating, serving, healing (broken, repair running, last good data still
   served) and failed (a person is needed, e.g. a login or captcha blocks us).
3. Repair: get back to correct delivery on its own after the portal changes.

No person or service of ours may steer it while it runs. The judges run it on portals
we have never seen: private ones they built, and real ones. They score Attach, Notice,
Repair, Dashboard, and Approach (how it scales to thousands of portals, and what one
portal costs in model usage).

Hard rules
- An LLM learns how a portal is read, checks it and repairs it. Regular reads should
  make no model call.
- At most 1 request per second per portal. No logins, no captcha solving.

Portals vary: server-rendered HTML, JavaScript apps backed by a JSON API, multi-step
downloads, ZIPs over 1 GB, deadlines in local time, links that lead to summary pages
instead of the tender, and captchas on pages whose files still download.

Output per tender: id (the portal's own, stable), url, title, buyerName,
publicationDate, submissionDeadline (with UTC offset), status (open/closed/withdrawn),
documents (fileName, sizeBytes, sha256, download path; ZIPs unpacked), lastChangedAt.
If shown: referenceNumber, description, procedureType, contractNature, cpvCodes
(8 digits), placeOfPerformance. A wrong value is worse than a missing one.

Where we are (2026-11-20)

- Decided: OpenAI is the model provider. The specific model is chosen by benchmark and price.
- Working assumptions, not final: Python 3.12. The LLM writes a per-portal "recipe" that
  a deterministic engine runs on every read. A validator checks each read. On failure,
  the LLM repairs the recipe.

Open questions being researched in parallel: Q1 recipe model · Q2 field locators ·
Q3 explore vs map · Q4 agent tools · Q5 agent framework · Q6 language · Q7 schemas ·
Q8 benchmark · Q9 OpenAI models and cost · Q10 failure rules · Q11 reuse across
portals · Q12 large portals.

What we need back
- A recommendation in one or two sentences, then the options you compared and why.
- Every source linked. Date anything that changes fast (prices, model names, versions).
- What to prototype first to confirm it, and roughly how many hours that costs us.
- Anything you found that changes another open question (name it by number).
```
