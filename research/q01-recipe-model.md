# Q1. Recipe model: how do we represent what the LLM learned about a portal?

Owner: teammate who took Q1, Q3 and Q4 · Status: **open, no answer in the repo yet**

## Question

The representation must let a deterministic engine read the portal again with no model call, and let a repair change only a small part.

Options
- Navigation graph (current favourite): nodes are pages or app states. Edges are actions: follow a link, next page, call a JSON API, submit a search form, click a download. The graph runs from the entry URL to the tender list, each tender page and its files. Each node stores locators for the fields on that page. A further idea: crawl the sitemap into the graph and use the LLM only to label nodes (see Q3).
- Fixed-stage JSON spec: fixed slots for list source, paging, list fields, detail fields and documents.
- LLM-generated Python extractor per portal, run in a sandbox.

Judge each on:
- Does it express multi-step downloads, JS apps and paging?
- How small is the diff when a portal changes?
- How reliably does an LLM produce a valid one with structured output?
- How simple is the runner?
- Can it be reused across portals running the same software?

Prior art to check: wrapper induction research, Scrapy/Crawlee spiders, LLM scraping libraries (ScrapeGraphAI, Crawl4AI, Firecrawl extraction schemas), and recorded browser flows (Playwright codegen).

Deliverable: a recommendation, plus a draft recipe in that format for one real portal.

## Answer

None yet. When it is written, it follows the answer standard in [README.md](README.md).
