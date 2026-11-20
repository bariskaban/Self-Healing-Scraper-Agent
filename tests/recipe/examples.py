"""Three recipes written by hand, one per kind of portal the design has to read.

They are the worked examples of the schema: a server-rendered table with a detail page per
tender, a JSON API with one ZIP per tender, and a portal whose list pages and downloads go
through form posts. The addresses are made up; no request is made anywhere in the tests.
"""
from __future__ import annotations

from app.recipe.build import (
    call, css, documents, facts, field, follow, get, host, identity, jsonpath, label, node, paging, post,
    regex, submit, xpath,
)
from app.recipe.schema import AuthoredRecipe, FieldName as F, NodeKind, NodeRole, PagingKind, ValueType as T

STATUS_DE = {"Laufend": "open", "Beendet": "closed", "Aufgehoben": "withdrawn"}


def html_table_portal() -> AuthoredRecipe:
    """A German portal: a table of 20 rows per page, a detail page per tender, files on the detail page."""
    return AuthoredRecipe(
        start="list",
        nodes=[
            node("list", NodeRole.list, request=get("/ausschreibungen", sort="neueste"),
                 items=css("table#vergaben tbody tr"),
                 fields=[
                     field(F.id, css("td.aktenzeichen"), css("a.titel", attr="data-id"), type=T.id),
                     field(F.url, css("a.titel", attr="href"), type=T.url),
                     field(F.title, css("a.titel")),
                     field(F.submission_deadline, css("td.frist"), css("td.frist time", attr="datetime"),
                           type=T.datetime, formats=["%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M"]),
                 ],
                 paging=paging(PagingKind.next_link, next=css("nav.seiten a[rel=next]", attr="href")),
                 facts=facts(total=regex(r"(\d+) Ausschreibungen gefunden"), total_counts_closed=False,
                             empty_marker=css("p.keine-treffer"), newest_first=True)),
            node("detail", NodeRole.detail,
                 fields=[
                     field(F.id, label("Aktenzeichen", "Vergabenummer"), type=T.id),
                     field(F.buyer_name, label("Auftraggeber", "Vergabestelle"), css("div.auftraggeber .name")),
                     field(F.publication_date, label("Veröffentlicht am"), type=T.date, formats=["%d.%m.%Y"]),
                     field(F.submission_deadline, label("Angebotsfrist", "Abgabefrist"),
                           xpath("//dt[normalize-space()='Angebotsfrist']/following-sibling::dd"),
                           type=T.datetime, formats=["%d.%m.%Y %H:%M", "%d.%m.%Y"]),
                     field(F.status, label("Status"), type=T.status, words=STATUS_DE),
                     field(F.procedure_type, label("Verfahrensart"), type=T.procedure,
                           words={"Offenes Verfahren": "open", "Öffentliche Ausschreibung": "open",
                                  "Nichtoffenes Verfahren": "restricted", "Verhandlungsverfahren": "negotiated",
                                  "Wettbewerblicher Dialog": "other"}),
                     field(F.contract_nature, label("Auftragsart"), type=T.nature,
                           words={"Bauleistung": "works", "Dienstleistung": "services", "Lieferleistung": "supplies"}),
                     field(F.cpv_codes, label("CPV-Code", "CPV"), type=T.cpv),
                     field(F.description, css("section.beschreibung")),
                     field(F.postal_code, css("span.plz"), type=T.postal_code),
                     field(F.city, css("span.ort")),
                 ],
                 documents=documents(css("ul.unterlagen a.datei", attr="href"), name=css("span.name"),
                                     size=css("span.groesse"))),
        ],
        edges=[follow("list", "detail", css("a.titel", attr="href"))],
        identity=identity(r"^\d{4}-\d{3,6}$", from_url=r"/ausschreibungen/(\d{4}-\d+)", must_agree=True),
        family=None,
        host=host("de"),
        rationale="The list is a table with 20 rows per page and a link to the next page. Each row links to "
                  "the tender's own page, which carries the remaining fields and the files.",
    )


