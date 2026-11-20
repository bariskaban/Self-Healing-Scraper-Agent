# Q9. OpenAI models and cost per portal

Owner: Danil. Researched 20 Nov 2026 (OpenAI pricing and model pages first, third parties marked). Prices in USD per 1M tokens, standard tier, requests under 272K input tokens.

## Recommendation

**Learn and repair on `gpt-6.2-sol`** (Responses API, reasoning `medium`, strict JSON schema output), with **`gpt-6.1-terra` benchmarked against it** as the half-price option. **Spot checks on `gpt-6-luna`** at reasoning `none`. One new portal costs about **$1.70 to attach**, a known-software portal about **$0.003**, a regular read **$0**.

## Checked live on our key (20 Nov 2026)

- `GET /v1/models` lists 99 models, including the whole GPT-6 family below.
- One tiny call each on `gpt-6-sol` and `gpt-6-luna`: 5,000 requests/min; 1M tokens/min on Sol, 2M on Luna. That is the **Build** usage tier. Draft 2 caps model calls at 4 at a time, about 150K tokens in flight, far under the limit.

## Shortlist to benchmark

| Job | Models | Why |
|---|---|---|
| Learn | `gpt-6.2-sol` (default), `gpt-6.1-terra` (half price), `gpt-6.2-astra` (quality ceiling, 4x price) | Sol has the cheapest cached input of the frontier tier; Terra may be enough for recipe writing |
| Repair | same as learn | same prompts and cache prefixes as learn |
| Spot check | `gpt-6-luna`, `gpt-5.6-luna`, `gpt-5.4-mini` | quote-and-verify is a short, cheap job; all allow reasoning `none` |

## Model facts

| Model | In / cached / out | Over 272K input | Context / max out | Reasoning `none` | Batch / Flex |
|---|---|---|---|---|---|
| gpt-6.2-sol | 2 / 0.10 / 10 | 4 / 0.20 / 15 | 1.05M / 128K | rejected | Batch 1 / 5; no Flex |
| gpt-6.1-sol | 2 / 0.10 / 10 | 4 / 0.20 / 15 | 1.05M / 128K | no | 1 / 5 |
| gpt-6-sol | 2 / 0.20 / 10 | 2x in, 1.5x out | 1.05M / 128K | yes | 50% |
| gpt-6.1-terra | 1 / 0.05 / 5 | 2 / 0.10 / 7.50 | 1.05M / 128K | yes | 0.50 / 2.50 |
| gpt-6-luna | 0.10 / 0.01 / 0.50 | 0.20 / 0.02 / 0.75 | 1.05M / 128K | yes | 0.05 / 0.25 |
| gpt-6.2-astra | 8 / 0.40 / 40 | 16 / 0.80 / 60 | 1.05M / 128K | rejected | Batch 4 / 20 |
| gpt-5.6-terra | 2 / 0.20 / 12 | 4 / 0.40 / 18 | 1.05M / 128K | yes | 1 / 6 |
| gpt-5.6-luna | 0.20 / 0.02 / 1.20 | 0.40 / 0.04 / 1.80 | 1.05M / 128K | yes | 0.10 / 0.60 |
| gpt-5.4-mini | 0.75 / 0.075 / 4.50 | max input 272K | 400K / 128K | yes (default) | Batch 0.375 / 2.25 |

All support tool calling and Structured Outputs. **Use the Responses API**: on Chat Completions, Sol and Luna only accept tool calls at reasoning `none`. Reasoning tokens bill as output. `gpt-5.6-sol` is on a promotion (4 / 20) that ends 30 Nov 2026 per the pricing page; skip it.

Published benchmarks are browsing, coding and computer use (OpenAI, 22 Sep and 17 Nov 2026; Artificial Analysis, 17 Nov 2026: GPT-6.2 Astra index 62, GPT-6.2 Sol 57, GPT-6.1 Terra 38 at medium). **None measure HTML or JSON extraction**, so our own eval decides (Q8).

## Cost per portal

Assumptions (ours, to replace with measured numbers at hour 16): learn = 12 calls of 30K input and 8K output (3K visible + 5K reasoning); repair = 5 such calls; spot check = 1 call of 20K in, 1.5K out. No caching counted.

