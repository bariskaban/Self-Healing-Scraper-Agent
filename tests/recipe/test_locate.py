"""The locators (app/recipe/locate.py). Run: pytest tests/recipe/test_locate.py

Every document is written here; nothing is fetched.
"""
from __future__ import annotations

import json

import pytest

from app.recipe.build import css, jsonpath, label, regex, xpath
from app.recipe.locate import Doc, Found, PageError, find, find_items, first_text, parse_page, try_locator
from app.recipe.schema import Locator, LocatorKind, NodeKind

URL = "https://vergabe.example.test/ausschreibungen"

LIST_PAGE = """<!DOCTYPE html>
<html><head><title>Ausschreibungen</title><style>td { color: red }</style></head>
<body>
<p class="treffer">2 Ausschreibungen gefunden</p>
<table id="vergaben">
  <thead><tr><th>Aktenzeichen</th><th>Titel</th><th>Frist</th></tr></thead>
  <tbody>
    <tr>
      <td class="aktenzeichen">2026-0101</td>
      <td><a class="titel" data-id="2026-0101" href="/ausschreibungen/2026-0101">Neubau
          Kita&nbsp;Sonnenschein</a></td>
      <td class="frist"><time datetime="2026-03-01T10:00">01.03.2026 10:00</time></td>
    </tr>
    <tr>
      <td class="aktenzeichen">2026-0102</td>
      <td><a class="titel" data-id="2026-0102" href="/ausschreibungen/2026-0102">Straßenreinigung</a></td>
      <td class="frist"></td>
    </tr>
  </tbody>
</table>
<nav class="seiten"><a href="?seite=1">1</a> <a rel="next" href="?seite=2">weiter</a></nav>
<script>var frist = "31.12.2099";</script>
</body></html>"""

DETAIL_DL = """<html><body>
<h1>Neubau Kita Sonnenschein</h1>
<dl class="eckdaten">
  <dt>Aktenzeichen</dt><dd>2026-0101</dd>
  <dt>Angebotsfrist:</dt><dd>01.03.2026 10:00</dd>
  <dt>STATUS</dt><dd>Laufend</dd>
</dl>
<p>Die Angebotsfrist endet am 15.04.2026. Fragen zur Angebotsfrist richten Sie an die Vergabestelle.</p>
</body></html>"""

DETAIL_TABLE = """<html><body>
<table class="daten">
  <tr><th>Auftraggeber</th><td>Stadt Musterstadt</td></tr>
  <tr><td>angebotsfrist:</td><td>01.03.2026 10:00</td></tr>
  <tr><td>CPV-Code</td><td>45214100-1</td></tr>
</table>
</body></html>"""

DETAIL_INLINE = """<html><body>
<div class="kasten">
  <p>Veröffentlicht am: 12.02.2026</p>
  <p><b>Abgabefrist:</b> 01.03.2026 10:00</p>
  <div class="zeile"><span class="name">Verfahrensart</span><span class="wert">Offenes Verfahren</span></div>
  <div class="zeile"><div class="name">Auftragsart</div><div class="wert">Bauleistung</div></div>
  <p>Hinweis: <b>Auftragsart</b> und Umfang siehe Leistungsbeschreibung.</p>
</div>
</body></html>"""

JSON_LIST = {
    "totalElements": 2,
    "content": [
        {"publicatieId": "300001", "aanbestedingNaam": "Onderhoud  wegen", "sluitingsDatum": "2026-10-12T10:00:00",
         "procedure": {"code": "OPE"}, "europees": True, "opmerking": None,
         "cpvCodes": [{"code": "45233141-9"}, {"code": "45233142-6"}]},
        {"publicatieId": "300002", "aanbestedingNaam": "Schoonmaak", "sluitingsDatum": "2026-11-01T12:00:00",
         "procedure": {"code": "REP"}, "europees": False, "kosten": 1250.5,
         "cpvCodes": [{"code": "90911200-8"}]},
    ],
}

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <title>Ausschreibungen</title>
  <entry>
    <id>urn:tender:2026-0101</id>
    <title>Neubau Kita</title>
    <link rel="alternate" href="https://vergabe.example.test/ausschreibungen/2026-0101"/>
    <cbc:ContractFolderID>2026-0101</cbc:ContractFolderID>
  </entry>
  <entry>
    <id>urn:tender:2026-0102</id>
    <title>Stra\xc3\x9fenreinigung</title>
    <link rel="alternate" href="https://vergabe.example.test/ausschreibungen/2026-0102"/>
    <cbc:ContractFolderID>2026-0102</cbc:ContractFolderID>
  </entry>
