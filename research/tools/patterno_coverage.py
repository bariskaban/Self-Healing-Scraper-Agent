"""Read Patterno's public portal coverage pages and count portals per country and platform.

    python research/tools/patterno_coverage.py [folder with pages saved earlier]

Source: https://www.patterno.de/de/vergabe-portale/coverage and its 29 country pages.
One request per second, a client name that says what it is. The pages are public; this
script keeps counts only, not Patterno's list of addresses, and writes them to
research/sources/patterno-coverage.json.
"""

import collections
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.patterno.de/de/vergabe-portale/coverage"
CLIENT = "WatchtowerResearch/0.2 (hackathon research; one request per second)"
# Second-level suffixes under which organisations register, so that "x.com.pl" groups
# under "x.com.pl" and not under "com.pl".
SUFFIXES = {
    "com.pl", "gov.pl", "org.pl", "edu.pl", "net.pl", "waw.pl", "gov.it", "com.es", "gob.es",
    "co.uk", "gov.uk", "org.uk", "gv.at", "co.at", "or.at", "gov.gr", "com.gr", "gov.pt",
    "com.pt", "gouv.fr", "asso.fr", "gov.cz", "gov.sk", "gov.hu", "gov.ro", "gov.ie",
    "gov.mt", "gov.cy", "com.cy", "com.mt", "europa.eu",
}


def fetch(path: str, cache: Path | None) -> str:
    name = (path.strip("/") or "index") + ".html"
    if cache and (cache / name).exists():
        return (cache / name).read_text(encoding="utf-8", errors="replace")
    time.sleep(1.0)
    request = urllib.request.Request(BASE + path, headers={"User-Agent": CLIENT})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read().decode("utf-8", errors="replace")


def visible(page: str) -> str:
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def platform(host: str) -> str:
    labels = host.strip(".").split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def main() -> None:
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    index = fetch("", cache)
    countries = sorted(set(re.findall(r'href="/de/vergabe-portale/coverage/([a-z-]+)"', index)))
    stated = re.search(r"(\d+) Portale in (\d+) Ländern", visible(index))

    per_country, hosts_by_platform, all_hosts = {}, collections.Counter(), 0
    germany_types: collections.Counter = collections.Counter()
    for country in countries:
        text = visible(fetch("/" + country, cache))
        listing = re.search(r"(\d+) Portale? für [^.]+\. (.*?) Portal nicht dabei", text)
        if listing:  # a plain list of every portal address in the country
            hosts = [h for h in listing.group(2).split(" ") if "." in h.strip(".")]
            counts = collections.Counter(platform(h) for h in hosts)
            hosts_by_platform.update(counts)
            all_hosts += len(hosts)
            per_country[country] = {
                "portals": int(listing.group(1)),
                "platforms": len(counts),
                "largest": counts.most_common(6),
            }
            continue
        # Germany is shown differently: the top 100 by market share, tagged by software type.
        total = re.search(r"(\d+) Vergabeportale? in", text)
        top10 = re.search(r"Die Top 10 abdecken (\d+)%", text)
        rows = re.findall(r"#(\d+) ((?:[a-z0-9-]+(?:, )?)*?) ?[a-z0-9.-]+\.[a-z]{2,} (\d+,\d+)% Marktanteil", text)
        rows += [(rank, types, share) for rank, types, share in
                 re.findall(r"# (\d+) [a-z0-9.-]+\.[a-z]{2,} ((?:[a-z0-9-]+(?:, )?)*?) ?(\d+,\d+)%", text)]
        for _, types, share in rows:
            names = [t for t in types.split(", ") if t] or ["(no type given)"]
            for name in names:
                germany_types[name] += float(share.replace(",", ".")) / len(names)
        per_country[country] = {
            "portals": int(total.group(1)) if total else None,
            "top10_market_share_percent": int(top10.group(1)) if top10 else None,
            "ranked_portals_read": len(rows),
            "share_by_software_type_percent": {k: round(v, 1) for k, v in germany_types.most_common()},
        }

    ranked = hosts_by_platform.most_common()
    result = {
        "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": BASE,
        "stated_total": {"portals": int(stated.group(1)), "countries": int(stated.group(2))} if stated else None,
        "countries": per_country,
        "hosts_with_full_list": all_hosts,
        "distinct_platforms": len(ranked),
        "share_of_hosts_held_by_largest": {str(n): round(sum(c for _, c in ranked[:n]) / all_hosts * 100, 1) for n in (5, 10, 20, 50)},
        "single_host_platforms": sum(1 for _, c in ranked if c == 1),
        "largest_platforms": ranked[:25],
    }
    out = Path(__file__).resolve().parents[1] / "sources" / "patterno-coverage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("stated:", result["stated_total"])
    for country, info in sorted(per_country.items(), key=lambda kv: -(kv[1]["portals"] or 0))[:10]:
        print(f"  {country:<12} {info['portals']:>5} portals  {info.get('largest', '')}")
    print("hosts with a full list:", all_hosts, "| platforms:", len(ranked), "| single-host platforms:", result["single_host_platforms"])
    print("share of hosts held by the largest platforms:", result["share_of_hosts_held_by_largest"])
    print("Germany by software type:", list(germany_types.most_common(8)))
    print("wrote", out)


if __name__ == "__main__":
    main()