| Event | Tokens | gpt-6.2-sol | gpt-6.1-terra |
|---|---|---|---|
| Learn, new software | 360K in, 96K out | 0.72 + 0.96 = **$1.68** | 0.36 + 0.48 = **$0.84** |
| Spot check (Luna) | 20K in, 1.5K out | 0.002 + 0.00075 = **$0.003** | same |
| Attach, new software (learn + spot check) | | **$1.69** | **$0.84** |
| Attach, known software (spot check only) | | **$0.003** | **$0.003** |
| Regular read | none | **$0** | **$0** |
| Repair | 150K in, 40K out | 0.30 + 0.40 = **$0.70** | 0.15 + 0.20 = **$0.35** |

Range on Sol: a learn costs $0.48 (8 small calls) to $3.30 (15 large calls). If half the learn input hits the cache, the Sol learn falls to $1.34.

**The pitch line for "Approach":** at 4,500 portals with most running a few dozen software packages, the learning cost is paid per package, not per portal. Q11 covers how.

## Cost traps

- **The 272K cliff.** A learn loop that appends every tool result to one conversation grows about 30K per call; around call 10 it crosses 272K input and the whole request bills at 2x input and 1.5x output. Keep each call's context trimmed (draft 2 already trims pages).
- **Batch** has a 24-hour window: useless for learn and repair. **Flex** (50% off, may return 429 under load) suits only background spot checks.
- **The judging key.** The judges run our container on our key. Make a separate project key with a hard monthly cap, and keep the per-portal token cap from draft 2.

## Prototype first (about 5 hours)

Two portals (one JSON API, one paged HTML) x three models (`gpt-6.2-sol`, `gpt-6.1-terra`, `gpt-6-luna` at medium): 6 learns, under $3 at list price. Measure: recipe passes the checks first time, calls used, tokens, wall time, schema failures. Then one repair (break a locator) and the spot check on `gpt-6-luna` vs `gpt-5.4-mini`. About 3 h to build the Responses API loop (it becomes the real learner), 2 h to run and score.

## Effect on other questions

- Q5 framework: anything built on Chat Completions breaks tool use at medium reasoning. Use the OpenAI SDK's Responses API directly, or a framework that wraps Responses.
- Q8 benchmark: public numbers do not cover our task; the 2-portal eval above is the first slice of Q8.
- Q12 large portals: the model never reads a whole portal, so portal size does not change model cost. Keep every request under 272K.

## Sources (accessed 20 Nov 2026)

- OpenAI pricing (with the Sol promotion footnote): https://developers.openai.com/api/docs/pricing
- OpenAI model pages: https://developers.openai.com/api/docs/models/gpt-6-sol (and /gpt-6-luna, /gpt-6-astra, /gpt-6.2-sol, /gpt-6.1-terra, /gpt-5.6-terra, /gpt-5.6-luna, /gpt-5.4-mini)
- Function calling: https://developers.openai.com/api/docs/guides/function-calling; latest-model guide: https://developers.openai.com/api/docs/guides/latest-model
- Structured outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- Rate limits: https://platform.openai.com/docs/guides/rate-limits
- Batch: https://developers.openai.com/api/docs/guides/batch; Flex: https://developers.openai.com/api/docs/guides/flex-processing
- GPT-6 Sol and Luna launch (22 Sep 2026): https://openai.com/index/introducing-gpt-6-sol-and-luna
- GPT-6.2 Astra and Sol (17 Nov 2026): https://openai.com/index/introducing-gpt-6-2-astra-sol
- GPT-5.6 price cut (30 Jul 2026): https://openai.com/index/advancing-the-price-performance-frontier-with-gpt-5-6
- GPT-5.6 Sol promotion (21 Aug 2026): https://community.openai.com/t/20-price-reduction-for-gpt-5-6-sol-api-codex-credits-and-chatgpt-work/1391726
- Third party: Artificial Analysis https://artificialanalysis.ai (17 Nov 2026); saasfeeds price overview https://saasfeeds.com/en/news/openai-model-pricing-november-2026-current-api-rates-from-gpt-6-luna-to-gpt-6-as-80463 (19 Nov 2026)

Conflicts: the GPT-5.6 Sol promotion ends "at least 21 Nov" (community post) vs "30 Nov" (pricing page); the pricing page wins. Some third-party pages list pre-cut prices or claim GPT-6 Sol has no tool use; OpenAI's own pages win. Not confirmed: `gpt-6.2-sol` reasoning levels, whether it is on Flex, whether `gpt-6-astra` is generally available.
