"""The mock portal's pages as HTML, in two layouts.

The default layout is the one `mock_portal/recipe.py` reads: a table of tenders, and a detail
page built on a `<dl>`. The changed layout shows the same ids and values in other elements,
under other class names and other label words, so a recipe learned on the first cannot read it.

Every link is a path from the server's root with `root` in front of it, so the pages also
work when the portal is mounted under a prefix. Every text goes through `html.escape`.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

from mock_portal.data import COUNTRY, Tender

SITE_NAME = "Mock Tender Portal"
EMPTY_NOTICE = "No tenders are currently published."
# A marker `app.fetch.answer.captcha_product` knows as reCAPTCHA. It loads nothing and blocks nothing.
CAPTCHA_MARKER = '<div class="g-recaptcha" data-sitekey="mock-portal-site-key"></div>'


@dataclass(frozen=True)
class Shown:
    """One tender as the portal shows it right now, after the switches were applied."""

    tender: Tender
    status: str            # "Open" or "Cancelled"
    published: str         # the list's publication cell: "02.11.2026"
    deadline: str          # the list's deadline cell: "14.03.2027 12:00"
    deadline_machine: str  # the same moment for `<time datetime>`: "2027-03-14T12:00"
    detail_deadline: str   # the deadline on the tender's own page
    detail_published: str  # the publication date on the tender's own page


def size_text(size: int) -> str:
    """How the portal announces a file's size: the exact number of bytes, "12,345 bytes"."""
    return f"{size:,} bytes"


def tender_path(root: str, tender_id: str) -> str:
    return f"{root}/tenders/{tender_id}"


def file_path(root: str, tender_id: str, name: str) -> str:
    return f"{root}/files/{tender_id}/{name}"


def list_path(root: str, page: int) -> str:
    return f"{root}/tenders?page={page}"


def page(title: str, body: str, root: str, *, captcha: bool = False) -> bytes:
    """A whole page. `title` is the document title, never the place a tender's values are read from."""
    marker = f"\n{CAPTCHA_MARKER}" if captcha else ""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)} - {SITE_NAME}</title>\n</head>\n<body>{marker}\n"
        f'<header><p class="site-name"><a href="{escape(root)}/">{SITE_NAME}</a></p></header>\n'
        f"<main>\n{body}\n</main>\n"
        '<footer><p class="imprint">A test portal. Every tender on it is made up.</p></footer>\n'
        "</body>\n</html>\n"
    ).encode("utf-8")


def entry(root: str, *, captcha: bool = False) -> bytes:
    body = ("<h1>Public procurement</h1>\n"
            "<p>This portal publishes the tenders of six public buyers.</p>\n"
            f'<p><a class="tender-list" href="{escape(root)}/tenders">Current tenders</a></p>')
    return page("Welcome", body, root, captcha=captcha)


def not_found(root: str) -> bytes:
    return page("Page not found", "<h1>Page not found</h1>\n<p>There is no page at this address.</p>", root)


def login(root: str) -> bytes:
    body = ("<h1>Sign in</h1>\n"
            f'<form id="login" method="post" action="{escape(root)}/login">\n'
            '<label>User name <input type="text" name="username"></label>\n'
            '<label>Password <input type="password" name="password"></label>\n'
            '<button type="submit">Sign in</button>\n</form>')
    return page("Sign in", body, root)


def maintenance(root: str) -> bytes:
    """A notice `app.fetch.answer.maintenance_page` recognises: the word is in the title and the heading."""
    body = ("<h1>Scheduled maintenance</h1>\n"
            "<p>The portal is being updated. Please come back later.</p>")
    return page("Maintenance", body, root)


def tender_list(rows: list[Shown], root: str, *, total: int | None, notice: bool, number: int, pages: int,
                has_next: bool, changed: bool, captcha: bool = False) -> bytes:
    """One page of the list. `total` None prints no total; `notice` prints the empty-list notice."""
    render = _list_changed if changed else _list_default
    return page("Current tenders", render(rows, root, total, notice, number, pages, has_next), root,
                captcha=captcha)


def _list_default(rows: list[Shown], root: str, total: int | None, notice: bool, number: int, pages: int,
                  has_next: bool) -> str:
    out = ["<h1>Current tenders</h1>"]
    if total is not None:
        out.append(f'<p class="total">{total} tenders found</p>')
    if notice:
        out.append(f'<p class="no-results">{EMPTY_NOTICE}</p>')
    else:
        out.append('<table id="tenders">\n<thead><tr><th>Number</th><th>Title</th><th>Contracting authority</th>'
                   "<th>Published</th><th>Deadline</th><th>Status</th></tr></thead>\n<tbody>")
        for row in rows:
            t = row.tender
            out.append(
                f'<tr class="tender" data-id="{escape(t.id)}">'
                f'<td class="id">{escape(t.id)}</td>'
                f'<td class="title"><a href="{escape(tender_path(root, t.id))}">{escape(t.title)}</a></td>'
                f'<td class="buyer">{escape(t.buyer_name)}</td>'
                f'<td class="published">{escape(row.published)}</td>'
                f'<td class="deadline"><time datetime="{escape(row.deadline_machine)}">{escape(row.deadline)}</time></td>'
                f'<td class="status">{escape(row.status)}</td></tr>')
        out.append("</tbody>\n</table>")
        links = [f'<span class="current">Page {number} of {pages}</span>']
        if number > 1:
            links.append(f'<a rel="prev" href="{escape(list_path(root, number - 1))}">Previous</a>')
        if has_next:
            links.append(f'<a rel="next" href="{escape(list_path(root, number + 1))}">Next</a>')
        out.append(f'<nav class="pages">{" ".join(links)}</nav>')
    return "\n".join(out)


