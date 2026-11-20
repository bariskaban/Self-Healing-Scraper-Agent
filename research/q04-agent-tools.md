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

## Inputs from answered questions

- **Q6:** the tools live in Python. Playwright MCP is an npm package that needs Node on the path; our own tools on Playwright for Python do not. Request interception for the rate limiter exists in the Python API. See [q06-language.md](q06-language.md).
- **Q6, measured:** the headless browser takes 275 MB after launch, 375 MB with one blank page and 592 MB with two loaded tabs, whichever language drives it.
- **Q10:** a portal may refuse a plain HTTP client and serve a browser (seen today on Spain's national portal), so "blocked" is decided only after one try through the browser. See [q10-failure-rules.md](q10-failure-rules.md).
