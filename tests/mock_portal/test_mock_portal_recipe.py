"""The hand-written recipe reads the mock portal's default layout, locator by locator.

This is the check below the executor: every locator of every field, run with `find` and parsed
with `app.extract.parse`, must give the value `portal.truth()` holds.
"""
from __future__ import annotations

import re
from zoneinfo import ZoneInfo

import pytest

from app.extract import ParseContext, parse
from app.recipe.locate import Doc, Found, find, find_items, first_text, parse_page
from app.recipe.schema import AuthoredRecipe, FieldName, Node, NodeRole, RecipeBody, problems
from mock_portal import TIMEZONE, MockPortal, recipe
from mock_portal.pages import size_text

BASE = "https://mock.example"
# The newest (two PDFs and a ZIP), the oldest (two PDFs) and one with three PDFs.
DETAIL_IDS = ["MP-2026-0045", "MP-2026-0001", "MP-2026-0022"]


def node_of(authored: AuthoredRecipe, role: NodeRole) -> Node:
    return next(node for node in authored.nodes if node.role is role)


def fetch_doc(portal: MockPortal, node: Node, url: str) -> Doc:
    status, headers, body = portal.respond("GET", url)
    assert status == 200, url
    return parse_page(body, node.kind, url, headers["Content-Type"])


def assert_fields_read(node: Node, scope: Doc | Found, page_url: str, truth: dict, authored: AuthoredRecipe) -> None:
    """Every locator of every field of the node finds one value in the scope, and it is the true one."""
    context = ParseContext(zone=ZoneInfo(TIMEZONE), page_url=page_url, language=authored.host.language)
    for field in node.fields:
        for number, locator in enumerate(field.locators, 1):
            where = f"{truth['id']} {node.id}.{field.name.value} locator {number}"
            hits = find(locator, scope)
            assert len(hits) == 1, where
            parsed = parse(field.value, hits[0].text, context)
            assert parsed.problem is None, f"{where}: {parsed.problem}"
            assert parsed.value == truth[field.name.value], where


def test_the_recipe_has_no_problems():
    assert problems(recipe()) == []
    assert problems(recipe("/mock")) == []
    assert RecipeBody.from_authored(recipe()).format == "recipe/v1"


def test_the_recipe_reads_what_the_contract_needs():
    authored = recipe()
    listed = {field.name for field in node_of(authored, NodeRole.list).fields}
    detailed = {field.name for field in node_of(authored, NodeRole.detail).fields}
    assert listed | detailed == set(FieldName)
    assert node_of(authored, NodeRole.detail).documents is not None


def test_every_list_locator_reads_the_truth():
    portal, authored = MockPortal(), recipe()
    node = node_of(authored, NodeRole.list)
    truth = {t["id"]: t for t in portal.truth()}
    url: str | None = portal.base_url + node.request.url
    url_spec = next(field.value for field in node.fields if field.name is FieldName.url)
    read: list[str] = []
    pages = 0
    while url:
        doc = fetch_doc(portal, node, url)
        pages += 1
        assert first_text(node.facts.total, doc) == "45"
        assert find(node.facts.empty_marker, doc) == []
        items = find_items(node.items, doc)
        for item in items:
            ident = first_text(node.fields[0].locators[0], item)
            read.append(ident)
            assert_fields_read(node, item, doc.url, truth[ident], authored)
        # The next link is a path; the url field's value spec makes it absolute, as the executor will.
        following = first_text(node.paging.next, doc)
        context = ParseContext(zone=None, page_url=doc.url, language="en")
        url = parse(url_spec, following, context).value if following else None
    assert pages == 3
    assert read == [t["id"] for t in portal.truth()]


@pytest.mark.parametrize("tender_id", DETAIL_IDS)
def test_every_detail_locator_reads_the_truth(tender_id: str):
    portal, authored = MockPortal(), recipe()
    node = node_of(authored, NodeRole.detail)
    truth = next(t for t in portal.truth() if t["id"] == tender_id)
    doc = fetch_doc(portal, node, truth["url"])
    assert_fields_read(node, doc, doc.url, truth, authored)


@pytest.mark.parametrize("tender_id", DETAIL_IDS)
def test_the_documents_rule_finds_every_file(tender_id: str):
    portal, authored = MockPortal(), recipe()
    node = node_of(authored, NodeRole.detail)
    truth = next(t for t in portal.truth() if t["id"] == tender_id)
    doc = fetch_doc(portal, node, truth["url"])
    links = find(node.documents.links, doc)
    assert [link.text for link in links] == [f"/files/{tender_id}/{name}" for name, _, _ in truth["documents"]]
    for link, (name, size, _) in zip(links, truth["documents"]):
        assert first_text(node.documents.name, link) == name
        assert first_text(node.documents.size, link) == size_text(size)
        assert portal.respond("GET", portal.base_url + link.text)[0] == 200


def test_the_follow_edge_and_the_identity_agree_with_the_list():
    portal, authored = MockPortal(), recipe()
    node = node_of(authored, NodeRole.list)
    edge = authored.edges[0]
    assert (edge.source, edge.target, edge.per_item) == ("list", "detail", True)
    doc = fetch_doc(portal, node, portal.base_url + "/tenders")
    for item, truth in zip(find_items(node.items, doc), portal.truth()):
        href = first_text(edge.link, item)
        assert portal.base_url + href == truth["url"]
        assert re.search(authored.identity.from_url, href).group(1) == truth["id"]
        assert re.fullmatch(authored.identity.shape, truth["id"])


def test_the_recipe_follows_the_switches_that_change_what_is_true():
    portal, authored = MockPortal(), recipe()
    portal.withdrawn = {"MP-2026-0045"}
    portal.deadline_moved = {"MP-2026-0001": "30.09.2027 15:30"}
    detail = node_of(authored, NodeRole.detail)
    for tender_id in ("MP-2026-0045", "MP-2026-0001"):
        truth = next(t for t in portal.truth() if t["id"] == tender_id)
        doc = fetch_doc(portal, detail, truth["url"])
        assert_fields_read(detail, doc, doc.url, truth, authored)


def test_the_recipe_sees_the_empty_list_notice():
    portal, authored = MockPortal(), recipe()
    node = node_of(authored, NodeRole.list)
    portal.list_emptied = "with_notice"
    doc = fetch_doc(portal, node, portal.base_url + "/tenders")
    assert find_items(node.items, doc) == []
    assert first_text(node.facts.empty_marker, doc) == "No tenders are currently published."
    assert first_text(node.facts.total, doc) == "0"
    portal.list_emptied = "without_notice"
    doc = fetch_doc(portal, node, portal.base_url + "/tenders")
    assert find_items(node.items, doc) == []
    assert find(node.facts.empty_marker, doc) == [] and find(node.facts.total, doc) == []


def test_the_recipe_cannot_read_the_changed_layout():
    portal, authored = MockPortal(), recipe()
    portal.layout_changed = True
    listing = node_of(authored, NodeRole.list)
    doc = fetch_doc(portal, listing, portal.base_url + "/tenders")
    assert find_items(listing.items, doc) == []
    assert find(listing.facts.total, doc) == [] and find(listing.paging.next, doc) == []
    detail = node_of(authored, NodeRole.detail)
    doc = fetch_doc(portal, detail, portal.tender_url("MP-2026-0045"))
    for name in (FieldName.submission_deadline, FieldName.buyer_name, FieldName.status, FieldName.reference_number):
        field = next(f for f in detail.fields if f.name is name)
        assert [hit.text for locator in field.locators for hit in find(locator, doc)] == [], name
    assert find(detail.documents.links, doc) == []
