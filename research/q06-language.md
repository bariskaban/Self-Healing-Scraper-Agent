# Q6. Language: Python for the whole system, or TypeScript/Node for part of it?

Owner: Goktug · Researched 20 Nov 2026 · Status: **answered**

How each claim is known is marked: **measured** (we ran it today, commands in the appendix), **read** (seen in the package, registry or document itself), **search** (seen only in a search result), **reasoning** (ours).

## Question

Python for the whole system, or TypeScript/Node for part of it? Our repo is set up for Python 3.12.

Judge on maturity for: headless browser with network capture; HTML parsing; the OpenAI SDK and agent tooling; ZIP and PDF handling; a small web server with a dashboard. Also weigh Docker image size and build time, and the cost of running two runtimes in one container.

Deliverable: a recommendation. If mixed, say where the boundary between the two sits.

## Decision

**Python for the whole system. No TypeScript part, so no boundary.**

We choose it for four reasons:

1. **Nothing we need is stronger in Node, and three things are stronger in Python**: parsing with XPath as well as CSS, date parsing in all six of our languages, and ZIP and SQLite from the standard library.
2. **Language speed cannot matter.** Every per-page cost we measured is at most 6% of the one second we must wait between requests anyway.
3. **A second runtime buys nothing and costs a supervisor, a second dependency manifest and a process boundary.** The image would grow 1 to 5%; the complexity is the real price.
4. **The repo, the project rules and every research answer so far already assume Python**, and in 24 hours one language means anyone can work on any part.

## The alternatives, and why they lose here

| Option | What it means | Why it loses for this project |
| --- | --- | --- |
| **A. Python only** (chosen) | FastAPI, httpx, Playwright for Python, lxml, Pydantic, SQLite | |
| B. TypeScript/Node only | Playwright (native), Fastify or Hono, cheerio, Zod, a SQLite package | It would work. But cheerio has no XPath and Q2's locators use XPath; the main date parser has no Polish; SQLite is either a native add-on or a built-in that is a release candidate in Node 24 and "active development" in Node 22; and we would redo the repo setup. No capability is gained in return. |
| C. Python core, Node side process for the browser or the agent | Two processes, talking over HTTP or pipes | Playwright for Python already starts its own Node process: the package ships a 150 MB Node 26 binary as its driver. A side process would put a second Node next to that one. It adds a supervisor, a `package.json` beside `pyproject.toml`, and a boundary that can fail. Docker's own guidance is one service per container. The only gain is Playwright releases 4 to 11 days sooner. |

**When B would win:** if most of the team is clearly faster in TypeScript than in Python. That is the one input this research could not measure. Nothing in the repo suggests it.

## Evidence

### 1. Capability by capability

| Capability | Python | Node | Stronger for us | How we know |
| --- | --- | --- | --- | --- |
| Headless browser, network capture | Playwright 1.65.2 (14 Nov 2026) | Playwright 1.65.1 (13 Nov 2026) | Tie. Same engine; request interception with abort and continue, HAR record and replay, CDP sessions, tracing and an async API exist in both. Python minor releases trail npm by 4 to 11 days. | read: PyPI and npm registries; both packages' API files compared |
| HTML parsing | lxml 6.1.3 and parsel 1.12.1: CSS and XPath. selectolax 1.0.2: CSS only, fastest | cheerio 1.2.0: CSS only. jsdom 31: XPath, but a whole DOM | Python. One fast parser covers both selector kinds Q2 uses. | read: the installed cheerio package contains no XPath at all (checked twice) |
| OpenAI SDK | openai 3.57.0, `responses.parse` with Pydantic models | openai 7.62.0, `zodTextFormat` | Tie. Both released 20 Nov 2026 with the Responses API and structured output built in. | read: both packages |
| Agent frameworks (Q5) | OpenAI Agents SDK 0.25.0, PydanticAI 2.71.0, LangGraph 1.2.24 | OpenAI Agents SDK 0.22.0, LangGraph 1.7.5; no PydanticAI | Python, by choice available | read: registries |
| ZIP | Standard library `zipfile`: ZIP64, reads an entry as a stream, `metadata_encoding` for file names that are not UTF-8 | yauzl 3.4.0 and others | Python. No dependency, and 2.4 times faster in our test. Neither side caps unpacked size; that check is ours in any language. | read: CPython docs source; measured |
| PDF (a validity check at most) | pypdf 7.1.1 (BSD), or just the `%PDF-` header | unpdf, pdfjs-dist | Tie. We do not read documents for content. | read: registries |
| Web server, dashboard, SQLite | FastAPI 0.165, Jinja2, standard-library `sqlite3` | Fastify 5.12 or Hono 4.13; better-sqlite3 13.2 (ships a prebuilt Linux binary) or the built-in `node:sqlite` | Python. SQLite needs no package and has been stable for years. | read: registries, Node docs; measured: no compile step on either side |
| Dates in DE, FR, ES, NL, PL, IT | dateparser 1.5.1 has all six; `zoneinfo` with `tzdata` for offsets | chrono-node 2.10.3 has no Polish | Python | read: both installed packages (checked twice) |
| Validation, strict JSON schema for the model | Pydantic 2.14 | Zod 4.6 | Tie | read: both SDKs convert them |

