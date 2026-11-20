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
    Signature("cosinex-vmp", hosts=("dtvp.de", "vmp.nrw.de", "evergabe.nrw.de", "evergabe.blb.nrw.de"),
              paths=(r"/VMPSatellite(?:/|$)", r"/Satellite/notice/", r"projectForwarding\.do"),
              brands=(r"cosinex", r"Vergabemarktplatz")),
    Signature("ai-netserver", hosts=("vmstart.de", "tender24.de", "evergabe.de"),
              paths=(r"/NetServer/",),
              brands=(r"AI Vergabeplattform", r"AI BIETERCOCKPIT", r"Administration Intelligence")),
    Signature("subreport-elvis", hosts=("subreport-elvis.de", "subreport.de", "evergabemv.de"),
              brands=(r"subreport\s+ELViS",)),
    Signature("deutsche-evergabe", hosts=("deutsche-evergabe.de",), brands=(r"Deutsche eVergabe",)),
    Signature("atexo-place", hosts=("marches-publics.gouv.fr",),
              # No "PLACE" brand pattern: with case ignored it is the word "place" on any page.
              paths=(r"[?&]page=[Ee]ntreprise\.",), brands=(r"Atexo", r"Local Trust")),
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

_GENERATOR = re.compile(r"\bname\s*=\s*[\"']?generator\b", re.IGNORECASE)
_CONTENT = re.compile(r"\bcontent\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
_TAG_START = re.compile(r"[A-Za-z/!?]")
# Elements whose content is code, not page text, each with the pattern that ends it.
_SKIPPED = tuple((name, re.compile("</" + name, re.IGNORECASE)) for name in ("script", "style"))


def _named(tag: str, name: str) -> bool:
    """Whether the inside of a tag starts with this element name, in any case."""
    return tag[:len(name)].lower() == name and not tag[len(name):len(name) + 1].isalnum()


def _host_matches(host: str, wanted: str) -> bool:
    return host == wanted or host.endswith("." + wanted)


def page_text(html: str) -> str:
    """Visible text plus the generator meta tag, enough for brand matching.

    One pass with `str.find`, so the time grows with the page and no faster: a regular
    expression over the whole page took 45 s on 320 KB of unclosed `<script ` (measured).
    Comments, tags, scripts and styles are left out; one that never closes drops the rest.
    """
    out: list[str] = []
    pos = 0
    while True:
        start = html.find("<", pos)
        if start < 0:
            out.append(html[pos:])
            break
        if not _TAG_START.match(html, start + 1):    # a bare "<" in the text, as in "a < b"
            out.append(html[pos:start + 1])
            pos = start + 1
            continue
        out.append(html[pos:start])
        if html.startswith("<!--", start):
            end = html.find("-->", start + 4)
            pos = end + 3
        else:
            end = html.find(">", start)
            pos = end + 1
            tag = html[start + 1:end] if end >= 0 else ""
            closing = next((c for n, c in _SKIPPED if _named(tag, n)), None)
            if closing:
                found = closing.search(html, pos)
                end = pos = found.start() if found else -1
            elif _named(tag, "meta") and _GENERATOR.search(tag):
                content = _CONTENT.search(tag)
                if content:
                    out.append(" " + (content.group(1) or content.group(2) or ""))
        if end < 0:
            break
        out.append(" ")
    return "".join(out)


def detect(url: str, html: str | None = None) -> list[Candidate]:
    """Software families this address (and, if given, its page) points to, strongest first."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:              # an address urlsplit refuses, such as "https://[::1/": nothing to match
        return []
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
    """The family to store in `Portal.fingerprint`, or None when nothing or a tie at the top.

    Two families tie when their strongest evidence is of the same kind. How many patterns
    matched does not break the tie: two names of one product are not two pieces of evidence.
    """
    candidates = detect(url, html)
    if not candidates:
        return None
    top = candidates[0]
    ties = [c for c in candidates if c.strength == top.strength]
    return top.family if len(ties) == 1 else None
