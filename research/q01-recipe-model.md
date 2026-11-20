# Q1. Recipe model: how to represent what the LLM learned

Research date: 2026-11-20. Hackathon: Patterno track.

**Summary:**
Use a navigation graph whose nodes come from a closed set of kinds (http_json, http_html, browser_state, feed, download) and whose edges come from a closed set of actions. Each node carries a fixed-shape extraction block. That gives you the reach of a graph with the reliability of a fixed spec, and a repair touches one node. Allow generated Python only as a sandboxed escape-hatch node.

---

## Q1. Recipe model

### Recommendation

Use a **typed navigation graph with fixed node and edge kinds**. Each node has a fixed-slot extraction block: a list selector, field locators, a paging rule and a documents rule. Generated Python is allowed only as a rare `custom_code` node that runs in a sandbox. The LLM produces the graph with OpenAI structured outputs. Repairs are JSON patches scoped to a single node.

### Options compared

| Criterion | Navigation graph (free-form) | Fixed-stage JSON spec | LLM-generated Python | **Typed graph (recommended)** |
|---|---|---|---|---|
| Multi-step downloads, JS apps, paging | Yes | Partly. Fixed slots can't express "search form → list → summary page → real tender → file portal" | Yes | Yes. Edges are typed actions; a JS app is an `http_json` node once its API is found |
| Diff size when the portal changes | Small, but the shape is unbounded | Smallest | Large. Regenerated code often rewrites unrelated lines | Small. Patch one node's locators |
| LLM produces a valid one | Medium | High | Medium. Runs, but can be silently wrong | High. One closed schema, enum node kinds |
| Runner complexity | Medium | Low | Low runner, high sandbox and security cost | Medium. About 6 node interpreters |
| Reuse across portals on the same software | Good | Good | Poor | Good. A subgraph becomes a template keyed by platform fingerprint |

**Why typed graph.** Research on reusable LLM-generated scrapers points the same way. The model should produce a *program-like artefact* once, then a deterministic runner reuses it.

