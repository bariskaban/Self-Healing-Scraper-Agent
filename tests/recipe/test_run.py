"""The executor on pages written here and on the mock portal. No request leaves the process."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.checks import LookOutcome
from app.fetch import Fetcher, FetchMode, FetchSettings, PortalLimiter
from app.models import Portal, url_key
from app.recipe.build import css, field, label
from app.recipe.locate import parse_page
from app.recipe.resolve import read_fields, read_id, settle_single_witnesses
from app.recipe.run import (
    CachedPage, PageCache, dry_run, judge_look, known_item, read_detail, read_list, settle,
)
from app.recipe.schema import FieldName as F, NodeKind, ValueType as T
from app.extract import ParseContext
from mock_portal import TIMEZONE, MockPortal, recipe as mock_recipe
from tests.recipe.examples import form_post_portal, html_table_portal, json_api_portal

BERLIN = ZoneInfo("Europe/Berlin")


def portal(url: str, zone: str = "Europe/Berlin") -> Portal:
    return Portal(id="p1", url=url, url_key=url_key(url), timezone=zone)


def context(url: str = "https://x.example/") -> ParseContext:
    return ParseContext(zone=BERLIN, page_url=url, language="de")


def html_doc(body: str, url: str = "https://x.example/"):
    return parse_page(f"<html><body>{body}</body></html>", NodeKind.html, url, "text/html")


# == Q2's rule ==

DEADLINE = field(F.submission_deadline, css("td.frist"), css("time", attr="datetime"), type=T.datetime,
                 formats=["%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M"])


def test_locators_that_agree_give_the_value():
    doc = html_doc('<table><tr><td class="frist">12.03.2027 10:00 <time datetime="2027-03-12T10:00"></time></td></tr></table>')
    read = read_fields([DEADLINE], doc, context())[F.submission_deadline]
    assert read.value == datetime(2027, 3, 12, 10, 0, tzinfo=BERLIN)
    assert read.flag is None and read.witnesses == 2


def test_locators_that_differ_give_null_and_a_conflict():
    doc = html_doc('<table><tr><td class="frist">12.03.2027 10:00 <time datetime="2027-03-13T10:00"></time></td></tr></table>')
    read = read_fields([DEADLINE], doc, context())[F.submission_deadline]
    assert read.value is None and read.flag == "conflict"
    assert read.raw  # the text stays, so check C2 can say "not read"


def test_a_date_and_the_same_day_with_its_time_are_not_a_conflict():
    spec = field(F.submission_deadline, css("td.frist"), css("time", attr="datetime"), type=T.datetime,
                 formats=["%d.%m.%Y", "%Y-%m-%dT%H:%M"])
    doc = html_doc('<table><tr><td class="frist">12.03.2027</td><td><time datetime="2027-03-12T10:00"></time></td></tr></table>')
    read = read_fields([spec], doc, context())[F.submission_deadline]
    assert read.value == datetime(2027, 3, 12, 10, 0, tzinfo=BERLIN) and read.flag is None


def test_one_locator_of_two_is_a_single_witness_and_one_of_one_is_not():
    doc = html_doc('<table><tr><td class="frist">12.03.2027 10:00</td></tr></table>')
    assert read_fields([DEADLINE], doc, context())[F.submission_deadline].flag == "single_witness"
    alone = field(F.title, css("td.frist"))
    assert read_fields([alone], doc, context())[F.title].flag is None


def _witness(value: str):
    doc = html_doc(f'<p class="a">{value}</p>')
    return read_fields([field(F.title, css("p.a"), css("p.b"))], doc, context())


def _record(tender_id: str, title: str | None):
    from app.models import TenderRecord
    return TenderRecord(portal_id="p1", tender_id=tender_id, title=title)


def test_single_witnesses_are_kept_at_the_attach():
    settled = settle_single_witnesses({"A": _witness("Road works")}, None)
    assert settled["A"][F.title].value == "Road works"


def test_a_single_witness_must_equal_the_last_good_value():
    rows = {"A": _witness("Road works"), "B": _witness("Something else")}
    last = {"A": _record("A", "Road works"), "B": _record("B", "Bridge repair")}
    settled = settle_single_witnesses(rows, last)
    assert settled["A"][F.title].value == "Road works"
    assert settled["B"][F.title].value is None and settled["B"][F.title].flag == "single_witness"


def test_a_new_tender_keeps_its_single_witness_only_when_the_known_ones_vouch_for_the_locator():
    known = {f"K{i}": _witness(f"Title {i}") for i in range(5)}
    good = {f"K{i}": _record(f"K{i}", f"Title {i}") for i in range(5)}
    moved = {f"K{i}": _record(f"K{i}", f"Other {i}") for i in range(5)}
    rows = {**known, "NEW": _witness("A new tender")}
    assert settle_single_witnesses(rows, good)["NEW"][F.title].value == "A new tender"
    assert settle_single_witnesses(rows, moved)["NEW"][F.title].value is None
    assert settle_single_witnesses({"NEW": _witness("A new tender")}, good)["NEW"][F.title].value is None


def test_the_id_must_match_the_shape_and_agree_with_the_address():
    identity = html_table_portal().identity
    fields = read_fields([field(F.id, css("b"), type=T.id)], html_doc("<b>2026-1234</b>"), context())
    assert read_id(identity, fields, "https://x.example/ausschreibungen/2026-1234").tender_id == "2026-1234"
    assert read_id(identity, fields, "https://x.example/ausschreibungen/2026-9999").tender_id is None
    assert read_id(identity, {}, "https://x.example/ausschreibungen/2026-1234").tender_id == "2026-1234"
    odd = read_fields([field(F.id, css("b"), type=T.id)], html_doc("<b>Bekanntmachung</b>"), context())
    assert read_id(identity, odd, None).tender_id is None


# == An HTML table with a detail page ==

def _row(n: int) -> str:
    return (f'<tr><td class="aktenzeichen">2026-{n:04d}</td>'
            f'<td><a class="titel" data-id="2026-{n:04d}" href="/ausschreibungen/2026-{n:04d}">Auftrag {n}</a></td>'
            f'<td class="frist">12.03.2027 10:00 <time datetime="2027-03-12T10:00"></time></td></tr>')


def _list_page(rows: range, total: int, next_href: str | None) -> str:
    nav = f'<nav class="seiten"><a rel="next" href="{next_href}">weiter</a></nav>' if next_href else ""
    return (f"<html><body><p>{total} Ausschreibungen gefunden</p>"
            f'<table id="vergaben"><tbody>{"".join(_row(n) for n in rows)}</tbody></table>{nav}</body></html>')


def _detail_page(n: int, status: str = "Laufend") -> str:
    return f"""<html><body><dl>
      <dt>Aktenzeichen</dt><dd>2026-{n:04d}</dd>
      <dt>Auftraggeber</dt><dd>Stadt Musterhausen</dd>
      <dt>Veröffentlicht am</dt><dd>01.02.2027</dd>
      <dt>Angebotsfrist</dt><dd>12.03.2027 10:00</dd>
      <dt>Status</dt><dd>{status}</dd>
      <dt>Verfahrensart</dt><dd>Offenes Verfahren</dd>
      <dt>Auftragsart</dt><dd>Bauleistung</dd>
      <dt>CPV-Code</dt><dd>45000000-7, 45233120-6</dd></dl>
      <div class="auftraggeber"><span class="name">Stadt Musterhausen</span></div>
      <section class="beschreibung">Sanierung der Hauptstraße.</section>
      <span class="plz">50667</span> <span class="ort">Köln</span>
      <ul class="unterlagen">
        <li><a class="datei" href="/dl/{n}/lv.pdf"><span class="name">Leistungsverzeichnis.pdf</span> <span class="groesse">12.345 Bytes</span></a></li>
        <li><a class="datei" href="/dl/{n}/plan.zip"><span class="name">Pläne.zip</span> <span class="groesse">1,2 MB</span></a></li>
      </ul></body></html>"""


BASE = "https://vergabe.example"


def html_pages() -> list[CachedPage]:
    pages = [
        CachedPage(f"{BASE}/ausschreibungen?sort=neueste", _list_page(range(1, 4), 5, "/ausschreibungen?sort=neueste&seite=2")),
        CachedPage(f"{BASE}/ausschreibungen?sort=neueste&seite=2", _list_page(range(4, 6), 5, None)),
    ]
    pages += [CachedPage(f"{BASE}/ausschreibungen/2026-{n:04d}", _detail_page(n)) for n in range(1, 6)]
    return pages


def test_an_html_list_is_paged_to_its_end_with_the_facts_the_checks_need():
    read = read_list(html_table_portal(), PageCache(html_pages()), portal(BASE))
    assert [item.tender_id for item in read.items] == [f"2026-{n:04d}" for n in range(1, 6)]
    assert (read.rows, read.pages, read.reached_end, read.printed_total) == (5, 2, True, 5)
    assert read.problems == [] and read.dropped == [] and not read.empty_marker
    assert len(read.exchanges) == 2 and all(exchange.ok for exchange in read.exchanges)
    assert read.structure_paths and len({item.row_hash for item in read.items}) == 5
    first = read.items[0]
    assert first.address == f"{BASE}/ausschreibungen/2026-0001"
    assert first.deadline == datetime(2027, 3, 12, 10, 0, tzinfo=BERLIN)


def test_the_first_page_alone_does_not_claim_the_end():
    read = read_list(html_table_portal(), PageCache(html_pages()), portal(BASE), first_page_only=True)
    assert (read.pages, len(read.items), read.reached_end) == (1, 3, False)


def test_the_list_is_cut_at_the_limit_per_portal_and_then_counts_as_partial():
    from app.recipe.settings import RecipeSettings
    read = read_list(html_table_portal(), PageCache(html_pages()), portal(BASE),
                     settings=RecipeSettings(max_tenders_per_portal=4))
    assert [item.tender_id for item in read.items] == [f"2026-{n:04d}" for n in range(1, 5)]   # the first four
    assert (read.capped, read.partial, read.reached_end, read.pages) == (True, True, False, 2)
    assert not read.first_page_only


def test_a_limit_above_the_list_or_zero_changes_nothing():
    from app.recipe.settings import RecipeSettings
    for limit in (0, 5, 50):   # exactly as many as the list holds is not a cut
        read = read_list(html_table_portal(), PageCache(html_pages()), portal(BASE),
                         settings=RecipeSettings(max_tenders_per_portal=limit))
        assert len(read.items) == 5 and not read.capped and not read.partial and read.reached_end


def test_the_limit_is_a_setting_from_the_environment_and_cannot_be_negative():
    from app.recipe.settings import RecipeSettings
    assert RecipeSettings().max_tenders_per_portal == 2000
    assert RecipeSettings.from_env({"RECIPE_MAX_TENDERS_PER_PORTAL": "50"}).max_tenders_per_portal == 50
    with pytest.raises(ValueError):
        RecipeSettings(max_tenders_per_portal=-1)


def test_a_detail_page_adds_fields_and_documents():
    recipe, source, where = html_table_portal(), PageCache(html_pages()), portal(BASE)
    item = read_list(recipe, source, where).items[0]
    detail = read_detail(recipe, source, where, item)
    assert detail.complete and detail.problems == []
    record = settle("p1", {item.tender_id: detail.fields}, last_good=None)[item.tender_id]
    assert record.buyer_name == "Stadt Musterhausen"
    assert record.publication_date == date(2027, 2, 1)
    assert record.submission_deadline == datetime(2027, 3, 12, 10, 0, tzinfo=BERLIN)
    assert (record.procedure_type, record.contract_nature) == ("open", "works")
    assert record.cpv_codes == ["45000000", "45233120"]
    assert (record.place.postalCode, record.place.city) == ("50667", "Köln")
    assert record.url == f"{BASE}/ausschreibungen/2026-0001" and not record.withdrawn
    assert record.raw["submission_deadline"].startswith("12.03.2027")
    assert [(d.source_url, d.name, d.size_bytes) for d in detail.documents] == [
        (f"{BASE}/dl/1/lv.pdf", "Leistungsverzeichnis.pdf", 12345),
        (f"{BASE}/dl/1/plan.zip", "Pläne.zip", None),  # a rounded size is not an exact one
    ]


def test_a_value_that_differs_between_the_list_and_the_detail_page_is_a_conflict():
    pages = html_pages()
    pages[2] = CachedPage(pages[2].url, _detail_page(1).replace("12.03.2027 10:00", "19.03.2027 10:00"))
    recipe, source, where = html_table_portal(), PageCache(pages), portal(BASE)
    item = read_list(recipe, source, where).items[0]
    read = read_detail(recipe, source, where, item).fields[F.submission_deadline]
    assert read.value is None and read.flag == "conflict"


def test_a_row_whose_id_disagrees_with_its_address_is_left_out():
    pages = html_pages()
    pages[0] = CachedPage(pages[0].url, str(pages[0].body).replace('href="/ausschreibungen/2026-0002"',
                                                                  'href="/ausschreibungen/2026-0777"'))
    read = read_list(html_table_portal(), PageCache(pages), portal(BASE))
    assert "2026-0002" not in [item.tender_id for item in read.items]
    assert read.rows == 5 and len(read.items) == 4 and len(read.dropped) == 1


def test_a_page_that_repeats_the_last_one_ends_the_list_and_shows_as_duplicates():
    pages = html_pages()
    pages[1] = CachedPage(pages[1].url, _list_page(range(1, 4), 5, "/ausschreibungen?sort=neueste&seite=3"))
    read = read_list(html_table_portal(), PageCache(pages), portal(BASE))
    assert read.reached_end and read.pages == 2 and len(read.items) == 3
    assert sorted(read.duplicate_ids) == ["2026-0001", "2026-0002", "2026-0003"]


def test_a_tender_of_an_earlier_read_can_be_looked_at_without_the_list():
    recipe, where = html_table_portal(), portal(BASE)
    source = PageCache(html_pages())
    item = read_list(recipe, source, where).items[0]
    record = settle("p1", {item.tender_id: read_detail(recipe, source, where, item).fields}, last_good=None,
                    addresses={item.tender_id: item.address})[item.tender_id]
    now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    again = known_item(recipe, where, record)
    assert judge_look(recipe, read_detail(recipe, source, where, again), now) is LookOutcome.still_open
    assert judge_look(recipe, read_detail(recipe, source, where, again), now + timedelta(days=365)) is LookOutcome.closed
    withdrawn = PageCache([CachedPage(record.url, _detail_page(1, "Aufgehoben"))])
    assert judge_look(recipe, read_detail(recipe, withdrawn, where, again), now) is LookOutcome.withdrawn
    gone = PageCache([CachedPage(record.url, "<html><body>Nicht gefunden</body></html>", status=404)])
    assert judge_look(recipe, read_detail(recipe, gone, where, again), now) is LookOutcome.gone


# == A JSON API ==

API = "https://api.example"


def _publication(n: int) -> dict:
    return {"publicatieId": 100000 + n, "aanbestedingNaam": f"Opdracht {n}", "opdrachtgeverNaam": "Gemeente Voorbeeld",
            "publicatieDatum": "2027-01-15", "sluitingsDatum": "2027-03-01T12:00:00+01:00",
            "procedure": {"code": "OPE"}, "typeOpdracht": {"code": "D"}, "laatsteWijziging": f"2027-01-{10 + n}"}


def json_pages(total: int = 3, size: int = 2) -> list[CachedPage]:
    def page(number: int) -> CachedPage:
        content = [_publication(n) for n in range(number * size + 1, min(total, (number + 1) * size) + 1)]
        return CachedPage(f"{API}/papi/v2/publicaties?page={number}&size=100&publicatieType=AAO",
                          json.dumps({"content": content, "totalElements": total}), content_type="application/json")
    pages = [page(0)]
    for n in range(1, total + 1):
        tender = 100000 + n
        pages.append(CachedPage(f"{API}/papi/v2/publicaties/{tender}", json.dumps({
            "linkNaarAankondiging": f"https://www.example/aankondigingen/{tender}", "opdrachtBeschrijving": "Schoonmaak",
            "referentieNummer": f"REF-{n}", "cpvCodes": [{"code": "90910000-9"}, {"code": "90911200-8"}],
            "aanbestedingStatus": "ACTIEF", "plaatsVanUitvoering": {"plaats": "Utrecht", "land": "Nederland"},
        }), content_type="application/json"))
        pages.append(CachedPage(f"{API}/papi/v2/publicaties/{tender}/documenten",
                                json.dumps({"zipLink": "zip"}), content_type="application/json"))
    return pages


def test_a_json_api_is_read_with_its_page_parameter_detail_call_and_zip():
    recipe, where = json_api_portal(), portal(API, "Europe/Amsterdam")
    source = PageCache(json_pages(total=3, size=100))
    read = read_list(recipe, source, where)
    assert [item.tender_id for item in read.items] == ["100001", "100002", "100003"]
    assert (read.printed_total, read.reached_end, read.problems) == (3, True, [])
    detail = read_detail(recipe, source, where, read.items[0])
    assert detail.complete, detail.problems
    record = settle("p1", {"100001": detail.fields}, last_good=None)["100001"]
    assert record.title == "Opdracht 1" and record.url == "https://www.example/aankondigingen/100001"
    assert record.submission_deadline == datetime(2027, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=1)))
    assert record.cpv_codes == ["90910000", "90911200"] and record.place.countryCode == "NL"
    assert (record.procedure_type, record.contract_nature) == ("open", "services")
    assert [d.source_url for d in detail.documents] == [f"{API}/papi/v2/publicaties/100001/documenten/zip"]


def test_an_api_that_answers_with_an_empty_list_says_the_portal_is_empty():
    page = CachedPage(f"{API}/papi/v2/publicaties?page=0&size=100&publicatieType=AAO",
                      json.dumps({"content": [], "totalElements": 0}), content_type="application/json")
    read = read_list(json_api_portal(), PageCache([page]), portal(API))
    assert read.rows == 0 and read.api_empty and read.printed_total == 0 and read.reached_end


def test_the_row_hash_moves_with_the_portals_own_change_mark():
    recipe, where = json_api_portal(), portal(API)
    before = read_list(recipe, PageCache(json_pages(3, 100)), where).items[0].row_hash
    pages = json_pages(3, 100)
    pages[0] = CachedPage(pages[0].url, str(pages[0].body).replace("2027-01-11", "2027-02-02"),
                          content_type="application/json")
    assert read_list(recipe, PageCache(pages), where).items[0].row_hash != before


# == A list behind a search form, paged by form post ==

FORM = "https://forms.example"


def _results(numbers: range, more: bool) -> str:
    rows = "".join(
        f'<div class="result"><h3><a href="/view?tender=AB{n:06d}">Tender {n}</a></h3><span class="buyer">Council</span>'
        f'<span class="published">01/02/2027</span><span class="deadline">15/03/2027 12:00</span>'
        f'<a class="documents" href="/docs?tender=AB{n:06d}">Documents</a></div>' for n in numbers)
    pager = ('<form id="pager" method="post" action="/results"><input type="hidden" name="__STATE" value="s2">'
             '<input type="hidden" name="page" value="2"><input type="submit" value="Next"></form>') if more else ""
    return f'<html><body><span id="resultCount">3</span>{rows}{pager}</body></html>'


def test_a_search_form_then_paging_by_form_post_then_a_terms_page_per_file():
    posts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path, form = request.url.path, dict(httpx.QueryParams(request.content.decode()))
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/":
            return httpx.Response(200, html='<form id="search" method="post" action="/results">'
                                            '<input type="hidden" name="token" value="t1">'
                                            '<select name="status"><option value="all" selected>All</option></select></form>')
        if path == "/results":
            posts.append(form)
            return httpx.Response(200, html=_results(range(1, 3), True) if "page" not in form else _results(range(3, 4), False))
        if path == "/docs":
            return httpx.Response(200, html='<table class="docs"><tr><td class="filename">Spec.pdf</td>'
                                            '<td><a class="open" href="/terms?f=7">Open</a></td></tr></table>')
        if path == "/terms":
            return httpx.Response(200, html='<a id="confirm-download" href="/file/7/spec.pdf">I agree</a>')
        return httpx.Response(404)

    clock = [0.0]
    limiter = PortalLimiter(1.0, 10.0, clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    source = Fetcher(FetchSettings(mode=FetchMode.live), transport=httpx.MockTransport(handler), limiter=limiter,
                     clock=lambda: clock[0], rng=lambda: 0.0)
    recipe, where = form_post_portal(), portal(FORM, "Europe/London")
    read = read_list(recipe, source, where)
    assert read.problems == []
    assert [item.tender_id for item in read.items] == ["AB000001", "AB000002", "AB000003"]
    assert (read.pages, read.reached_end, read.printed_total) == (2, True, 3)
    assert posts[0] == {"token": "t1", "status": "open"}   # the form's own fields, the recipe's on top
    assert posts[1] == {"__STATE": "s2", "page": "2"}      # the pager's hidden state
    detail = read_detail(recipe, source, where, read.items[0])
    assert [d.source_url for d in detail.documents] == [f"{FORM}/file/7/spec.pdf"]
    assert detail.complete and len(detail.exchanges) == 2


# == Dry run ==

def test_a_dry_run_gives_records_and_names_the_pages_it_lacks():
    full = dry_run(html_table_portal(), html_pages(), url=BASE, timezone="Europe/Berlin")
    assert full.ok and len(full.records) == 5 and full.details_read == 5 and full.missing_pages == []
    assert full.filled["submission_deadline"] == 5 and full.single_witnesses.get("buyer_name") is None
    assert len(full.documents["2026-0001"]) == 2

    partial = dry_run(html_table_portal(), html_pages()[:1], url=BASE, timezone="Europe/Berlin")
    assert len(partial.records) == 3 and not partial.reached_end
    assert f"GET {BASE}/ausschreibungen?sort=neueste&seite=2" in partial.missing_pages
    assert partial.problems == []


def test_a_dry_run_says_what_is_wrong():
    broken = html_table_portal()
    broken.nodes[0].items.expr = "table#nothing tr"
    result = dry_run(broken, html_pages(), url=BASE, timezone="Europe/Berlin")
    assert not result.ok and result.problems == ["The item locator matched no row on the list."]
    invalid = html_table_portal()
    invalid.start = "nowhere"
    assert "not a node" in dry_run(invalid, html_pages(), url=BASE).problems[0]


# == The mock portal, through the real network layer ==

@pytest.fixture
def mock():
    site = MockPortal()
    clock = [0.0]
    limiter = PortalLimiter(1.0, 10.0, clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    source = Fetcher(FetchSettings(mode=FetchMode.live), transport=httpx.MockTransport(site.handle), limiter=limiter,
                     clock=lambda: clock[0], rng=lambda: 0.0)
    return site, source, portal(site.base_url, TIMEZONE)


def test_the_mock_portal_is_read_exactly_as_it_is(mock):
    site, source, where = mock
    recipe = mock_recipe()
    listed = read_list(recipe, source, where)
    assert (listed.rows, listed.pages, listed.reached_end, listed.printed_total) == (45, 3, True, 45)
    reads, documents, addresses = {}, {}, {}
    for item in listed.items:
        detail = read_detail(recipe, source, where, item)
        assert detail.complete, detail.problems
        reads[item.tender_id], documents[item.tender_id] = detail.fields, detail.documents
        addresses[item.tender_id] = item.address
        assert all(read.flag is None for read in detail.fields.values())
    records = settle("p1", reads, last_good=None, addresses=addresses)
    truth = {tender["id"]: tender for tender in site.truth()}
    assert set(records) == set(truth)
    for tender_id, record in records.items():
        want = truth[tender_id]
        got = {
            "url": record.url, "title": record.title, "buyer_name": record.buyer_name,
            "publication_date": record.publication_date, "submission_deadline": record.submission_deadline,
            "reference_number": record.reference_number, "description": record.description,
            "procedure_type": record.procedure_type, "contract_nature": record.contract_nature,
            "cpv_codes": record.cpv_codes, "postal_code": record.place.postalCode, "city": record.place.city,
            "country_code": record.place.countryCode,
        }
        assert got == {name: want[name] for name in got}, tender_id
        assert [(d.name, d.size_bytes) for d in documents[tender_id]] == [(n, s) for n, s, _ in want["documents"]]
    assert len(site.requests) == 1 + 3 + 45  # robots.txt, three list pages, one page per tender


@pytest.mark.parametrize("switch, value, expect", [
    ("outage", True, dict(rows=0, pages=0, reached_end=False)),
    ("layout_changed", True, dict(rows=0, pages=1, empty_marker=False, printed_total=None)),
    ("list_emptied", "with_notice", dict(rows=0, empty_marker=True, printed_total=0)),
    ("list_emptied", "without_notice", dict(rows=0, empty_marker=False, printed_total=None)),
    ("paging_cut", True, dict(rows=20, pages=1, printed_total=45)),
])
def test_what_the_list_read_reports_when_the_mock_portal_breaks(mock, switch, value, expect):
    site, source, where = mock
    setattr(site, switch, value)
    read = read_list(mock_recipe(), source, where)
    assert {name: getattr(read, name) for name in expect} == expect


def test_a_login_wall_and_a_maintenance_page_reach_the_checks_as_facts(mock):
    site, source, where = mock
    site.login_wall = "all"
    assert read_list(mock_recipe(), source, where).list_answer.login_redirect == "/login"
    site.reset()
    site.maintenance = True
    assert read_list(mock_recipe(), source, where).list_answer.maintenance
    site.reset()
    site.outage = True
    read = read_list(mock_recipe(), source, where)
    assert read.list_answer.status == 503 and not read.exchanges[-1].answered
