"""Which e-procurement software a portal runs (Q11, research/q11-reuse.md). No model call.

The answer fills `Portal.fingerprint` and picks the recipes worth trying before a cold learn.
It is a hint, never a key: the same `/NetServer/` path runs under two vendor brands, and
installations of one product differ per tenant. A reused recipe is trusted only after the
canary read, the full first read and a spot check (DESIGN.md, Reuse). This module only
proposes candidates.

Evidence is ordered by strength: host, then path, then brand text on the page. Candidates
come back strongest first; there is no numeric score (the Q11 review found the weights
unvalidated), and the structural canary is the trust boundary.

Not to be confused with `app.checks.skeleton.fingerprint`, the structure hash of one page (Q10).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from urllib.parse import urlsplit


class Evidence(IntEnum):
    """How a family was recognised. Higher is stronger."""

    brand = 1
    path = 2
    host = 3


@dataclass(frozen=True)
class Signature:
    family: str
    hosts: tuple[str, ...] = ()        # a host, or a parent domain the host ends with
    paths: tuple[str, ...] = ()        # regular expressions on the path and query
    brands: tuple[str, ...] = ()       # regular expressions on the page text (case-insensitive)


@dataclass(frozen=True)
class Candidate:
    family: str
    strength: Evidence
    reasons: tuple[str, ...] = field(default_factory=tuple)


# Seen in published notices, product pages or live pages (Q11 research and fact-check, 20 Nov 2026).
SIGNATURES: tuple[Signature, ...] = (
    Signature("cosinex-vmp", hosts=("dtvp.de", "vmp.nrw.de", "evergabe.nrw.de"),
              paths=(r"/(?:VMP)?Satellite/", r"projectForwarding\.do"),
              brands=(r"cosinex", r"Vergabemarktplatz")),
    Signature("ai-netserver", hosts=("vmstart.de", "tender24.de", "evergabe.de"),
              paths=(r"/NetServer/",),
              brands=(r"AI Vergabeplattform", r"AI BIETERCOCKPIT", r"Administration Intelligence")),
    Signature("subreport-elvis", hosts=("subreport-elvis.de", "subreport.de"), brands=(r"subreport\s+ELViS",)),
    Signature("deutsche-evergabe", hosts=("deutsche-evergabe.de",), brands=(r"Deutsche eVergabe",)),
    Signature("atexo-place", hosts=("marches-publics.gouv.fr",),
              paths=(r"[?&]page=[Ee]ntreprise\.",), brands=(r"\bPLACE\b", r"Atexo", r"Local Trust")),
    Signature("boamp", hosts=("boamp.fr", "boamp-datadila.opendatasoft.com")),
    Signature("placsp", hosts=("contrataciondelestado.es",),
              paths=(r"/wps/poc\?uri=deeplink:detalle_licitacion", r"sindicacion_\d+"),
              brands=(r"Plataforma de Contrataci[oó]n del Sector P[uú]blico",)),
    Signature("tenderned", hosts=("tenderned.nl",), paths=(r"/papi/tenderned-rs-tns/",), brands=(r"TenderNed",)),
    Signature("mercell", hosts=("mercell.com", "eu-supply.com", "negometrix.com", "tendsign.com"),
              brands=(r"\bMercell\b", r"Negometrix", r"EU-Supply")),
    Signature("e-zamowienia", hosts=("ezamowienia.gov.pl",), paths=(r"/mo-(?:client-)?board/",),
              brands=(r"e-Zam[oó]wienia",)),
    Signature("open-nexus", hosts=("platformazakupowa.pl",), brands=(r"platformazakupowa", r"Open Nexus")),
    Signature("vortal", hosts=("vortal.biz", "vortalgov.pt"), brands=(r"\bVORTAL(?:next)?\b",)),
    Signature("ted", hosts=("ted.europa.eu",), brands=(r"Tenders Electronic Daily",)),
)

_TAGS = re.compile(r"<script\b.*?</script>|<style\b.*?</style>|<[^>]+>", re.IGNORECASE | re.DOTALL)
_GENERATOR = re.compile(r"<meta[^>]+name=[\"']generator[\"'][^>]*content=[\"']([^\"']+)", re.IGNORECASE)


def _host_matches(host: str, wanted: str) -> bool:
    return host == wanted or host.endswith("." + wanted)


def page_text(html: str) -> str:
    """Visible text plus the generator meta tag, enough for brand matching."""
    generator = " ".join(_GENERATOR.findall(html))
    return f"{_TAGS.sub(' ', html)} {generator}"


def detect(url: str, html: str | None = None) -> list[Candidate]:
    """Software families this address (and, if given, its page) points to, strongest first."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    where = parts.path + ("?" + parts.query if parts.query else "")
    text = page_text(html) if html else ""
    found: list[Candidate] = []
    for sig in SIGNATURES:
        reasons: list[tuple[Evidence, str]] = []
        reasons += [(Evidence.host, f"host {h}") for h in sig.hosts if host and _host_matches(host, h)]
        reasons += [(Evidence.path, f"path /{p}/") for p in sig.paths if re.search(p, where)]
        if text:
            reasons += [(Evidence.brand, f"text /{b}/") for b in sig.brands if re.search(b, text, re.IGNORECASE)]
        if reasons:
            found.append(Candidate(sig.family, max(r[0] for r in reasons), tuple(r[1] for r in reasons)))
    return sorted(found, key=lambda c: (-c.strength, -len(c.reasons), c.family))


def best(url: str, html: str | None = None) -> str | None:
    """The family to store in `Portal.fingerprint`, or None when nothing or a tie at the top."""
    candidates = detect(url, html)
    if not candidates:
        return None
    top = candidates[0]
    ties = [c for c in candidates if c.strength == top.strength and len(c.reasons) == len(top.reasons)]
    return top.family if len(ties) == 1 else None
