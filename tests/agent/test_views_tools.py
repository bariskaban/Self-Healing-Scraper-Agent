"""What the model sees of a page, and the tools, on the mock portal's pages. No request leaves the process.

Run: pytest tests/agent/test_views_tools.py
"""
from __future__ import annotations

import json

from app.agent import views
from app.agent.settings import AgentSettings
from app.agent.tools import Workspace, site_of, tools
from mock_portal import MockPortal, recipe as mock_recipe
from tests.agent.helpers import URL, MockFetch, portal

LIST = f"{URL}/tenders"


def space(mock: MockPortal | None = None, **settings) -> tuple[Workspace, MockFetch, dict]:
    fetch = MockFetch(mock or MockPortal(tenders=45, page_size=20))
    made = Workspace(portal(), fetch, max_requests=settings.pop("max_requests", 30), settings=AgentSettings(**settings))
    return made, fetch, {tool.name: tool for tool in tools(made)}


def body(path: str, mock: MockPortal | None = None) -> str:
    return (mock or MockPortal(tenders=45, page_size=20)).respond("GET", URL + path)[2].decode()


# -- views --

def test_the_html_view_keeps_the_hooks_and_drops_scripts():
    page = ('<html><head><script>var a=1</script><style>p{}</style><title>T</title>'
            '<link rel="alternate" type="application/atom+xml" href="/feed.atom"></head>'
            '<body><div id="x" class="row big" data-oid="77" style="color:red" onclick="go()">'
            '<a href="/t/1" aria-label="open">One</a><svg><path d="M0"/></svg></div><!-- note --></body></html>')
    view = views.html_view(page)
    assert 'id="x"' in view and 'class="row big"' in view and 'data-oid="77"' in view and 'href="/t/1"' in view
    assert 'aria-label="open"' in view and "/feed.atom" in view and "<title>T</title>" in view
    for gone in ("var a=1", "color:red", "onclick", "<svg", "note", "p{}"):
        assert gone not in view


def test_a_long_list_shows_three_rows_and_says_how_many_it_left_out():
    view = views.html_view(body("/tenders"))
    assert view.count('<tr class="tender"') == 3
    assert '17 more tr.tender rows like these are not shown' in view
    assert "45 tenders found" in view and 'rel="next"' in view  # the total and the paging stay
    assert views.html_view(body("/tenders"), all_rows=True).count('<tr class="tender"') == 20
    assert len(view) < len(body("/tenders")) / 3


def test_label_and_value_rows_of_a_detail_page_are_never_cut():
    rows = "".join(f"<tr><th>Label {n}</th><td>Value {n}</td></tr>" for n in range(30))
    view = views.html_view(f"<html><body><table>{rows}</table></body></html>")
    assert view.count("<tr>") == 30 and "Value 29" in view and "not shown" not in view
    detail = views.html_view(body("/tenders/MP-2026-0045"))
    assert "Deadline for tenders" in detail and "not shown" not in detail


def test_long_text_and_long_attributes_are_cut():
    view = views.html_view(f'<html><body><p>{"word " * 400}</p><input type="hidden" name="s" value="{"A" * 5000}"></body></html>')
    assert len(view) < 1000 and "chars]" in view


def test_the_json_view_cuts_arrays_to_three_items_with_a_count():
    shown = json.loads(views.json_view(json.dumps({"total": 50, "items": [{"id": n} for n in range(50)]})))
    assert shown["total"] == 50 and shown["items"][:3] == [{"id": 0}, {"id": 1}, {"id": 2}]
    assert "47 more" in shown["items"][3] and "50 in all" in shown["items"][3]
    assert views.json_view("<html>") is None


def test_links_are_grouped_by_the_pattern_of_their_address():
    text = views.links_view(body("/tenders"), LIST)
    assert "20 x mock.example/tenders/MP-{n}-{n}" in text and "/tenders?page=…" in text
    assert "MP-" not in views.links_view(body("/tenders"), LIST, contains="page=")


def test_search_finds_addresses_the_trimmed_view_leaves_out():
    page = '<html><script>fetch("/api/v2/notices?size=20")</script><body></body></html>'
    assert "/api/v2/notices" not in views.html_view(page)
    assert "/api/v2/notices?size=20" in views.search(page, r"/api/[\w/]+")
    assert views.search(page, "(") .startswith("Not a valid regular expression")
    assert views.search(page, "nothing-here") == "No match."


def test_a_view_is_paged():
    text = "\n".join(f"line {n} " + "x" * 90 for n in range(400))
    first, parts = views.part_of(text, 1, AgentSettings(view_chars=5000))
    assert parts > 5 and len(first) <= 5000 and first.endswith("\n")
    assert "".join(views.part_of(text, n, AgentSettings(view_chars=5000))[0] for n in range(1, parts + 1)) == text


# -- the workspace and the tools --

def test_a_page_is_fetched_once_and_then_served_from_the_cache():
    made, fetch, tool = space()
    first = tool["open_page"].run({"url": "/tenders"})
    assert "answered 200" in first.text and "trimmed HTML" in first.text and 'class="tender"' in first.text
    assert first.summary.startswith(f"Opened {LIST}: status 200")
    tool["open_page"].run({"url": LIST})
    tool["view_page"].run({"url": LIST, "part": 1, "all_rows": True})
    tool["page_links"].run({"url": LIST, "contains": None})
    tool["search_page"].run({"url": LIST, "pattern": "tenders found"})
    assert fetch.asked == [("GET", LIST)] and made.requests == 1


