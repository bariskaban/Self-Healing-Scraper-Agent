# Q15. Storage: SQLite, or a graph database?

Owner: David · Researched 20 Nov 2026 · Status: **answered**

How each claim is known is marked: **measured** (we ran it today), **read** (seen at the source: the package index, GitHub's own repository data, our code), **search** (seen only in a search result), **ours** (our own reasoning or choice).

## Question

Do we keep Watchtower's data in SQL, in SQLite as `app/schema.sql` already assumes, or in a dedicated graph database? The question comes from Q1: the recipe is a navigation graph, so should a graph database hold it?

## Decision

**SQLite, from Python's standard library. No graph database.** The recipe stays a graph in its model (Q1) and is stored as one JSON document per version in the `recipes` table, as `app/models.py` already has it; the runner loads it and walks it in memory.

We choose this for five reasons:

1. **Nearly everything we store is a table, and the API contract rests on relational guarantees.** Portals, runs, checks, steps, tenders and files are rows with keys. Three contract rules are SQL constraints in `app/schema.sql` today, and all three work (**measured**): a partial unique index allows one running read per portal, so a refresh can return that read's `runId`; `DELETE /portals/{id}` cascades through every table in 7 ms for a portal with 1,000 tenders; `changedSince` is served by an index in 1.4 ms over 50,000 tenders. A graph database would need each of these rebuilt in our code.
2. **The only graph we have is small and belongs to one portal.** A recipe of 40 nodes and 60 edges is 8 KB of JSON. Loading it and walking it in Python takes 0.15 ms (**measured**). No query crosses from one portal's graph into another's; the one link between recipes, a portal's documents held on another platform (Q1), is a lookup by key. Graph databases pay off on traversals of many hops through one large connected graph (**ours**); we have thousands of tiny separate ones.
3. **Reuse across portals is set similarity, not traversal.** Matching a new portal's structure fingerprint against 5,000 stored recipes takes 540 ms in Python over SQLite rows; finding the recipes of one software family takes 0.1 ms by index (**measured**). A graph query language adds nothing to a comparison of two sets.
4. **The embedded graph databases are not a safe dependency for a system that goes into production.** Kuzu is archived; its fork RyuGraph has not released in almost a year; FalkorDBLite is documented for development and testing; DuckDB's graph extension is still in development; Neo4j is a second server on the Java runtime. Details under Alternatives.
5. **SQLite costs nothing to add.** It ships with Python, so it adds no package to `pyproject.toml` and no layer to the image. The image's Ubuntu 24.04 carries SQLite 3.45.1 (**search**: Launchpad), which has the JSON functions built in (since 3.38) and the binary JSONB format (since 3.45) (**search**: sqlite.org).

## What we measured

`research/tools/q15_sqlite_bench.py` against `app/schema.sql` as it stands, unchanged: 50 portals with 1,000 tenders each, and 5,000 recipes of 40 nodes and 60 edges, about Patterno's number of portals. Results in `research/sources/q15-sqlite-bench.json`. Run on a team laptop with Python 3.14.9 and SQLite 3.54.0, not inside the image; every feature used exists in 3.45 (**measured**).

| What | Result |
| --- | --- |
| Insert 50,000 tenders, one transaction per portal | 0.62 s; 41 MB on disk |
| `GET /tenders?changedSince=` for one portal (300 of its 1,000 rows); the plan uses the index `tenders_changed` | 1.4 ms median, 2.8 ms p99 |
| A second running read for the same portal | Rejected: "UNIQUE constraint failed: runs.portal_id" |
| `DELETE` of a portal with 1,000 tenders and its recipes | 6.8 ms; no rows left behind |
| Load one recipe (8.1 KB JSON) and walk it in Python | 0.15 ms |
| The same walk in SQL: a recursive query over the JSON body | 3.2 ms; the same 40 nodes reached |
| Match one structure fingerprint against all 5,000 recipes | 540 ms |
| Find the recipes of one software family, by index | 0.1 ms |
| An API read while a writer commits 20 to 200 tender updates a second, one reader thread | 2.4 to 2.8 ms median, at most 5.1 ms p99; no lock errors |

At 1 request per second per portal, even 50 portals change fewer than 50 tenders a second, so the last row is above our real write load (**ours**).

### A trap: several threads reading in one process

With **no writer at all**, the same query (`research/tools/q15_threads_bench.py`, **measured**):

| Readers | Median | p99 |
| --- | --- | --- |
| 1 thread | 2.3 ms | 5.5 ms |
| 4 threads in one process | 130 ms | 177 ms |
| 4 threads, interpreter switch interval cut to 0.2 ms | 124 ms | 151 ms |
| 4 separate processes | 2.4 ms | 3.6 ms |

No read hit a lock error, and four processes are as fast as one thread, so SQLite's locking is not the cause: the slowdown comes from Python threads in one process taking turns. We did not pin down the exact mechanism; the likely one is that the `sqlite3` module releases and takes back Python's global interpreter lock for every row it steps through (**ours**). Any embedded database driven from Python threads would meet the same.

So `app/db.py` must not fan reads out over many threads in one process. FastAPI runs plain `def` handlers in a thread pool; ours should be `async def`, with every database call going through one database thread (or straight on the event loop, at 2 to 3 ms a query). The worker writes through its own single connection. Long scans, such as the fingerprint match, run in the worker, never in an API handler (**ours**).

## Alternatives, and why they lose here

| Option | What it is | Why it loses for this project |
| --- | --- | --- |
| **SQLite** (chosen) | Standard library; one file under `DATA_DIR`; WAL already switched on in `app/schema.sql` | |
| Neo4j Community | Graph server on the Java runtime, Cypher | A second server process in our one container, beside Chromium's 592 MB for two pages (Q6). Its cloud guidance lists 2 GB of memory as a minimum (**search**). Licensed GPL-3.0 (**read**: GitHub). Every contract rule above would move into our code. |
| Kuzu | Embedded graph database, Cypher, MIT | **Archived** on GitHub; last push and last release, 0.11.3, both on 10 October 2025 (**read**: GitHub, PyPI). No fixes from here on, in a system that goes into production. |
| RyuGraph, Ladybug | Forks of Kuzu | RyuGraph's last PyPI release is 25.9.2 of 6 December 2025 and its last push 20 January 2026, with 148 stars (**read**: PyPI, GitHub). Ladybug is said to be more active (**search**). Young forks of an abandoned engine, for a graph we do not need. |
| FalkorDBLite | FalkorDB inside a Python package: a Redis server with the graph module, run as a subprocess | Its documentation places it in development, testing and CI, and points production to server deployments (**search**). A 37.5 MB wheel that needs Python 3.12 or newer (**read**: PyPI 0.11.0, 19 Oct 2026). Another process to supervise. |
| DuckDB with DuckPGQ | An analytical database with the SQL/PGQ graph syntax from SQL:2023, as a community extension | The extension is "still under active development", and DuckDB's own pages disagree on which DuckDB release it works with (**search**). It is installed from the community repository, which means network at run time or extra build steps. DuckDB is built for analysis, and our load is many small writes. Wheel 24.9 MB (**read**: PyPI 2.0.1, released today). |
| SQLite with the recipe as rows of nodes and edges | Graph tables plus recursive queries | It works, but walking the recipe in SQL took 3.2 ms against 0.15 ms in Python (**measured**), and Q1's flat `nodes` and `edges` arrays map one to one onto a JSON document and onto the model's structured output. Edge tables are worth it only if we ever query across recipes. |
| PostgreSQL, with Apache AGE for graphs | A database server | A second process we do not need at this size. It is the natural move for Patterno's production (the same SQL), see below. |

The wider view agrees: Stonebraker and Pavlo's 2024 survey of data models finds that the relational model "continues to be the dominant data model and SQL has been extended to capture the good ideas from others" (**search**: SIGMOD Record, June 2024), graph syntax included through SQL/PGQ.

## Evidence

- **Our code** (**read**): `app/schema.sql` already sets `journal_mode = WAL` and `foreign_keys = ON`, and holds the partial unique index `runs_one_active_read`, the cascades and the index `tenders_changed`. `app/models.py` keeps `Recipe.body` as a dict and `Portal.timezone` on the portal.
- **SQLite in WAL mode** (**search**: sqlite.org/wal.html): "writers and readers can run at the same time. However, since there is only one WAL file, there can only be one writer at a time." A query "can return SQLITE_BUSY" in some obscure cases, so the code must handle it. Our runs saw none.
- **SQLite JSON** (**search**: sqlite.org): built in by default since 3.38.0 (February 2022); JSONB since 3.45.0.
- **SQLite in the image** (**search**: Launchpad): Ubuntu 24.04 ships `libsqlite3-0` 3.45.1, with security updates on that version.
- **Kuzu** (**read**: GitHub API and PyPI JSON, 20 Nov 2026): `archived: true`, last push 2025-10-10; release 0.11.3 uploaded 2025-10-10. Coverage of the shutdown: The Register, 14 Oct 2025 (**search**).
- **RyuGraph** (**read**: GitHub API and PyPI): last push 2026-01-20; latest release 25.9.2, 2025-12-06; 148 stars.
- **FalkorDBLite** (**read**: PyPI and GitHub): 0.11.0, 2026-10-19, wheel 37.5 MB, Python ≥3.12, last push 2026-11-19, 63 stars. Its role "for development and testing" and the subprocess model (**search**: docs.falkordb.com).
- **DuckDB and DuckPGQ** (**read**: PyPI) DuckDB 2.0.1 released 2026-11-20, wheel 24.9 MB; (**search**: duckdb.org) DuckPGQ "still under active development", compatibility notes that disagree.
- **Neo4j** (**read**: GitHub API) licence GPL-3.0; (**search**: neo4j.com operations manual) 2 GB memory minimum in the cloud guidance.

Not done: we did not install or benchmark any graph database. Nothing in the decision depends on how fast one is; it depends on what our queries are and what each option costs to run and to keep.

## What would change the decision

- **Questions that cross portals and need many hops**, for example a knowledge graph of buyers, platforms, tenders and companies for Patterno's matching product. That is outside this challenge. If it comes, it sits beside the store, not in place of it.
- **Recipes that share large subgraphs**, queried by pattern across thousands of portals. Then the edge tables above first, a graph engine second.
- **Patterno in production with many processes writing.** SQLite allows one writer at a time. The move is to PostgreSQL with the same tables, behind `app/db.py`; not to a graph database.

## Prototype first (about 1 hour)

`app/db.py` on `app/schema.sql`: one writer connection for the worker; reads through one database thread for the API; `async def` handlers; `PRAGMA busy_timeout` set and `SQLITE_BUSY` retried. Test it with the contract test while a mock read writes, and check the read latency stays near the single-thread figure.

## Effect on other questions

- **Q1 recipe model:** the graph is the model, JSON is the storage; nothing changes in the format.
- **Q7 schemas:** add a column on `recipes` for the structure fingerprint set (JSON), which the reuse match reads; today the benchmark had to borrow `rationale`. G2 (`app/db.py`) takes the threading rule above.
- **Q11 reuse:** the fingerprint match over all stored recipes runs in the worker (540 ms at 5,000 recipes), never in an API handler.
- **DESIGN.md:** the storage row cites Q15, and the worker rules gain the threading rule.

## Sources

Read or measured on 20 Nov 2026.

- Our benchmark: `research/tools/q15_sqlite_bench.py`, `q15_concurrency_bench.py`, `q15_threads_bench.py`; results in `research/sources/q15-sqlite-bench.json`
- SQLite, write-ahead logging: https://www.sqlite.org/wal.html ; JSON functions: https://www.sqlite.org/json1.html ; 3.38.0 release notes: https://www.sqlite.org/releaselog/3_38_0.html
- Ubuntu 24.04 SQLite package: https://launchpad.net/ubuntu/noble/+source/sqlite3
- Kuzu: https://github.com/kuzudb/kuzu (GitHub API), https://pypi.org/project/kuzu/0.11.3/ ; The Register, 14 Oct 2025: https://www.theregister.com/2025/10/14/kuzudb_abandoned/
- RyuGraph: https://github.com/predictable-labs/ryugraph , https://pypi.org/project/ryugraph/
- FalkorDBLite: https://pypi.org/project/falkordblite/ , https://docs.falkordb.com/operations/falkordblite/
- DuckPGQ: https://duckdb.org/community_extensions/extensions/duckpgq ; DuckDB on PyPI: https://pypi.org/project/duckdb/
- Neo4j: https://github.com/neo4j/neo4j ; system requirements: https://neo4j.com/docs/operations-manual/current/installation/requirements/
- Stonebraker and Pavlo, "What Goes Around Comes Around… And Around…", SIGMOD Record, June 2024: https://db.cs.cmu.edu/papers/2024/whatgoesaround-sigmodrec2024.pdf
