# Watchtower: what we built, how we tested it, and what the results mean

MAIN AI Hackathon 2026, Patterno track. Team Kaolin. Written on 21 Nov 2026, the day of the hand-in.

**Team**

| Who | Worked on |
| --- | --- |
| Baris Kaban | Agent framework and conventions (Q5), data schemas (Q7), benchmark design (Q8); the dashboard with Danil; the demo |
| Danil (`Danila1801`) | Field locators (Q2), models and cost (Q9), recipe reuse (Q11); the dashboard and its front end |
| David-Valentin Neacsu | Recipe model (Q1), explore or map (Q3), agent tools (Q4); the network layer (`app/fetch/`), the database, the read loop's later fixes; the run on ten real portals |
| Goktug Yıldırım | Language (Q6), failure rules (Q10), large portals (Q12), read schedule (Q13), retry of failed portals (Q14); the API, the recipe and its executor, the read loop, the mock portal, the agent (`app/agent/`); the benchmark runs and the audit |

Most of the code was written by AI coding agents, one module per agent and branch, under the rules in `CLAUDE.md` and `CONVENTIONS.md`. Every change came in through a pull request with the tests and the Docker build run on it.

This report has five parts: what the system does, how we tested it, the results with their uncertainty, why each design decision was taken, and what is not solved. For how to run it, see `README.md`. For the full specification, see `DESIGN.md`.

---

## 1. What the system does, in one page

The brief: given only the address of a public-tender portal it has never seen, deliver every open tender and its documents (**attach**); know when the portal stops delivering correctly and say so (**notice**); get back to correct delivery after the portal has changed (**repair**). Nobody may help while it runs.

Our answer is "learn once, read cheaply, check every read, repair on failure":

1. **Learn.** A model (`gpt-6.2-sol`) explores the portal through a small set of tools and writes a *recipe*: a typed description of how to reach the list, page through it, open a tender, and find each field and each document. The recipe counts only once a dry run of it has read real tenders from the portal.
2. **Read.** A deterministic executor runs the recipe on every read. **No model is called in a regular read.** Requests go through one network layer that holds every portal to one request a second and obeys robots.txt.
3. **Check.** Every read is judged by a fixed list of checks (transport, block, list outcome, paging, duplicate ids, known tenders missing, values changed, structure). The checks decide the state: `serving`, `healing`, `failed`.
4. **Repair.** When the checks find a breakage, the model is asked to patch the recipe. The patch counts only if a dry run gives the tenders of the last good read again, with the same ids, values and files. If no patch is found, the portal is learned again with the old recipe as a draft. While this runs, the last good tenders stay delivered.
5. **Report.** The API of the brief and a dashboard show each portal's state, the reason in words, every run, and every step the system took, with its cost.

The model is used in three places only: learning, repairing, and a spot check of values when two specific checks fire.

---

## 2. How we tested

We had no list of portals and no labelled data, so we built four layers of test. Each answers a different question, and each has a limit we state.

| Layer | What it is | What it can show | What it cannot show |
| --- | --- | --- | --- |
| Unit and contract tests | 1,427 tests; the API contract of the brief as a test; the mock portal read through the whole app. No network, no model. | The code does what we specified, on every change. | Nothing about portals we did not think of. |
| Made-up portals | Eight portals that exist only in our code (`variants/portals.py`), each built like a real portal family: a JSON API behind an app shell, rows without links, three kinds of paging, four languages, a documents page of its own, a login wall, an empty list. The truth is known exactly. | Field-level correctness against a known truth, for learn and repair. | They are small and clean. Cost and difficulty are lower than on real portals. |
| Real portals, learner and repairer alone | 18 real portals of our test set (`bench/portals.toml`), 5 countries. Learn live; then alter a clone of the pages and repair. | Whether the mechanism holds on real markup, and what it costs. | There are **no gold labels**. "Right" means "the same values as the recipe's own first read". Nobody checked those values by hand. |
| Real portals, whole product | The container's app, live, on real portals at once, twice: David's run of ten portals, and the audit run of six on 21 Nov. | The product end to end: queueing, rate limits, long reads, restarts, real failures. | Few portals, one run each, one night. |

