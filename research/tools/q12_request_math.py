"""Request math for Q12 (large portals) and Q13 (read schedule).

    python research/tools/q12_request_math.py

Every number in research/q12-large-portals.md comes from this file. Change a parameter
here, run it again, and paste the tables.

Model: one request may START per second per portal (RATE). A first attach reads the
list, then one detail page per tender, then the documents. Parameters marked MEASURED
were read from TenderNed's public API on 20 Nov 2026 (one portal; 40 tenders for files and
sizes, 1,551 for lifetimes).
"""

from math import ceil

RATE = 1.0  # request starts per second per portal (the challenge's limit)
SIZES = (100, 1_000, 5_000)

# name: (tenders per list page, detail requests per tender, extra requests to reach the
#        documents, download requests per tender, megabytes per tender)
SCENARIOS = {
    "HTML list, 3 files each (the team's first guess)": (20, 1, 0, 3, 20),
    "HTML list, 9 files each (MEASURED mean, 40 tenders)": (20, 1, 0, 9, 20),
    "API list of 100, one all-documents ZIP (MEASURED: TenderNed)": (100, 0, 1, 1, 20),
    "API list of 100, 9 files each": (100, 0, 1, 9, 20),
}


def hms(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def attach(n: int, per_page: int, detail: int, reach: int, files: int) -> tuple[int, int, int]:
    """Return (list requests, requests until every tender record is known, all requests)."""
    pages = ceil(n / per_page)
    records = pages + n * detail
    return pages, records, records + n * (reach + files)


def poll_interval(pages: int, floor: float = 120, share: float = 0.10, cap: float = 1800) -> float:
    """Seconds between list reads: list reading may use `share` of the request budget."""
    return min(cap, max(floor, pages / (share * RATE)))


def steady(n: int, per_page: int, per_new: int, lifetime_days: float, checks: int = 8,
           rotation_share: float = 0.20) -> dict:
    """Requests per hour once attached. Detail pages of known tenders are re-read in an
    even rotation that may use `rotation_share` of the budget, never more than all of
    them on every read."""
    pages = ceil(n / per_page)
    interval = poll_interval(pages)
    polls_per_hour = 3600 / interval
    rotation = min(rotation_share * 3600 * RATE, n * polls_per_hour)
    return {
        "pages": pages,
        "interval": interval,
        "list": pages * polls_per_hour,
        "checks": checks * polls_per_hour,
        "rotation": rotation,
        "all_details_reread_every": n / rotation * 3600,
        "new": n / lifetime_days / 24 * per_new,
        "worst_wrong_serving": interval + pages / RATE,
    }


def main() -> None:
    print("FIRST ATTACH at 1 request per second\n")
    for name, (per_page, detail, reach, files, megabytes) in SCENARIOS.items():
        print(name)
        print(f"  {'tenders':>8} {'requests':>9} {'all records known':>18} {'everything':>11} {'disk':>8}")
        for n in SIZES:
            _, records, total = attach(n, per_page, detail, reach, files)
            print(f"  {n:>8} {total:>9} {hms(records / RATE):>18} {hms(total / RATE):>11} {n * megabytes / 1000:>6.1f} GB")
        print()

    print("At a portal that allows 30 requests a minute (MEASURED: e-Zamowienia), double every time.\n")

    # TenderNed as it stood on 20 Nov 2026: 1,551 open tenders found in 77 list pages of 100.
    tenders, list_pages = 1551, 77
    by_zip = list_pages + tenders * 2
    by_file = list_pages + tenders * (1 + 9)
    print(f"WORKED EXAMPLE, TenderNed today: {tenders} open tenders; with its ZIP link {by_zip} requests = {hms(by_zip)}; "
          f"file by file {by_file} requests = {hms(by_file)}; about {tenders * 22.7 / 1000:.0f} GB of documents\n")

    print("STEADY STATE, HTML list of 20 per page, new tender costs 10 requests")
    print(f"  {'tenders':>8} {'list pages':>10} {'read every':>10} {'list/h':>7} {'checks/h':>8} "
          f"{'rotation/h':>10} {'new/h (50 d .. 8 d life)':>25} {'budget used':>12} {'worst wrong serving':>20} "
          f"{'every detail re-read within':>28}")
    for n in SIZES:
        slow = steady(n, 20, 10, 50)
        fast = steady(n, 20, 10, 8)
        low = slow["list"] + slow["checks"] + slow["rotation"] + slow["new"]
        high = fast["list"] + fast["checks"] + fast["rotation"] + fast["new"]
        print(f"  {n:>8} {slow['pages']:>10} {hms(slow['interval']):>10} {slow['list']:>7.0f} {slow['checks']:>8.0f} "
              f"{slow['rotation']:>10.0f} {slow['new']:>11.0f} .. {fast['new']:<10.0f} "
              f"{low / 36:>5.0f}%..{high / 36:<3.0f}% {hms(slow['worst_wrong_serving']):>20} "
              f"{hms(slow['all_details_reread_every']):>28}")
    print()

    print("READ INTERVAL by list length: max(2 min, 10 x the time the list takes), at most 30 min")
    for pages in (1, 5, 12, 25, 50, 100, 250):
        interval = poll_interval(pages)
        print(f"  {pages:>4} list pages -> every {hms(interval):>7}; list reading uses {pages / interval * 100:>4.1f}% of the budget")
    print()

    print("WHERE A FULL RE-READ EVERY TIME STOPS FITTING (list + detail + 9 files, 20 per page)")
    for minutes in (2, 5, 15):
        n = 0
        while attach(n + 1, 20, 1, 0, 9)[2] <= minutes * 60 * RATE:
            n += 1
        print(f"  inside {minutes:>2} minutes: up to {n} tenders")


if __name__ == "__main__":
    main()
