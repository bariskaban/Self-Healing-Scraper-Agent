# First real portal: NFZ (ezamawiajacy.pl), 20 Nov 2026

What happened when the app was first pointed at a real portal, what it cost, and what went wrong. Taken from the run's own database (`/tmp/watchtower/watchtower.db`, read-only) on 20 Nov 2026 at 22:17 UTC. All times UTC. Model: `gpt-6.2-sol`, development key. Cost in USD from the app's price table; EUR at the placeholder rate 0.90.

## In one paragraph

The first attach failed at once (no learner was running). Six minutes later the same portal was learned by the model in 2 min 45 s for **$0.72 (about 0.65 EUR)** and reached `serving` with 5 tenders and 42 documents, all checks passing. Every read after that cost **$0** and took about 2 s. The learn call cost about two and a half times what it needed to: roughly 70% of it went on calls where the prompt cache missed.

## The portal

| | |
|---|---|
| Portal | NFZ, the Polish National Health Fund, on Marketplanet ezamawiajacy.pl |
| Address | `https://nfz.ezamawiajacy.pl/pn/nfz/demand/notice/publicpzp/current/list` |
| Why first | Poland is priority 1 (the mentor), server-rendered HTML, the largest platform (595 buyer sites) |
| Result | `serving`, recipe v1, fingerprint `marketplanet-ezamawiajacy`, 5 open tenders |

## Timeline

| Time | What | Model calls | Cost |
|---|---|---|---|
| 21:37:58 | Attach. Failed in 2 ms: "No recipe could be learned for this portal, so nothing can be read. A person is needed." | 0 | $0 |
| 21:43:43 | App restarted; the failed portal was rechecked | | |
| 21:43:48 – 21:46:28 | **Learn** (2 min 40 s): 84 steps, recipe v1 accepted, first full read published 5 tenders, 33 files downloaded (9.0 MB) | 24 | **$0.7199** |
| 21:46:28 – 22:15:50 | 16 scheduled reads, every two minutes, all `ok`, 1 to 3 s each | 0 | $0 |
| 21:52:28 | Read failed: "DNS failure, 3 tries". State `healing`, cause `outage`, the 5 tenders kept | 0 | $0 |
| 21:55:47 | Read passed, back to `serving` ("The portal is served again") | 0 | $0 |

## Cost of the learn

