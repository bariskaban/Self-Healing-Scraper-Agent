"""Software families of portals (app/software.py, Q11). Run: pytest tests/test_software.py"""
import time

import pytest

from app.software import Evidence, best, detect, page_text


@pytest.mark.parametrize("url, family", [
    ("https://evergabe.nrw.de/VMPSatellite/notice/CXP4Y73MZD6", "cosinex-vmp"),
    ("https://www.dtvp.de/Satellite/notice/CXP4Y73MZD6", "cosinex-vmp"),
    ("https://vergabe.vmstart.de/NetServer/", "ai-netserver"),
    ("https://www.tender24.de/NetServer/index.jsp", "ai-netserver"),
    ("https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseAdvancedSearch&AllCons", "atexo-place"),
    ("https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=abc", "placsp"),
    ("https://www.tenderned.nl/aankondigingen/overzicht", "tenderned"),
    ("https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/2026", "e-zamowienia"),
    ("https://platformazakupowa.pl/pn/gmina", "open-nexus"),
    ("https://my.mercell.com/en/m/tenders", "mercell"),
])
def test_known_addresses(url, family):
    assert best(url) == family


def test_host_beats_path_beats_text():
    # A NetServer path on an unknown host is a path match; the page text adds a brand match.
    c = detect("https://vergabe.example-landkreis.de/NetServer/", "<title>AI Vergabeplattform</title>")
    assert c[0].family == "ai-netserver" and c[0].strength == Evidence.path
    assert any("text" in r for r in c[0].reasons)


def test_brand_text_alone_is_the_weakest_evidence():
    html = "<html><body><footer>Powered by cosinex Vergabemarktplatz</footer><script>var cosinex=1</script></body></html>"
    c = detect("https://vergabe.stadt-irgendwo.de/", html)
    assert c[0].family == "cosinex-vmp" and c[0].strength == Evidence.brand


def test_script_text_does_not_count_as_brand():
    html = "<html><body><p>Ausschreibungen</p><script>// TenderNed widget</script></body></html>"
    assert detect("https://beispiel.de/", html) == []


def test_generator_meta_tag_counts():
    html = '<head><meta name="generator" content="Atexo Local Trust MPE"></head><body></body>'
    assert best("https://achats.region-x.fr/", html) == "atexo-place"


def test_subdomains_match_their_parent_but_lookalikes_do_not():
    assert best("https://portal.deutsche-evergabe.de/dashboards") == "deutsche-evergabe"
    assert detect("https://notevergabe.de/") == []
    assert detect("https://tenderned.nl.evil.example/") == []


def test_unknown_portal_is_none():
    assert best("https://www.some-buyer-profile.eu/tenders", "<html><body>Tenders</body></html>") is None


def test_tie_at_the_top_is_none():
    # Two families with the same strongest evidence: no guess.
    html = "<p>Mercell</p><p>TenderNed</p>"
    assert best("https://aanbesteden.example.nl/", html) is None


def test_two_names_of_one_product_do_not_break_a_tie():
    # Mercell's page names two of its brands and says where it also publishes. Still a tie.
    html = "<p>Mercell (Negometrix)</p><p>Publicatie op TenderNed</p>"
    assert [c.family for c in detect("https://aanbesteden.example.nl/", html)] == ["mercell", "tenderned"]
    assert best("https://aanbesteden.example.nl/", html) is None
    assert best("https://x.example/", "<p>cosinex Vergabemarktplatz. Auch auf TenderNed.</p>") is None


@pytest.mark.parametrize("text", [
    "Mairie, 1 place de la République",
    "The opening will take place on 3 May",
])
def test_the_word_place_is_not_a_brand(text):
    assert detect("https://achats.ville-x.example/", f"<p>{text}</p>") == []


def test_no_brand_pattern_is_a_plain_word():
    # Brand text is matched with case ignored, so a pattern must not also be an everyday word.
    everyday = "place places market portal tender tenders vergabe ausschreibung platform achat marché"
    assert detect("https://x.example/", f"<p>{everyday}</p>") == []


@pytest.mark.parametrize("url, family", [
    ("https://evergabe.nrw.de/VMPSatellite", "cosinex-vmp"),          # as the research cites it, no slash
    ("https://vergabe.example-stadt.de/VMPSatellite/notice/CXP4", "cosinex-vmp"),
    ("https://vergabe.example-stadt.de/Satellite/notice/CXP4", "cosinex-vmp"),
    ("https://evergabe.blb.nrw.de/", "cosinex-vmp"),
    ("https://www.evergabemv.de/", "subreport-elvis"),
    ("https://www.tenderned.nl./aankondigingen", "tenderned"),         # a host written with its final dot
])
def test_addresses_the_research_names(url, family):
    assert best(url) == family


def test_a_satellite_path_of_other_software_is_no_match():
    # "/cs/Satellite/" is the address form of an unrelated content system; cosinex is "/Satellite/notice/".
    assert detect("https://www.bank.example/cs/Satellite/home") == []
    assert detect("https://www.example.de/VMPSatelliten/") == []


@pytest.mark.parametrize("url", ["https://[::1/x", "", "   ", "not an address"])
def test_an_address_that_cannot_be_parsed_gives_nothing(url):
    assert detect(url) == [] and best(url) is None


@pytest.mark.parametrize("html", [
    "<!-- if a > b : TenderNed --><p>x</p>",                 # a comment holding a ">"
    '<p>x</p><script>var a="TenderNed";',                    # a script that never closes
    "<SCRIPT type='x'>TenderNed</SCRIPT><STYLE>.TenderNed{}</STYLE>",
    '<script src="https://cdn.mercell.com/x.js"></script><a href="https://www.tenderned.nl/">hier</a>',
])
def test_text_outside_the_visible_page_is_no_brand(html):
    assert detect("https://beispiel.example/", html) == []


def test_page_text_keeps_what_a_reader_sees():
    html = "<title>AI Vergabeplattform</title><p>a < b</p><scripted>TenderNed</scripted>"
    text = page_text(html)
    assert "AI Vergabeplattform" in text and "a < b" in text and "TenderNed" in text
    assert "Atexo" in page_text("<META content='Atexo MPE' NAME=generator>")
    assert "Atexo" not in page_text('<meta name="description" content="Atexo">')


@pytest.mark.parametrize("piece", ["<", "<script ", "<meta ", "<meta name='generator' ", "<style ", "<!-- ", "subreport "])
def test_time_grows_with_the_page_not_with_its_square(piece):
    # The first version took 45 s on 320 KB of "<script ". Linear work on 2 MB takes well under a second.
    html = piece * (2_000_000 // len(piece))
    started = time.perf_counter()
    detect("https://beispiel.example/", html)
    assert time.perf_counter() - started < 5
