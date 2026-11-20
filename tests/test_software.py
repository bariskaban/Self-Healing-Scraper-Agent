"""Software families of portals (app/software.py, Q11). Run: pytest tests/test_software.py"""
import pytest

from app.software import Evidence, best, detect


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
