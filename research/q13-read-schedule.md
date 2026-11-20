# Q13. Read schedule: how often do we read a portal again?

Owner: Goktug (leftover) · Researched 20 Nov 2026 · Status: **answered**. This replaces the answer that was proposed without research.

How each claim is known is marked: **measured**, **read**, **search**, **ours** (see [README.md](README.md)).

## Question

How often do we re-read each portal, and what does a refresh call do?

The proposed answer was: every 15 minutes, re-read the tender list of each portal that is serving. Fetch detail pages and files only for tenders that are new or changed. A refresh call starts the same read right away. If a read is already running, the refresh returns that read's runId.

## Decision

**Keep the shape of the proposal; change the interval.** Read each serving portal's list every **2 minutes, or 10 times as long as the list takes to read if that is more, and never less often than every 30 minutes.** A refresh call starts the same read at once and returns the running read's `runId` if there is one.

A read is: the list; detail pages and files for tenders that are new or changed; the few checks from Q10; and a slice of the rotation that re-reads known tenders' detail pages, which may use a fifth of the request budget (Q12).

We choose this for three reasons:

1. **The interval is the longest a broken portal can be reported `serving`.** That, and not how often tenders change, is what the Notice criterion scores.
2. **Reading the list is cheap.** Under this rule it never uses more than about 10% of a portal's request budget.
3. **One fixed number is wrong for most portals.** 15 minutes leaves a 5-page portal reporting a stale state for 15 minutes to save 5 requests, and makes a 250-page portal spend 28% of its budget on list reads.

For a list longer than 12 pages that is sorted newest first, also read its **first page alone every 2 minutes** between full list reads. That one request shows new tenders and exercises the list recipe, so a changed layout is noticed in 2 minutes on a large portal too. Removed tenders and the printed total still need the full list. (The idea of reading only what is new comes from the Q1 and Q3 answers; they call it a watermark.)

## What the rule gives

From `research/tools/q12_request_math.py` (**measured**: computed).

| List pages | Tenders at 20 per page | Read every | Share of the budget spent on the list | Longest time wrongly `serving` |
| --- | --- | --- | --- | --- |
| 1 | up to 20 | 2 min | 0.8% | 2 min |
| 5 | 100 | 2 min | 4.2% | 2 min |
| 12 | 240 | 2 min | 10% | 2 min |
| 50 | 1,000 | 8 min | 10% | 9 min |
| 100 | 2,000 | 17 min | 10% | 18 min |
| 250 | 5,000 | 30 min | 14% | 34 min |

The longest wrong time is the interval plus the time the list takes. A change that shows only on detail pages is caught by the two detail pages every read re-fetches (Q10, rule C6), and by the rotation: every detail page is re-read on every read for a portal of 24 tenders, within 8 minutes for 100, within 83 minutes for 1,000 (Q12).

## The alternatives, and why they lose here

| Alternative | Why it loses |
| --- | --- |
| Every 15 minutes, fixed (the proposal) | Up to 15 minutes of a wrong `serving` on a small portal, which is most portals and all the private ones, to save a handful of requests. |
| Every 5 minutes, fixed (draft 2) | Fine for small portals, but a 250-page list takes over 4 minutes to read, so the portal would do little else. |
| 3 times the last read's duration (draft 2) | After a 67-minute first attach it allows a 200-minute gap. |
| Only when the judges call refresh | They "may" call it every few minutes. A portal they change and do not refresh would stay `serving` until they do. |
| Read each tender as often as it tends to change | Tenders change rarely, so this would read rarely, and detection would suffer. With about 3 changes in a tender's life, even a daily re-read of its detail page keeps it fresh 95% of the time (**measured**: computed from the standard model below). Crawler research also found that refreshing all pages evenly beats refreshing in proportion to their change rate (**search**). |

## Evidence

- **Detection time is a first-class measure.** Google's SRE workbook defines it, "How long it takes to send notifications in various conditions", beside precision and recall (**read**). For us it is the time until the reported state is true again.
- **Longest wrong time = interval + list duration** (**ours**: an event just after a read is seen at the end of the next one).
- **Freshness of a tender under a re-read period I**, with changes arriving at rate λ: (1 - e^(-λI)) / (λI). At λ = 0.1 per day and I = 24 hours this is 0.952 (**measured**: computed). This is the model used in crawler-refresh research (**search**: Cho and Garcia-Molina 2003; the paper was not opened).
- **Changes do happen.** 14 of TenderNed's newest 100 notices were rectifications (**measured** today). So detail pages must be re-read, which the rotation does.
- **Being first matters to Patterno.** The mentor on why aggregators are not enough: they are late, and Patterno wants to be first ([mentor-answers.md](mentor-answers.md)). A short interval serves that as well as the Notice criterion.
- **The judges' cadence.** The brief says refresh may be called "every few minutes" (**read**). A 2-minute floor means we have read at least once on our own between two such calls.

## Numbers that are our own choice

- The **2-minute floor**. Anchored to the judges' "every few minutes", not to a source.
- The **10% share** of the budget for list reads, and the **20% share** for re-reading detail pages.
- The **30-minute cap**.

All three are settings. `READ_INTERVAL_SECONDS` sets the floor.

## What would change the decision

- Patterno running this on 4,500 portals would raise the floor, to spare small portals' servers and its own machines: 4,500 portals at 2 minutes is about 40 list requests a second in total. That is one setting, and worth saying under Approach.
- A portal that states its own limit (Q10, rule T2) stretches its interval automatically, because its list takes longer to read.

## Prototype first

Part of Q12's prototype: the scheduler computes the interval from the last list read's duration. About 30 minutes on top.

## Effect on other questions

- **Q10:** rule F1 uses 3 times this interval as the age at which `serving` stops being true.
- **Q12:** the steady-state table uses this rule.
- **Q14:** covers portals that are not `serving`.
- **DESIGN.md:** replace "5 minutes, or 3 times the last read's duration".

## Sources

- Google SRE workbook, "Alerting on SLOs": https://sre.google/workbook/alerting-on-slos/ (read 20 Nov 2026)
- The track description, appendix: refresh "may" be called "every few minutes"
- TenderNed public API (measured 20 Nov 2026): https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties
- Search only: Cho and Garcia-Molina, "Effective page refresh policies for Web crawlers", TODS 28(4), 2003, https://doi.org/10.1145/958942.958945