On top of that, on the day of the hand-in the code was audited by three independent agent reviews (the API contract, the notice and repair logic, the hand-in rules). Every finding was reproduced with a script before anything was changed and run again afterwards (section 3.6).

**Rules we kept while testing.** One request a second per portal, through the product's own network layer. robots.txt obeyed. No login, no captcha solving. Test portals marked `unseen` were never touched. Live runs happened only when a person asked for them.

---

## 3. Results

### 3.1 How we state uncertainty

Our samples are small: 6 to 26 cases per question, one run per case. A bare "11 of 18" hides how little that pins down, so every rate below comes with a **95% Wilson score interval**. We use Wilson because the usual textbook interval (Wald) is unreliable at small samples and near 0% or 100%, which is exactly where our numbers are; Brown, Cai and DasGupta (2001) show this and recommend the Wilson or Jeffreys interval for n of 40 or less, and the NIST handbook recommends the same method [1][2][3]. For a result with no failures, the "rule of three" gives the same message in one line: with 0 failures in n independent tries, the true failure rate can still be up to about 3/n [4].

For costs and times we give the **median with the range and the quartiles**, not the mean alone: the samples are small and skewed (a few expensive cases), and a median is not pulled by them. Where we give an interval for a median, it is the distribution-free one from order statistics, which assumes nothing about the shape of the data.

Three cautions apply to every number:

- **One run per case.** The model is not deterministic. We did not repeat runs, so we cannot separate "this portal is hard" from "this run was unlucky".
- **The portals are not a random sample.** We chose them to cover countries and software families. Portals built on the same software are not independent of each other, so the true uncertainty is wider than the intervals say.
- **No gold labels on real portals.** A rate of "repaired to the same values" measures consistency with the first read, not truth.

### 3.2 Attach: learning a portal it has never seen

**Made-up portals (truth known).**

| Measure | Result | 95% interval |
| --- | --- | --- |
| Learnable portals learned | 6 of 6 | 61% to 100% |
| Tenders delivered, of those in the truth | 234 of 234 | 98.4% to 100% |
| Fields wrong or missing (10 fields compared per tender) | 0 | |
| Documents found | 234 of 234 tenders had the right number | |
| Portals that cannot be read (login wall, empty list): gave up, as they should | 2 of 2 | 34% to 100% |

Cost per learn: median $0.14 (range $0.11 to $0.16). The 234 tenders are not 234 independent trials: they come from six recipes, and a recipe is right or wrong for all its tenders together. The honest sample size is six.

**Real portals, learner alone (20 and 21 Nov).**

| Measure | Result | 95% interval |
| --- | --- | --- |
| Learned, of all 18 portals tried | 11 of 18 (61%) | 39% to 80% |
| Learned, of the 14 that could be read at all | 11 of 14 (79%) | 52% to 92% |

The seven that were not learned, by cause:

| Cause | Portals | Is it a fault of the product? |
| --- | --- | --- |
| robots.txt forbids the address | 3 | No. We obey it, and the portal is reported as not readable. |
| Bot wall (HTTP 418 "Access Denied") | 1 | No. The brief says no captcha solving; the right answer is `failed` with the reason. |
| A host our test session could not reach | 1 | No. A fault of the test set-up. |
| The list's paging lives in the server's session | 2 | **Yes, a real limit.** The executor sends plain requests and keeps no session. See section 5. |

So the second row is the fairer one: of 14 portals that a polite, session-less reader could have read, 11 were learned. With 14 cases the interval is wide, 52% to 92%: we can say "most", not "four in five".

Cost and effort of the 11 learns that worked:

| | Median | Middle half (quartiles) | Range |
| --- | --- | --- | --- |
| Cost per learn | $0.62 | $0.46 to $0.66 | $0.37 to $0.86 |
| Model calls | 30 | 22 to 36 | 17 to 40 |
| Requests to the portal | 19 | 15 to 25 | 10 to 36 |
| Wall-clock time | 200 s | 159 to 238 s | 144 to 307 s |

A 93.5% interval for the median cost is $0.45 to $0.67. A failed learn costs $0.04 to $0.05 when the portal refuses us at the door, and cost $0.70 and $0.88 on the two session-paging portals before we taught the learner to stop early (afterwards: $0.14 and $0.27).

