# Watchtower

Watchtower attaches to a public procurement portal it has never seen, learns once how to read it, and then keeps an up-to-date list of its open tenders and their documents. After the first learn it reads the portal on a schedule with **no model call**. It notices when the portal stops delivering correctly, and it repairs itself. Built for the Patterno track of the MAIN AI Hackathon 2026.

One Docker container serves a JSON API and an operator dashboard on port 8080.

How it was tested, the results with their uncertainty, and why each design decision was taken: [`docs/REPORT.md`](docs/REPORT.md).

## Run it

You need Docker, or Python 3.11 or newer. You need an OpenAI key only to let the system learn real portals.

### With Docker

```sh
docker build -t watchtower .
docker run -p 8080:8080 -e OPENAI_API_KEY=sk-... -v "$PWD/data:/data" watchtower
```

Open <http://localhost:8080> for the dashboard. The image is `linux/amd64`. Records and downloaded files go to `/data`, so keep that volume to keep them across restarts.

The container reads **real** portals. Do not point it at a portal you have no right to read.

### Add a portal

```sh
curl -X POST http://localhost:8080/portals -H 'Content-Type: application/json' \
     -d '{"url": "https://portal.example/tenders"}'
# {"id": "..."}   the attach runs in the background
curl http://localhost:8080/portals                 # state and reason of every portal
curl http://localhost:8080/portals/ID/tenders      # the tenders it holds
```

A new portal is `integrating` while it is attached. Then it is `serving`. Without `OPENAI_API_KEY` only the built-in mock portal (`http://localhost:8080/mock`) can be attached.

