"""The made-up portals of `bench/variants.py` serve what their truth says. No model, no network.

Run: pytest tests/test_bench_variants.py
"""
from __future__ import annotations

import pytest

from bench.run_variants import VariantFetch
from bench.variants import VARIANTS


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_a_variant_serves_its_entry_and_every_tender_page_names_its_tender(name):
    variant = VARIANTS[name]()
    fetch = VariantFetch(variant)
    entry = fetch.fetch("p", variant.base_url + "/")
    assert entry.status == 200 and entry.body
    assert fetch.fetch("p", variant.base_url + "/robots.txt").status == 200
    assert fetch.fetch("p", variant.base_url + "/no/such/page").status in (200, 404)
    truth = variant.truth()
    if variant.expect == "give_up":
        assert truth == []
        return
    assert len(truth) == len(variant.tenders) >= 20 and len({t["id"] for t in truth}) == len(truth)
    for tender, want in zip(variant.tenders, truth):
        page = fetch.fetch("p", want["url"])
        assert page.status == 200, want["url"]
        if name != "json_api":  # there the tender's page is an app shell and the values come from the API
            assert want["title"].replace("'", "&#x27;") in page.text or want["title"] in page.text
        file = tender.files[0]
        assert fetch.fetch("p", f"{variant.base_url}/files/{want['id']}/{file.name}").body == file.body


def test_the_login_wall_redirects_every_page_to_a_password_form():
    variant = VARIANTS["login_wall"]()
    got = VariantFetch(variant).fetch("p", variant.base_url + "/tenders")
    assert got.final_url.endswith("/login") and got.redirects and 'type="password"' in got.text
