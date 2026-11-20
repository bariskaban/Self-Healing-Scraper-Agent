"""Q15 follow-up: is the slow concurrent read SQLite or Python's GIL? No writer at all.

Usage: python3 -I research/tools/q15_threads_bench.py <bench.db written by q15_sqlite_bench.py>
"""
import json
import multiprocessing as mp
import random
import sqlite3
import statistics
import sys
import threading
import time

DB = sys.argv[1]
Q = "SELECT * FROM tenders WHERE portal_id = ? AND last_changed_at > ? ORDER BY last_changed_at"


def read_loop(seconds, out):
    r = sqlite3.connect(DB)
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        t = time.perf_counter()
        r.execute(Q, (f"p{random.randrange(40):03d}", "2026-11-15T00:00:00+00:00")).fetchall()
        out.append(time.perf_counter() - t)


def threads(n, seconds=3):
    lat = []
    ts = [threading.Thread(target=read_loop, args=(seconds, lat)) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return lat


def proc(seconds, q):
    lat = []
    read_loop(seconds, lat)
    q.put(lat)


def processes(n, seconds=3):
    q = mp.Queue()
    ps = [mp.Process(target=proc, args=(seconds, q)) for _ in range(n)]
    for p in ps:
        p.start()
    lat = [x for _ in ps for x in q.get()]
    for p in ps:
        p.join()
    return lat


def summary(name, lat):
    lat.sort()
    return {"case": name, "reads": len(lat), "ms_median": round(statistics.median(lat) * 1000, 2),
            "ms_p99": round(lat[int(len(lat) * 0.99)] * 1000, 2)}


if __name__ == "__main__":
    res = [summary("1 thread", threads(1)), summary("4 threads", threads(4))]
    sys.setswitchinterval(0.0002)
    res.append(summary("4 threads, GIL switch interval 0.2 ms", threads(4)))
    sys.setswitchinterval(0.005)
    res.append(summary("4 processes", processes(4)))
    print(json.dumps(res, indent=2))
