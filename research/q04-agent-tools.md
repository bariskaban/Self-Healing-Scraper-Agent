# Q4. Tools the learning and repair agent uses

Research date: 2026-11-20. Hackathon: Patterno track.

**Summary:**
Build about 8 tools on Playwright (Python) and httpx. The model sees a trimmed, numbered DOM or accessibility view of 1-5k tokens per page, plus a network-request log. One asyncio token bucket per portal host is enforced inside `page.route("**/*")`. Images, fonts, media and third-party origins are blocked. Static same-origin scripts are served from a cache.

---

## Q4. Tools the learning and repair agent uses

### Recommendation

Build **our own ~8 tools on Playwright Python plus httpx**, exposed through OpenAI function calling. Use **Playwright 1.64.x** (1.64.1 released 14 Oct 2026, [Wikipedia](https://en.wikipedia.org/wiki/Playwright_(software))). Every request from either client goes through one `PortalLimiter` per host. Borrow Playwright MCP's ideas, such as element refs in accessibility snapshots, but don't run it.

### Options compared

| | Playwright MCP | browser-use | **Own tools (recommended)** |
|---|---|---|---|
| Rate limiting | `--blocked-origins` / `--allowed-origins` only. The docs say these are "not a security boundary" and "do not affect redirects" ([playwright.dev MCP network](https://playwright.dev/mcp/tools/network-mocking)). No per-host token bucket | Dropped Playwright for raw CDP. Its own changelog (19 Aug 2025) says "Nothing runs on Playwright anymore" ([browser-use changelog](https://browser-use.com/changelog/19-8-2025)). Our Playwright `route` interception would not apply, so we would need a CDP Fetch-domain shim | `page.route("**/*")` plus a shared token bucket. Full control |
| Network capture | Has `browser_network_requests` | Limited | Ours: a `responses` log with JSON bodies |
| OpenAI tool calling | Needs an MCP client bridge. The 25 default tools cost ~3,919 tokens of definitions ([TestDino](https://testdino.com/blog/playwright-mcp-token-cost)) | Runs its own agent loop and planner, which overlaps Q5 | Native function schemas, ~8 tools |
| Output | Locators are snapshot refs that aren't stable across navigations, so not reusable as recipes | Numeric element indices, not stable selectors | `test_locator` returns stable CSS/XPath/JSONPath candidates that go straight into the recipe |
| Container | Node runtime as well as Python | Python, Chromium-only | Python only |

The deciding point is that the agent's output must be a **recipe with durable locators**. Both off-the-shelf tools are designed to *do a task now*, not to *emit a replayable program*. WebLists made the same point when it built record/replay tools rather than reusing a generic agent loop ([arXiv 2504.12682](https://arxiv.org/pdf/2504.12682)).

### Tool set (OpenAI function schemas)

1. **`open(url)`.** Navigates in Playwright. Returns status, final URL, title, and a short **network summary**: same-origin JSON responses with URL, method, item count and the first record's keys.
2. **`view(mode, scope?)`.** `mode` is one of:
   - `outline`: headings, forms, tables and lists with counts;
   - `interactive`: a numbered list of links, buttons and inputs;
   - `text`: trimmed DOM/Markdown of a region;
   - `a11y`: an aria snapshot.

   Each mode is capped at about 4k tokens and paged.
3. **`links(filter?)`.** Groups links by URL pattern, for example `/tender/{id}` x20, with one sample each.
4. **`act(ref, action, value?)`.** Click, fill, select or submit. Returns the diff in network requests and URL.
5. **`fetch(url, method, params, body)`.** Direct HTTP through httpx, sharing the browser's cookies. Used to replay discovered APIs.
6. **`test_locator(page_ref, locator_spec)`.** Runs a CSS/XPath/JSONPath/regex locator on the 3 cached seed pages and returns the values. This lets the model check a locator *without new requests*.
7. **`download(url)`.** Streams to disk, then returns size, sha256, MIME type and the ZIP listing. Detects HTML-instead-of-file and captcha pages.
8. **`propose_recipe(json)` / `patch_recipe(node_id, json_patch)`.** Validated against the schema, then dry-run on the cached pages.

Every page is cached to disk the first time it's fetched, so repeated views cost no requests.

### Page views: token cost

All figures below are **published measurements**, plus the sizes of pages our subagent fetched. We could not instrument raw HTML ourselves inside this research environment.

| View | Reported size | Source |
|---|---|---|
| Raw HTML | WorkArena pages 40K-500K tokens. SWDE pages up to 219K, longest-site average 91K | [Read More, Think More (arXiv 2604.01535)](https://arxiv.org/html/2604.01535); [Co-Scraper](https://arxiv.org/pdf/2606.14821) |
| Accessibility tree | About 10x smaller than page text/HTML | [FocusAgent (arXiv 2510.03204)](https://arxiv.org/pdf/2510.03204) |
| Playwright MCP snapshot | example.com 1,272 chars (~320 tokens). A real marketing homepage 14,200 chars (**~3,500 tokens, 3x its screenshot**) | [RenderScreenshot, checked 2026-10-15](https://renderscreenshot.com/blog/playwright-mcp-screenshots) |
| Screenshot | 1280x720 = ~1,196 visual tokens (Anthropic formula). Format doesn't matter, only pixels. It gives no actionable selectors | same |
| browser-use DOM state | 10,000+ DOM nodes reduced to ~200 interactive elements, ~5-10 KB of text (~1.5-2.5k tokens) | [DeepWiki on browser-use](https://deepwiki.com/browser-use/browser-use/5-language-model-integration) |
| **Procurement pages (our subagent, extracted text)** | FTS OCDS release JSON ~10k chars = **~2.5k tokens**. FTS notice PDF text ~3.2k chars = **~800 tokens**. TED HTML detail page ~9k chars = **~2.2k tokens, all navigation with the notice body missing (JS-rendered)**. FTS HTML notice pages were **blocked by bot detection** | fetched 2026-11-20 |

**Interpretation.**

- **Screenshots** are cheap per image, but they can't yield locators, so they are useless for recipe writing. Keep them only as a fallback for captcha detection.
- **Accessibility trees** are the right default for *navigation*, meaning what to click.
- **Extraction locators need DOM structure.** The a11y tree drops the class and id attributes that selectors rely on.
- **Stronger models extract more from detailed HTML.** One study found high-capability models (GPT-5.1, Claude Sonnet 4.6) do **up to 17.5 pp better with HTML than with the a11y tree**. Weaker models get worse with HTML ([arXiv 2604.01535](https://arxiv.org/html/2604.01535)).

So: use `interactive` or a11y views to navigate. Use **pruned DOM restricted to one region** (Co-Scraper-style: strip head, script and style, keep id and class, truncate text, sample repeated rows) for locator writing. Use **JSON samples** whenever an API exists, since they are the cheapest and most precise view.

End-to-end reference points: a browsing agent on GPT-4.1 averaged about **146K input tokens and $0.31 per task** on WebMall ([arXiv 2508.13024](https://arxiv.org/html/2508.13024v2)). HTML-only agents used about 241K tokens per task, against 47-140K for API/RAG-style interfaces ([arXiv 2511.23281](https://arxiv.org/html/2511.23281)). Budget the learning phase at **100-300K tokens per portal**. Repair should take far fewer tokens because it targets one node. For model choice and price, see Q9.

### Enforcing 1 req/s with a headless browser

Rule: **every request that reaches the portal's hosts counts**, whether it is a document, xhr/fetch, script, stylesheet, redirect hop or download. That is the conservative reading of "1 request per second per portal", and the judges can only observe the server side.

1. **One limiter per registrable domain.** An `asyncio` token bucket with capacity 1 and refill 1/s, shared by httpx and Playwright. The httpx side uses an event hook or transport wrapper. Honour `Retry-After` on 429/503, which FTS documents.
2. **Route interception on the browser context:** `context.route("**/*", handler)`. The handler does the following:
   - aborts `image`, `media`, `font` and usually `stylesheet` (the standard Playwright pattern, [BrowserStack guide](https://www.browserstack.com/guide/playwright-block-request));
   - aborts third-party origins such as analytics and CDNs, except those found to serve the app's own API or bundle;
   - for same-origin `document`/`xhr`/`fetch`, calls `await limiter.acquire()` and then `route.continue_()`;
   - for same-origin `script`, serves it from a disk cache with `route.fulfill()` if seen before, otherwise acquires a token. App bundles then cost tokens only once per portal.
3. **Service workers off** (`service_workers="block"` in the context options). Otherwise requests bypass `route`. Playwright MCP has the equivalent `--block-service-workers` flag.
4. **One page at a time per portal.** Set waits to `domcontentloaded` and avoid `networkidle`, because polling SPAs never go idle.
5. **Redirects.** Each hop is a separate server hit. Count them with `response.request.redirected_from` in the log and keep a small safety margin, for example 0.9 req/s.
6. **Downloads use httpx, not the browser.** Pass cookies from `context.cookies()`, stream to disk and hash while streaming. This covers captcha-gated pages whose files still download: the file URL is fetched directly without solving anything.
7. **Regular reads mostly skip the browser.** Once the recipe has an `http_json` node, Playwright is needed only for `browser_state` nodes. That means fewer sub-requests and a simpler limiter.

### Prototype first (Q4)

- **Limiter plus route handler plus request audit log. ~3 h.** Test it against a local server that logs hit timestamps and assert that no two hits come less than 1 s apart.
- **Tools 1, 2, 6 and 7 with OpenAI function calling, run on FTS plus one SPA portal. ~5 h.** Measure tokens per view mode on 3 real portal pages. This replaces the published numbers above with our own.

---

## Changes to other open questions (from the Q1, Q3 and Q4 research together)

- **Q2 (field locators):** Each field should be a *locator bundle*: primary selector, fallbacks, label-text anchor and a value regex or type. This follows Co-Scraper's fallback wrappers and SG-WRAM's preserved features. Prefer JSONPath whenever an API exists.
- **Q5 (agent framework):** You probably need none. A plain OpenAI tool-calling loop over ~8 tools is enough. Avoid browser-use, because its own planner loop overlaps this question.
- **Q6 (language):** Python 3.12 works. Playwright Python, httpx and asyncio cover everything, and there is no need to run Node for Playwright MCP.
- **Q7 (schemas):** Write the recipe schema in the OpenAI strict subset: flat `nodes`/`edges` arrays, every field required, optional fields as `null`-unions, no root `anyOf`.
- **Q8 (benchmark):** Use FTS OCDS, TED `scope: ACTIVE` and the PLACSP ATOM feed as ground truth to score our HTML attach on the matching portals, and model choice with it.
- **Q9 (models and cost):** Budget about 100-300K tokens for learning and much less for each repair. HTML views favour stronger models, so a cheaper model may work for navigation and a stronger one for locator writing.
- **Q10 (failure rules):** "Bot detection on HTML but the API works" means `serving`, not `failed`. Mark the portal `failed` only when every route needs login or a captcha. Use the JAIR result (verification recall 0.95, precision 0.73) as a reason to require two consecutive bad reads before entering `healing`.
- **Q11 (reuse across portals):** Platform fingerprints plus `subrecipe_ref` nodes, such as the external e-sourcing portals linked from FTS, are the reuse mechanism.
- **Q12 (large portals):** Use watermark-based incremental reads (`updatedFrom` with overlap, cursors). Load metadata first, then documents round-robin. Report progress during `integrating`, because full document sets won't fit in minutes at 1 req/s.

## Caveats

- Several token figures come from vendor or tutorial blogs (TestDino, RenderScreenshot, DeepWiki), not peer-reviewed papers. Treat them as order-of-magnitude figures.
- The AutoScraper break-even of about 10-30 pages per domain is our own calculation from the paper's Table 6 (GPT-4-Turbo timings), not a figure the paper states.
- Our subagent could not fetch raw HTML byte counts, the PLACSP feed, or a live FTS tender-stage release. The FTS `tenderPeriod.endDate` path and offset are inferred from the docs and must be checked first.
- Co-Scraper (June 2026) and several other cited works are recent preprints that have not been peer reviewed.

---

## Caveats

- Several token figures come from vendor or tutorial blogs (TestDino, RenderScreenshot, DeepWiki), not peer-reviewed papers. Treat them as order-of-magnitude figures.
- The AutoScraper break-even of about 10-30 pages per domain is our own calculation from the paper's Table 6 (GPT-4-Turbo timings), not a figure the paper states.
- Our subagent could not fetch raw HTML byte counts, the PLACSP feed, or a live FTS tender-stage release. The FTS `tenderPeriod.endDate` path and offset are inferred from the docs and must be checked first.
- Co-Scraper (June 2026) and several other cited works are recent preprints that have not been peer reviewed.
