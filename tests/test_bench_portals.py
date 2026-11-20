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
    trusted = load_portals(trusted_only=True)
    assert all(p.address not in (Address.example, Address.doubtful) for p in trusted)
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