Not verified: Playwright's own list of features missing in Python. Its site was unreachable, so parity rests on comparing the two packages' API files, not on that list.

### 2. Speed cannot decide (measured)

We may send one request per second per portal. So the question is whether any per-page work comes near 1,000 ms. It does not.

| Work | Python | Node | Share of the 1,000 ms budget |
| --- | --- | --- | --- |
| Parse a 400 KB tender list and read 200 rows of 6 fields | lxml 13 to 15 ms; selectolax 5 to 6 ms | cheerio 42 to 60 ms | 0.5% to 6% |
| SHA-256 of a 500 MB file | 402 ms | 511 ms | under 1 ms per MB either way |
| Unzip 205 MB (50 files) and hash each entry | 579 ms | 1,415 ms | 12 to 28 ms per file |
| Validate 5,000 tender records | Pydantic 87 ms | Zod 18 ms (does less: strings only) | under 0.02 ms per record |
| Idle memory of the web server | 44 MB | 61 MB | |

The parse test was run twice, by two separate runs on the same machine; the ranges above span both. The slowest jobs, hashing and unzipping large files, are local work that runs beside the network waiting, not in place of it.

### 3. Image, build and memory (measured)

| | Size or time |
| --- | --- |
| `mcr.microsoft.com/playwright/python:v1.65.2-noble`, compressed | 1,067 MB |
| `mcr.microsoft.com/playwright:v1.65.1-noble` (Node), compressed | 1,013 MB |
| Python image plus a Node runtime (estimate from layer sizes) | about 1,117 MB, +5% |
| Node image plus a Python runtime (estimate) | about 1,026 MB, +1% |
| Our Python dependencies: install time, size | 10 s, 240 MB |
| The equivalent Node dependencies | 8 s, 127 MB |
| Pull of the Python base image | 66 s |
| `docker build` on top of it, cold | 24 s |
| Rebuild after a code change only | 4 s |
| Rebuild after adding one package | 27 s |
| Final image on disk | 2.72 GB |

The browser is about 80% of the image whichever language drives it, so the language does not move image size either. The Docker times were taken with a slow storage driver and through a proxy; a normal host should be faster.

Browser memory, the same binary under either language: 275 MB after launch, 375 MB with one blank page, 445 MB with a 300 KB table loaded, 592 MB with two such tabs. This is what "small to medium machines" have to carry, and it supports draft 2's cap of two browser pages at a time and its rule to read with plain HTTP whenever a recipe allows.

### 4. What "Python only" does not avoid

Installing Playwright for Python installs Node. The package contains `playwright/driver/node`, a 150 MB executable that reports version 26.13.1, and the Python library talks to it over a pipe (**measured**: file present and runs; **read**: package layout). Two consequences:

- There is no "smaller image without Node" to be had by choosing Python. The case for Python rests on the reasons above, not on avoiding Node.
- The Python package and the base image must be the same Playwright version, or the driver will not find its browser. Pin `playwright==1.65.2` with the `v1.65.2-noble` image.

### 5. Licences

Our results are licensed exclusively to Patterno, so copyleft dependencies are a risk. Everything in the table in section 1 is MIT, BSD or Apache-2.0 by its registry entry. Three things to stay away from: **PyMuPDF** (AGPL-3.0 or commercial), and embedding **Skyvern** or the **Firecrawl** server (both AGPL-3.0). Registry licence strings only; transitive dependencies were not reviewed.

## What would change the decision

