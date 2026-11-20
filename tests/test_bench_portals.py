"""The test-portal list (bench/portals.toml): every entry valid, and the set meets the rules of Q8.

Nothing here makes a request.
"""
from __future__ import annotations

import pytest

from bench.portals import Address, Expect, TestPortal, load_portals, read_file


def test_every_entry_is_valid_and_ids_are_unique():
    portals, excluded = read_file()
    assert len(portals) >= 40
    assert len({p.id for p in portals}) == len(portals)
    assert excluded and all(e.reason for e in excluded)


def test_the_set_meets_the_rules_of_the_test_set():
    """Q8 and the brief: 8 or more portals, 4 or more countries, 3 or more software families,
    1 or 2 behind a login, and 2 held back unseen."""
    portals, _ = read_file()
    runnable = [p for p in portals if p.url and p.expect is Expect.serve and not p.unseen]
    assert len(runnable) >= 8
    assert len({p.country for p in runnable}) >= 4
    assert len({p.family for p in runnable if p.family != "unknown"}) >= 3
    assert 1 <= len([p for p in portals if p.expect is Expect.fail_login]) <= 2
    assert {p.id for p in portals if p.unseen} == {"platformazakupowa", "eproc-austria"}


def test_the_platforms_that_hold_most_portals_are_in():
    """research/patterno-landscape.md: the five largest platforms hold 40% of Patterno's portal addresses."""
    families = {p.family for p in read_file()[0]}
    for platform in ("ezamawiajacy.pl", "e-marchespublics.com", "logintrade.net", "acquistitelematici.it",
                     "tuttogare.it"):
        assert platform in families


def test_no_aggregator_is_a_test_portal():
    portals, excluded = read_file()
    names = " ".join(e.name.lower() for e in excluded)
    assert "ted" in names and "service.bund.de" in names
    assert not any("ted.europa.eu" in (p.url or "") or "service.bund.de" in (p.url or "") for p in portals)


def test_by_default_unseen_portals_and_entries_without_an_address_are_left_out():
    default = load_portals()
    assert default and all(p.url and not p.unseen for p in default)
    assert [p.priority for p in default] == sorted(p.priority for p in default)
    assert any(p.unseen for p in load_portals(include_unseen=True))
    poland = load_portals(priority_max=1)
    assert poland and {p.country for p in poland} == {"PL"}
    assert all(p.address not in (Address.example, Address.doubtful) for p in default)
    guessed = {p.id for p in load_portals(include_guessed=True)} - {p.id for p in default}
    assert len(guessed) == 10


@pytest.mark.xfail(strict=True, reason="Known gap: without guessed addresses only PL, NL and DE remain (AT is unseen, "
                   "ES forbids robots, PLACE is suspended, IT and FR unconfirmed). Confirm an Italian or French "
                   "address in a browser and this passes; then remove the mark.")
def test_the_default_list_alone_meets_the_rules_of_the_test_set():
    """What runs by default, with no guessed address, should be a test set by Q8's rules (4+ countries)."""
    runnable = load_portals(expect=Expect.serve)
    assert len(runnable) >= 8
    assert len({p.country for p in runnable}) >= 4
    assert len({p.family for p in runnable if p.family != "unknown"}) >= 3


def test_an_address_marked_fetched_was_opened_itself():
    """From Goktug's review: `fetched` only where our research opened that very address."""
    fetched = {p.id for p in read_file()[0] if p.address is Address.fetched}
    assert not fetched & {"ezamowienia", "vmp-brandenburg", "placsp", "evergabe-de"}
    assert {p.id for p in load_portals(expect=Expect.fail_login)} == {"mercell", "deutsche-evergabe"}


