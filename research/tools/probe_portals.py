"""Record what a plain client sees on public procurement portals.

Run this from a laptop on a normal network (the cloud research session cannot reach
several of these sites):

    python research/tools/probe_portals.py

It writes research/sources/portal-probe.json. Commit that file; the research on
failure rules (Q10) and large portals (Q12) reads it.

What it does: one GET per URL, at most one request per second per host, no logins,
no retries, and a client name that says what it is. It never tries to get past a
block. A block is the finding we want to record.
"""

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Candidate portals. Add the ones in our test set; remove any we should not touch.
URLS = [
    "https://patterno.de/de/vergabe-portale",
    "https://www.dtvp.de/",
    "https://www.evergabe.de/",
    "https://evergabe.nrw.de/VMPSatellite",
    "https://vergabe.vmstart.de/NetServer",
    "https://www.subreport.de/",
    "https://ted.europa.eu/en/",
    "https://www.tenderned.nl/papi/tenderned-rs-tns/v2/publicaties?page=0&size=1",
    "https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseAdvancedSearch&AllCons",
    "https://www.boamp.fr/",
    "https://contrataciondelestado.es/wps/portal/plataforma",
    "https://ezamowienia.gov.pl/",
    "https://platformazakupowa.pl/",
]

CLIENT = "WatchtowerProbe/0.1 (hackathon research; one request per page)"
KEEP = [
    "server", "content-type", "content-length", "www-authenticate", "retry-after",
    "location", "cf-mitigated", "x-amzn-waf-action", "etag", "last-modified",
]
# Markers that a captcha or bot wall is present in the page. Presence is not a block.
MARKERS = {
    "recaptcha": r"google\.com/recaptcha|g-recaptcha",
    "hcaptcha": r"hcaptcha\.com|h-captcha",
    "turnstile": r"challenges\.cloudflare\.com|cf-turnstile",
    "friendly_captcha": r"frc-captcha|friendlycaptcha",
    "altcha": r"altcha",
    "aws_waf": r"awswaf|aws-waf-token",
    "datadome": r"datadome|captcha-delivery\.com",
    "incapsula": r"_Incapsula_Resource|incapsula",
    "password_field": r"type=[\"']?password",
}


def probe(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": CLIENT, "Accept": "*/*"})
    started = time.monotonic()
    row: dict = {"url": url}
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(2_000_000)
            row.update(status=response.status, final_url=response.geturl())
            headers = response.headers
    except urllib.error.HTTPError as error:
        body = error.read(200_000)
        row.update(status=error.code, final_url=error.geturl())
        headers = error.headers
    except Exception as error:  # DNS, TLS, timeout: an outage as far as we can tell
        row.update(status=None, error=f"{type(error).__name__}: {error}")
        row["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        return row
    text = body.decode("utf-8", errors="replace")
    title = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)
    row.update(
        elapsed_ms=round((time.monotonic() - started) * 1000),
        bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        headers={name: headers.get(name) for name in KEEP if headers.get(name)},
        cookie_names=sorted({c.split("=", 1)[0].strip() for c in headers.get_all("set-cookie") or []}),
        title=" ".join(title.group(1).split())[:160] if title else None,
        markers=sorted(name for name, pattern in MARKERS.items() if re.search(pattern, text, flags=re.I)),
    )
    return row


def main() -> None:
    last_call: dict[str, float] = {}
    rows = []
    for url in URLS:
        host = urlparse(url).netloc
        wait = 1.0 - (time.monotonic() - last_call.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        last_call[host] = time.monotonic()
        row = probe(url)
        print(row.get("status"), url, row.get("markers", row.get("error", "")))
        rows.append(row)
    out = Path(__file__).resolve().parents[1] / "sources" / "portal-probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"probed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "client": CLIENT, "results": rows},
        indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
