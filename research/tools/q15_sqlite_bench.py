"""Q15 benchmark: can SQLite carry Watchtower's store, recipe graphs included?

Usage: python3 -I research/tools/q15_sqlite_bench.py app/schema.sql <scratch dir>
Standard library only. Prints one JSON object with every measurement.
"""
import json
import random
import sqlite3
import statistics
import sys
import threading
import time
from pathlib import Path

SCHEMA, WORK = Path(sys.argv[1]), Path(sys.argv[2])
WORK.mkdir(parents=True, exist_ok=True)
DB = WORK / "bench.db"
for suffix in ("", "-wal", "-shm"):
    Path(str(DB) + suffix).unlink(missing_ok=True)

random.seed(15)
NOW = "2026-11-20T12:00:00+00:00"
PORTALS, TENDERS_PER_PORTAL, RECIPES = 50, 1000, 5000
out = {"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
       "portals": PORTALS, "tenders": PORTALS * TENDERS_PER_PORTAL, "recipes": RECIPES}


def connect():
    con = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def ms(seconds):
    return round(seconds * 1000, 3)


con = connect()
con.executescript(SCHEMA.read_text())
out["journal_mode"] = con.execute("PRAGMA journal_mode").fetchone()[0]

# 1. Bulk insert: 50 portals x 1,000 tenders, one transaction per portal (one attach).
t0 = time.perf_counter()
for p in range(PORTALS):
    pid = f"p{p:03d}"
    with con:
        con.execute("INSERT INTO portals (id, url, url_key, state, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                    (pid, f"https://portal{p}.example", f"portal{p}.example", "serving", NOW, NOW))
        con.executemany(
            "INSERT INTO tenders (portal_id, tender_id, url, title, buyer_name, publication_date, submission_deadline,"
            " cpv_codes, first_seen_at, last_seen_at, last_changed_at, content_hash, raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(pid, f"T{t}", f"https://portal{p}.example/t/{t}", "Construction of a school building " * 2,
              "City of Example", "2026-11-01", "2026-12-15T10:00:00+01:00", json.dumps(["45000000", "45210000"]),
              NOW, NOW, f"2026-11-{1 + t % 20:02d}T{t % 24:02d}:00:00+00:00", f"h{t}", json.dumps({"row": "x" * 300}))
             for t in range(TENDERS_PER_PORTAL)])
out["insert_all_tenders_ms"] = ms(time.perf_counter() - t0)
out["db_size_mb_after_tenders"] = round(sum(Path(str(DB) + s).stat().st_size for s in ("", "-wal") if Path(str(DB) + s).exists()) / 1e6, 1)

# 2. GET /portals/{id}/tenders?changedSince=..., as the API asks it.
q = "SELECT * FROM tenders WHERE portal_id = ? AND last_changed_at > ? ORDER BY last_changed_at"
out["changed_since_plan"] = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + q, ("p007", "2026-11-15"))]
times = []
for _ in range(300):
    pid = f"p{random.randrange(PORTALS):03d}"
    t0 = time.perf_counter()
    rows = con.execute(q, (pid, "2026-11-15T00:00:00+00:00")).fetchall()
    times.append(time.perf_counter() - t0)
out["changed_since_rows"] = len(rows)
out["changed_since_ms_median"] = ms(statistics.median(times))
out["changed_since_ms_p99"] = ms(sorted(times)[int(len(times) * 0.99)])

# 3. One running read per portal, enforced by the partial unique index.
with con:
    con.execute("INSERT INTO runs (id, portal_id, kind, trigger, started_at, state_before) VALUES ('r1','p001','read','schedule',?, 'serving')", (NOW,))
try:
    with con:
        con.execute("INSERT INTO runs (id, portal_id, kind, trigger, started_at, state_before) VALUES ('r2','p001','read','refresh',?, 'serving')", (NOW,))
    out["second_active_read_rejected"] = False
except sqlite3.IntegrityError as e:
    out["second_active_read_rejected"] = str(e)

# 4. Recipe graphs at Patterno's scale: 5,000 recipes of 40 nodes and 60 edges, plus a
#    structure fingerprint (set of tag-and-class paths) per recipe for reuse matching (Q11, Q10 C7).
#    The schema has no column for that set yet, so `rationale` stands in for it here.
TAGS = [f"html>body>div.c{i}>table>tr>td.f{j}" for i in range(60) for j in range(40)]


def make_recipe(n_nodes=40, n_edges=60):
    nodes = [{"id": f"n{i}", "kind": random.choice(["http_html", "http_json", "documents", "browser_state"]),
              "fields": [{"field": "title", "locators": [{"kind": "css", "selector": f"td.f{i}"}]}]} for i in range(n_nodes)]
    edges = [{"from": f"n{i}", "to": f"n{i + 1}", "action": "follow_link"} for i in range(n_nodes - 1)]
    edges += [{"from": f"n{random.randrange(n_nodes)}", "to": f"n{random.randrange(n_nodes)}", "action": "next_page"}
              for _ in range(n_edges - len(edges))]
    return {"format": "recipe/v1", "nodes": nodes, "edges": edges}