def test_a_bad_entry_is_refused(tmp_path):
    bad = tmp_path / "portals.toml"
    bad.write_text('[[portal]]\nid = "x"\nname = "X"\ncountry = "PL"\nfamily = "f"\n'
                   'url = "nfz.example/list"\nkind = "server_html"\nexpect = "serve"\npriority = 1\n'
                   'address = "fetched"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="absolute"):
        read_file(bad)
    with pytest.raises(ValueError, match="evidence"):
        TestPortal(id="y", name="Y", country="PL", family="f", url="https://y.example/", kind="unknown",
                   expect="serve", priority=1)


# == The loader refuses a broken file, and says which entry ==

_ENTRY = ('[[portal]]\nid = "{id}"\nname = "X"\ncountry = "PL"\nfamily = "f"\nurl = "{url}"\n'
          'kind = "server_html"\nexpect = "serve"\npriority = 1\naddress = "fetched"\n')


def _file(tmp_path, text):
    path = tmp_path / "portals.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _entry(id="a", url="https://a.example/list"):
    return _ENTRY.format(id=id, url=url)


def test_a_good_small_file_is_read(tmp_path):
    portals, excluded = read_file(_file(tmp_path, _entry() + _entry("b", "https://b.example/")))
    assert [p.id for p in portals] == ["a", "b"] and excluded == []


@pytest.mark.parametrize("text, message", [
    ("[[portal]\nid =", r"portals\.toml: not valid TOML.*line 1"),
    ("", r"no \[\[portal\]\] entry"),
    (_entry().replace("[[portal]]", "[[portals]]"), r"unknown top-level tables \['portals'\]"),
    (_entry().replace("[[portal]]", "[portal]"), r"must be written as \[\[portal\]\]"),
    (_entry() + _entry("b", "https://b.example/").replace("server_html", "html"), r"entry 2 \('b'\)(.|\n)*kind"),
    (_entry() + _entry("b", "https://b.example/") + 'timezone = "Europe/Warsaw"\n',
     r"entry 2 \('b'\)(.|\n)*timezone(.|\n)*not permitted"),
    (_entry().replace('family = "f"\n', ""), r"entry 1 \('a'\)(.|\n)*family(.|\n)*required"),
    (_entry().replace('address = "fetched"\n', ""), r"entry 1 \('a'\)(.|\n)*evidence"),
    (_entry().replace("priority = 1", "priority = 6"), r"entry 1 \('a'\)(.|\n)*priority"),
    (_entry().replace('"PL"', '"Poland"'), r"entry 1 \('a'\)(.|\n)*country"),
    (_entry() + _entry("a", "https://b.example/"), r"entry 2 \('a'\): portal id 'a' is used twice \(also .*entry 1"),
    (_entry() + '[[excluded]]\nname = "X"\n', r"\[\[excluded\]\] entry 1 \('X'\)(.|\n)*reason"),
])
def test_a_broken_file_is_refused_with_the_entry_named(tmp_path, text, message):
    with pytest.raises(ValueError, match=message):
        read_file(_file(tmp_path, text))


@pytest.mark.parametrize("second", [
    "https://a.example/list",
    "https://a.example/list/",
    "https://A.Example:443/list",
])
def test_one_address_listed_twice_is_refused(tmp_path, second):
    """The same address under two ids would be recorded twice: two requests where one is allowed."""
    with pytest.raises(ValueError, match=r"entry 2 \('b'\): the address .* is listed twice \(also .*entry 1"):
        read_file(_file(tmp_path, _entry() + _entry("b", second)))


def test_the_same_address_with_its_parameters_in_another_order_is_the_same_address(tmp_path):
    text = _entry(url="https://a.example/l?x=1&y=2") + _entry("b", "https://a.example/l?y=2&x=1")
    with pytest.raises(ValueError, match="listed twice"):
        read_file(_file(tmp_path, text))


@pytest.mark.parametrize("url, message", [
    ("https://", "no host name"),
    ("https://localhost/list", "no host name"),
    ("https:// a.example/list", "white space"),
    ("https://someone:secret@a.example/list", "user name or password"),
    ("https://a.example/list#rows", "fragment"),
    ("https://a.example/list;jsessionid=0A1B2C", "session id"),
    ("https://a.example/list?page=1&token=abc", "session id"),
    ("https://a.example/list?PHPSESSID=abc", "session id"),
    ("https://a.example/list?sid=abc", "session id"),
    ("https://a.example/list?contact=someone@a.example", "e-mail"),
    ("ftp://a.example/list", "absolute"),
])
def test_an_address_that_is_not_one_or_carries_a_secret_is_refused(tmp_path, url, message):
    with pytest.raises(ValueError, match=message):
        read_file(_file(tmp_path, _entry(url=url)))


def test_ordinary_parameters_are_not_taken_for_secrets(tmp_path):
    url = "https://a.example/s?function=Search&OrderBy=Publishing&method=show&page=0&size=20&AllCons"
    assert read_file(_file(tmp_path, _entry(url=url)))[0][0].url == url


@pytest.mark.parametrize("url", ["https://ted.europa.eu/en/search", "https://www.boamp.fr/avis"])
def test_a_portal_on_an_excluded_site_is_refused(tmp_path, url):
    excluded = ('[[excluded]]\nname = "TED (ted.europa.eu)"\nreason = "r"\n'
                '[[excluded]]\nname = "BOAMP (boamp.fr)"\nreason = "r"\n')
    with pytest.raises(ValueError, match="which the file excludes"):
        read_file(_file(tmp_path, _entry(url=url) + excluded))
    assert read_file(_file(tmp_path, _entry(url="https://notboamp.fr/") + excluded))


# == robots.txt ==

def test_a_portal_whose_robots_txt_forbids_everything_is_left_out_by_default(tmp_path):
    text = _entry() + _entry("b", "https://b.example/") + "robots_disallow_all = true\n"
    path = _file(tmp_path, text)
    assert [p.id for p in load_portals(path)] == ["a"]
    assert [p.id for p in load_portals(path, include_robots_forbidden=True)] == ["a", "b"]


def test_spains_national_portal_is_marked_and_not_in_the_default_set():
    """research/audit.md (Q3): it answers `Disallow: /` for every robot. The mentor: obey robots.txt."""
    marked = {p.id for p in read_file()[0] if p.robots_disallow_all}
    assert marked == {"placsp"}
    assert "placsp" not in {p.id for p in load_portals()}
    assert "placsp" in {p.id for p in load_portals(include_robots_forbidden=True)}


# == Nothing here can reach a portal, and the list does not ship ==

def test_the_bench_package_imports_nothing_that_can_make_a_request():
    """CLAUDE.md: no request to a live portal from a test or a script. bench/ may only parse."""
    import ast
    from pathlib import Path

    allowed = {"__future__", "re", "tomllib", "enum", "pathlib", "typing", "urllib.parse", "pydantic", "app.models"}
    bench = Path(__file__).resolve().parent.parent / "bench"
    sources = sorted(bench.glob("*.py"))
    assert [s.name for s in sources] == ["__init__.py", "portals.py"], "a new module: review it, then list it here"
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert set(names) <= allowed, f"{source.name} imports {names}"
            assert not (isinstance(node, ast.Name) and node.id in ("__import__", "eval", "exec"))


def test_the_list_is_not_packaged_and_not_in_the_image():
    """bench/ is repo-only: the live addresses do not ship with the app or the container."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any(p.startswith("bench") for p in project["tool"]["setuptools"]["packages"]["find"]["include"])
    copies = [line for line in (root / "Dockerfile").read_text(encoding="utf-8").splitlines()
              if line.strip().upper().startswith(("COPY", "ADD"))]
    assert copies and not any("bench" in line or line.split()[1] == "." for line in copies)


def test_nothing_in_the_app_imports_the_bench():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for folder in ("app", "mock_portal"):
        for source in (root / folder).rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            assert "import bench" not in text and "from bench" not in text, source