def _list_changed(rows: list[Shown], root: str, total: int | None, notice: bool, number: int, pages: int,
                  has_next: bool) -> str:
    """The same rows as cards: the id sits in a badge, the buyer and the deadline in a list of facts."""
    out = ["<h1>Current tenders</h1>"]
    if total is not None:
        out.append(f'<div class="summary">Showing {total} notices</div>')
    if notice:
        out.append(f'<div class="empty-state">{EMPTY_NOTICE}</div>')
    else:
        out.append('<section id="results">')
        for row in rows:
            t = row.tender
            out.append(
                '<div class="result-card">\n'
                f'<h3 class="card-title"><a href="{escape(tender_path(root, t.id))}">{escape(t.title)}</a></h3>\n'
                f'<p class="card-meta"><span class="badge">{escape(t.id)}</span> '
                f'<span class="state">{escape(row.status)}</span></p>\n'
                '<ul class="card-facts">'
                f'<li class="org">Buyer: <strong>{escape(t.buyer_name)}</strong></li>'
                f'<li class="opened">Publication date: <strong>{escape(row.published)}</strong></li>'
                f'<li class="closes">Closing date: <strong>{escape(row.deadline)}</strong></li></ul>\n'
                "</div>")
        out.append("</section>")
        links = [f'<span class="here">{number} / {pages}</span>']
        if number > 1:
            links.append(f'<a class="pager-prev" href="{escape(list_path(root, number - 1))}">Back</a>')
        if has_next:
            links.append(f'<a class="pager-next" href="{escape(list_path(root, number + 1))}">More</a>')
        out.append(f'<div class="pager">{" ".join(links)}</div>')
    return "\n".join(out)


def detail(row: Shown, root: str, *, changed: bool, captcha: bool = False) -> bytes:
    """One tender's own page."""
    render = _detail_changed if changed else _detail_default
    return page(row.tender.title, render(row, root), root, captcha=captcha)


def _detail_default(row: Shown, root: str) -> str:
    t = row.tender
    facts = [("Tender number", "tender-id", t.id), ("Reference", "reference", t.reference_number),
             ("Contracting authority", "buyer", t.buyer_name), ("Published", "published", row.detail_published),
             ("Deadline for tenders", "deadline", row.detail_deadline), ("Status", "status", row.status),
             ("Procedure", "procedure", t.procedure_word), ("Type of contract", "nature", t.nature_word),
             ("CPV", "cpv", ", ".join(t.cpv))]
    place = [("Postal code", "postal-code", t.postal_code), ("City", "city", t.city),
             ("Country", "country", COUNTRY)]

    def pairs(items: list[tuple[str, str, str]]) -> str:
        return "\n".join(f'<dt>{escape(name)}</dt><dd class="{cls}">{escape(value)}</dd>'
                         for name, cls, value in items)

    files = "\n".join(
        f'<li><a class="file" href="{escape(file_path(root, t.id, f.name))}"><span class="name">{escape(f.name)}</span> '
        f'<span class="size">{size_text(f.size)}</span></a></li>' for f in t.files)
    return (f"<h1>{escape(t.title)}</h1>\n"
            f'<dl class="facts">\n{pairs(facts)}\n</dl>\n'
            '<section class="place">\n<h2>Place of performance</h2>\n'
            f"<dl>\n{pairs(place)}\n</dl>\n</section>\n"
            f'<section class="description">\n<h2>Description</h2>\n<p>{escape(t.description)}</p>\n</section>\n'
            '<section class="files">\n<h2>Documents</h2>\n'
            f'<ul class="documents">\n{files}\n</ul>\n</section>\n'
            f'<p><a class="back" href="{escape(root)}/tenders">Back to the list</a></p>')


def _detail_changed(row: Shown, root: str) -> str:
    """The same values in a table, under other label words; the files in a table of their own."""
    t = row.tender
    facts = [("Notice ID", t.id), ("File reference", t.reference_number), ("Buyer", t.buyer_name),
             ("Publication date", row.detail_published), ("Closing date", row.detail_deadline),
             ("State", row.status), ("Procedure type", t.procedure_word), ("Contract category", t.nature_word),
             ("CPV codes", ", ".join(t.cpv)), ("Postcode", t.postal_code), ("Town", t.city),
             ("Country of performance", COUNTRY)]
    rows = "\n".join(f"<tr><th>{escape(name)}</th><td>{escape(value)}</td></tr>" for name, value in facts)
    files = "\n".join(
        f'<tr><td class="doc-name"><a class="download" href="{escape(file_path(root, t.id, f.name))}">{escape(f.name)}</a></td>'
        f'<td class="doc-size">{size_text(f.size)}</td></tr>' for f in t.files)
    return (f'<h1 class="notice-title">{escape(t.title)}</h1>\n'
            f'<table class="notice-facts">\n{rows}\n</table>\n'
            f'<div class="summary-text">\n<h2>About this contract</h2>\n<p>{escape(t.description)}</p>\n</div>\n'
            '<h2>Attachments</h2>\n'
            f'<table class="attachments">\n{files}\n</table>\n'
            f'<p><a class="back" href="{escape(root)}/tenders">All notices</a></p>')