def json_api_portal() -> AuthoredRecipe:
    """A Dutch portal: a JSON list API with a page number, a detail call, and one ZIP per tender."""
    return AuthoredRecipe(
        start="list",
        nodes=[
            node("list", NodeRole.list, NodeKind.json,
                 request=get("/papi/v2/publicaties", page="{page}", size="{size}", publicatieType="AAO"),
                 items=jsonpath("$.content[*]"),
                 fields=[
                     field(F.id, jsonpath("@.publicatieId"), type=T.id),
                     field(F.title, jsonpath("@.aanbestedingNaam")),
                     field(F.buyer_name, jsonpath("@.opdrachtgeverNaam")),
                     field(F.publication_date, jsonpath("@.publicatieDatum"), type=T.date),
                     field(F.submission_deadline, jsonpath("@.sluitingsDatum"), type=T.datetime),
                     field(F.procedure_type, jsonpath("@.procedure.code"), type=T.procedure,
                           words={"OPE": "open", "REP": "restricted", "ONP": "negotiated", "CDI": "other"}),
                     field(F.contract_nature, jsonpath("@.typeOpdracht.code"), type=T.nature,
                           words={"W": "works", "D": "services", "L": "supplies"}),
                 ],
                 paging=paging(PagingKind.page_param, param="page", first=0, size_param="size", size=100),
                 facts=facts(total=jsonpath("$.totalElements"), total_counts_closed=False, newest_first=True,
                             has_all_required=False, change_mark=jsonpath("@.laatsteWijziging"))),
            node("detail", NodeRole.detail, NodeKind.json,
                 fields=[
                     field(F.url, jsonpath("$.linkNaarAankondiging"), type=T.url),
                     field(F.description, jsonpath("$.opdrachtBeschrijving")),
                     field(F.reference_number, jsonpath("$.referentieNummer")),
                     field(F.cpv_codes, jsonpath("$.cpvCodes[*].code"), type=T.cpv),
                     field(F.status, jsonpath("$.aanbestedingStatus"), type=T.status,
                           words={"ACTIEF": "open", "GESLOTEN": "closed", "INGETROKKEN": "withdrawn"}),
                     field(F.city, jsonpath("$.plaatsVanUitvoering.plaats")),
                     field(F.country_code, jsonpath("$.plaatsVanUitvoering.land"), type=T.country,
                           words={"Nederland": "NL", "NLD": "NL"}),
                 ]),
            node("files", NodeRole.documents, NodeKind.json,
                 documents=documents(jsonpath("$.zipLink"), url="/papi/v2/publicaties/{id}/documenten/zip",
                                     all_in_one_zip=True)),
        ],
        edges=[
            call("list", "detail", get("/papi/v2/publicaties/{id}")),
            call("detail", "files", get("/papi/v2/publicaties/{id}/documenten")),
        ],
        identity=identity(r"^\d{5,7}$"),
        family="tenderned",
        host=host("nl", publicatieType="AAO"),
        rationale="The site is a JavaScript app on a JSON API. The list call takes a page number and up to "
                  "100 items; each tender has a detail call and one ZIP with all its documents.",
    )


def form_post_portal() -> AuthoredRecipe:
    """A portal behind a start page: the list pages by form post, and each file sits behind a terms page."""
    return AuthoredRecipe(
        start="home",
        nodes=[
            node("home", NodeRole.entry, request=get("/")),
            node("list", NodeRole.list,
                 items=css("div.result"),
                 fields=[
                     field(F.title, css("h3 a")),
                     field(F.url, css("h3 a", attr="href"), type=T.url),
                     field(F.buyer_name, css(".buyer")),
                     field(F.publication_date, css(".published"), type=T.date, formats=["%d/%m/%Y"]),
                     field(F.submission_deadline, css(".deadline"), type=T.datetime, formats=["%d/%m/%Y %H:%M"]),
                 ],
                 paging=paging(PagingKind.form_post, form=css("form#pager"), max_pages=200),
                 facts=facts(total=css("span#resultCount"), empty_marker=css("div.no-results"),
                             has_all_required=True)),
            node("docs", NodeRole.documents,
                 documents=documents(css("table.docs a.open", attr="href"), then=css("a#confirm-download", attr="href"),
                                     name=css("td.filename"))),
        ],
        edges=[
            submit("home", "list", css("form#search"), request=post("", form={"status": "open"}), per_item=False),
            follow("list", "docs", css("a.documents", attr="href")),
        ],
        identity=identity(r"^[A-Z]{2}\d{6}$", from_url=r"[?&]tender=([A-Z]{2}\d{6})"),
        family=None,
        host=host("en", status="open"),
        rationale="The address leads to a search form. Submitting it gives the list, which pages by a form "
                  "post. The list carries every required field; each file is reached through a terms page.",
    )


EXAMPLES = {"html_table": html_table_portal, "json_api": json_api_portal, "form_post": form_post_portal}
