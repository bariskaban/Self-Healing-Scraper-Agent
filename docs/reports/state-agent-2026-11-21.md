# Where the agent stands: 21 Nov 2026, 00:45 UTC

Written for David, by Goktug's Claude session (stream B: `app/agent/`). It covers what was done since stream B was merged (pull request 49, 20 Nov, 21:13 UTC), how it was tested, what happened, and what is open. The hand-in is today at 09:30 UTC. Where this file and the code disagree, the code is right.

## In one paragraph

`app/agent/` learns a portal it has not seen, repairs a recipe after a portal changes, and spot-checks values, all live on `gpt-6.2-sol` and `gpt-6-luna`. On the 18 test portals of `bench/portals.toml`, 11 were learned (median $0.62), 3 are forbidden by their robots.txt, 1 is a bot wall, 2 cannot be read because their paging lives in the server's session, and 1 was not reachable from the session that ran it. A repair after one broken node gave the earlier values again in 15 of 15 cases that broke (after the fixes below). With only the domain left of a portal's address, the repair found the list again on 10 of 10 portals where that broke the recipe. `main` passes 1386 tests; pull request 67 (the last three fixes, 1389 tests) is open and will be merged by this session when its CI is green.

## What was built, in order

| Pull request | What it did |
| --- | --- |
| 49 | `app/agent/`: runner (the only model caller), tools, learn, repair, spot check, prompts as files, settings; wired into `create_app` through the reader's protocols |
| 50, 51 | First live learn and repair on the mock portal; learn prompt 2; `CONVENTIONS.md` describes the runner as built; measured cost in `DESIGN.md` |
| 54 | From your NFZ report: steps dropped in batches so the prompt cache hits; a run's model cost saved as soon as the agent returns; learn prompt 3 (the contract's allowed values) |
| 55, 46 | Your fix merged into the recipe schema rules, then into `main`, on Goktug's word |
| 56 | Demo: a second mock portal (`https://login.mock.example`) and `POST /demo/layout`, `/demo/login-wall`, `/demo/reset`, `GET /demo/runs/{id}` |
| 60 | `variants/`: eight made-up portals with exact truth, each with a redesigned face; `python -m variants.run` |
| 64 | Rate-limit wait; a repair must give the last good read's tenders again; repair prompt 2 (only the domain stays); `portal_hints` (sitemaps); mock `paths_moved`; `variants/real.py`; the report on the real portals |
| 67 (open) | A failed repair is followed by a learn with the old recipe as a draft; a repair must keep the tenders' files; the learner stops early on session paging |

Your handoff "finding a portal again after its paths move" is done in 64: the `paths_moved` switch, the prompt section, `portal_hints` with its size cap, the tests, and the live proof you said was missing.

## How it was tested

Four layers, from cheapest to closest to the real thing. Only the first runs in CI.

1. **Scripted model** (`tests/agent/`, about 90 tests): a stand-in model that follows a script, the mock portal as the network. Covers the runner's rules (budgets, trimming, one retry, rate limit), every tool, learn, repair, spot check, and the app end to end: learn on attach, a changed layout repaired to recipe version 2, every address moved and found again with the spot check in between. No model call, no request.
2. **Live model on the mock portal** (in process): learn, repair of `layout_changed`, repair of `paths_moved`, and the scheduled read repairing on its own in the demo. This is where the reader's trial read and the spot check ran with the real model.
3. **Live model on made-up portals** (`variants/portals.py`): a JSON API behind an app shell, rows without links, offset paging, month-name dates, a deadline only on the tender page, files on their own page, a login wall, an empty list. Each has a redesigned face (hooks and JSON keys renamed) and a moved face (every address but the domain changed). The recipe is run over every page and compared with the truth, field by field.
4. **Live model on the real test portals** (`variants/real.py`): learn live, every page kept in a clone on disk; a baseline read of two list pages and five tenders; then the clone served with one node's pages altered (list or detail), or the stored address replaced by a dead one, and one repair. No gold labels exist: "same values" means the same as the recipe's own baseline.

Layer 4 broke the rule in `CLAUDE.md` that no agent session reads a live portal. Goktug lifted it for these runs, on the condition that nobody else was reading the portals. One request a second per portal, robots.txt obeyed, through `app/fetch`. `CLAUDE.md` is unchanged; the session tried to write the exception into it and was refused by its permission system. A person should decide whether the file is to say so.

## What happened

Numbers are single runs. Full tables: `docs/reports/agent-on-made-up-portals.md`, `docs/reports/agent-on-real-portals.md`, with every recipe and step in the JSON files beside them.

| What | Result | Cost |
| --- | --- | --- |
| Learn, mock portal | all 45 tenders, every checked value right | $0.12 to $0.14 |
| Learn, 6 made-up portals | every tender, field and document count right | $0.11 to $0.16 |
| Learn, 18 real portals | 11 learned | $0.37 to $0.86, median $0.62; 10 to 36 requests |
| Repair, one node altered, 22 real cases | 7 did not break the recipe; 15 repaired to the same values (one only after the files fix) | $0.07 to $0.23 |
| Repair, only the domain left, real | 10 of 10 found again (one only after the learn-again step, for $1.13) | $0.07 to $0.25 |
| Repair, made-up portals redesigned / moved | 6 of 6 / 6 of 6, everything right | $0.08 to $0.13 |
| In the app, mock: layout changed / paths moved | serving again in 46 s / 26 s | $0.08 / $0.09 |
| Give up: login wall, robots.txt, bot wall | stops after 2 to 4 calls | $0.04 to $0.05 |
| Give up: session paging (`evergabe-online`, `place`) | stops after 8 and 11 calls (was 33 and 39) | $0.14, $0.27 |

