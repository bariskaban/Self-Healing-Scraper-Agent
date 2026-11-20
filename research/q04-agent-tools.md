# Q4. Agent tools: what does the learning and repair agent use to see and drive a portal?

Owner: teammate who took Q1, Q3 and Q4 · Status: **open, no answer in the repo yet**

## Question

Options
- Playwright MCP (Microsoft's browser MCP server).
- browser-use (a Python library).
- Our own tools on Playwright and httpx: fetch a page, get a compact view of it, list links, click or fill, capture network requests, test a locator, download a file.

Constraints
- All traffic passes our per-portal rate limiter (1 req/s). Settle whether a headless browser's sub-requests (scripts, images) count, and how to block or limit them.
- Network calls can be captured, so we can find JSON APIs.
- Runs headless inside our container.
- Works with OpenAI tool calling.
- Shows pages to the model compactly.

Deliverable: a recommendation. Compare page views for the model (trimmed HTML, markdown, accessibility tree, screenshot), with token counts measured on 2-3 real portal pages. Explain how the rate limit is enforced with a headless browser.

## Answer

None yet. When it is written, it follows the answer standard in [README.md](README.md).
