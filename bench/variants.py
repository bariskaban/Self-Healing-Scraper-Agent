"""Made-up portals for trying the learner: the mock portal's tenders, shown the way other portals show theirs.

None of these exists. Each one takes a trait we saw on a real portal family (research/q04-page-
views-measured.md, research/q08-test-portals.md) and builds it from the mock portal's seed data,
so the truth is exact and no request leaves the process (CLAUDE.md: no live portals):

  json_api       an app shell with no rows; the list and the tenders come from a JSON API a script names
  de_netserver   German labels; rows carry only `data-oid`, no link; the tender page is found by that id
  pl_offset      Polish labels; offset paging; ISO-like dates; the id is a number in the address
  fr_cards       French labels; cards; dates with month names ("12 mars 2027 à 10:00")
  it_detail      Italian labels; the list has no deadline, only the tender's page has; `?p=` paging
  docs_page      everything on one page, no total; a tender's files are on a page of their own
  login_wall     every page leads to a login: the learner should give up, cheaply
  empty          the list says there are no tenders: nothing to learn from

`VARIANTS[name]()` gives a `Variant`; `respond` answers a request, `truth` is what a correct read gives.
Run them with `python -m bench.run_variants` (a person, with the development key).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape
from urllib.parse import parse_qsl, urlsplit

from mock_portal.data import Tender, make_tenders

Answer = tuple[int, dict[str, str], bytes]
HTML = {"Content-Type": "text/html; charset=utf-8"}
JSON = {"Content-Type": "application/json"}
FR_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]
WORDS = {
    "de": {"Open procedure": "Offenes Verfahren", "Restricted procedure": "Nicht offenes Verfahren",
           "Negotiated procedure": "Verhandlungsverfahren", "Competitive dialogue": "Wettbewerblicher Dialog",
           "Works": "Bauleistung", "Services": "Dienstleistung", "Supplies": "Lieferleistung"},
    "pl": {"Open procedure": "Przetarg nieograniczony", "Restricted procedure": "Przetarg ograniczony",
           "Negotiated procedure": "Negocjacje z ogłoszeniem", "Competitive dialogue": "Dialog konkurencyjny",
           "Works": "Roboty budowlane", "Services": "Usługi", "Supplies": "Dostawy"},
    "fr": {"Open procedure": "Appel d'offres ouvert", "Restricted procedure": "Appel d'offres restreint",
           "Negotiated procedure": "Procédure avec négociation", "Competitive dialogue": "Dialogue compétitif",
           "Works": "Travaux", "Services": "Services", "Supplies": "Fournitures"},
    "it": {"Open procedure": "Procedura aperta", "Restricted procedure": "Procedura ristretta",
           "Negotiated procedure": "Procedura negoziata", "Competitive dialogue": "Dialogo competitivo",
           "Works": "Lavori", "Services": "Servizi", "Supplies": "Forniture"},
}
PROCEDURE = {"Open procedure": "open", "Restricted procedure": "restricted", "Negotiated procedure": "negotiated",
             "Competitive dialogue": "other"}
NATURE = {"Works": "works", "Services": "services", "Supplies": "supplies"}


@dataclass
class Variant:
    name: str
    base_url: str
    what: str                                   # the trait it tests, one line
    tenders: list[Tender]
    route: Callable[["Variant", str, dict[str, str]], Answer | None]
    ident: Callable[[Tender], str] = lambda t: t.id
    tender_url: Callable[[Tender], str] = lambda t: f"/tenders/{t.id}"
    expect: str = "serve"                       # serve | give_up
    requests: list[tuple[str, str]] = field(default_factory=list)

    def respond(self, method: str, url: str, form: dict[str, str] | None = None) -> Answer:
        parts = urlsplit(url)
        self.requests.append((method.upper(), parts.path + (f"?{parts.query}" if parts.query else "")))
        if parts.path == "/robots.txt":
            return 200, {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /\n"
        for tender in self.tenders:  # every variant serves its files the same way
            for file in tender.files:
                if parts.path == f"/files/{self.ident(tender)}/{file.name}":
                    return 200, {"Content-Type": file.content_type}, file.body
        answer = self.route(self, parts.path or "/", dict(parse_qsl(parts.query)))
        return answer or (404, HTML, _page("Not found", "<p>Not found</p>"))

    def truth(self) -> list[dict]:
        if self.expect != "serve":
            return []
        return [{"id": self.ident(t), "url": self.base_url + self.tender_url(t), "title": t.title,
                 "buyer_name": t.buyer_name, "publication_date": t.publication_date,
                 "submission_deadline": t.submission_deadline, "reference_number": t.reference_number,
                 "cpv_codes": [code.split("-")[0] for code in t.cpv], "procedure_type": PROCEDURE[t.procedure_word],
                 "contract_nature": NATURE[t.nature_word], "documents": len(t.files)} for t in self.tenders]


def _page(title: str, body: str, lang: str = "en", head: str = "") -> bytes:
    return (f'<!doctype html>\n<html lang="{lang}"><head><meta charset="utf-8"><title>{escape(title)}</title>{head}'
            f'</head>\n<body>\n{body}\n</body></html>\n').encode("utf-8")


def _newest(v: Variant) -> list[Tender]:
    return sorted(v.tenders, key=lambda t: -t.number)


def _files(v: Variant, t: Tender, item: str = '<li><a class="doc" href="{href}">{name}</a> <span class="sz">{size} B</span></li>') -> str:
    return "".join(item.format(href=f"/files/{v.ident(t)}/{f.name}", name=escape(f.name), size=f.size) for f in t.files)


# -- json_api --------------------------------------------------------------------------------

def _json_api(v: Variant, path: str, query: dict[str, str]) -> Answer | None:
    def short(t: Tender) -> dict:
        return {"noticeId": t.id, "title": t.title, "buyer": {"name": t.buyer_name},
                "publishedOn": t.publication_date.isoformat(), "deadline": t.submission_deadline.isoformat(),
                "contractType": t.nature_word.upper(), "link": f"/notice/{t.id}"}

    if path in ("/", "/notices") or path.startswith("/notice/"):
        return 200, HTML, _page("Notices", '<div id="app-root"></div>\n<script src="/static/app.4f2a.js"></script>')
    if path == "/static/app.4f2a.js":
        script = ('(function(){var API="/api/v2";function load(p){return fetch(API+"/notices?page="+p+"&size=20")'
                  '.then(function(r){return r.json()})}function one(id){return fetch(API+"/notices/"+id)}'
                  'load(0).then(render)})();')
        return 200, {"Content-Type": "application/javascript"}, script.encode()
    if path == "/api/v2/notices":
        size, page = min(int(query.get("size", 20)), 100), int(query.get("page", 0))
        rows = _newest(v)
        part = rows[page * size:(page + 1) * size]
        body = {"totalElements": len(rows), "page": page, "size": size, "last": (page + 1) * size >= len(rows),
                "content": [short(t) for t in part]}
        return 200, JSON, json.dumps(body).encode()
    if path.startswith("/api/v2/notices/"):
        t = next((t for t in v.tenders if t.id == path.rsplit("/", 1)[1]), None)
        if t is None:
            return 404, JSON, b'{"error":"not found"}'
        body = {**short(t), "reference": t.reference_number, "description": t.description,
                "procedure": {"code": t.procedure_word.upper().replace(" ", "_"), "label": t.procedure_word},
                "cpv": [{"code": code} for code in t.cpv], "place": {"postalCode": t.postal_code, "city": t.city},
                "documents": [{"fileName": f.name, "url": f"/files/{t.id}/{f.name}", "sizeBytes": f.size}
                              for f in t.files]}
        return 200, JSON, json.dumps(body).encode()
    return None


# -- de_netserver ----------------------------------------------------------------------------

def _oid(t: Tender) -> str:
    return f"54321-{0x18a00 + t.number * 37:x}"


def _de(v: Variant, path: str, query: dict[str, str]) -> Answer | None:
    w = WORDS["de"]
    if path in ("/", "/NetServer/"):
        return 200, HTML, _page("Vergabeplattform", '<ul id="nav"><li><a href="/NetServer/PublicationSearchControllerServlet'
                                '?function=SearchPublications&Category=InvitationToTender">Ausschreibungen</a></li>'
                                '<li><a href="/NetServer/Help">Hilfe</a></li></ul>', "de")
    if path == "/NetServer/PublicationSearchControllerServlet":
        rows = "".join(
            f'<tr class="tableRow clickable-row publicationDetail" data-oid="{_oid(t)}" data-category="InvitationToTender">'
            f'<td>{t.publication_date:%d.%m.%Y}</td><td>{t.submission_deadline:%d.%m.%Y %H:%M} Uhr</td>'
            f'<td class="tender">{escape(t.title)}</td><td>{w[t.nature_word]}</td><td class="tenderAuthority">'
            f'{escape(t.buyer_name)}</td></tr>\n' for t in _newest(v))
        table = ('<h1>Aktuelle Ausschreibungen</h1>\n<table class="table" id="publicationList"><thead><tr><th>Veröffentlicht</th>'
                 '<th>Angebotsfrist</th><th>Kurzbezeichnung</th><th>Typ</th><th>Vergabestelle</th></tr></thead>\n<tbody>'
                 f'{rows}</tbody></table>\n<p class="hits">{len(v.tenders)} Treffer</p>')
        return 200, HTML, _page("Ausschreibungen", table, "de")
    if path == "/NetServer/PublicationControllerServlet" and query.get("function") == "Detail":
        t = next((t for t in v.tenders if _oid(t) == query.get("TOID")), None)
        if t is None:
            return None
        facts = [("Vergabenummer", t.reference_number), ("Vergabestelle", t.buyer_name),
                 ("Veröffentlicht am", f"{t.publication_date:%d.%m.%Y}"),
                 ("Angebotsfrist", f"{t.submission_deadline:%d.%m.%Y %H:%M} Uhr"),
                 ("Verfahrensart", w[t.procedure_word]), ("Leistungsart", w[t.nature_word]),
                 ("CPV-Codes", ", ".join(t.cpv)), ("Erfüllungsort", f"{t.postal_code} {t.city}")]
        body = (f'<h1 class="color-main">{escape(t.title)}</h1>\n<div class="tenderDetails">'
                + "".join(f'<div class="row"><div class="label">{k}:</div><div class="value">{escape(val)}</div></div>\n'
                          for k, val in facts)
                + f'</div>\n<h2>Beschreibung</h2><div class="descr"><p>{escape(t.description)}</p></div>\n'
                  f'<h2>Vergabeunterlagen</h2><ul class="downloads">{_files(v, t)}</ul>')
        return 200, HTML, _page(t.title, body, "de")
    return None


# -- pl_offset ------------------------------------------------------------------------------

def _num(t: Tender) -> str:
    return str(700100 + t.number)


def _pl(v: Variant, path: str, query: dict[str, str]) -> Answer | None:
    w = WORDS["pl"]
    if path in ("/", "/postepowania"):
        rows, start, size = _newest(v), int(query.get("start", 0)), 20
        cards = "".join(
            f'<article class="postepowanie"><h2><a href="/postepowanie/{_num(t)}">{escape(t.title)}</a></h2>'
            f'<p class="zamawiajacy">Zamawiający: <b>{escape(t.buyer_name)}</b></p>'
            f'<p class="daty">Data publikacji: <span class="pub">{t.publication_date:%Y-%m-%d}</span> | '
            f'Termin składania ofert: <span class="termin">{t.submission_deadline:%Y-%m-%d %H:%M}</span></p>'
            f'<p class="nr">Numer: {_num(t)}</p></article>\n' for t in rows[start:start + size])
        nxt = (f'<a class="nastepna" href="/postepowania?start={start + size}">następna »</a>'
               if start + size < len(rows) else "")
        body = (f'<h1>Postępowania</h1>\n<p class="wyniki">Znaleziono postępowań: {len(rows)}</p>\n{cards}'
                f'<div class="stronicowanie">{nxt}</div>')
        return 200, HTML, _page("Postępowania", body, "pl")
    if path.startswith("/postepowanie/"):
        t = next((t for t in v.tenders if _num(t) == path.rsplit("/", 1)[1]), None)
        if t is None:
            return None
        facts = [("Numer postępowania", _num(t)), ("Znak sprawy", t.reference_number), ("Zamawiający", t.buyer_name),
                 ("Data publikacji", f"{t.publication_date:%Y-%m-%d}"),
                 ("Termin składania ofert", f"{t.submission_deadline:%Y-%m-%d %H:%M}"),
                 ("Tryb postępowania", w[t.procedure_word]), ("Rodzaj zamówienia", w[t.nature_word]),
                 ("Kody CPV", "; ".join(t.cpv)), ("Miejscowość", t.city), ("Kod pocztowy", t.postal_code)]
        body = (f'<h1>{escape(t.title)}</h1>\n<table class="szczegoly">'
                + "".join(f"<tr><th>{k}</th><td>{escape(val)}</td></tr>\n" for k, val in facts)
                + f'</table>\n<section class="opis"><h2>Opis</h2><p>{escape(t.description)}</p></section>\n'
                  f'<section class="zalaczniki"><h2>Załączniki</h2><ul>{_files(v, t)}</ul></section>')
        return 200, HTML, _page(t.title, body, "pl")
    return None


# -- fr_cards -------------------------------------------------------------------------------

def _fr_date(moment, with_time: bool = True) -> str:
    text = f"{moment.day} {FR_MONTHS[moment.month - 1]} {moment.year}"
    return text + (f" à {moment:%H:%M}" if with_time else "")


def _fr(v: Variant, path: str, query: dict[str, str]) -> Answer | None:
    w = WORDS["fr"]
    if path == "/":
        return 200, HTML, _page("Marchés publics", '<p><a href="/consultations">Consultations en cours</a></p>'
                                '<p><a href="/aide">Aide</a></p>', "fr")
    if path == "/consultations":
        rows, page, size = _newest(v), int(query.get("page", 1)), 20
        cards = "".join(
            f'<div class="consultation" data-ref="{t.id}"><div class="objet"><a href="/consultation/{t.id}">'
            f'{escape(t.title)}</a></div><div class="organisme">{escape(t.buyer_name)}</div>'
            f'<div class="infos"><span class="date-publication">Publié le {_fr_date(t.publication_date, False)}</span>'
            f'<span class="date-limite">Date limite de remise des plis : {_fr_date(t.submission_deadline)}</span>'
            f'<span class="type">{w[t.nature_word]}</span></div></div>\n' for t in rows[(page - 1) * size:page * size])
        nxt = f'<a rel="next" class="suivant" href="/consultations?page={page + 1}">Page suivante</a>' if page * size < len(rows) else ""
        body = (f'<h1>Consultations en cours</h1>\n<p class="resultats"><strong>{len(rows)}</strong> consultations</p>\n'
                f'{cards}<nav class="pagination">{nxt}</nav>')
        return 200, HTML, _page("Consultations", body, "fr")
    if path.startswith("/consultation/"):
        t = next((t for t in v.tenders if t.id == path.rsplit("/", 1)[1]), None)
        if t is None:
            return None
        facts = [("Référence", t.reference_number), ("Organisme", t.buyer_name),
                 ("Date de publication", _fr_date(t.publication_date, False)),
                 ("Date limite de remise des plis", _fr_date(t.submission_deadline)),
                 ("Procédure", w[t.procedure_word]), ("Type de marché", w[t.nature_word]),
                 ("Codes CPV", ", ".join(t.cpv)), ("Lieu d'exécution", f"{t.postal_code} {t.city}")]
        body = (f'<h1 class="objet">{escape(t.title)}</h1>\n<dl class="fiche">'
                + "".join(f"<dt>{k}</dt><dd>{escape(val)}</dd>\n" for k, val in facts)
                + f'</dl>\n<div class="description"><p>{escape(t.description)}</p></div>\n'
                  f'<h2>Dossier de consultation</h2><ul class="dce">{_files(v, t)}</ul>')
        return 200, HTML, _page(t.title, body, "fr")
    return None


# -- it_detail ------------------------------------------------------------------------------

def _it(v: Variant, path: str, query: dict[str, str]) -> Answer | None:
    w = WORDS["it"]
    if path in ("/", "/gare/elenco.do"):
        rows, page, size = _newest(v), int(query.get("p", 1)), 20
        trs = "".join(
            f'<tr class="gara"><td class="codice">{t.id}</td><td class="oggetto"><a href="/gare/dettaglio.do?codice={t.id}">'
            f'{escape(t.title)}</a></td><td class="ente">{escape(t.buyer_name)}</td>'
            f'<td class="pubblicazione">{t.publication_date:%d/%m/%Y}</td><td class="tipo">{w[t.nature_word]}</td></tr>\n'
            for t in rows[(page - 1) * size:page * size])
        pages = -(-len(rows) // size)
        links = " ".join(f'<a href="/gare/elenco.do?p={n}">{n}</a>' if n != page else f"<b>{n}</b>"
                         for n in range(1, pages + 1))
        body = (f'<h1>Bandi di gara in corso</h1>\n<p class="totale">Risultati: {len(rows)}</p>\n'
                '<table id="elenco"><thead><tr><th>Codice</th><th>Oggetto</th><th>Stazione appaltante</th>'
                f'<th>Pubblicazione</th><th>Tipologia</th></tr></thead><tbody>\n{trs}</tbody></table>\n'
                f'<div class="pagine">Pagina {page} di {pages}: {links}</div>')
        return 200, HTML, _page("Bandi di gara", body, "it")
    if path == "/gare/dettaglio.do":
        t = next((t for t in v.tenders if t.id == query.get("codice")), None)
        if t is None:
            return None
        facts = [("Codice gara", t.id), ("CIG", t.reference_number), ("Stazione appaltante", t.buyer_name),
                 ("Data di pubblicazione", f"{t.publication_date:%d/%m/%Y}"),
                 ("Scadenza presentazione offerte", f"{t.submission_deadline:%d/%m/%Y} ore {t.submission_deadline:%H:%M}"),
                 ("Procedura", w[t.procedure_word]), ("Tipologia", w[t.nature_word]), ("CPV", " - ".join(t.cpv)),
                 ("Luogo", f"{t.postal_code} {t.city}")]
        body = (f'<h1>{escape(t.title)}</h1>\n<div class="scheda">'
                + "".join(f'<p><span class="etichetta">{k}:</span> <span class="valore">{escape(val)}</span></p>\n'
                          for k, val in facts)
                + f'</div>\n<div class="descrizione"><p>{escape(t.description)}</p></div>\n'
                  f'<h2>Documentazione di gara</h2><ul class="allegati">{_files(v, t)}</ul>')
        return 200, HTML, _page(t.title, body, "it")
    return None


# -- docs_page ------------------------------------------------------------------------------

def _docs_page(v: Variant, path: str, query: dict[str, str]) -> Answer | None:
    if path == "/":
        items = "".join(
            f'<li class="opportunity" id="opp-{t.id}"><a class="opp-link" href="/opportunity/{t.id}">{escape(t.title)}</a>'
            f'<span class="opp-buyer">{escape(t.buyer_name)}</span>'
            f'<time class="opp-closes" datetime="{t.submission_deadline.isoformat()}">closes {t.submission_deadline:%d %b %Y, %H:%M}</time></li>\n'
            for t in _newest(v))
        return 200, HTML, _page("Opportunities", f'<h1>Open opportunities</h1>\n<ul id="opportunities">\n{items}</ul>')
    parts = path.strip("/").split("/")
    t = next((t for t in v.tenders if len(parts) > 1 and parts[0] == "opportunity" and t.id == parts[1]), None)
    if t is None:
        return None
    if len(parts) == 3 and parts[2] == "documents":
        return 200, HTML, _page(f"Documents - {t.title}", f'<h1>Documents</h1>\n<ul class="documents">{_files(v, t)}</ul>\n'
                                f'<p><a href="/opportunity/{t.id}">Back</a></p>')
    if len(parts) == 2:
        facts = [("Opportunity ID", t.id), ("Reference", t.reference_number), ("Buyer", t.buyer_name),
                 ("Published", f"{t.publication_date:%d %B %Y}"), ("Closing", f"{t.submission_deadline:%d %B %Y, %H:%M}"),
                 ("Procedure", t.procedure_word), ("Category", t.nature_word), ("CPV", ", ".join(t.cpv))]
        body = (f'<h1>{escape(t.title)}</h1>\n<dl class="summary">'
                + "".join(f"<dt>{k}</dt><dd>{escape(val)}</dd>\n" for k, val in facts)
                + f'</dl>\n<div class="about"><p>{escape(t.description)}</p></div>\n'
                  f'<p><a class="documents-link" href="/opportunity/{t.id}/documents">View documents ({len(t.files)})</a></p>')
        return 200, HTML, _page(t.title, body)
    return None


# -- the two that cannot be learned ----------------------------------------------------------

def _login_wall(v: Variant, path: str, query: dict[str, str]) -> Answer | None:
    if path == "/login":
        return 200, HTML, _page("Sign in", '<h1>Sign in</h1>\n<form method="post" action="/login"><label>User '
                                '<input name="username"></label><label>Password <input type="password" name="password">'
                                '</label><button>Sign in</button></form>\n<p>Tenders are visible to registered suppliers only.</p>')
    return 302, {"Location": "/login", **HTML}, b""


def _empty(v: Variant, path: str, query: dict[str, str]) -> Answer | None:
    if path == "/":
        return 200, HTML, _page("Tenders", '<p><a href="/tenders">Current tenders</a></p>')
    if path == "/tenders":
        return 200, HTML, _page("Current tenders", '<h1>Current tenders</h1>\n<p class="no-results">There are no '
                                'current tenders. Please check back later.</p>')
    return None


def _make(name: str, what: str, route, count: int = 45, **more) -> Callable[[], Variant]:
    return lambda: Variant(name=name, base_url=f"https://{name.replace('_', '-')}.variants.example", what=what,
                           tenders=make_tenders(count), route=route, **more)


VARIANTS: dict[str, Callable[[], Variant]] = {
    "json_api": _make("json_api", "app shell; list and tenders from a JSON API named in a script", _json_api,
                      tender_url=lambda t: f"/notice/{t.id}"),
    "de_netserver": _make("de_netserver", "German; rows with data-oid and no link; one page", _de, count=30,
                          ident=_oid, tender_url=lambda t: f"/NetServer/PublicationControllerServlet?function=Detail&TOID={_oid(t)}"),
    "pl_offset": _make("pl_offset", "Polish; offset paging; numeric id in the address", _pl, ident=_num,
                       tender_url=lambda t: f"/postepowanie/{_num(t)}"),
    "fr_cards": _make("fr_cards", "French; cards; dates with month names", _fr,
                      tender_url=lambda t: f"/consultation/{t.id}"),
    "it_detail": _make("it_detail", "Italian; deadline only on the tender page; numbered pages", _it,
                       tender_url=lambda t: f"/gare/dettaglio.do?codice={t.id}"),
    "docs_page": _make("docs_page", "one page, no total; files on a page of their own", _docs_page, count=24,
                       tender_url=lambda t: f"/opportunity/{t.id}"),
    "login_wall": _make("login_wall", "every page leads to a login", _login_wall, count=5, expect="give_up"),
    "empty": _make("empty", "the list says there are no tenders", _empty, count=0, expect="give_up"),
}