t0 = time.perf_counter()
with con:
    for r in range(RECIPES):
        pid = f"p{r % PORTALS:03d}"
        fp = sorted(random.sample(TAGS, 300))
        con.execute("INSERT INTO recipes (portal_id, version, body_format, body, fingerprint, status, created_at, rationale)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (pid, r // PORTALS + 1, "recipe/v1", json.dumps(make_recipe()), f"family{r % 40}", "active", NOW,
                     json.dumps(fp)))
out["insert_recipes_ms"] = ms(time.perf_counter() - t0)
body = con.execute("SELECT body FROM recipes WHERE portal_id='p003' AND version=7").fetchone()[0]
out["recipe_json_bytes"] = len(body)

# 4a. Walk one recipe graph: Python in memory after json.loads (what the runner does).
t0 = time.perf_counter()
for _ in range(1000):
    rec = json.loads(con.execute("SELECT body FROM recipes WHERE portal_id='p003' AND version=7").fetchone()[0])
    adj = {}
    for e in rec["edges"]:
        adj.setdefault(e["from"], []).append(e["to"])
    seen, stack = {"n0"}, ["n0"]
    while stack:
        for nxt in adj.get(stack.pop(), []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
out["load_and_walk_one_recipe_us"] = round((time.perf_counter() - t0) / 1000 * 1e6, 1)
out["reachable_nodes"] = len(seen)

# 4b. The same walk inside SQL: a recursive CTE over the JSON body, no separate edge table.
cte = """
WITH RECURSIVE edges(src, dst) AS (
  SELECT json_extract(e.value, '$.from'), json_extract(e.value, '$.to')
  FROM recipes r, json_each(r.body, '$.edges') e WHERE r.portal_id = ? AND r.version = ?),
reach(node) AS (SELECT 'n0' UNION SELECT dst FROM edges JOIN reach ON src = node)
SELECT count(*) FROM reach"""
t0 = time.perf_counter()
for _ in range(1000):
    n = con.execute(cte, ("p003", 7)).fetchone()[0]
out["recursive_cte_walk_one_recipe_us"] = round((time.perf_counter() - t0) / 1000 * 1e6, 1)
out["recursive_cte_reachable_nodes"] = n

# 4c. Reuse matching: compare a new portal's fingerprint with all 5,000 stored ones (Jaccard).
new_fp = set(random.sample(TAGS, 300))
t0 = time.perf_counter()
best = max(((len(new_fp & (s := set(json.loads(fp)))) / len(new_fp | s), pid, v)
            for pid, v, fp in con.execute("SELECT portal_id, version, rationale FROM recipes")))
out["fingerprint_scan_all_recipes_ms"] = ms(time.perf_counter() - t0)

# 4d. Candidates by software family: an indexed lookup.
t0 = time.perf_counter()
for _ in range(1000):
    con.execute("SELECT portal_id, version FROM recipes WHERE fingerprint = ? AND status = 'active'", ("family7",)).fetchall()
out["family_lookup_us"] = round((time.perf_counter() - t0) / 1000 * 1e6, 1)

# 5. DELETE /portals/{id}: cascade through tenders, runs and recipes.
t0 = time.perf_counter()
with con:
    con.execute("DELETE FROM portals WHERE id = 'p049'")
out["delete_portal_cascade_ms"] = ms(time.perf_counter() - t0)
out["tenders_left_for_deleted_portal"] = con.execute("SELECT count(*) FROM tenders WHERE portal_id='p049'").fetchone()[0]

# 6. Concurrency: one writer updating tenders (a read in progress) while 4 API threads query.
stop = threading.Event()
lat, writes = [], [0]


def writer():
    w = connect()
    i = 0
    while not stop.is_set():
        with w:
            w.executemany("UPDATE tenders SET last_seen_at=?, last_changed_at=? WHERE portal_id=? AND tender_id=?",
                          [(NOW, f"2026-11-20T12:{i % 60:02d}:00+00:00", f"p{i % 40:03d}", f"T{(i * 20 + k) % 1000}") for k in range(20)])
        writes[0] += 20
        i += 1


def reader():
    r = connect()
    while not stop.is_set():
        t = time.perf_counter()
        r.execute(q, (f"p{random.randrange(40):03d}", "2026-11-15T00:00:00+00:00")).fetchall()
        lat.append(time.perf_counter() - t)


threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(4)]
for t in threads:
    t.start()
time.sleep(5)
stop.set()
for t in threads:
    t.join()
out["concurrent_seconds"] = 5
out["concurrent_tender_updates_per_s"] = round(writes[0] / 5)
out["concurrent_api_reads"] = len(lat)
out["concurrent_api_read_ms_median"] = ms(statistics.median(lat))
out["concurrent_api_read_ms_p99"] = ms(sorted(lat)[int(len(lat) * 0.99)])

print(json.dumps(out, indent=2))