"Only the broken node changes" held in 10 of 14 one-node repairs; in 3 the repair changed one more node, with the values still right. Why was not looked into.

## What the runs found and what was changed

| Found | Where | Change |
| --- | --- | --- |
| Prompt cache missed on calls after the context filled (your report) | runner | steps are summarised in batches, one cache key per run; cached share is now 77% to 84% on every real portal |
| A run's cost showed $0 until the run ended (your report) | reader | saved when the agent returns. Your pull request 61 touches the same thing in `app/loop.py` and `app/db.py`: see below |
| Four learns at once hit 1M tokens a minute and each died of one 429 | runner | waits (the API's own wait, 60 s at most) and tries again, five times |
| A repair was accepted although the tenders' pages no longer gave their values, or their files | tools | a repair's dry run must give the last good read's tenders again: ids, values, files |
| No step for "the page answers 404" | repair prompt, tools | go to the domain root, follow links, `portal_hints`, keep the ids |
| A list loaded by a script's own call was not found again in 20 calls | repair | a failed repair is followed by a learn with the old recipe as a draft (40 calls) |
| The learner spent its whole budget on session paging | learn prompt | stop after two tries and say so |

## What you need to know for your own work

- **The network layer ignores `HTTPS_PROXY`.** `Fetcher` hands httpx its own transport, so behind a proxy it connects directly and fails to resolve hosts ("robots.txt could not be read (dns)"). It cost this session an hour. It does not matter in the container. `variants/real.py` works around it with `live_fetcher()`; if you want it in `app/fetch`, it is a few lines there.
- **A portal whose robots.txt redirects to another host** (`evergabe.nrw.de` to `www.evergabe.nrw.de`) could not be read from this session because of its network allowlist. Untested whether the fetch layer follows that redirect itself.
- **Session paging** (`evergabe-online`: Wicket links; `place`: a form whose next page answers 400) needs cookies kept across requests and the page's own form state, or a browser. Today the learner says so and the portal ends `failed`.
- **Rate limits when several portals attach at once.** The runner now waits, but nothing caps how many learns run at a time. If the judges add five portals together, expect waits of up to a minute inside the learns, not failures.
- **Settings added** (all `AGENT_<NAME>`, in `app/agent/settings.py`): `CONTEXT_KEEP_SHARE`, `RATE_LIMIT_WAITS`, `RATE_LIMIT_WAIT_SECONDS`, `RATE_LIMIT_WAIT_MAX_SECONDS`, `HINTS_SITEMAPS`, `HINTS_SITEMAP_BYTES`, `HINTS_ADDRESSES`, `HINTS_SAMPLES`, `REPAIR_RELEARNS`. `MOCK_LEARNED_BY_MODEL=1` makes the model learn the mock portal instead of using its hand-written recipe.
- **`bench/` still imports nothing that can make a request**: your guard test is untouched. The made-up portals and the live runner are in `variants/`, repo-only.
- **To run things:** `python -m variants.run` (made-up portals; `--repair-from results.json --face changed|moved|both`), `python -m variants.real <ids> --out file.json --scenarios list,detail,lost` (real portals; needs `FETCH_MODE=live` by hand and a person's word), `python -m mock_portal.demo` then `POST /demo/layout` or `/demo/move`.

## Your open pull requests, as they stand against `main` at `69de8a1`

Checked with `git merge-tree`; I did not review their code.

| Pull request | Conflicts with `main` | Note |
| --- | --- | --- |
| 66 TenderNed overview page, `docs/BACKLOG.md` | none | docs and `bench/` |
| 65 fast tenders answer | none | |
| 61 repeated file links, lost usage | none | The lost-usage half overlaps pull request 54, which saves usage in the reader when the agent returns. Check that the two do not write the run twice. |
| 58 limit on tenders per portal | none | |
| 57 an outage is `failed` with the cause outage | 1 file | Changes what a state means. Goktug's view on 20 Nov was: no new state, the reason and cause say "outage". This is a decision for people. |
| 53 NFZ report | none | docs only |
| 52 debug logs | 2 files | touches `app/agent/` (3 files), which changed a lot since |
| 45 two new mock portals | 1 file (`README.md`) | `variants/` now has a JSON API portal and a German one too; these may still be worth having inside `mock_portal/` |
| 41 benchmark harness | 1 file | |

## Open

- No real portal has gold labels. Every "right" on a real portal is against the recipe's own first read.
- The reader's checks after a trial read ran live only on the mock portal.
- Not built: trying other stored recipes before a repair (DESIGN.md, Repair, step 1); a browser tool; a spot check after a learn.
- A portal with no tenders today cannot be learned and ends `failed`.
- `eb2b-gddkia` reads a deadline on 405 of 2000 rows and `vergabe-niedersachsen` on 19 of 40; nobody checked whether the rest have none.
- For people before the hand-in: `EUR_PER_USD` at the day's ECB rate; the hand-in README with the measured cost per portal (now: $0.37 to $0.86 to learn a real portal, $0.07 to $0.25 a repair, $0 a regular read); delete `docs/HANDOFF.md` and `docs/handoff/`.

## Spend

About $20 on the development key across all live runs of this session.
