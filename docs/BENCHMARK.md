# Watchtower benchmark (Q8)

Goal: compare Q1 recipe models, Q4 agent tools and Q9 models on equal terms, scored the way the judges score.

## Two test beds
1. **Mock portal** (fully deterministic, main ground for Notice and Repair). A small FastAPI app with ~30 seeded tenders in several languages, served in switchable variants. Our test harness flips variants; the system under test never sees the switch.
2. **Real portals** (Attach realism). 8+ portals, 4+ countries, 3+ software packages, mix of server pages, JS apps and multi-step downloads, plus 1 to 2 behind a login or captcha. Run against recorded traffic.

## Replaying real portals
* Record at our own fetch layer (`FETCH_MODE=record`): every request and response, from httpx and from the browser, keyed by method, URL and body. This is simpler than HAR because all traffic already passes through `fetch/`.
* Playwright HAR (`record_har_path` on the context, `route_from_har` to replay) is the alternative for browser-only flows.
* Catch: agents explore differently, so a pure replay misses requests the recorder never saw. Use **record on miss** (replay if known, else fetch live and add), then freeze the cassette after two or three full runs. Report how many requests went live in each run.

## Metrics
Match predicted tenders to gold by `id` (fallback: `url`).
* **Tender recall** = matched gold open tenders / gold open tenders. **Tender precision** = matched / predicted.
* **Field scores**, per field, over matched tenders: `correct`, `wrong` (value present but differs), `missing` (gold has it, we sent null), `invented` (gold null, we sent a value). Report `recall = correct / gold non-null` and `error rate = (wrong + invented) / predicted non-null`.
* **Field score** (one number) = recall minus 2 × error rate, because a wrong value is worse than a missing one.
* **Documents**: file recall by sha256 (fallback: name and size); bytes correct = our sha256 equals the gold file's.
* **State accuracy**: the harness polls `GET /portals/{id}` every 10 s; each poll is right if the state matches the scenario's expected state. Also **time to notice** (change to `healing`) and **false alarms** (healing or failed on an unchanged portal).
* **Repair success**: back to `serving` with tender recall at least 0.95 within 15 minutes of the change. Also repair tokens and euros.
* **Cost**: tokens and euros per attach and per repair, from the `portal_costs` view. **Model calls during regular reads must be 0.**
* **Time to attach** and **HTTP requests per attach**.

## Gold labels
* Every real portal: the full list of open tender ids (cheap, counted from the list pages).
* 5 tenders per portal labelled field by field (8 portals: 40 tenders, about 2 minutes each, roughly 1.5 hours split over the team). The model may prefill, a person checks every value against the page.
* Mock portal: gold is generated from the seed data, so it is free and exact.

## Mock portal scenarios (scripted changes)
Each runs: attach, wait for `serving`, apply change, refresh, poll states, score.
1. CSS classes renamed.
2. Table layout replaced by cards (DOM restructure).
3. Field labels reworded or reordered.
4. Pagination changed (page number to offset, or a "load more" button).
5. Server pages replaced by a JS app with a JSON API.
6. JSON API field renamed or path moved (`/api/v1` to `/api/v2`).
7. Date format and timezone display changed.
8. Documents become multi-step (detail page, documents tab, download with a token).
9. Captcha on the list page: expect `failed` with a captcha reason.
10. Captcha shown but files still download: expect `serving` (no false alarm).
11. Login wall: expect `failed`.
12. Transient 500 errors and slow answers: expect no state change.
13. Portal legitimately has 0 open tenders ("no results" text): expect `serving`.
14. A tender gets cancelled: expect `withdrawn`.
15. Entry URL becomes a summary page linking to the list.
16. A ZIP over 250 MB (streamed, not stored): expect it to be skipped, others delivered.

## What is automated, what is checked by eye
* Automated: scoring, state polling, scenario switching, cost, attach time, the "0 model calls per read" assertion.
* By eye: gold labels, dashboard readability, whether reason texts make sense, and 10 random tenders per real portal after each benchmark run.

## Harness
`bench/run.py <config>` starts the app (in process or the container), posts the portals, polls until every portal is `serving` or `failed` or times out, pulls tenders, scores against `bench/gold/`, and runs the mock scenarios. Output: one markdown report per config plus a CSV row per portal, so configs can be compared side by side.

## Effort
* Mock portal with variants: 3 to 4 hours (one person).
* Record and replay in `fetch/`: 1 to 2 hours (whoever owns fetch).
* Harness and scorer: 2 to 3 hours.
* Gold labels: about 1.5 hours, split.
* Total: roughly 8 to 10 person-hours. Build the mock portal first; it is also the best demo for the video.