- The team turns out to be much stronger in TypeScript.
- Q4 picks a tool that only exists for Node. The one candidate on Q4's list, Playwright MCP, is an npm package (`@playwright/mcp` 0.0.86, needs Node 20 or newer on the path) (**read**: npm registry). Choosing it would add a Node runtime and a process to the image; our own tools on Playwright for Python would not.

## Prototype first (about 1 hour)

1. A Dockerfile from `mcr.microsoft.com/playwright/python:v1.65.2-noble` with `playwright==1.65.2` pinned, built on linux/amd64 in CI. This is already in the plan for hours 0 to 3.
2. In the running container: load one page with Playwright, send every browser request through `page.route` and the rate limiter, and read the container's memory.
3. Optional, 20 minutes: build the same thing from `python:3.12-slim` plus `playwright install --with-deps --only-shell chromium` and compare size and build time. We could not measure this variant (the browser download host was unreachable from the research machine), so the base image choice in draft 2 stands on reliability, one pull from one registry, not on a measured comparison.

## Effect on other questions

- **Q1 recipe model:** a generated-extractor option would be Python.
- **Q2 locators:** XPath and CSS are both fine. Use lxml or parsel as the one parser; selectolax is faster but has no XPath, and speed does not matter here.
- **Q4 agent tools:** Playwright MCP needs Node on the path (see above). Request interception for the rate limiter exists in the Python API. Budget browser memory from section 3.
- **Q5 framework:** all four candidates exist for Python; PydanticAI exists only for Python.
- **Q7 schemas:** Pydantic models can serve the API contract, the recipe and the model's strict output schema at once.
- **DESIGN.md:** the stack table stands. Add the version pin from section 4.

## Sources

Read on 20 Nov 2026 unless marked.

- Package registries: https://pypi.org/pypi/playwright/json, https://registry.npmjs.org/playwright, and the same endpoints for lxml, parsel, selectolax, openai, openai-agents, pydantic-ai, langgraph, pypdf, pymupdf, fastapi, starlette, jinja2, dateparser, tzdata, pydantic, cheerio, jsdom, zod, yauzl, fastify, hono, better-sqlite3, chrono-node, @openai/agents, @langchain/langgraph, @playwright/mcp
- Image registries: https://mcr.microsoft.com/v2/playwright/python/tags/list, https://mcr.microsoft.com/v2/playwright/tags/list, https://hub.docker.com/v2/repositories/library/python/tags/3.12-slim
- Python `zipfile` documentation source: https://raw.githubusercontent.com/python/cpython/3.12/Doc/library/zipfile.rst
- Docker on several services in one container: https://raw.githubusercontent.com/docker/docs/main/content/manuals/engine/containers/multi-service_container.md
- Node built-in SQLite status: https://nodejs.org/docs/latest-v24.x/api/sqlite.html and https://nodejs.org/docs/latest-v22.x/api/sqlite.html
- Playwright's Node image definition: https://raw.githubusercontent.com/microsoft/playwright/main/utils/docker/Dockerfile.noble
- selectolax's own benchmark (author's numbers, not ours): https://raw.githubusercontent.com/rushter/selectolax/master/README.md

## Appendix: how the measurements were made

Machine: 4 cores, 16 GB, Linux, Python 3.12.3, Node 22.23.5, Docker 29.10 with the vfs storage driver, all traffic through a proxy. Five runs each, median reported.

- Image sizes: sum of layer sizes in each registry manifest for linux/amd64.
- Install: `pip install --no-cache-dir fastapi uvicorn httpx lxml cssselect selectolax pydantic openai playwright jinja2 aiosqlite dateparser tzdata` in a fresh environment; `npm install fastify cheerio playwright openai zod better-sqlite3 yauzl chrono-node luxon` in a fresh directory with an empty cache.
- Build: `FROM mcr.microsoft.com/playwright/python:v1.65.2-noble` plus the pip install above, `docker build`, then rebuilt after a code-only change and after adding one package.
- Parse: one generated 400 KB HTML page, 200 table rows of 6 fields, all 1,200 values read by CSS selector (and by XPath for lxml).
- Hash: SHA-256 over a 500 MB file in 1 MB chunks. Unzip: a 205 MB archive of 50 files, each entry written to disk and hashed. Half of each entry was random bytes, so compression is not typical.
- Browser memory: resident memory summed over the browser's process tree, headless Chromium 157.

Weakest numbers: the Docker times (slow storage driver, proxy in the path), and Pydantic against Zod (not the same work).