</feed>"""


def html(text: str | bytes, content_type: str | None = None) -> Doc:
    return parse_page(text, NodeKind.html, URL, content_type)


def texts(found: list[Found]) -> list[str]:
    return [f.text for f in found]


@pytest.fixture
def listing() -> Doc:
    return html(LIST_PAGE.encode("utf-8"), "text/html; charset=utf-8")


@pytest.fixture
def rows(listing) -> list[Found]:
    return find_items(css("table#vergaben tbody tr"), listing)


@pytest.fixture
def api() -> Doc:
    return parse_page(json.dumps(JSON_LIST).encode(), NodeKind.json, URL, "application/json")


# -- HTML: CSS and XPath ----------------------------------------------------------

def test_items_are_the_rows(rows):
    assert len(rows) == 2
    assert rows[0].text.startswith("2026-0101 Neubau Kita Sonnenschein")


def test_css_on_the_page_and_in_an_item(listing, rows):
    assert texts(find(css("td.aktenzeichen"), listing)) == ["2026-0101", "2026-0102"]
    assert first_text(css("td.aktenzeichen"), rows[1]) == "2026-0102"
    assert first_text(css("a.titel"), rows[0]) == "Neubau Kita Sonnenschein"  # nbsp and line break cleaned


def test_attr_reads_an_attribute(listing, rows):
    assert first_text(css("a.titel", attr="href"), rows[1]) == "/ausschreibungen/2026-0102"
    assert first_text(css("td.frist time", attr="datetime"), rows[0]) == "2026-03-01T10:00"
    assert first_text(css("nav.seiten a[rel=next]", attr="href"), listing) == "?seite=2"
    assert find(css("a.titel", attr="nosuch"), rows[0]) == []


def test_an_empty_cell_is_no_match(rows):
    assert find(css("td.frist"), rows[1]) == []
    assert first_text(css("td.frist"), rows[1]) is None


def test_xpath_on_the_page_and_in_an_item(listing, rows):
    assert texts(find(xpath("//a[@class='titel']/@data-id"), listing)) == ["2026-0101", "2026-0102"]
    assert first_text(xpath(".//a[@class='titel']", attr="href"), rows[0]) == "/ausschreibungen/2026-0101"
    assert first_text(xpath("td[@class='aktenzeichen']"), rows[1]) == "2026-0102"
    assert first_text(xpath("string(.//td[@class='aktenzeichen'])"), rows[0]) == "2026-0101"
    assert first_text(xpath("count(td)"), rows[0]) == "3"


def test_an_item_scoped_xpath_does_not_leak_into_the_next_row(listing, rows):
    expr = "//td[@class='aktenzeichen']"
    assert texts(find(xpath(expr), rows[0])) == ["2026-0101"]
    assert texts(find(xpath(expr), rows[1])) == ["2026-0102"]
    assert texts(find(xpath(f"{expr} | //a[@class='titel']/@data-id"), rows[1])) == ["2026-0102", "2026-0102"]
    assert texts(find(xpath("//time/@datetime"), rows[1])) == []          # row 2 has none; row 1's is not borrowed
    assert len(find(xpath(expr), listing)) == 2                            # on the page it searches the page


def test_script_and_style_text_never_counts(listing):
    assert "31.12.2099" not in listing.text and "color" not in listing.text
    assert find(regex(r"(\d\d\.\d\d\.2099)"), listing) == []
    body = find(css("body"), listing)[0]
    assert "31.12.2099" not in body.text


def test_a_selector_that_does_not_parse_finds_nothing(listing, rows):
    assert find(css("td[[["), listing) == []
    assert find(css("a::nonsense-pseudo"), listing) == []
    assert find(xpath("//td[@class="), listing) == []
    assert find(xpath("//atom:entry"), rows[0]) == []      # unknown prefix
    assert find(regex("(unclosed"), listing) == []
    assert find(jsonpath("$.a"), listing) == []             # JSONPath on HTML
    assert find(Locator(kind=LocatorKind.css, expr=None, labels=[], attr=None), listing) == []


# -- HTML: regex -----------------------------------------------------------------

def test_regex_on_the_page_and_in_an_item(listing, rows):
    assert first_text(regex(r"(\d+) Ausschreibungen gefunden"), listing) == "2"
    assert texts(find(regex(r"\d{4}-\d{4}"), listing)) == ["2026-0101", "2026-0102"]   # no group: whole match
    assert texts(find(regex(r"(\d\d\.\d\d\.\d{4} \d\d:\d\d)"), rows[0])) == ["01.03.2026 10:00"]
    assert find(regex(r"(\d\d\.\d\d\.\d{4})"), rows[1]) == []


def test_cells_are_separated_in_the_text(listing):
    assert "2026-0101 Neubau" in listing.text   # not "2026-0101Neubau"


# -- labels ----------------------------------------------------------------------

def test_label_in_a_definition_list_with_colon_and_case():
    doc = html(DETAIL_DL)
    assert texts(find(label("Angebotsfrist"), doc)) == ["01.03.2026 10:00"]  # the paragraph does not count
    assert first_text(label("status"), doc) == "Laufend"
    assert first_text(label("Aktenzeichen", "Vergabenummer"), doc) == "2026-0101"


def test_label_in_a_two_column_table():
    doc = html(DETAIL_TABLE)
    assert first_text(label("Auftraggeber", "Vergabestelle"), doc) == "Stadt Musterstadt"   # th then td
    assert first_text(label("Angebotsfrist"), doc) == "01.03.2026 10:00"                  # td "angebotsfrist:"
    assert first_text(label("CPV-Code"), doc) == "45214100-1"


def test_label_and_value_in_one_element():
    doc = html(DETAIL_INLINE)
    assert first_text(label("Veröffentlicht am"), doc) == "12.02.2026"
    assert texts(find(label("Abgabefrist"), doc)) == ["01.03.2026 10:00"]


def test_label_then_next_sibling_element():
    doc = html(DETAIL_INLINE)
    assert first_text(label("Verfahrensart"), doc) == "Offenes Verfahren"
    assert texts(find(label("Auftragsart"), doc)) == ["Bauleistung"]   # not the running-text mention


def test_a_label_inside_running_text_does_not_match():
    doc = html("<html><body><p>Die Angebotsfrist endet am 01.03.2026.</p>"
               "<p>Bitte die <b>Angebotsfrist</b> <span>beachten</span>.</p>"
               "<p><b>Angebotsfrist</b> endet bald</p>"
               "<p>Hinweis zur Angebotsfrist: siehe unten</p></body></html>")
    assert find(label("Angebotsfrist"), doc) == []


def test_several_labels_give_several_matches_in_order():
    doc = html("<html><body><table>"
               "<tr><td>Frist</td><td>01.03.2026</td></tr><tr><td>Los</td><td>1</td></tr>"
               "<tr><td>Frist</td><td>08.03.2026</td></tr></table></body></html>")
    assert texts(find(label("Frist"), doc)) == ["01.03.2026", "08.03.2026"]


def test_label_inside_an_item():
    doc = html("<html><body><ul>"
               "<li class='t'><span>Frist:</span><span>01.03.2026</span></li>"
               "<li class='t'><span>Frist:</span><span>02.03.2026</span></li></ul></body></html>")
    items = find_items(css("li.t"), doc)
    assert [first_text(label("Frist"), item) for item in items] == ["01.03.2026", "02.03.2026"]


def test_a_label_with_nothing_next_to_it_finds_nothing():
    doc = html("<html><body><table><tr><th>Angebotsfrist</th></tr><tr><td>01.03.2026</td></tr></table>"
               "</body></html>")
    assert find(label("Angebotsfrist"), doc) == []


# -- broken HTML and encodings ---------------------------------------------------

def test_broken_html_is_read_anyway():
    doc = html(b"<html><body><table><tr><td class=a>eins<td class=a>zwei</tr><p>Frist: 1.3.<div><b>fett")
    assert texts(find(css("td.a"), doc)) == ["eins", "zwei"]
    assert first_text(label("Frist"), doc) == "1.3."
    for body in (b"", b"   ", b"\x00\x01garbage<<<>>>", "<?xml version='1.0' encoding='utf-8'?><p>x</p>"):
        assert isinstance(html(body), Doc)


def test_an_encoding_declared_only_in_the_meta_tag():
    page = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=ISO-8859-1"></head>'
            '<body><td class="ort">Lüneburg, Straße 5</td></body></html>').encode("iso-8859-1")
    doc = html(page, "text/html")
    assert first_text(css("td.ort"), doc) == "Lüneburg, Straße 5"
    assert first_text(css("td.ort"), html(page.replace(b"ISO-8859-1", b"nonsense"))) == "L\ufffdneburg, Stra\ufffde 5"


def test_the_content_type_wins_over_the_meta_tag():
    page = '<html><head><meta charset="utf-8"></head><body><p>Größe</p></body></html>'.encode("cp1252")
    assert first_text(css("p"), html(page, "text/html; charset=windows-1252")) == "Größe"


def test_a_browser_page_is_html():
    doc = parse_page("<div id='x'>Hallo</div>", NodeKind.browser, URL)
    assert doc.kind is NodeKind.browser and first_text(css("#x"), doc) == "Hallo"


# -- JSON --------------------------------------------------------------------------

def test_json_items_and_relative_paths(api):
    items = find_items(jsonpath("$.content[*]"), api)
    assert len(items) == 2 and items[0].node["publicatieId"] == "300001"
    assert [first_text(jsonpath("@.publicatieId"), item) for item in items] == ["300001", "300002"]
    assert first_text(jsonpath("@.procedure.code"), items[1]) == "REP"
    assert first_text(jsonpath("@.aanbestedingNaam"), items[0]) == "Onderhoud wegen"     # whitespace collapsed
    assert first_text(jsonpath("$.totalElements"), items[0]) == "2"                     # $ is the document


def test_jsonpath_subset(api):
    assert first_text(jsonpath("$.totalElements"), api) == "2"
    assert first_text(jsonpath("$['content'][0]['publicatieId']"), api) == "300001"
    assert first_text(jsonpath('$["content"][-1].publicatieId'), api) == "300002"
    assert texts(find(jsonpath("$.content[*].cpvCodes[*].code"), api)) == ["45233141-9", "45233142-6", "90911200-8"]
    assert texts(find(jsonpath("$..code"), api)) == ["OPE", "45233141-9", "45233142-6", "REP", "90911200-8"]
    assert first_text(jsonpath('$.content[?(@.publicatieId=="300002")].aanbestedingNaam'), api) == "Schoonmaak"
    assert first_text(jsonpath("$.content[?(@.procedure.code=='OPE')].publicatieId"), api) == "300001"
    assert texts(find(jsonpath("$.content[?(@.kosten)].publicatieId"), api)) == ["300002"]
    assert texts(find(jsonpath("$.content[?(@.europees==true)].publicatieId"), api)) == ["300001"]
    assert texts(find(jsonpath("$.content[*].europees"), api)) == ["true", "false"]
    assert first_text(jsonpath("$.content[1].kosten"), api) == "1250.5"


def test_jsonpath_whole_values_are_compact_json(api):
    found = find(jsonpath("$.content[0].procedure"), api)
    assert found[0].text == '{"code":"OPE"}' and found[0].node == {"code": "OPE"}
    assert first_text(jsonpath("@.code"), found[0]) == "OPE"
    assert first_text(jsonpath("$.content[1].cpvCodes"), api) == '[{"code":"90911200-8"}]'


def test_jsonpath_missing_null_and_unsupported(api):
    assert find(jsonpath("$.nosuch"), api) == []
    assert find(jsonpath("$.content[5].publicatieId"), api) == []
    assert find(jsonpath("$.content[0].opmerking"), api) == []      # null is no match
    assert find(jsonpath("$.totalElements.deeper"), api) == []
    for unsupported in ("$.content[0:1]", "$.content[?(@.kosten > 1)]", "$..*", "content", "$.a[", "$[?(@.x=="):
        assert find(jsonpath(unsupported), api) == []
    assert find(css("a"), api) == [] and find(label("x"), api) == []


def test_regex_over_json(api):
    assert texts(find(regex(r'"publicatieId": "(\d+)"'), api)) == ["300001", "300002"]


def test_json_that_does_not_parse_is_a_page_error():
    with pytest.raises(PageError):
        parse_page(b"<html>not json</html>", NodeKind.json, URL)
    assert parse_page(b"\xef\xbb\xbf[1]", NodeKind.json, URL).root == [1]


# -- feeds -------------------------------------------------------------------------

def test_an_atom_feed_with_namespaces():
    doc = parse_page(ATOM, NodeKind.feed, URL, "application/atom+xml")
    entries = find_items(css("feed > entry"), doc)
    assert len(entries) == 2
    assert [first_text(css("entry > title"), e) for e in entries] == ["Neubau Kita", "Straßenreinigung"]
    assert first_text(xpath("link[@rel='alternate']/@href"), entries[1]).endswith("/2026-0102")
    assert first_text(css("link", attr="href"), entries[0]).endswith("/2026-0101")
    assert first_text(xpath("//ContractFolderID"), entries[1]) == "2026-0102"   # prefix stripped, stays in item
    assert texts(find(xpath("entry/title"), doc)) == ["Neubau Kita", "Straßenreinigung"]
    assert len(find_items(xpath("//entry"), doc)) == 2


def test_a_feed_never_resolves_entities():
    evil = b"""<?xml version="1.0"?>
