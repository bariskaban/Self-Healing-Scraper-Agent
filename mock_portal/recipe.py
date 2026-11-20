"""The recipe that reads the mock portal's default layout, written by hand.

It is what a learner should arrive at for this portal. The read loop's tests attach the portal
with it, so no model is needed to test a read, a failed check or a repair that is handed in.
Most fields have two locators, so the "two witnesses must agree" rule has something to compare.
"""
from __future__ import annotations

from app.recipe.build import (
    css, documents, facts, field, follow, get, host, identity, label, node, paging, regex, xpath,
)
from app.recipe.schema import AuthoredRecipe, FieldName as F, NodeRole, PagingKind, ValueType as T
from mock_portal.data import (
    COUNTRY, COUNTRY_CODE, DATE_FORMAT, DATETIME_FORMAT, MACHINE_FORMAT, NATURE_WORDS, PROCEDURE_WORDS,
    STATUS_WORDS, TIMEZONE,
)

__all__ = ["TIMEZONE", "recipe"]


def recipe(root_path: str = "") -> AuthoredRecipe:
    """The recipe for `MockPortal`'s default layout. `root_path` is the portal's mount prefix, if any."""
    root = f"/{root_path.strip('/')}" if root_path.strip("/") else ""
    return AuthoredRecipe(
        start="list",
        nodes=[
            node("list", NodeRole.list, request=get(f"{root}/tenders"),
                 items=css("table#tenders tr.tender"),
                 fields=[
                     field(F.id, css("tr.tender", attr="data-id"), css("td.id"), type=T.id),
                     field(F.url, css("td.title a", attr="href"), type=T.url),
                     field(F.title, css("td.title a")),
                     field(F.buyer_name, css("td.buyer")),
                     field(F.publication_date, css("td.published"), type=T.date, formats=[DATE_FORMAT]),
                     field(F.submission_deadline, css("td.deadline"), css("td.deadline time", attr="datetime"),
                           type=T.datetime, formats=[DATETIME_FORMAT, MACHINE_FORMAT]),
                     field(F.status, css("td.status"), type=T.status, words=STATUS_WORDS),
                 ],
                 paging=paging(PagingKind.next_link, next=css("nav.pages a[rel=next]", attr="href")),
                 # The total counts every listed tender, the cancelled ones too.
                 facts=facts(total=regex(r"(\d+) tenders found"), total_counts_closed=True,
                             empty_marker=css("p.no-results"), newest_first=True)),
            node("detail", NodeRole.detail,
                 fields=[
                     field(F.id, label("Tender number"), css("dd.tender-id"), type=T.id),
                     field(F.title, css("main h1")),
                     field(F.reference_number, label("Reference"), css("dd.reference")),
                     field(F.buyer_name, label("Contracting authority"), css("dd.buyer")),
                     field(F.publication_date, label("Published"),
                           xpath("//dl[@class='facts']/dd[@class='published']"),
                           type=T.date, formats=[DATE_FORMAT]),
                     field(F.submission_deadline, label("Deadline for tenders"), css("dd.deadline"),
                           type=T.datetime, formats=[DATETIME_FORMAT]),
                     field(F.status, label("Status"), css("dd.status"), type=T.status, words=STATUS_WORDS),
                     field(F.procedure_type, label("Procedure"), css("dd.procedure"), type=T.procedure,
                           words=PROCEDURE_WORDS),
                     field(F.contract_nature, label("Type of contract"), css("dd.nature"), type=T.nature,
                           words=NATURE_WORDS),
                     field(F.cpv_codes, label("CPV"), css("dd.cpv"), type=T.cpv),
                     field(F.description, label("Description"), css("section.description p")),
                     field(F.postal_code, label("Postal code"), css("dd.postal-code"), type=T.postal_code),
                     field(F.city, label("City"), css("dd.city")),
                     field(F.country_code, label("Country"), css("dd.country"), type=T.country,
                           words={COUNTRY: COUNTRY_CODE}),
                 ],
                 documents=documents(css("ul.documents a.file", attr="href"), name=css("span.name"),
                                     size=css("span.size"))),
        ],
        edges=[follow("list", "detail", css("td.title a", attr="href"))],
        identity=identity(r"^MP-\d{4}-\d{4,}$", from_url=r"/tenders/(MP-\d{4}-\d{4,})", must_agree=True),
        family=None,
        host=host("en"),
        rationale="The list is a table of 20 rows per page with a link to the next page, newest first. "
                  "Each row links to the tender's own page, which carries the remaining fields as label and "
                  "value pairs and lists the files with their names and sizes.",
    )
