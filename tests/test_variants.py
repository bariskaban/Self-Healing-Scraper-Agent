"""The made-up portals of `variants/portals.py` serve what their truth says. No model, no network.

Run: pytest tests/test_variants.py
"""
from __future__ import annotations

import pytest

from variants.run import VariantFetch
from variants.portals import VARIANTS


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


@pytest.mark.parametrize("name", sorted(n for n in VARIANTS if VARIANTS[n]().expect == "serve"))
def test_a_changed_variant_keeps_its_tenders_and_addresses_but_none_of_its_hooks(name):
    import re

    before, after = VARIANTS[name](), VARIANTS[name]()
    after.changed = True
    assert after.truth() == before.truth()
    want = before.truth()[0]
    old = VariantFetch(before).fetch("p", want["url"]).text
    new = VariantFetch(after).fetch("p", want["url"]).text
    hooks = lambda text: set(re.findall(r'class="([^"]+)"', text))  # noqa: E731
    if name == "json_api":
        api = lambda v, path: VariantFetch(v).fetch("p", v.base_url + path)  # noqa: E731
        assert api(after, "/api/v2/notices?page=0&size=20").status == 404
        listing = api(after, "/api/v3/notices?page=0&size=20").json()
        assert listing["total_elements"] == 45 and listing["content"][0]["notice_id"] == before.truth()[-1]["id"]
        assert "/api/v3" in api(after, "/static/app.4f2a.js").text
    else:
        assert want["title"] in new.replace("&#x27;", "'") and hooks(old) and not hooks(old) & hooks(new)


@pytest.mark.parametrize("name", sorted(n for n in VARIANTS if VARIANTS[n]().expect == "serve"))
def test_a_moved_variant_keeps_only_its_domain(name):
    from variants.portals import MOVED

    before, after = VARIANTS[name](), VARIANTS[name]()
    after.moved = True
    fetch = VariantFetch(after)
    old, new = before.truth()[0], after.truth()[0]
    assert new["url"] == old["url"].replace(before.base_url, before.base_url + MOVED) and new["id"] == old["id"]
    assert fetch.fetch("p", old["url"]).status == 404                 # every old address is gone
    assert fetch.fetch("p", new["url"]).status == 200
    root = fetch.fetch("p", after.base_url + "/")
    assert root.status == 200 and f'href="{MOVED}/"' in root.text     # the domain's root leads to the new place
    entry = fetch.fetch("p", after.base_url + MOVED + "/")
    assert entry.status == 200 and 'href="/' not in entry.text.replace(f'href="{MOVED}/', "")
    file = before.tenders[0].files[0]
    assert fetch.fetch("p", f"{after.base_url}{MOVED}/files/{old['id']}/{file.name}").body == file.body
    if name == "json_api":
        script = fetch.fetch("p", f"{after.base_url}{MOVED}/static/app.4f2a.js").text
        assert f'API="{MOVED}/api/v2"' in script
        listing = fetch.fetch("p", f"{after.base_url}{MOVED}/api/v2/notices?page=0&size=20").json()
        assert listing["content"][0]["link"].startswith(MOVED + "/notice/")
