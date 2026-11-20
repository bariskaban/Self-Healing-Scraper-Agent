"""The mock portal: its pages, its files and every switch. No socket, no request to anything real."""
from __future__ import annotations

import asyncio
import hashlib
import io
import re
import zipfile
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter
from app.fetch.answer import captcha_product, maintenance_page
from app.recipe.locate import parse_page
from app.recipe.schema import NodeKind
from mock_portal import TIMEZONE, MockPortal

BASE = "https://mock.example"
FIRST, NEWEST = "MP-2026-0001", "MP-2026-0045"


def get(portal: MockPortal, path: str) -> tuple[int, dict[str, str], bytes]:
    return portal.respond("GET", BASE + path)


def page(portal: MockPortal, path: str):
    """The parsed page at a path, which must answer 200 with HTML."""
    status, headers, body = get(portal, path)
    assert status == 200, path
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    return parse_page(body, NodeKind.html, BASE + path, headers["Content-Type"]).root


def list_ids(portal: MockPortal, path: str = "/tenders") -> list[str]:
    return [row.get("data-id") for row in page(portal, path).cssselect("tr.tender")]


def walk_list(portal: MockPortal) -> list[str]:
    """Every id of the list, following the next link until there is none."""
    ids: list[str] = []
    path: str | None = "/tenders"
    while path:
        root = page(portal, path)
        ids += [row.get("data-id") for row in root.cssselect("tr.tender")]
        links = root.cssselect("nav.pages a[rel=next]")
        path = links[0].get("href") if links else None
    return ids


def detail_facts(portal: MockPortal, tender_id: str) -> dict[str, str]:
    """The label and value pairs of a tender's page in the default layout."""
    root = page(portal, f"/tenders/{tender_id}")
    return {dt.text_content(): dt.getnext().text_content() for dt in root.cssselect("dt")}