<!DOCTYPE feed [<!ENTITY xxe SYSTEM "file:///etc/passwd"><!ENTITY word "boom">]>
<feed><entry><title>a&xxe;b&word;</title></entry></feed>"""
    doc = parse_page(evil, NodeKind.feed, URL)
    text = first_text(css("title"), doc) or ""
    assert "root:" not in text and "boom" not in text


def test_a_feed_that_is_not_xml_is_a_page_error():
    with pytest.raises(PageError):
        parse_page(b"", NodeKind.feed, URL)


# -- try_locator -------------------------------------------------------------------

def test_try_locator_on_the_page_and_per_item(listing):
    assert try_locator(css("td.aktenzeichen"), listing) == ["2026-0101", "2026-0102"]
    assert try_locator(css("td.aktenzeichen"), listing, limit=1) == ["2026-0101"]
    items = css("table#vergaben tbody tr")
    assert try_locator(css("a.titel", attr="href"), listing, items=items) == [
        "/ausschreibungen/2026-0101", "/ausschreibungen/2026-0102"]
    assert try_locator(css("td.frist"), listing, items=items) == ["01.03.2026 10:00"]
    assert try_locator(css("td.aktenzeichen"), listing, items=items, limit=1) == ["2026-0101"]


def test_try_locator_on_json(api):
    assert try_locator(jsonpath("@.publicatieId"), api, items=jsonpath("$.content[*]")) == ["300001", "300002"]