### Try it with no key and no network

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -e . --group dev
python -m mock_portal.demo        # http://127.0.0.1:8791
```

The demo runs the real app on a fake portal inside the same process. Nothing leaves your machine. In a second terminal:

```sh
curl -X POST http://127.0.0.1:8791/portals -H 'Content-Type: application/json' -d '{"url": "https://mock.example"}'
curl -X POST http://127.0.0.1:8791/demo/layout        # the fake portal changes its layout
curl -X POST http://127.0.0.1:8791/demo/login-wall    # another fake portal puts a login in front of everything
curl -X POST http://127.0.0.1:8791/demo/reset         # both work again
```

The layout change is repaired by the model, so that step needs `OPENAI_API_KEY`. The login wall needs nothing: it is never bypassed, and the portal ends `failed` with that reason.

### Run without Docker

```sh
DATA_DIR=./data OPENAI_API_KEY=sk-... uvicorn app.main:app --port 8080
```

Without `DATA_DIR` the records live in memory and nothing is read. `FETCH_MODE` defaults to `replay` outside Docker, so nothing reaches a live portal by accident. Set `FETCH_MODE=live` to read real portals.

### Tests

```sh
pytest                                                          # unit tests; no network, no model call
CONTRACT_BASE_URL=http://localhost:8080 pytest tests/contract   # the API contract, against a running app
```

### The dashboard

`GET /` serves a built React page that is committed in `app/dashboard/static/`. To change it, edit `dashboard/`, then:

```sh
cd dashboard && bun install --frozen-lockfile && bun run test && bun run build
```

and replace `app/dashboard/static/` with `dashboard/dist/`. Open `/?demo` to see the page with its bundled demo data and no server.

## Settings

All settings are environment variables. These are the ones you are likely to need.

| Variable | Default | What it does |
| --- | --- | --- |
| `OPENAI_API_KEY` | not set | Turns on learning, repair and the spot check. Never commit it or write it to a log. |
| `MODEL_LEARN`, `MODEL_REPAIR`, `MODEL_CHECK` | `gpt-6.2-sol`, `gpt-6.2-sol`, `gpt-6-luna` | The model for each job |
| `EUR_PER_USD` | `0.9114` | Rate for showing costs in euros. The default is the rate of 21 Nov 2026. |
| `DATA_DIR` | not set (`/data` in Docker) | Where SQLite and the files live |
| `FETCH_MODE` | `replay` (`live` in Docker) | `live`, `record` or `replay` |
| `READ_INTERVAL_SECONDS` | `120` | The shortest gap between two reads of a portal |
| `ATTACH_TIME_LIMIT_SECONDS` | `1200` | How long a first attach may run before it publishes what it has |
| `IGNORE_ROBOTS_TXT` | off | For testing only |
| `LOG_LEVEL` | `info` | `debug` shows every request, check, decision and state change. `LOG_FILE` also writes to a file. The container logs JSON. |
| `AGENT_LEARN_MAX_USD`, `AGENT_REPAIR_MAX_USD` | `5.0`, `2.5` | Spending cap for one learn and for one repair |
| `AGENT_MAX_CONCURRENT_RUNS` | `2` | How many learns, repairs and spot checks call the model at once. The others wait their turn. Raise it on a key with a high rate limit. |
| `AGENT_RATE_LIMIT_WAIT_BUDGET_SECONDS` | `90` | How long one model call waits when OpenAI answers "rate limit" before the run gives up |
| `READ_THREADS` | `64` | How many portals can be in a read at the same moment |
| `RECIPE_MAX_TENDERS_PER_PORTAL` | `500` | The most tenders read from one portal; `0` means no limit. A portal that lists more delivers its first 500 (the newest, where it lists newest first), its reason says "Stopped at the limit", and no tender is closed for being past the limit. Why 500: each tender costs at least one request at one request a second, so 500 are delivered in 10 to 30 minutes (measured: 17 minutes on a portal that needs two requests per tender) and 4,000 take over an hour. It can also be changed on the dashboard (Settings). More in `docs/BACKLOG.md`. |

Many more numbers are settings too, each with a prefix per area: `AGENT_`, `RECIPE_`, `CHECKS_`, `DOCS_`, `FETCH_`, `EXTRACT_`. The defaults are in `app/*/settings.py`. A request to one portal is never sent faster than once a second unless `FETCH_REQUESTS_PER_SECOND` says so; leave it alone for real portals.

## How it works

1. **Attach.** `POST /portals` stores the portal and starts a first read. A model explores the portal with tools and writes a **recipe**: a typed description of where the list, the tender pages and the documents are and how to read them. A recipe is accepted only when a dry run on the pages it saw gives sensible tenders.
2. **Read.** On every scheduled read the recipe is run with no model call. It reads the list page by page, then each tender's page and its documents. ZIP files are unpacked, and files are stored under their SHA-256. A file over 250 MB may be left out.
3. **Notice.** A set of checks judges every read: did the portal answer, did the list arrive, are the values plausible, did the files download. A first failure is looked at a second time before anything is decided.
4. **Repair.** If the portal's layout changed, a model gets the old recipe and the failed checks and changes as little as it can. The new recipe is verified with a full read before it replaces the old one. The last good tenders stay served meanwhile.
5. **Give up gracefully.** A login or captcha wall is never bypassed: the portal is `failed` and the reason says so. A portal that does not answer is `failed` with the cause `outage` and is tried again, first within minutes, then less often.

The four states: `integrating` (being attached), `serving` (delivering correctly), `healing` (a repair is running; the last good tenders are still served), `failed` (cannot deliver; the `cause` says whether a person is needed).

Every request goes through one network layer that sends at most one request a second to a portal, obeys robots.txt, slows down when a portal asks, and can record and replay traffic.

## What one portal costs

Measured on the development key with `gpt-6.2-sol` on 18 real test portals. These are single runs, not averages over many.

| | Cost |
| --- | --- |
| Learning a portal (11 of the 18 were learned) | $0.37 to $0.86, median $0.62; 10 to 36 requests |
| One repair after a change | $0.07 to $0.25 |
| A regular read | $0 (no model call) |

A learn is paid once per portal. A repair is paid only when a portal changes. A repair that needs a second, full learn cost $1.13 in the one measured case. The system stops a learn at `AGENT_LEARN_MAX_USD` and a repair at `AGENT_REPAIR_MAX_USD`.

Not every portal can be learned: three forbid reading in their robots.txt, one is behind a bot wall, and two keep their paging in the server's session. The system says so and stops after a few calls.

## The API

| Call | Answer |
| --- | --- |
| `POST /portals` `{"url"}` | 201 `{"id"}` at once; the attach runs in the background. The same address gives the same id. |
| `GET /portals`, `GET /portals/{id}` | `id`, `url`, `state`, `reason`, `tenderCount`, `lastSuccessAt` |
| `DELETE /portals/{id}` | 204; the portal stops being read within a minute |
| `POST /portals/{id}/refresh` | 202 `{"runId"}`; the running read's id if one is running |
| `GET /portals/{id}/tenders[?changedSince=]` | A JSON array of tenders, each with its documents |
| `GET /portals/{id}/runs` | Every read and repair of the portal |
| `GET /files/{id}` | The bytes of one document |
| `GET /` | The dashboard |

`GET /api/dashboard`, `GET /api/portals/{id}/timeline` and `POST /api/settings` are extra routes for the dashboard, described in `docs/DASHBOARD_API.md`. Interactive docs are at `/api-docs`.

## Where things are

```
app/            the application: API (main.py), read loop, one read (reader.py), checks, state rules,
                recipe executor (recipe/), network layer (fetch/), documents (docs/), agents (agent/)
dashboard/      source of the dashboard; the build is in app/dashboard/static/
mock_portal/    the fake portal we break on purpose, and the demo server
variants/       made-up portals for trying the learner, and a runner for real test portals
bench/          the list of real test portals
tests/          unit tests, one folder per module, and the contract test
DESIGN.md       the design, with the research question behind each decision
research/       the research answers and the measurements they stand on
docs/REPORT.md  how it was tested, the results, and why each decision was taken
CHECKME.md      the team's guide and status checklist
CLAUDE.md, CONVENTIONS.md   the rules the AI agents that wrote this code follow
```

## Limits, and why each is there

Each limit below is a choice we made on purpose, or a boundary the system reports instead of guessing past. In every case the portal's state and reason say what happened.

- **A large portal delivers its first 500 tenders.** Every request to a portal waits one second, as the brief asks, so reading thousands of tenders would leave a portal `integrating` for an hour or more. With the limit, two national portals we tested (TenderNed, e-Zamowienia) delivered 500 tenders with their fields in 17 and 25 minutes; without it one delivered nothing. Portals with fewer than 500 tenders are read in full. The limit is one setting, on the dashboard and in the environment.
- **A big first read takes minutes, not seconds.** That is the price of one request a second and of obeying robots.txt. Tenders are delivered as soon as they are validated; documents follow, soonest deadlines first.
- **Pages that only a script builds are read through the JSON call behind them.** Where a portal has such a call, the learner finds it and uses it (TenderNed and e-Zamowienia are read this way). There is no live browser yet, so a page with no such call is reported as not readable.
- **A portal that keeps its paging in the server's session is not read.** The reader sends plain, stateless requests, which is what makes regular reads cheap and repeatable. The learner sees this early, stops, and says so.
- **A portal with no open tenders today is not learned.** A recipe counts only once it has read real tenders: we would rather wait than store a recipe nobody has checked.
- **"Correct" on a real portal means the same as the recipe's own first read.** We had no hand-labelled truth for real portals. On made-up portals with a known truth, every field of 234 tenders was right. `docs/REPORT.md` gives every result with its interval.
- **The API has no authentication, as the track description says.** `POST /api/settings` can turn robots.txt off for testing, so do not expose a judging container to people you do not trust.

What reading all of a giant portal would take, and why we did not build it in the last hours, is in `docs/BACKLOG.md`.