| | |
|---|---|
| Model calls | 24 (limit 40) |
| Tokens in / cached / out | 908,220 / 616,755 (68%) / 7,532 (335 reasoning) |
| Cost | $0.7199 (0.65 EUR) |
| Tool calls | `search_page` 24, `try_locator` 14, `call_api` 6, `open_page` 5, `replace_node` 2, `page_links` 1, `propose_recipe` 1 |
| Portal requests of the first read | 6 (1 list page, 5 tender pages), plus 33 file downloads |
| Cost per tender delivered | $0.14 for the first 5, then $0 |
| For comparison, the mock portal (PR #51) | $0.12 to $0.14 per learn |

**Where the money went.** The calls fall into two groups:

| Calls | Cached input | Cost | Share |
|---|---|---|---|
| 14 where the prompt cache hit (cached more than 20,000 tokens) | high | $0.20 | 28% |
| 10 where only the fixed 16,833-token prefix was cached | low | $0.52 | **72%** |

A cache-missing call cost $0.04 to $0.07; a cache-hitting one about $0.01. If every call had cached 93% of its input, as the best ones do, the learn would have cost about **$0.28**, not $0.72. The same pattern is in the TenderNed learn (13 of 28 calls missed, 73% of $0.74).

*Likely cause, not verified:* the runner trims older steps to one line near `AGENT_CONTEXT_TOKENS` (30,000), but the inputs here are 35,000 to 48,000 tokens. Rewriting the earlier part of the conversation changes the start of the prompt, so the cache cannot match it. Worth checking in `app/agent/runner.py` (`_input`) before the hand-in: halving the learn cost matters for the cost-per-portal figure in the README.

## Errors and problems

| # | When | What | Cost of it | Status |
|---|---|---|---|---|
| 1 | 21:37:58 | **"No recipe could be learned"** on the first attach. The reason has no "The learner says" part, so no model was called: the app had no `OPENAI_API_KEY`, and the only learner without a key knows just the mock portal. | $0, 6 minutes | Explained. A key was set at the restart and the next recheck learned it. The new debug logs (PR #52) say this outright at startup ("no agents: OPENAI_API_KEY is not set"). |
| 2 | 21:45 (call 21 of 40) | **First recipe proposal rejected**: three procedure words were mapped to values the contract does not have (`competitive_dialogue`, `innovation_partnership`, `direct_award`; only `open`, `restricted`, `negotiated`, `other` exist). The model fixed it with `replace_node` on the next call. TenderNed's first proposal was also rejected (7 problems) and fixed the same way. | Two extra calls each | Recovered by itself. The learn prompt should list the allowed values so the first proposal passes. |
| 3 | 21:52:28 | **A DNS failure shows as `healing`, not as an outage.** The reads recorded it correctly: the `outage` check failed ("The portal did not answer (DNS failure, 3 tries)"), severity `outage`, cause `outage`. But the portal's *state* was `healing`, so the dashboard showed a Healing badge, and its overview band offers "Inspect repair" although no repair ran and no model was called. Only the portal's detail page says "Cause: outage". It recovered by itself at 21:55. | $0 | **Open, by design but misleading.** Q10 and DESIGN.md give an outage the state `healing` (then `failed` after 60 minutes), and the API has only four states (`outage` is a cause, not a state), so the state machine did what the design says. The wording is the problem: "healing" reads as a repair. See below. |
| 4 | after the learn | **Optional fields not read**: `description` and `cpv_codes` are empty on all 5 tenders (the other nine fields are filled on all 5). The checks do not flag it because they are optional. | | Open. Not a failure, but a lower field score than the portal could give. |
| 5 | 22:08 onward | **Cost of an unfinished run is not stored.** TenderNed's learn cost $0.74 (28 calls), but its run row shows 0 calls and $0 and the dashboard shows 0.00 EUR, because a run's usage is saved only when the run ends. The figure is visible only in the text of a step. If the app stops before the run ends, the spend is lost. | $0.74 invisible | Open. The true spend of the session is at least $1.46, not the $0.72 the runs table shows. |

## Outage shown as healing: options

| Option | Change | Cost |
|---|---|---|
| A. Keep the state, fix the wording | The dashboard shows the cause beside the state on the overview ("Healing: outage, the portal is not answering") and the repair band says "Not answering" instead of "Inspect repair" when the cause is an outage | Dashboard only (Danil's files); no contract change |
| B. Say it in the reason | The reason already says "has not answered since 21:52 (DNS failure, 3 tries)"; show it on the overview row, not only on the detail page | Dashboard only |
| C. Change the state | Report an outage as something other than `healing` | **Not possible without breaking the contract**: the brief's four states are fixed. Research (Q10) also says `healing`, and research wins over our wishes |

Also to decide: a DNS failure may be *our* network, not the portal (here it probably was). The app cannot tell the two apart from one portal; it would need to resolve a known-good name too. Not built.

## The second portal: TenderNed (for context, not finished)

`https://www.tenderned.nl/aankondigingen/overzicht`, attached at 22:08:52. The learn (28 calls, $0.74) found TenderNed's JSON API and its dry run read 200 records. The first read then found 4,143 rows over 42 list pages and was reading each tender's page at 1 request per second, about 69 minutes. At 22:17 it was still `integrating` with nothing published; the 20-minute attach limit should publish what is validated at about 22:29. **Its outcome is not in this report.**

## What to do with this

1. Check the prompt cache in the runner (error table above): the biggest saving available, about 60% of a learn.
2. Tell the learn prompt the allowed values of the enum fields (error 2).
3. Save a run's usage as it goes, not only at the end (error 5), so cost is visible and survives a restart.
4. Decide whether `description` and `cpv_codes` should be required of a learned recipe when the portal shows them (error 4).
5. Say in the README that these costs are for two portals only: one server-rendered, one JSON API. The cost per portal for the hand-in is still an estimate.