class Clock:
    """Monotonic time that moves only when something sleeps, so no test waits."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def make_fetcher(portal: MockPortal, *, robots: bool = False) -> Fetcher:
    """A Fetcher in live mode whose only network is the portal, as tests/fetch/conftest.py builds one."""
    clock = Clock()
    limiter = PortalLimiter(1.0, 10.0, clock=clock, sleep=clock.sleep)
    settings = FetchSettings(mode=FetchMode.live, ignore_robots_txt=not robots)
    return Fetcher(settings, transport=httpx.MockTransport(portal.handle), limiter=limiter, clock=clock,
                   rng=lambda: 0.0)


# == The data ==

def test_the_portal_is_the_same_every_time():
    one, two = MockPortal(), MockPortal()
    assert one.truth() == two.truth()
    assert get(one, "/tenders") == get(two, "/tenders")
    assert get(one, f"/files/{NEWEST}/annexes.zip") == get(two, f"/files/{NEWEST}/annexes.zip")


def test_truth_holds_contract_values():
    truth = MockPortal().truth()
    assert [t["id"] for t in truth] == [f"MP-2026-{n:04d}" for n in range(45, 0, -1)]
    assert len({t["buyer_name"] for t in truth}) >= 3
    assert {t["procedure_type"] for t in truth} == {"open", "restricted", "negotiated", "other"}
    assert {t["contract_nature"] for t in truth} == {"works", "services", "supplies"}
    zone = ZoneInfo(TIMEZONE)
    for t in truth:
        assert t["url"] == f"{BASE}/tenders/{t['id']}"
        assert isinstance(t["publication_date"], date) and t["publication_date"].year == 2026
        deadline = t["submission_deadline"]
        assert isinstance(deadline, datetime) and deadline.tzinfo == zone and deadline.year == 2027
        assert deadline.date() > t["publication_date"]
        assert t["status"] == "open" and t["country_code"] == "NL"
        assert t["cpv_codes"] and all(re.fullmatch(r"\d{8}", code) for code in t["cpv_codes"])
        assert 2 <= len(t["documents"]) <= 4
        assert "maintenance" not in t["title"].lower()
    newest_first = [t["publication_date"] for t in truth]
    assert newest_first == sorted(newest_first, reverse=True)


def test_a_larger_portal_keeps_its_dates_in_range():
    truth = MockPortal(tenders=400, page_size=100).truth()
    assert len(truth) == 400
    assert {t["publication_date"].year for t in truth} == {2026}
    assert {t["submission_deadline"].year for t in truth} == {2027}


# == The pages ==

def test_robots_allows_everything_by_default():
    status, headers, body = get(MockPortal(), "/robots.txt")
    assert status == 200 and headers["Content-Type"].startswith("text/plain")
    assert body == b"User-agent: *\nAllow: /\n"


def test_entry_page_links_to_the_list():
    root = page(MockPortal(), "/")
    assert [a.get("href") for a in root.cssselect("a.tender-list")] == ["/tenders"]


def test_list_page_shows_a_row_per_tender():
    portal = MockPortal()
    root = page(portal, "/tenders?page=1")
    rows = root.cssselect("table#tenders tr.tender")
    assert len(rows) == 20
    assert root.cssselect("p.total")[0].text_content() == "45 tenders found"
    first, truth = rows[0], portal.truth()[0]
    assert first.get("data-id") == NEWEST == truth["id"]
    assert first.cssselect("td.id")[0].text_content() == NEWEST
    link = first.cssselect("td.title a")[0]
    assert link.get("href") == f"/tenders/{NEWEST}" and link.text_content() == truth["title"]
    assert first.cssselect("td.buyer")[0].text_content() == truth["buyer_name"]
    assert first.cssselect("td.published")[0].text_content() == truth["publication_date"].strftime("%d.%m.%Y")
    deadline = first.cssselect("td.deadline time")[0]
    assert deadline.text_content() == truth["submission_deadline"].strftime("%d.%m.%Y %H:%M")
    assert deadline.get("datetime") == truth["submission_deadline"].strftime("%Y-%m-%dT%H:%M")
    assert first.cssselect("td.status")[0].text_content() == "Open"
    assert root.cssselect("nav.pages a[rel=next]")[0].get("href") == "/tenders?page=2"


def test_paging_covers_every_tender_exactly_once():
    portal = MockPortal()
    assert walk_list(portal) == portal.ids == [t["id"] for t in portal.truth()]
    assert len(list_ids(portal, "/tenders?page=3")) == 5
    assert not page(portal, "/tenders?page=3").cssselect("a[rel=next]")
    assert get(portal, "/tenders?page=4")[0] == 404
    assert get(portal, "/tenders?page=x")[0] == 404


def test_page_size_and_count_are_arguments():
    portal = MockPortal(tenders=7, page_size=3)
    assert walk_list(portal) == [f"MP-2026-{n:04d}" for n in range(7, 0, -1)]
    assert len(list_ids(portal)) == 3


def test_detail_page_shows_labels_and_values():
    portal = MockPortal()
    truth = next(t for t in portal.truth() if t["id"] == FIRST)
    facts = detail_facts(portal, FIRST)
    assert list(facts) == ["Tender number", "Reference", "Contracting authority", "Published",
                           "Deadline for tenders", "Status", "Procedure", "Type of contract", "CPV",
                           "Postal code", "City", "Country"]
    assert facts["Tender number"] == FIRST
    assert facts["Reference"] == truth["reference_number"]
    assert facts["Contracting authority"] == truth["buyer_name"]
    assert facts["Deadline for tenders"] == truth["submission_deadline"].strftime("%d.%m.%Y %H:%M")
    assert facts["Status"] == "Open" and facts["Country"] == "Netherlands"
    assert [code[:8] for code in facts["CPV"].split(", ")] == truth["cpv_codes"]
    assert all(re.fullmatch(r"\d{8}-\d", code) for code in facts["CPV"].split(", "))
    root = page(portal, f"/tenders/{FIRST}")
    assert root.cssselect("main h1")[0].text_content() == truth["title"]
    assert root.cssselect("section.description p")[0].text_content() == truth["description"]


def test_unknown_paths_answer_404():
    portal = MockPortal()
    for path in ("/nothing", "/tenders/MP-2026-9999", f"/files/{FIRST}/missing.pdf", "/files/x"):
        status, headers, body = get(portal, path)
        assert status == 404 and headers["Content-Type"] == "text/html; charset=utf-8", path
        assert b"Page not found" in body
    assert portal.respond("DELETE", BASE + "/tenders")[0] == 405


def test_a_post_is_answered_like_a_get():
    portal = MockPortal()
    assert portal.respond("POST", BASE + "/tenders", {"q": "roof"}) == get(portal, "/tenders")


# == The files ==

def test_files_are_valid_and_their_announced_sizes_are_exact():
    portal = MockPortal()
    seen: set[bytes] = set()
    zips = 0
    for truth in portal.truth():
        root = page(portal, f"/tenders/{truth['id']}")
        links = root.cssselect("ul.documents a.file")
        assert len(links) == len(truth["documents"])
        for link, (name, size, sha256) in zip(links, truth["documents"]):
            assert link.get("href") == f"/files/{truth['id']}/{name}"
            assert link.cssselect("span.name")[0].text_content() == name
            assert link.cssselect("span.size")[0].text_content() == f"{size:,} bytes"
            status, headers, body = get(portal, link.get("href"))
            assert status == 200
            assert int(headers["Content-Length"]) == len(body) == size
            assert hashlib.sha256(body).hexdigest() == sha256
            assert body not in seen
            seen.add(body)
            if name.endswith(".zip"):
                zips += 1
                assert headers["Content-Type"] == "application/zip"
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    assert archive.testzip() is None
                    entries = archive.namelist()
                    assert len(entries) == 2
                    assert all(archive.read(entry).startswith(b"%PDF-1.4") for entry in entries)
            else:
                assert headers["Content-Type"] == "application/pdf"
                assert body.startswith(b"%PDF-1.4") and body.rstrip().endswith(b"%%EOF")
                # The cross-reference table is where the trailer says it is.
                offset = int(re.search(rb"startxref\n(\d+)\n", body).group(1))
                assert body[offset:offset + 4] == b"xref"
    assert zips == 9  # one tender in five


# == The switches ==

def test_layout_changed_keeps_ids_and_values_in_other_elements():
    portal = MockPortal()
    portal.layout_changed = True
    root = page(portal, "/tenders")
    assert not root.cssselect("table#tenders") and not root.cssselect("tr.tender")
    assert not root.cssselect("p.total") and not root.cssselect("nav.pages")
    cards = root.cssselect("div.result-card")
    assert len(cards) == 20
    truth = portal.truth()
    assert [card.cssselect(".badge")[0].text_content() for card in cards] == [t["id"] for t in truth[:20]]
    card = cards[0]
    assert card.cssselect("h3 a")[0].get("href") == f"/tenders/{NEWEST}"
    assert card.cssselect("li.org strong")[0].text_content() == truth[0]["buyer_name"]
    assert card.cssselect("li.closes strong")[0].text_content() == \
        truth[0]["submission_deadline"].strftime("%d.%m.%Y %H:%M")
    assert root.cssselect("div.pager a.pager-next")[0].get("href") == "/tenders?page=2"

    detail = page(portal, f"/tenders/{NEWEST}")
    assert not detail.cssselect("dl") and not detail.cssselect("ul.documents")
    facts = {row[0].text_content(): row[1].text_content() for row in detail.cssselect("table.notice-facts tr")}
    assert "Deadline for tenders" not in facts
    assert facts["Closing date"] == truth[0]["submission_deadline"].strftime("%d.%m.%Y %H:%M")
    assert facts["Notice ID"] == NEWEST and facts["Buyer"] == truth[0]["buyer_name"]
    files = detail.cssselect("table.attachments a.download")
    assert [a.text_content() for a in files] == [name for name, _, _ in truth[0]["documents"]]
    assert get(portal, files[0].get("href"))[0] == 200


def test_outage_answers_503_everywhere():
    portal = MockPortal()
    portal.outage = True
    for path in ("/", "/tenders", f"/tenders/{FIRST}", f"/files/{FIRST}/tender-notice.pdf", "/robots.txt"):
        status, headers, body = get(portal, path)
        assert status == 503 and body and "Retry-After" not in headers, path


def test_maintenance_is_a_page_the_fetch_layer_recognises():
    portal = MockPortal()
    assert not maintenance_page(*get(portal, "/tenders")[::2])
    assert not maintenance_page(*get(portal, f"/tenders/{FIRST}")[::2])
    portal.maintenance = True
    for path in ("/", "/tenders", f"/tenders/{FIRST}"):
        status, _, body = get(portal, path)
        assert status == 200 and maintenance_page(status, body), path


def test_login_wall_in_front_of_the_documents():
    portal = MockPortal()
    portal.login_wall = "documents"
    status, headers, _ = get(portal, f"/files/{FIRST}/tender-notice.pdf")
    assert status == 302 and headers["Location"] == "/login"
    assert page(portal, "/login").cssselect("input[type=password]")
    assert get(portal, "/tenders")[0] == 200 and get(portal, f"/tenders/{FIRST}")[0] == 200


def test_login_wall_in_front_of_everything():
    portal = MockPortal()
    portal.login_wall = "all"
    for path in ("/", "/tenders", f"/tenders/{FIRST}", f"/files/{FIRST}/tender-notice.pdf"):
        status, headers, _ = get(portal, path)
        assert status == 302 and headers["Location"] == "/login", path
    assert get(portal, "/login")[0] == 200 and get(portal, "/robots.txt")[0] == 200


def test_list_emptied_with_the_notice():
    portal = MockPortal()
    portal.list_emptied = "with_notice"
    root = page(portal, "/tenders")
    assert not root.cssselect("tr.tender")
    assert root.cssselect("p.no-results")[0].text_content() == "No tenders are currently published."
    assert root.cssselect("p.total")[0].text_content() == "0 tenders found"
    assert get(portal, f"/tenders/{FIRST}")[0] == 200


def test_list_emptied_without_the_notice():
    portal = MockPortal()
    portal.list_emptied = "without_notice"
    status, _, body = get(portal, "/tenders")
    root = page(portal, "/tenders")
    assert status == 200 and not root.cssselect("tr.tender")
    assert not root.cssselect("p.no-results") and not root.cssselect("p.total")
    assert b"tenders found" not in body and b"No tenders" not in body


def test_withdrawn_tenders_show_cancelled():
    portal = MockPortal()
    portal.withdrawn = {NEWEST}
    rows = page(portal, "/tenders").cssselect("tr.tender")
    assert [row.cssselect("td.status")[0].text_content() for row in rows[:2]] == ["Cancelled", "Open"]
    assert detail_facts(portal, NEWEST)["Status"] == "Cancelled"
    assert detail_facts(portal, FIRST)["Status"] == "Open"
    assert [t["status"] for t in portal.truth()[:2]] == ["withdrawn", "open"]
    assert page(portal, "/tenders").cssselect("p.total")[0].text_content() == "45 tenders found"


def test_removed_tenders_are_gone():
    portal = MockPortal()
    portal.removed = {NEWEST, FIRST}
    ids = walk_list(portal)
    assert len(ids) == 43 and NEWEST not in ids and FIRST not in ids
    assert page(portal, "/tenders").cssselect("p.total")[0].text_content() == "43 tenders found"
    assert get(portal, f"/tenders/{NEWEST}")[0] == 404
    assert get(portal, f"/files/{NEWEST}/tender-notice.pdf")[0] == 404
    assert [t["id"] for t in portal.truth()] == ids


def test_paging_cut_serves_one_page_under_the_full_total():
    portal = MockPortal()
    portal.paging_cut = True
    root = page(portal, "/tenders")
    assert len(root.cssselect("tr.tender")) == 20 and not root.cssselect("a[rel=next]")
    assert root.cssselect("p.total")[0].text_content() == "45 tenders found"
    assert get(portal, "/tenders?page=2")[0] == 404


def test_rate_limited_answers_429_with_retry_after():
    portal = MockPortal()
    portal.rate_limited = True
    for path in ("/tenders", f"/tenders/{FIRST}", f"/files/{FIRST}/tender-notice.pdf"):
        status, headers, _ = get(portal, path)
        assert status == 429 and headers["Retry-After"] == "1", path


def test_captcha_marker_is_on_the_pages_and_blocks_nothing():
    portal = MockPortal()
    assert captcha_product(get(portal, "/tenders")[2]) is None
    portal.captcha_on_pages = True
    for path in ("/", "/tenders", f"/tenders/{FIRST}"):
        assert captcha_product(get(portal, path)[2]) == "reCAPTCHA", path
    assert walk_list(portal) == portal.ids
    assert get(portal, f"/files/{FIRST}/tender-notice.pdf")[2].startswith(b"%PDF-1.4")


def test_robots_can_forbid_every_path():
    portal = MockPortal()
    portal.robots_disallow_all = True
    assert get(portal, "/robots.txt")[2] == b"User-agent: *\nDisallow: /\n"


def test_deadline_moved_shows_on_the_detail_page_only():
    portal = MockPortal()
    before = portal.truth()[0]["submission_deadline"]
    portal.deadline_moved = {NEWEST: "30.09.2027 15:30"}
    assert detail_facts(portal, NEWEST)["Deadline for tenders"] == "30.09.2027 15:30"
    row = page(portal, "/tenders").cssselect("tr.tender")[0]
    assert row.cssselect("td.deadline")[0].text_content() == before.strftime("%d.%m.%Y %H:%M")
    assert portal.truth()[0]["submission_deadline"] == datetime(2027, 9, 30, 15, 30, tzinfo=ZoneInfo(TIMEZONE))
    assert portal.truth()[1]["submission_deadline"].strftime("%d.%m.%Y %H:%M") == \
        detail_facts(portal, portal.ids[1])["Deadline for tenders"]


def test_columns_swapped_leaves_two_valid_dates_in_the_wrong_cells():
    portal = MockPortal()
    truth = portal.truth()[0]
    portal.columns_swapped = True
    row = page(portal, "/tenders").cssselect("tr.tender")[0]
    published = row.cssselect("td.published")[0].text_content()
    deadline = row.cssselect("td.deadline")[0].text_content()
    assert datetime.strptime(published, "%d.%m.%Y").date() == truth["submission_deadline"].date()
    assert datetime.strptime(deadline, "%d.%m.%Y %H:%M").date() == truth["publication_date"]
    assert datetime.strptime(row.cssselect("td.deadline time")[0].get("datetime"), "%Y-%m-%dT%H:%M") == \
        datetime.strptime(deadline, "%d.%m.%Y %H:%M")
    # The tender's own page is not touched.
    assert detail_facts(portal, NEWEST)["Published"] == truth["publication_date"].strftime("%d.%m.%Y")


def test_reset_puts_every_switch_back():
    portal = MockPortal()
    fresh = dict(vars(MockPortal()))
    portal.layout_changed = portal.outage = portal.maintenance = portal.paging_cut = True
    portal.rate_limited = portal.captcha_on_pages = portal.robots_disallow_all = portal.columns_swapped = True
    portal.login_wall, portal.list_emptied = "all", "with_notice"
    portal.withdrawn, portal.removed, portal.deadline_moved = {FIRST}, {NEWEST}, {FIRST: "01.02.2027 10:00"}
    portal.reset()
    switches = {name: value for name, value in vars(portal).items() if not name.startswith("_")}
    assert switches == {name: value for name, value in fresh.items() if not name.startswith("_")}
    assert walk_list(portal) == portal.ids


def test_a_misspelt_switch_value_is_refused():
    portal = MockPortal()
    portal.login_wall = "everything"
    with pytest.raises(ValueError, match="login_wall"):
        get(portal, "/tenders")


def test_requests_are_counted():
    portal = MockPortal()
    get(portal, "/tenders?page=2")
    portal.respond("POST", f"/tenders/{FIRST}", {})
    get(portal, "/nothing")
    assert portal.requests == [("GET", "/tenders"), ("POST", f"/tenders/{FIRST}"), ("GET", "/nothing")]


# == Under a mount, and behind the real network layer ==

def test_links_carry_the_root_path():
    portal = MockPortal(root_path="/mock")
    assert portal.truth()[0]["url"] == f"{BASE}/mock/tenders/{NEWEST}"
    root = page(portal, "/mock/tenders")
    assert root.cssselect("td.title a")[0].get("href") == f"/mock/tenders/{NEWEST}"
    assert root.cssselect("a[rel=next]")[0].get("href") == "/mock/tenders?page=2"
    file = page(portal, f"/mock/tenders/{NEWEST}").cssselect("a.file")[0].get("href")
    assert file.startswith(f"/mock/files/{NEWEST}/") and get(portal, file)[0] == 200
    assert portal.requests[0] == ("GET", "/tenders")
    portal.login_wall = "all"
    assert get(portal, "/mock/tenders")[1]["Location"] == "/mock/login"


def test_the_portal_works_behind_the_fetcher():
    portal = MockPortal()
    fetcher = make_fetcher(portal, robots=True)
    fetched = fetcher.fetch("mock", portal.base_url + "/tenders")
    assert fetched.status == 200 and fetched.content_type == "text/html"
    root = parse_page(fetched.body, NodeKind.html, fetched.final_url, fetched.headers["content-type"]).root
    assert [row.get("data-id") for row in root.cssselect("tr.tender")] == portal.ids[:20]
    assert portal.requests == [("GET", "/robots.txt"), ("GET", "/tenders")]
    assert not fetched.answer.maintenance and fetched.answer.captcha is None
    assert not fetched.answer.password_field and fetched.answer.login_redirect is None


def test_the_fetcher_sees_the_signs_the_switches_put_up():
    portal = MockPortal()
    fetcher = make_fetcher(portal)
    address = portal.base_url + "/tenders"

    portal.login_wall = "all"
    walled = fetcher.fetch("mock", address)
    assert walled.final_url.endswith("/login") and walled.answer.login_redirect == "/login"
    assert walled.answer.password_field

    portal.reset()
    portal.maintenance = True
    assert fetcher.fetch("mock", address).answer.maintenance

    portal.reset()
    portal.captcha_on_pages = True
    assert fetcher.fetch("mock", address).answer.captcha == "reCAPTCHA"

    portal.reset()
    with fetcher.download("mock", portal.file_url(FIRST, "tender-notice.pdf")) as download:
        assert download.status == 200


def test_the_asgi_app_serves_the_portal_under_a_mount():
    portal = MockPortal()
    app = portal.asgi()

    def call(method: str, path: str, query: bytes = b"", body: bytes = b"") -> tuple[int, dict[str, str], bytes]:
        sent: list[dict] = []
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": query,
                 "root_path": "/mock", "headers": [], "server": ("testserver", 80)}
        inbox = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive() -> dict:
            return inbox.pop(0) if inbox else {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            sent.append(message)

        asyncio.run(app(scope, receive, send))
        start, content = sent
        assert start["type"] == "http.response.start" and content["type"] == "http.response.body"
        headers = {name.decode(): value.decode() for name, value in start["headers"]}
        return start["status"], headers, content["body"]

    # Starlette hands a mounted app the full path together with the mount's root path.
    status, headers, body = call("GET", "/mock/tenders", b"page=3")
    assert status == 200 and headers["content-type"] == "text/html; charset=utf-8"
    assert int(headers["content-length"]) == len(body)
    root = parse_page(body, NodeKind.html, "http://testserver/mock/tenders?page=3").root
    rows = root.cssselect("tr.tender")
    assert len(rows) == 5
    assert rows[0].cssselect("td.title a")[0].get("href").startswith("/mock/tenders/MP-2026-")

    status, headers, body = call("GET", f"/mock/files/{FIRST}/tender-notice.pdf")
    assert status == 200 and headers["content-type"] == "application/pdf" and body.startswith(b"%PDF-1.4")
    # Older servers strip the mount from the path; the portal answers that as well.
    assert call("POST", f"/tenders/{FIRST}", body=b"a=b")[0] == 200
    assert call("GET", "/mock/nothing")[0] == 404
    assert portal.requests == [("GET", "/tenders"), ("GET", f"/files/{FIRST}/tender-notice.pdf"),
                               ("POST", f"/tenders/{FIRST}"), ("GET", "/nothing")]


def test_the_asgi_app_acknowledges_the_lifespan():
    app = MockPortal().asgi()
    inbox = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    sent: list[dict] = []

    async def receive() -> dict:
        return inbox.pop(0)

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(app({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send))
    assert [m["type"] for m in sent] == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