**Real portals, whole product (21 Nov, audit run).** Six portals added at once to a clean app. Two hosts were not reachable from the test session. The other four (tender24, NFZ, TenderNed, e-Zamowienia) were all learned, for $0.43 to $0.53 each, with no rate-limit error, while only two learns ran at a time and the others waited about two minutes. Four of four is 51% to 100%; it confirms that the path works in the product, nothing more. What this run was really for is in section 3.6.

### 3.3 Repair: correct delivery again after a change

We cannot change a real portal, so the changes were made on copies: every class, id and `data-*` hook renamed, JSON keys renamed.

| Scenario | Result at first run | 95% interval | After the fix the run led to |
| --- | --- | --- | --- |
| Made-up portals, redesign | 6 of 6, every tender, field and document right, ids kept | 61% to 100% | |
| Made-up portals, every address moved | 6 of 6 | 61% to 100% | |
| Real portals, one part of the pages altered | 15 of 16 repaired to the same values | 72% to 99% | 16 of 16 |
| Real portals, only the domain left | 9 of 10 found the list again | 60% to 98% | 10 of 10 |
| All real-portal recoveries together | 24 of 26 | 76% to 98% | 26 of 26 |

Notes on reading this table:

- Of 22 altered scenarios on the 11 learned portals, 6 did not break the recipe at all, because it reads those pages by label, JSON path or address, which the alteration does not touch. That is the best kind of repair: none. (An earlier report of ours says 7 unaffected and 15 broken; counting its own table gives 6 and 16, and we use the table.)
- The two first-run failures were real defects, and both were fixed the same night: a repair that brought the values back but lost the document links (now a repair's dry run compares files too), and a list loaded by the page's own script that the repairer did not find within 20 calls (now a failed repair is followed by a full learn with the old recipe as a draft).
- **The "after the fix" column is weaker evidence than it looks.** The failing case was run again after we changed the code for exactly that case. It shows the fix works on the case that motivated it, not that the next unseen case will pass. The first-run column is the one to quote.
- By the rule of three, 26 of 26 would still be compatible with a true failure rate of up to about one in nine.

Cost of a repair: median $0.14 (quartiles $0.10 to $0.16, range $0.07 to $0.23) when one part of the pages changed; median $0.11 (range $0.07 to $0.25) to find a list again from the domain. The one repair that needed a full learn afterwards cost $1.13.

**In the product.** On the mock portal, with the real model: layout changed, portal `healing`, repaired in 35 seconds for $0.10, recipe version 1 to 2, `serving` again with the same 45 tenders. Run several times by different team members with the same outcome.

### 3.4 Notice: the state matches what is delivered

Notice is tested mostly without a model, because it is rule-based. In the audit, these were driven on the mock portal and each gave the right state, cause and reason, with the last good tenders still delivered: an outage, a maintenance page, HTTP 429, a login wall on every page (on a serving portal and at attach), paging cut short, columns swapped. Three failed repairs in a row end as `failed` with "All 3 repair attempts failed. A person is needed", and the portal is served again when it recovers.

Notice is also where the audit found the most important defect of the day (section 3.6, first row): a healthy portal could report `failed` for a minute after a long download. A wrong `failed` is exactly what this criterion scores.

### 3.5 Cost per portal

| Event | How often | Measured cost |
| --- | --- | --- |
| Learn a portal | once | median $0.62, range $0.37 to $0.86 (11 real portals) |
| Regular read | every 2 minutes or slower | **$0**: no model call. NFZ: 29 reads in a row, 6 requests each. |
| Repair after a change | only when the portal changes | median $0.14; $1.13 in the one case that needed a second learn |
| Portal that cannot be read | once, then at most 3 tries a day | $0.04 to $0.27 |

Hard caps stop a run from outside: $5.00 for a learn, $2.50 for a repair, three repair attempts per incident. At the median, 4,500 portals (the number Patterno reads today) would cost about $2,800 to learn once, with a plausible span of about $2,000 to $3,000 from the interval of the median. Running them costs nothing in model usage until a portal changes. This extrapolation assumes our 11 portals are typical, which we cannot show.

### 3.6 What the whole-product runs and the audit found

These runs were worth more than any score, because they found defects that no unit test had. Each was reproduced first and checked again after the change.

| Found | How | Effect on the jury's criteria | Fixed |
| --- | --- | --- | --- |
| A healthy `serving` portal turned `failed` ("reads are not completing") on the read after a long document phase, and after any restart | Audit script: 150 tenders, 405 files | Notice: a wrong state | Yes. A read whose list arrived is never an outage for its age. |
| Ten learns at once exceeded the model's limit of tokens a minute; four portals ended `failed` | David's run of ten portals | Attach | Yes. Two model runs at a time; a refused call waits up to 90 s; a learn the limit ended does not use up the day's tries. |
| A learned recipe was thrown away when the first read met an outage; the next try paid for a second learn | David's run; seen again live on e-Zamowienia | Approach (cost) | Yes. Seen working live: the next read used the kept recipe, $0. |
| `GET /portals/{id}/runs` never said `kind: "repair"` | A real repair on the mock portal | Repair, as the jury reads it from the API | Yes |
| `POST /portals` refused a body with an extra field or without a JSON content type | Contract audit | Attach: the first call could fail | Yes |
| `?changedSince=` gave back tenders the caller had seen | Contract audit | Attach | Yes |
| `DELETE` did not stop a running learn: 20 more model calls and 18 more requests to the deleted portal | Audit script | The brief: "stops calling the portal within a minute" | Yes. 0 and 0 afterwards. |
| With six to eight portals attaching, no other portal was read | Audit script | Notice on every other portal | Yes. 64 read threads. |
| A portal with more than 10,000 tenders delivered nothing; one with 4,132 was still reading after 36 minutes | Audit run, live | Attach | Partly: a limit per portal. Both then delivered 500 tenders, in 17 and 25 minutes. See section 4.3. |

---

## 4. Why each decision was taken

Fifteen questions were researched before the build (`research/q01` to `q15`), then audited against sources and our own measurements (`research/audit.md`). Where the audit corrected the research, the audit won. Where the build later showed something else, the code won and the change is named here. Each block gives the decision, the reason, and the options that lost. The research files hold the full argument and every source.

### 4.1 The fifteen design questions

**Q1. How is what the model learned stored? (David)**
- *Decided:* a **recipe**: a typed graph of nodes (list, detail, documents, steps) and edges, written by the model through strict structured output and run by our own engine.
- *Why:* the model writes it once and a deterministic engine reads with it for nothing. A repair can patch one node and leave the rest. Prior work points the same way: a verifier of learned wrappers caught 35 of 37 real site changes (Lerman, Minton and Knoblock, 2003), and WebLists, the closest prior work, has the model record a program once and replays it without the model: 66% recall at over 72% precision on 200 tasks over 50 sites, more than twice the recall of agents that act on every page.
- *Not chosen:* generated Python as the main form (a change is not local, and code can run green on the wrong field); fixed stages (every new kind of hop needs a new flag); an agent on every read (breaks "no model call in a regular read").

**Q2. How is each field found on a page? (Danil)**
- *Decided:* two or three locators per field, all run on every read. If they agree after parsing, the value is taken. If they disagree, the field is `null` and flagged.
- *Why:* the brief says a wrong value is worse than a missing one. Position-based locators are fragile: in the ROBULA+ study absolute XPaths broke in 871 of 1,110 cases against 91 for robust ones. The audit added a warning: locators written by one model from one page fail together (in Similo's data, five kinds of locator fail together on 24% of elements), so a single surviving locator counts only if it gives the last good value.
- *Not chosen:* absolute XPath and `nth-child` positions; default values; similarity "self-healing" that always returns its best guess.

**Q3. Explore toward the list, or map the whole site first? (David)**
- *Decided:* first use what the portal itself offers (a JSON call in its page traffic, a feed it links, embedded app state), then explore toward the list within a page budget. Never crawl the site.
- *Why:* mapping only adds requests at one a second: about 1,300 requests to explore against 1,500 to 4,300 to map, in the research's example. TenderNed's sitemap alone lists about 95,000 old notices. Guessed paths such as `/api` and `/feed` gave 0 hits in 32 tries and were dropped.
- *Not chosen:* map first; guessed API paths; TED or a national feed as the source of the tenders (the task is the portal).

**Q4. Which tools does the agent get? (David)**
- *Decided:* about eight tools of our own over the product's network layer, and pages shown to the model as trimmed HTML.
- *Why:* the agent's output is a recipe with durable locators, so it must see ids, classes and `data-*` hooks. Measured: a 50-row list is about 4,000 tokens trimmed against 49,000 raw.
- *Not chosen:* a browser-automation agent framework (its own planner loop, and requests that slip past our rate limiter); the accessibility tree (it drops the hooks a locator needs).
- *Changed in the build:* there is **no live browser** in the product. A list built only by JavaScript is readable when the portal has a JSON call behind it, and not otherwise.

**Q5. Which framework runs the agents? (Baris)**
- *Decided:* our own loop on OpenAI's Responses API (`app/agent/runner.py`).
- *Why:* the research first chose the OpenAI Agents SDK. Its audit, run against the SDK, found three gaps: it does not trim the context, it does not stop on a budget from outside a tool, and it raises on one invalid answer where we want one retry. Those three are most of what a runner does. Trimming alone matters: a learn that keeps every tool result in context was estimated at 4.6 times the cost.
- *Not chosen:* the Agents SDK (as above); PydanticAI; LangGraph (too heavy for 24 hours).

**Q6. Python only, or TypeScript for part of it? (Goktug)**
- *Decided:* Python for everything.
- *Why:* at one request a second the language is not the bottleneck: parsing a 400 KB page takes 13 to 15 ms. A second runtime would add a supervisor and a boundary and gain nothing.

**Q7. What do the records look like? (Baris)**
- *Decided:* two layers: API models that give the brief's answers exactly, and internal records that map one to one onto SQLite tables. The contract's rules live in code (required fields present or `null`, every time with its offset, CPV codes of eight digits, the same address gives the same id).
- *Why:* modules could be built in parallel against fixed shapes. The shapes are shared interfaces and change only in a pull request of their own.

**Q8. How do we measure ourselves? (Baris)**
- *Decided:* a mock portal that we break on purpose, made-up portals with a known truth, and real portals.
- *Why:* only something we control gives an exact truth and the same break twice. The audit's warning shaped section 3 of this report: five labelled tenders per portal cannot show a per-portal error rate.
- *Not done:* hand-labelled truth for real portals. This is the largest gap in our evidence.

**Q9. Which models, and what does a portal cost? (Danil)**
- *Decided:* `gpt-6.2-sol` to learn and repair, `gpt-6-luna` for spot checks. Models and prices are settings.
- *Why:* learning is rare and hard, so it gets the stronger model; a spot check is frequent and simple.
- *Measured:* section 3.5. *Not done:* the cheaper `gpt-6.1-terra` was never benchmarked against Sol; we have no evidence either way.

**Q10. Which rules say a read failed? (Goktug)**
- *Decided:* checks that do not depend on how many tenders a portal has. A cheap check marks a read as suspect; a second look in the same run confirms or clears it; only then does the state change. No model is involved.
- *Why:* each simple rule fails in a known way. A "30% fewer tenders" rule fires on 14% of healthy reads of a portal with three known tenders. Thresholds learned from history need days we do not have. Waiting for three failures in a row means 10 to 15 minutes of a wrong `serving`. A status code alone does not prove a block.
- *Changed in the build:* an outage is `failed` with the cause `outage` from the first read that finds it, and the last good tenders stay delivered. The brief defines `healing` as "a repair is running", and an outage has no repair.

**Q11. How is learned work reused across portals? (Danil)**
- *Decided:* a portal that looks like a known software family is first tried with that family's recipe, which must pass a small trial read and then a full read.
- *Why:* Patterno's own list is concentrated: four countries hold 83% of the portals and ten platforms hold half the addresses. A reused attach costs a fraction of a cent.
- *Not built:* trying stored recipes before a repair. The recipes record their software family, so the data for it is there.

**Q12. How do we read large portals at one request a second? (Goktug)**
- *Decided:* the list first, then each tender's page, then documents by soonest deadline. A portal becomes `serving` when its tenders are validated; documents follow, and after 20 minutes what is validated is published.
- *Why:* measured on TenderNed, 1,551 tenders need about 53 minutes by API against 4.3 hours file by file. Holding everything back until the last file would leave a correct portal `integrating` for hours.
- *Changed in the build:* a limit of tenders per portal. See 4.3.

**Q13. How often is a serving portal read again? (Goktug)**
- *Decided:* every 2 minutes, or ten times the time the list took if that is longer, at most every 30 minutes.
- *Why:* the interval is the longest a broken portal can go on saying `serving`, and the list should use about a tenth of the request budget.

**Q14. How is a failed portal tried again? (Goktug)**
- *Decided:* a refresh checks it at once. On its own: after 5 minutes, 15 minutes, 1 hour, then every 6 hours, with jitter. A check costs no model call. A repair starts only for a page structure not seen before, at most three a day.
- *Why:* the likely test is "break it, see `failed`, restore it, refresh", which a fixed long interval would miss. Model cost is capped by what we see, not by the clock.

**Q15. SQLite or a graph database? (David)**
- *Decided:* SQLite; a recipe is one JSON document per version.
- *Why:* measured: `changedSince` over 50,000 tenders in 1.4 ms; a recipe loads and walks in 0.15 ms. A graph database would be a second server for a graph of a few dozen nodes.

### 4.2 Decisions taken by a person during the build

| When | Who | Decision | Why |
| --- | --- | --- | --- |
| 20 Nov | David, with Goktug | An outage is `failed` (cause `outage`), not `healing` | The brief's own definition of `healing` |
| 20 Nov, 23:15 UTC | Goktug | Agent sessions may read the test portals live for benchmark runs, one session at a time | Real portals could not be tested otherwise. The standing rule in `CLAUDE.md` was left as written. |
| 21 Nov, 00:50 UTC | David | A failed repair is followed by a full learn with the old recipe as a draft | One real case: the patch alone failed, patch plus learn worked ($1.13) |
| 21 Nov | Goktug, on David's findings | Two model runs at a time; a rate limit is waited out for up to 90 s | Ten portals at once killed four learns |
| 21 Nov | Goktug | A read whose list arrived is never an outage for its age | Audit finding: a wrong `failed` after a long download |
| 21 Nov | Goktug | At most 500 tenders per portal by default | See 4.3 |

### 4.3 The limit of 500 tenders per portal, and what we did not build

**What we met.** In the live run, `ezamowienia.gov.pl` was learned for $0.53. Its list has more than 10,000 tenders, and its API answers HTTP 500 for every page past result 10,000. Every read made 202 requests and ended as an outage; the portal delivered nothing. In the same run TenderNed was learned in under five minutes, and then its 4,132 tender pages had to be read one request at a time: 36 minutes with nothing delivered when we stopped it, and more than an hour to go.

**What we decided.** A read stops at 500 tenders (`RECIPE_MAX_TENDERS_PER_PORTAL`, also a field in the dashboard's settings). The reason says "Stopped at the limit", and no tender is closed for being past it. Measured afterwards, live, with both portals learned again on the new code: e-Zamowienia delivered 500 tenders 17 minutes after its list was read (two requests per tender), and TenderNed 25 minutes after (three). Before the limit the first delivered nothing and the second was still reading after 36 minutes. A portal with fewer than 500 tenders is not touched by the limit.

**The price.** The brief asks for every open tender. Above the limit we deliver the first 500, the newest where the portal lists newest first. We chose a part in minutes over the whole in an hour or never.

**Option not built: rounds.** Read tenders 1 to 500, then 501 to 1,000 on the next read, and so on. It needs a remembered position per portal, and it changes the rule by which the reader concludes that a tender has left the list: today, absence from a full read; with rounds, absence from a full pass. A mistake there closes open tenders on every portal. Too deep a change for the last hours.

**Option not built: slices.** Split a list by a filter the portal offers (month, region, CPV division) so that each slice stays under the portal's own stop. The learner would have to find the filter and prove the slices add up to the whole list, and the recipe format would need a new kind of paging. That is a feature of days.

**Why not building slices matters less now.** Slices exist to reach the end of a list like e-Zamowienia's. With a limit of 500 we do not try to reach the end, so the wall at 10,000 is never met. The limit makes the portal deliver today; rounds would be the next step, and slices only after that.

---

## 5. What is not solved

We list these plainly, because a reader who runs the system will meet them.

1. **No hand-checked truth on real portals.** Every "right" on a real portal means "same as our first read". A recipe that reads the wrong date consistently would pass.
2. **Lists whose paging lives in the server's session** cannot be read (2 of our 18 test portals). It needs a session kept across requests, or a browser. The learner now stops early and says so.
3. **No browser.** A portal that builds its list in JavaScript with no JSON call behind it cannot be read.
4. **Portals above the limit deliver a part** (4.3).
5. **A portal with no tenders today cannot be learned**: it ends `failed`, not "serving, 0 tenders".
6. **A portal that cannot be reached while it is first learned** costs a few cents per try and is reported as "no recipe could be learned", where "the portal does not answer" would be truer.
7. **A portal whose document downloads all fail** reports `failed` and then `serving` on the next read without the portal changing.
8. **One run per case, one night of live runs.** Section 3.1.
9. **The cheaper model was not compared.** Cost per portal could be lower.
10. **Stored recipes are not tried before a repair** (Q11).

`docs/BACKLOG.md` holds the designs for the ones we thought through.

---

## 6. What the results mean, in short

- **The mechanism works across shapes.** On portals with a known truth it learned every readable one and got every field right; on real portals it learned most of those a polite reader can read at all (11 of 14; 52% to 92%).
- **Repair is the strongest part.** 24 of 26 real-portal recoveries were right at the first run (76% to 98%), and both failures led to a fix the same night.
- **The running cost is what the brief asked for.** About $0.60 once per portal, nothing per read, about $0.15 per change.
- **The evidence is thin, and we say so.** Fewer than 30 cases per question, no repeats, no hand-checked truth. The intervals are wide on purpose: they are what this amount of testing can support.
- **The most useful testing was running the whole product on real portals.** It found nine defects that 1,400 unit tests had not, and eight of them were fixed before the hand-in.

---

## References

Statistics:

1. Brown, L. D., Cai, T. T. and DasGupta, A. (2001). Interval Estimation for a Binomial Proportion. *Statistical Science* 16(2), 101–133. https://doi.org/10.1214/ss/1009213286
2. Wilson, E. B. (1927). Probable Inference, the Law of Succession, and Statistical Inference. *Journal of the American Statistical Association* 22(158), 209–212.
3. NIST/SEMATECH e-Handbook of Statistical Methods, section 7.2.4.1, Confidence intervals. https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm
4. Hanley, J. A. and Lippman-Hand, A. (1983). If Nothing Goes Wrong, Is Everything All Right? Interpreting Zero Numerators. *JAMA* 249(13), 1743–1745.
5. Agresti, A. and Coull, B. A. (1998). Approximate Is Better than "Exact" for Interval Estimation of Binomial Proportions. *The American Statistician* 52(2), 119–126.

Design (as cited in `research/`, where each is discussed):

6. Lerman, K., Minton, S. and Knoblock, C. (2003). Wrapper Maintenance: A Machine Learning Approach. *Journal of Artificial Intelligence Research* 18.
7. Kushmerick, N. (1999). Regression Testing for Wrapper Maintenance. *AAAI-99*.
8. Leotta, M. et al. (2016). ROBULA+: An Algorithm for Generating Robust XPath Locators for Web Testing. *Journal of Software: Evolution and Process*.
9. Nass, M. et al. (2023). Similarity-based Web Element Localization for Robust Test Automation (Similo). *ACM TOSEM*.
10. AutoScraper (EMNLP 2024, arXiv 2404.12753); WebLists (arXiv 2504.12682); Beyond Browsing: API-Based Web Agents (arXiv 2410.16464).
11. Google, *The Site Reliability Workbook*, Alerting on SLOs; AWS Architecture Blog, Exponential Backoff And Jitter; RFC 9110, HTTP Semantics.

Our own data: `docs/reports/agent-on-real-portals.md` and its JSON files (every learn, repair, recipe and step); `docs/reports/agent-on-made-up-portals.md`; `docs/reports/first-real-portal-nfz.md`; `research/` for the fifteen questions and their audit.