def test_only_the_portals_own_site_is_fetched():
    made, fetch, tool = space()
    said = tool["open_page"].run({"url": "https://ted.europa.eu/notices"})
    assert "not part of the portal's site" in said.text and fetch.asked == []
    assert "not an http" in tool["open_page"].run({"url": "file:///etc/passwd"}).text
    assert site_of("vergabe.stadt.example.de") == "example.de" and site_of("www.find-tender.service.gov.uk") == "service.gov.uk"
    made.portal = portal("https://www.mock.example/start")
    assert made.absolute("https://files.mock.example/a.pdf") == "https://files.mock.example/a.pdf"


def test_the_request_budget_is_enforced_in_the_tool():
    made, fetch, tool = space(max_requests=2)
    for path in ("/", "/tenders"):
        tool["open_page"].run({"url": path})
    said = tool["open_page"].run({"url": "/tenders?page=2"})
    assert "budget of 2 requests" in said.text and len(fetch.asked) == 2
    assert "answered 200" in tool["open_page"].run({"url": "/tenders"}).text  # cached pages still open


def test_a_page_not_opened_cannot_be_viewed_and_arguments_must_fit_the_schema():
    _, _, tool = space()
    assert "has not been opened" in tool["view_page"].run({"url": "/tenders", "part": 1, "all_rows": False}).text
    assert "do not fit the tool's schema" in tool["open_page"].run({"address": "/tenders"}).text


def test_try_locator_runs_on_a_cached_page_without_a_request():
    made, fetch, tool = space()
    tool["open_page"].run({"url": "/tenders"})
    css = lambda expr, attr=None: {"kind": "css", "expr": expr, "labels": [], "attr": attr}  # noqa: E731
    said = tool["try_locator"].run({"url": "/tenders", "page_kind": "html", "locator": css("td.title a", "href"),
                                    "items": css("table#tenders tr.tender")})
    out = json.loads(said.text)
    assert out["items_matched"] == 20 and out["matches_shown"][0] == "/tenders/MP-2026-0045"
    nothing = json.loads(tool["try_locator"].run({"url": "/tenders", "page_kind": "html",
                                                  "locator": css("td.nope"), "items": None}).text)
    assert nothing["matches_shown"] == [] and "hint" in nothing
    refused = tool["try_locator"].run({"url": "/tenders", "page_kind": "html",
                                       "locator": css("tr:nth-child(2) td"), "items": None})
    assert "no position" in refused.text.lower()
    assert len(fetch.asked) == 1


def test_proposing_the_right_recipe_fetches_what_the_dry_run_lacks_and_is_accepted():
    made, fetch, tool = space()
    said = tool["propose_recipe"].run({"recipe": mock_recipe().model_dump(mode="json"),
                                       "timezone": "Europe/Amsterdam", "country_code": "NL"})
    out = json.loads(said.text)
    assert out["accepted"] is True and out["problems"] == [] and out["pages_not_fetched"] == []
    # Two list pages and three tenders' own pages: enough to show that paging and the detail edge work.
    assert out["list_pages_read"] == 2 and out["records"] == 40 and out["tender_pages_read"] == 3
    assert sorted(path for _, path in fetch.mock.requests) == sorted(
        ["/tenders", "/tenders", "/tenders/MP-2026-0045", "/tenders/MP-2026-0044", "/tenders/MP-2026-0043"])
    sample = out["sample_records"][0]
    assert sample["id"] == "MP-2026-0045" and sample["submission_deadline"].endswith(("+01:00", "+02:00"))
    assert sample["documents"]
    assert made.accepted is not None and made.accepted.timezone == "Europe/Amsterdam"
    assert "passed" in said.summary


def test_a_recipe_with_a_wrong_locator_is_not_accepted_and_one_node_can_be_replaced():
    made, _, tool = space()
    good = mock_recipe().model_dump(mode="json")
    bad = json.loads(json.dumps(good))
    bad["nodes"][0]["items"]["expr"] = "table#tenders tr.notice"
    out = json.loads(tool["propose_recipe"].run({"recipe": bad, "timezone": "Europe/Amsterdam",
                                                 "country_code": None}).text)
    assert out["accepted"] is False and any("matched no row" in problem for problem in out["problems"])
    assert made.accepted is None
    assert "no node" in tool["replace_node"].run({"node": {**good["nodes"][0], "id": "elsewhere"}}).text
    fixed = tool["replace_node"].run({"node": good["nodes"][0]})
    assert json.loads(fixed.text)["accepted"] is True and fixed.summary.startswith("Replaced node 'list'.")
    shown = json.loads(tool["check_recipe"].run({"show_recipe": True}).text)
    assert shown["working_recipe"]["nodes"][0]["items"]["expr"] == "table#tenders tr.tender"


def test_a_recipe_that_does_not_validate_is_refused_with_what_is_wrong():
    _, _, tool = space()
    broken = mock_recipe().model_dump(mode="json")
    broken["start"] = "nowhere"
    out = json.loads(tool["propose_recipe"].run({"recipe": broken, "timezone": None, "country_code": None}).text)
    assert out["accepted"] is False and any("nowhere" in problem for problem in out["problems"])
    del broken["nodes"]
    assert "do not fit" in tool["propose_recipe"].run({"recipe": broken, "timezone": None, "country_code": None}).text


def test_a_field_the_contract_wants_and_no_record_has_is_a_warning():
    _, _, tool = space()
    recipe = mock_recipe().model_dump(mode="json")
    for node in recipe["nodes"]:
        node["fields"] = [f for f in node["fields"] if f["name"] != "buyer_name"]
    out = json.loads(tool["propose_recipe"].run({"recipe": recipe, "timezone": None, "country_code": None}).text)
    assert any(w.startswith("No record has a buyer_name") for w in out["warnings"])
    assert any("No time zone" in w for w in out["warnings"])


def test_every_tool_schema_is_strict():
    _, _, tool = space()
    for one in tool.values():
        schema = one.parameters
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"]), one.name
