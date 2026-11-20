"""Q15 follow-up: API read latency while a writer commits, by writer pace and reader busy timeout.

Usage: python3 -I research/tools/q15_concurrency_bench.py <bench.db written by q15_sqlite_bench.py>
"""
import json
import random
import sqlite3
import statistics
import sys
import threading
import time

DB = sys.argv[1]
NOW = "2026-11-20T12:00:00+00:00"
Q = "SELECT * FROM tenders WHERE portal_id = ? AND last_changed_at > ? ORDER BY last_changed_at"


def run(pause_s, reader_timeout, seconds=4, batch=20, readers=4):
    stop = threading.Event()
    lat, busy, writes = [], [0], [0]

    def writer():
        w = sqlite3.connect(DB, timeout=30)
        i = 0
        while not stop.is_set():
            with w:
                w.executemany("UPDATE tenders SET last_seen_at=?, last_changed_at=? WHERE portal_id=? AND tender_id=?",
                              [(NOW, f"2026-11-20T12:{i % 60:02d}:00+00:00", f"p{i % 40:03d}", f"T{(i * batch + k) % 1000}")
                               for k in range(batch)])
            writes[0] += batch
            i += 1
            if pause_s:
                time.sleep(pause_s)

    def reader():
        r = sqlite3.connect(DB, timeout=reader_timeout)
        while not stop.is_set():
            t = time.perf_counter()
            try:
                r.execute(Q, (f"p{random.randrange(40):03d}", "2026-11-15T00:00:00+00:00")).fetchall()
                lat.append(time.perf_counter() - t)
            except sqlite3.OperationalError:
                busy[0] += 1

    ts = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(readers)]
    for t in ts:
        t.start()
    time.sleep(seconds)
    stop.set()
    for t in ts:
        t.join()
    lat.sort()
    return {"writer_pause_ms": pause_s * 1000, "reader_busy_timeout_s": reader_timeout,
            "updates_per_s": round(writes[0] / seconds), "reads": len(lat), "busy_errors": busy[0],
            "read_ms_median": round(statistics.median(lat) * 1000, 2) if lat else None,
            "read_ms_p99": round(lat[int(len(lat) * 0.99)] * 1000, 2) if lat else None}


results = [run(0, 30), run(0, 0), run(0.001, 30), run(0.1, 30), run(1.0, 30),
           run(0.1, 30, readers=1), run(1.0, 30, readers=1), run(0, 30, readers=1)]
print(json.dumps({"sqlite": sqlite3.sqlite_version, "runs": results}, indent=2))