- [AutoScraper (EMNLP 2024)](https://arxiv.org/abs/2404.12753) generates reusable action sequences and XPaths from HTML. The paper's time-efficiency analysis (section 6.3, Table 6, GPT-4-Turbo) defines the break-even as N_W >= (n_s*T_g+T_s)/(T_d-T_e). Our own calculation from that table puts the point where it becomes cheaper than direct LLM extraction at about 9.7 pages (University) to about 29.9 pages (Auto) per domain, averaging about 19. The paper's Table 4 also shows direct LLM extraction scored a higher F1 than AutoScraper for every model except GPT-4-Turbo (88.69 vs 78.56).
- [Co-Scraper (arXiv 2606.14821, June 2026)](https://arxiv.org/pdf/2606.14821) induces a site-level program from **three seed pages** and reports **F1 94.78% and a 90.39% reuse success rate** on SWDE. It also notes that raw SWDE pages reach **219K tokens**, so pruning has to come before induction. Its programmatic wrapper with fallbacks beat bare XPaths on robustness. That is the reason to give each field a primary locator plus fallbacks rather than a single XPath.
- [WebLists / BardeenAgent (arXiv 2504.12682)](https://arxiv.org/pdf/2504.12682) is the closest prior art to our "attach" task. An agent runs a **record phase** that produces a **content-robust executable program** with list scoping and pagination controls (an `EnterList` tool). A **replay phase** then runs without the LLM. It explicitly handles end-of-list detection, such as "Next" turning into "Previous". On 200 tasks across 50 sites it reached **66% recall with more than 72% precision**, over twice the recall of state-of-the-art web agents. Our graph is the same idea, made explicit and patchable.

**Why not a pure fixed-stage spec.** Our portal list includes multi-step downloads, links to summary pages and captcha-gated pages whose files still download. Each of these needs an extra hop that fixed slots can't represent without ad-hoc flags.

**Why not generated Python as the primary form.** Diffs aren't local. A wrong value is worse than a missing one, and code can "run green" while reading the wrong field. Structured outputs guarantee only the *shape* of the output, not its correctness. OpenAI's own documentation says structured outputs "can still contain mistakes" ([OpenAI structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs); [launch post](https://openai.com/index/introducing-structured-outputs-in-the-api/)).

**Repair and verification have decades of prior art.** Lerman, Minton & Knoblock split wrapper maintenance into **verification**, which detects a broken wrapper from changes in the statistics of extracted data, and **reinduction**, which relabels the data on changed pages and rebuilds the wrapper ([JAIR 2003, arXiv 1106.4872](https://arxiv.org/pdf/1106.4872)). Their verifier caught **35 of 37 real wrapper changes** over 10 months (recall 0.95, precision 0.73). That is a useful baseline for our validator: favour recall and expect false alarms. Schema-guided maintenance (SG-WRAM) uses features that survive a redesign, such as data patterns, hyperlinks and labels, to find values again ([Meng et al., ACM](https://dl.acm.org/doi/10.1145/956699.956701)). This is why each field locator should store the **label text anchor** and a **value pattern** as well as the selector.

**Libraries.**

- [Crawl4AI's `generate_schema()`](https://docs.crawl4ai.com/extraction/no-llm-strategies/) (docs v0.9.x, checked Nov 2026) makes one LLM call to write a CSS/XPath schema made of a `baseSelector` and fields. After that, extraction runs without an LLM. This is the same pattern as our list and detail nodes, and the schema format is worth copying.
- [ScrapeGraphAI](https://arxiv.org/abs/2602.15189) calls the LLM on every extraction, usually over Markdown. Its 100k-event dataset shows 96.5% structurally valid outputs. That is fine for one-off use but breaks our "no model call on regular reads" rule.
- Self-healing scraper write-ups make the same design point: run deterministic extraction and call a model only when monitoring says something broke ([Zyte](https://www.zyte.com/blog/what-is-a-self-healing-web-scraper/)).
- Scrapy spiders and Crawlee routers are code, which we should avoid. Their *labelled request queue* concept, where each request carries a handler label, maps directly to our node kinds.

**Structured-output constraints (OpenAI, checked Nov 2026).** Strict mode supports a subset of JSON Schema. Every property must be `required` with `additionalProperties: false`, so optional fields have to be typed as `null`-unions. The root can't be `anyOf`. Recursion and `$defs` are supported ([OpenAI guide](https://developers.openai.com/api/docs/guides/structured-outputs)). A secondary guide cites limits of 10 nesting levels and 5,000 properties ([ergini.com, checked Oct 2026](https://ergini.com/blog/openai-structured-outputs)). The design consequence is to keep the graph **flat**: `nodes: [...]` and `edges: [...]` arrays referencing node ids, not nested trees. Use one `kind` enum with nullable per-kind sub-objects.

### Draft recipe: UK Find a Tender Service (FTS)

FTS was chosen because it has both a documented OCDS API and an HTML front end. In testing, the HTML notice pages returned **bot-detection blocks** to our research fetcher, while the OCDS JSON route worked. That pattern is exactly why the recipe prefers the API. Field paths below come from the [FTS API documentation](https://www.find-tender.service.gov.uk/apidocumentation/1.0/GET-ocdsReleasePackages) and from a release package we fetched (notice 085175-2025, a UK6 award notice).

**Limits of what we verified.** We saw no `tender.tenderPeriod.endDate` in a live tender release. The award notice had `standstillPeriod.endDate = "2026-01-05T23:59:59+00:00"`. FTS docs give the date pattern `YYYY-MM-DDThh:mm:ssTZD`. So deadlines very likely carry an offset, but check one live UK4 notice first.

```json
{
  "recipe_version": 3,
  "portal": "https://www.find-tender.service.gov.uk",
  "platform_fingerprint": "fts-uk-ocds-1.1",
  "rate_limit_rps": 1.0,
  "nodes": [
    {
      "id": "list",
      "kind": "http_json",
      "request": {
        "method": "GET",
        "url": "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages",
        "params": {"stages": "tender", "limit": "100",
                   "updatedFrom": "{{watermark_minus_overlap}}", "updatedTo": "{{now_utc}}"}
      },
      "paging": {"type": "cursor", "next_url_path": "$.links.next", "stop_when": "next_missing"},
      "items_path": "$.releases[*]",
      "item_key": "$.ocid",
      "merge": {"strategy": "latest_by", "path": "$.date"},
      "fields": {
        "id":               {"path": "$.ocid"},
        "referenceNumber":  {"path": "$.id", "note": "notice id nnnnnn-yyyy"},
        "url":              {"template": "https://www.find-tender.service.gov.uk/Notice/{{$.id}}"},
        "title":            {"path": "$.tender.title"},
        "description":      {"path": "$.tender.description"},
        "buyerName":        {"path": "$.buyer.name",
                             "fallback": "$.parties[?(@.roles contains 'buyer')].name"},
        "publicationDate":  {"path": "$.date", "type": "datetime_tz"},
        "submissionDeadline": {"path": "$.tender.tenderPeriod.endDate", "type": "datetime_tz",
                               "require_offset": true},
        "status":           {"path": "$.tender.status",
                             "map": {"active": "open", "planned": null, "complete": "closed",
                                     "cancelled": "withdrawn", "unsuccessful": "closed"}},
        "procedureType":    {"path": "$.tender.procurementMethodDetails"},
        "contractNature":   {"path": "$.tender.mainProcurementCategory"},
        "cpvCodes":         {"paths": ["$.tender.classification[?(@.scheme=='CPV')].id",
                                       "$.tender.items[*].additionalClassifications[?(@.scheme=='CPV')].id",
                                       "$.tender.lots[*]..additionalClassifications[?(@.scheme=='CPV')].id"],
                             "pattern": "^\\d{8}$", "unique": true},
        "placeOfPerformance": {"path": "$.tender.items[*].deliveryAddresses[*].region"}
      },
      "edges": [{"action": "for_each_item", "to": "docs"}]
    },
    {
      "id": "docs",
      "kind": "documents",
      "sources": [
        {"path": "$.tender.documents[?(@.url)]", "url": "$.url", "name": "$.description"},
        {"regex_in": "$.tender.description", "pattern": "https?://\\S+",
         "classify_with": "link_class_rules", "as": "external_portal_link"}
      ],
      "edges": [{"action": "follow_if_class", "class": "external_portal_link", "to": "ext_portal"}]
    },
    {
      "id": "ext_portal",
      "kind": "subrecipe_ref",
      "resolve_by": "platform_fingerprint_of_target_host",
      "on_unknown": "mark_documents_unresolved"
    }
  ],
  "download": {"client": "httpx", "stream": true, "hash": "sha256", "unzip": true,
               "max_bytes": 5000000000},
  "validators": [
    "id unique and stable across two reads",
    "submissionDeadline has UTC offset or is null",
    "cpvCodes all 8 digits",
    "open count within +-30% of previous good read unless explained"
  ],
  "provenance": {"learned_at": "2026-11-20T00:00:00Z", "model": "<set by Q9>",
                 "evidence": ["OCDS docs URL", "sample release ids"]}
}
```

What this shows for FTS:

- **The list node needs no browser.** It needs one request per 100 releases, and the API returns 429/503 with `Retry-After`, which the limiter must honour.
- **Documents usually live off-portal.** FTS `tender.documents` often has no URL. The real tender pack sits on a buyer e-sourcing portal linked from free text, for example a `delta-esourcing.com` link in `tender.description`. This is the "link to a summary page" problem in concrete form. The `subrecipe_ref` edge is how the graph reuses a recipe learned once for that platform (see Q11).
- **A repair is a one-path patch.** If FTS moves CPV codes, the patch is a single change: `nodes[id=list].fields.cpvCodes.paths`.

### Prototype first (Q1)

1. **Recipe JSON Schema plus runner for `http_json`, `http_html`, `documents`, paging (cursor, page number, next link). ~5 h.** Hand-write the FTS recipe above and one HTML-portal recipe. Confirm the runner produces the output contract.
2. **LLM authoring with strict structured outputs. ~3 h.** Feed the agent's evidence (sample JSON, pruned HTML of three seed pages, following Co-Scraper) and measure the schema-valid rate and field accuracy on three portals.
3. **Repair as a node-scoped JSON patch. ~3 h.** Break a locator on a private test portal, then check that the validator flags it and the patch touches only that node.

Total ~11 h. That is too much for one person in 24 h, so split it across two people.

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
