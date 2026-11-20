"""`MockPortal`: a fake tender portal that we break on purpose (DESIGN.md, "Mock portal").

It is the server-rendered template: a table of tenders with paging, a page per tender, and
two to four files per tender. It opens no socket and makes no request. Tests hand
`portal.handle` to `httpx.MockTransport`; the app can mount `portal.asgi()` for the demo.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx

from mock_portal import pages
from mock_portal.data import (
    COUNTRY_CODE, DATETIME_FORMAT, MACHINE_FORMAT, NATURE_WORDS, PROCEDURE_WORDS, STATUS_CANCELLED,
    STATUS_OPEN, STATUS_WORDS, ZONE, Tender, make_tenders, print_date, print_moment,
)

HTML = "text/html; charset=utf-8"
TEXT = "text/plain; charset=utf-8"
_LOGIN_WALLS = ("none", "documents", "all")
_LIST_EMPTIED = ("no", "with_notice", "without_notice")

Answer = tuple[int, dict[str, str], bytes]


class MockPortal:
    """A tender portal held in memory, with switches that break it the way real portals break.

    `MockPortal(tenders=45, page_size=20, base_url="https://mock.example", root_path="")`
    builds the same tenders and the same file bytes every time. `root_path` is the prefix the
    portal is served under ("/mock"); every link on every page starts with it.

    Pages: `/robots.txt`, `/` (links to the list), `/tenders?page=N` (newest first, pages count
    from 1), `/tenders/{id}`, `/files/{id}/{name}`, `/login`. Any other path answers 404.

    The switches are plain attributes. A test sets one between two reads; `reset()` puts all of
    them back. When several are on, the first of these that applies answers the request:
    `outage`, `rate_limited`, `maintenance`, then the login wall, then the page itself.

    - `layout_changed` (bool): the list becomes `<div class="result-card">` blocks and the
      detail page a table with other label words. The ids and values stay the same.
    - `outage` (bool): every path answers 503 with a short body and no Retry-After.
    - `maintenance` (bool): every path answers 200 with a maintenance notice.
    - `login_wall` ("none", "documents", "all"): the files, or every page but `/robots.txt`,
      answer 302 to `/login`, a page with a password field.
    - `list_emptied` ("no", "with_notice", "without_notice"): the list shows no rows. With the
      notice it prints `<p class="no-results">` and "0 tenders found"; without, neither a notice
      nor a total. The tenders' own pages still answer.
    - `withdrawn` (set of ids): those tenders show the status "Cancelled" on the list and on
      their own page.
    - `removed` (set of ids): those tenders are gone from the list and from the total; their
      page and their files answer 404.
    - `paging_cut` (bool): only page 1 is served and it has no next link, while the total still
      prints the full count.
    - `rate_limited` (bool): every path answers 429 with `Retry-After: 1`.
    - `captcha_on_pages` (bool): every page carries a reCAPTCHA marker. Everything still works.
    - `robots_disallow_all` (bool): `/robots.txt` forbids every path.
    - `deadline_moved` (id to text): the deadline shown on that tender's own page, and only
      there. The list keeps the old one.
    - `columns_swapped` (bool): on the list, the publication cell shows the deadline's date and
      the deadline cell shows the publication date (with the deadline's time of day), so both
      cells still hold a date of the form they always held.

    `requests` lists the method and path of every request that arrived, in order, with the
    root path taken off. `truth()` gives what a correct read of the portal returns.
    """

    def __init__(self, tenders: int = 45, page_size: int = 20, base_url: str = "https://mock.example",
                 root_path: str = "") -> None:
        if tenders < 0 or page_size < 1:
            raise ValueError("A portal needs zero or more tenders and a page size of at least one.")
        self.page_size = page_size
        self.base_url = base_url.rstrip("/")
        self.root_path = _clean_root(root_path)
        self._tenders: list[Tender] = make_tenders(tenders)
        self._by_id = {t.id: t for t in self._tenders}
        self.requests: list[tuple[str, str]] = []
        self.reset()

    def reset(self) -> None:
        """Every switch back to a working portal. The request counter is left as it is."""
        self.layout_changed = False
        self.outage = False
        self.maintenance = False
        self.login_wall = "none"
        self.list_emptied = "no"
        self.withdrawn: set[str] = set()
        self.removed: set[str] = set()
        self.paging_cut = False
        self.rate_limited = False
        self.captcha_on_pages = False
        self.robots_disallow_all = False
        self.deadline_moved: dict[str, str] = {}
        self.columns_swapped = False

    # == What is true ==

    @property
    def ids(self) -> list[str]:
        """Every tender's id, newest first, tenders in `removed` left out: the order of the list."""
        return [t.id for t in self._listed()]

    def tender_url(self, tender_id: str) -> str:
        """The absolute address of a tender's own page."""
        return self.base_url + pages.tender_path(self.root_path, tender_id)

    def file_url(self, tender_id: str, name: str) -> str:
        """The absolute address of one file."""
        return self.base_url + pages.file_path(self.root_path, tender_id, name)

    def truth(self) -> list[dict[str, Any]]:
        """What a correct read returns, one dict per tender, newest first, in the contract's values.

        It follows the switches that change what is true: a tender in `removed` is left out, one
        in `withdrawn` has the status "withdrawn", and one in `deadline_moved` has the new
        deadline (None when the new text is not of the form `14.03.2027 12:00`). Switches that
        only break the reading (layout, paging, an emptied list, swapped columns) change nothing
        here. Addresses use the constructor's `base_url` and `root_path`.
        """
        out: list[dict[str, Any]] = []
        for t in self._listed():
            out.append({
                "id": t.id,
                "url": self.tender_url(t.id),
                "title": t.title,
                "buyer_name": t.buyer_name,
                "publication_date": t.publication_date,
                "submission_deadline": self._true_deadline(t),
                "status": STATUS_WORDS[self._status_word(t)],
                "reference_number": t.reference_number,
                "description": t.description,
                "procedure_type": PROCEDURE_WORDS[t.procedure_word],
                "contract_nature": NATURE_WORDS[t.nature_word],
                "cpv_codes": [code.split("-")[0] for code in t.cpv],
                "postal_code": t.postal_code,
                "city": t.city,
                "country_code": COUNTRY_CODE,
                "documents": [(f.name, f.size, f.sha256) for f in t.files],
            })
        return out

    def _listed(self) -> list[Tender]:
        return [t for t in reversed(self._tenders) if t.id not in self.removed]

    def _status_word(self, tender: Tender) -> str:
        return STATUS_CANCELLED if tender.id in self.withdrawn else STATUS_OPEN

    def _true_deadline(self, tender: Tender) -> datetime | None:
        moved = self.deadline_moved.get(tender.id)
        if moved is None:
            return tender.submission_deadline
        try:
            return datetime.strptime(moved.strip(), DATETIME_FORMAT).replace(tzinfo=ZONE)
        except ValueError:
            return None

    def _shown(self, tender: Tender) -> pages.Shown:
        deadline = tender.submission_deadline
        published, list_deadline = print_date(tender.publication_date), deadline
        if self.columns_swapped:
            published = print_date(deadline.date())
            list_deadline = datetime.combine(tender.publication_date, deadline.timetz())
        return pages.Shown(
            tender=tender, status=self._status_word(tender), published=published,
            deadline=print_moment(list_deadline), deadline_machine=list_deadline.strftime(MACHINE_FORMAT),
            detail_deadline=self.deadline_moved.get(tender.id, print_moment(deadline)),
            detail_published=print_date(tender.publication_date))

    # == Answering ==

    def respond(self, method: str, url: str, form: dict[str, str] | None = None, *,
                root_path: str | None = None) -> Answer:
        """The answer to one request: status, headers and body. No socket, no clock.

        `url` is an absolute address or a path with its query. `form` is the posted form, which
        no page reads: a POST is answered like a GET. `root_path` overrides the constructor's
        prefix for this one request (the ASGI wrapper passes the mount's).
        """
        root = self.root_path if root_path is None else _clean_root(root_path)
        parts = urlsplit(url)
        path = parts.path or "/"
        if root and (path == root or path.startswith(root + "/")):
            path = path[len(root):] or "/"
        method = method.upper()
        self.requests.append((method, path))
        status, headers, body = self._answer(method, path, dict(parse_qsl(parts.query)), root)
        return status, {**headers, "Content-Length": str(len(body))}, body

    def handle(self, request: httpx.Request) -> httpx.Response:
        """For `httpx.MockTransport(portal.handle)`."""
        form = dict(parse_qsl(request.content.decode("utf-8", "replace"))) if request.method == "POST" else None
        status, headers, body = self.respond(request.method, str(request.url), form)
        return httpx.Response(status, headers=headers, content=body, request=request)

    def asgi(self) -> Callable[[dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]],
                               Awaitable[None]]:
        """The portal as a plain ASGI application, for `app.mount("/mock", portal.asgi())`.

        Links start with the scope's `root_path`, so they work under any mount. Only the `http`
        scope is served; the lifespan messages are acknowledged so the app also runs alone.
        """
        async def app(scope: dict[str, Any], receive: Callable[..., Awaitable[Any]],
                      send: Callable[..., Awaitable[Any]]) -> None:
            if scope["type"] == "lifespan":
                while True:
                    message = await receive()
                    if message["type"] == "lifespan.startup":
                        await send({"type": "lifespan.startup.complete"})
                    elif message["type"] == "lifespan.shutdown":
                        await send({"type": "lifespan.shutdown.complete"})
                        return
            if scope["type"] != "http":
                return
            posted = b""
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    return  # the client went away
                posted += message.get("body", b"")
                if not message.get("more_body"):
                    break
            method = scope["method"].upper()
            url = scope["path"]
            if scope.get("query_string"):
                url += "?" + scope["query_string"].decode("latin-1")
            form = dict(parse_qsl(posted.decode("utf-8", "replace"))) if method == "POST" else None
            status, headers, body = self.respond(method, url, form, root_path=scope.get("root_path", ""))
            await send({"type": "http.response.start", "status": status,
                        "headers": [(name.lower().encode("latin-1"), value.encode("latin-1"))
                                    for name, value in headers.items()]})
            await send({"type": "http.response.body", "body": body})

        return app

    def _answer(self, method: str, path: str, query: dict[str, str], root: str) -> Answer:
        if self.login_wall not in _LOGIN_WALLS:
            raise ValueError(f"login_wall is one of {_LOGIN_WALLS}, not {self.login_wall!r}.")
        if self.list_emptied not in _LIST_EMPTIED:
            raise ValueError(f"list_emptied is one of {_LIST_EMPTIED}, not {self.list_emptied!r}.")
        if method not in ("GET", "POST"):
            return 405, {"Content-Type": TEXT, "Allow": "GET, POST"}, b"Method not allowed.\n"
        if self.outage:
            return 503, {"Content-Type": TEXT}, b"Service unavailable.\n"
        if self.rate_limited:
            return 429, {"Content-Type": TEXT, "Retry-After": "1"}, b"Too many requests.\n"
        if self.maintenance:
            return 200, {"Content-Type": HTML}, pages.maintenance(root)
        if path == "/robots.txt":
            rule = "Disallow: /" if self.robots_disallow_all else "Allow: /"
            return 200, {"Content-Type": TEXT}, f"User-agent: *\n{rule}\n".encode("ascii")
        if path == "/login":
            return 200, {"Content-Type": HTML}, pages.login(root)
        if self.login_wall == "all" or (self.login_wall == "documents" and path.startswith("/files/")):
            return 302, {"Content-Type": TEXT, "Location": f"{root}/login"}, b"Sign in first.\n"

        captcha = self.captcha_on_pages
        if path == "/":
            return 200, {"Content-Type": HTML}, pages.entry(root, captcha=captcha)
        if path in ("/tenders", "/tenders/"):
            return self._list(query, root)
        if path.startswith("/tenders/"):
            tender = self._by_id.get(path[len("/tenders/"):])
            if tender is not None and tender.id not in self.removed:
                return 200, {"Content-Type": HTML}, pages.detail(
                    self._shown(tender), root, changed=self.layout_changed, captcha=captcha)
        if path.startswith("/files/"):
            tender_id, _, name = path[len("/files/"):].partition("/")
            tender = self._by_id.get(tender_id)
            file = tender.file(name) if tender is not None and tender.id not in self.removed else None
            if file is not None:
                return 200, {"Content-Type": file.content_type,
                             "Content-Disposition": f'attachment; filename="{file.name}"'}, file.body
        return 404, {"Content-Type": HTML}, pages.not_found(root)

    def _list(self, query: dict[str, str], root: str) -> Answer:
        listed = self._listed()
        total: int | None = len(listed)
        notice = False
        if self.list_emptied != "no":
            notice = self.list_emptied == "with_notice"
            total = 0 if notice else None
            listed = []
        page_count = max(1, -(-len(listed) // self.page_size))
        if self.paging_cut:
            page_count = 1
        try:
            number = int(query.get("page", "1"))
        except ValueError:
            number = 0
        if not 1 <= number <= page_count:
            return 404, {"Content-Type": HTML}, pages.not_found(root)
        rows = listed[(number - 1) * self.page_size: number * self.page_size]
        body = pages.tender_list(
            [self._shown(t) for t in rows], root, total=total, notice=notice, number=number, pages=page_count,
            has_next=number < page_count, changed=self.layout_changed, captcha=self.captcha_on_pages)
        return 200, {"Content-Type": HTML}, body


def _clean_root(root_path: str) -> str:
    """"" for no prefix, else the prefix with one leading slash and no trailing one."""
    root = root_path.strip("/")
    return f"/{root}" if root else ""
