"""The recipe schema (app/recipe/schema.py). Run: pytest tests/recipe/test_recipe_schema.py"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.recipe import AuthoredRecipe, FieldName, NodeRole, PagingKind, RecipeBody, ValueType, problems, validate
from app.recipe.build import css, field, follow, get, identity, jsonpath, label, node, paging, regex, xpath
from app.recipe.schema import NodeKind, Via, nested_quantifier
from mock_portal import recipe as mock_portal_recipe
from tests.recipe.examples import EXAMPLES, form_post_portal, html_table_portal, json_api_portal


# -- the worked examples --------------------------------------------------------

@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_each_example_recipe_can_be_run(name):
    recipe = EXAMPLES[name]()
    assert problems(recipe) == []
    validate(recipe)


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_a_recipe_survives_storing_as_json(name):
    recipe = EXAMPLES[name]()
    body = RecipeBody.from_authored(recipe)
    assert body.format == "recipe/v1" and body.expectations is None
    stored = json.loads(json.dumps(body.model_dump(mode="json")))   # what Recipe.body holds
    assert RecipeBody.model_validate(stored) == body
    assert AuthoredRecipe.model_validate(recipe.model_dump(mode="json")) == recipe


# -- OpenAI's rules for strict structured output --------------------------------

ALLOWED_KEYWORDS = {"type", "properties", "required", "additionalProperties", "items", "anyOf", "enum", "const",
                    "$ref", "$defs", "title", "description"}


def walk(schema: dict, defs: dict, depth: int = 0, seen: tuple[str, ...] = ()):
    """Every object schema reachable from `schema`, with the depth it is nested at."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name in seen:
            return
        yield from walk(defs[name], defs, depth, (*seen, name))
        return
    if schema.get("type") == "object":
        yield schema, depth
        for child in schema.get("properties", {}).values():
            yield from walk(child, defs, depth + 1, seen)
    for child in schema.get("anyOf", []):
        yield from walk(child, defs, depth, seen)
    if "items" in schema:
        yield from walk(schema["items"], defs, depth, seen)


def test_the_learners_answer_fits_strict_structured_output():
    schema = AuthoredRecipe.model_json_schema()
    defs = schema.get("$defs", {})
    assert schema["type"] == "object" and "anyOf" not in schema, "the root is one object"
    objects = list(walk(schema, defs))
    assert len(objects) > 10
    properties = 0
    for obj, depth in objects:
        name = obj.get("title")
        assert obj.get("additionalProperties") is False, f"{name} must refuse unknown keys"
        assert set(obj.get("required", [])) == set(obj["properties"]), f"{name}: every field is required"
        assert depth < 10, f"{name} is nested deeper than strict output allows"
        properties += len(obj["properties"])
    assert properties < 5000

    def keywords(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                if key not in ("properties", "$defs"):
                    yield from keywords(value)
                else:
                    for child in value.values():
                        yield from keywords(child)
        elif isinstance(node, list):
            for child in node:
                yield from keywords(child)

    # No defaults, no maps with free keys, no keyword strict output does not know.
    assert set(keywords(schema)) <= ALLOWED_KEYWORDS, sorted(set(keywords(schema)) - ALLOWED_KEYWORDS)


def test_nothing_in_a_recipe_has_a_default_and_unknown_keys_are_refused():
    whole = html_table_portal().model_dump(mode="json")
    for key in whole:
        with pytest.raises(ValidationError):
            AuthoredRecipe.model_validate({k: v for k, v in whole.items() if k != key})
    with pytest.raises(ValidationError):
        AuthoredRecipe.model_validate({**whole, "validators": ["count within 30%"]})
    first_node = dict(whole["nodes"][0])
    first_node.pop("steps")
    with pytest.raises(ValidationError):
        AuthoredRecipe.model_validate({**whole, "nodes": [first_node, *whole["nodes"][1:]]})


# -- rules a JSON schema cannot say ---------------------------------------------

def changed(**updates) -> AuthoredRecipe:
    return html_table_portal().model_copy(update=updates)


def with_list_field(spec) -> AuthoredRecipe:
    """The HTML example with this field on its list, in place of the list's field of the same name."""
    recipe = html_table_portal()
    first = recipe.nodes[0]
    kept = [existing for existing in first.fields if existing.name is not spec.name]
    return recipe.model_copy(update={"nodes": [first.model_copy(update={"fields": [*kept, spec]}),
                                               *recipe.nodes[1:]]})


def one_problem(recipe: AuthoredRecipe, *words: str) -> str:
    found = [p for p in problems(recipe) if all(word in p for word in words)]
    assert found, f"no problem mentions {words}: {problems(recipe)}"
    return found[0]


@pytest.mark.parametrize("locator, words", [
    (xpath("/html/body/div[2]/table/tr/td"), ("absolute XPath",)),
    (xpath("//table//tr[3]/td"), ("positional XPath",)),
    (xpath("//td[position()=2]"), ("positional XPath",)),
    (css("table tr td:nth-child(3)"), ("position in a CSS selector",)),
    (css(""), ("needs `expr`",)),
    (label(), ("at least one label",)),
    (jsonpath("content.title"), ("JSONPath starts with",)),
])
def test_a_locator_that_is_a_position_or_incomplete_is_refused(locator, words):
    one_problem(with_list_field(field(FieldName.title, locator)), *words)


def test_a_locator_anchored_on_an_attribute_or_a_text_is_fine():
    good = with_list_field(field(FieldName.title, xpath("//td[@class='titel']/a"),
                                 xpath("//dt[normalize-space()='Titel']/following-sibling::dd"),
                                 css("td.titel a[data-kind='tender']")))
    assert problems(good) == []


def test_a_field_has_one_to_three_locators_and_the_type_its_name_needs():
    one_problem(with_list_field(field(FieldName.title)), "one to three locators")
    one_problem(with_list_field(field(FieldName.title, *[css("a")] * 4)), "one to three locators")
    one_problem(with_list_field(field(FieldName.submission_deadline, css("td.frist"))), "value type", "datetime")
    one_problem(with_list_field(field(FieldName.cpv_codes, css("td.cpv"))), "value type", "cpv")


def test_words_must_map_to_the_contracts_values():
    one_problem(with_list_field(field(FieldName.status, css("td.status"), type=ValueType.status)), "needs `words`")
    one_problem(with_list_field(field(FieldName.status, css("td.status"), type=ValueType.status,
                                      words={"Laufend": "active"})), "'active'", "not one of")
    assert problems(with_list_field(field(FieldName.status, css("td.status"), type=ValueType.status,
                                          words={"Laufend": "open", "Aufgehoben": "withdrawn"}))) == []


def test_a_recipe_has_exactly_one_list_and_every_node_is_reachable():
    recipe = html_table_portal()
    one_problem(changed(nodes=[recipe.nodes[1]], start="detail", edges=[]), "exactly one node with the role list")
    extra = node("orphan", NodeRole.step)
    one_problem(changed(nodes=[*recipe.nodes, extra]), "'orphan'", "cannot be reached")
    one_problem(changed(nodes=[*recipe.nodes, recipe.nodes[1]]), "used more than once")
    one_problem(changed(start="nowhere"), "`start`", "not a node")
    one_problem(changed(edges=[follow("list", "missing", css("a", attr="href"))]), "'missing' is not a node")


def test_a_tender_needs_an_id_from_the_list_or_from_its_address():
    recipe = html_table_portal()
    first = recipe.nodes[0]
    without_id = first.model_copy(update={"fields": first.fields[1:]})
    no_id_field = recipe.model_copy(update={"nodes": [without_id, recipe.nodes[1]]})
    assert problems(no_id_field) == []   # the id still comes from the address
    nowhere = no_id_field.model_copy(update={"identity": recipe.identity.model_copy(update={"from_url": None})})
    one_problem(nowhere, "a tender has no id")
    one_problem(changed(identity=recipe.identity.model_copy(update={"from_url": r"/ausschreibungen/\d+"})),
                "exactly one group")
    one_problem(changed(identity=recipe.identity.model_copy(update={"shape": "([0-9"})), "regular expression")


def test_paging_and_requests_are_complete():
    recipe = html_table_portal()
    first = recipe.nodes[0]

    def with_list(**updates) -> AuthoredRecipe:
        return recipe.model_copy(update={"nodes": [first.model_copy(update=updates), recipe.nodes[1]]})

    one_problem(with_list(paging=paging(PagingKind.page_param)), "page_param paging needs `param`")
    one_problem(with_list(paging=paging(PagingKind.cursor)), "cursor paging needs `next`")
    one_problem(with_list(request=get("/list", page="{seite}")), "unknown placeholder {seite}")
    assert problems(with_list(request=get("/list", page="{page}", size="{size}"))) == []
    one_problem(with_list(request=None), "start node needs a `request`")
    one_problem(with_list(items=None), "needs `items`")
    # Paging placeholders mean nothing on a tender's own page.
    one_problem(recipe.model_copy(update={"edges": [recipe.edges[0].model_copy(
        update={"action": "call_api", "request": get("/detail/{page}")})]}), "unknown placeholder {page}")


def test_validate_names_every_problem_in_one_message():
    broken = with_list_field(field(FieldName.title, xpath("/html/body/table/tr[2]/td")))
    with pytest.raises(ValueError) as error:
        validate(broken)
    assert "absolute XPath" in str(error.value) and "positional XPath" in str(error.value)


# -- the follow-up rules (review of the schema) ----------------------------------

def test_the_mock_portals_recipe_can_be_run():
    assert problems(mock_portal_recipe()) == [] and problems(mock_portal_recipe("/mock")) == []


@pytest.mark.parametrize("expr", [
    "//dt[normalize-space()='Angebotsfrist']/following-sibling::dd[1]",   # Q2's own: the value next to a label
    "//th[.='Frist']/following-sibling::td[ 2 ]",
    "//dd[@class='wert']/preceding-sibling::dt[1]",
    "//dt[.='Frist']/following-sibling::*[1]",
    "//dt[.='Frist']/following-sibling::dd[1]/span[@class='zeit']",
])
def test_a_number_straight_after_a_sibling_step_is_an_anchor(expr):
    assert problems(with_list_field(field(FieldName.title, xpath(expr)))) == []


@pytest.mark.parametrize("expr", [
    "//table//tr[3]/td",                                         # a position with no label before it
    "//dt[.='Frist']/following-sibling::dd[1]/span[2]",          # allowed after the sibling step, not after the next
    "//dt[.='Frist']/following-sibling::dd[1][2]",
    "//dt[.='Frist']/following-sibling::dd[@class='x'][1]",      # not straight after the node test
    "//dt[.='Frist']/following-sibling::dd[position()=1]",
    "//dt[.='Frist']/following-sibling::dd[last()]",
    "//dt[.='Frist']/following::dd[1]",                          # another axis
    "//ul/child::li[1]",
])
def test_a_number_anywhere_else_in_an_xpath_is_still_refused(expr):
    one_problem(with_list_field(field(FieldName.title, xpath(expr))), "positional XPath", "following-sibling::name")


def without_field(recipe: AuthoredRecipe, name: FieldName, *node_ids: str) -> AuthoredRecipe:
    """The recipe with one field taken off the named nodes (off every node when none is named)."""
    nodes = [n.model_copy(update={"fields": [f for f in n.fields if f.name is not name]})
             if (not node_ids or n.id in node_ids) else n for n in recipe.nodes]
    return recipe.model_copy(update={"nodes": nodes})


@pytest.mark.parametrize("name", ["url", "title", "buyer_name", "publication_date", "submission_deadline"])
@pytest.mark.parametrize("example", sorted(EXAMPLES))
def test_a_required_field_no_node_reads_is_a_problem(example, name):
    recipe = without_field(EXAMPLES[example](), FieldName(name))
    found = one_problem(recipe, "No node reads the required field", f"`{name}`")
    assert "every tender would be delivered without it" in found
    assert [p for p in problems(recipe) if "No node reads" in p] == [found]


def test_a_required_field_read_on_one_node_only_is_enough():
    # The deadline is on the list and on the detail page of the HTML example: either one will do.
    assert problems(without_field(html_table_portal(), FieldName.submission_deadline, "list")) == []
    assert problems(without_field(html_table_portal(), FieldName.submission_deadline, "detail")) == []
    # A field that is not required may be read nowhere.
    assert problems(without_field(html_table_portal(), FieldName.description)) == []


def test_the_id_is_read_by_a_node_or_comes_from_the_address():
    recipe = form_post_portal()   # no id field anywhere: the id is in the address
    assert problems(recipe) == []
    no_address = recipe.model_copy(update={"identity": recipe.identity.model_copy(update={"from_url": None})})
    assert problems(no_address) == [one_problem(no_address, "a tender has no id")]   # said once, by the list's rule


@pytest.mark.parametrize("name", ["url", "title", "buyer_name", "publication_date", "submission_deadline"])
def test_a_list_that_says_it_has_every_required_field_must_read_each_one(name):
    recipe = form_post_portal()   # `has_all_required` is true, and the tender has no page of its own
    kind = next(f.value.type for f in recipe.nodes[1].fields if f.name.value == name)
    formats = ["%d/%m/%Y"] if "date" in kind.value else None
    extra = node("detail", NodeRole.detail, fields=[field(FieldName(name), css(".x"), type=kind, formats=formats)])
    elsewhere = without_field(recipe, FieldName(name), "list")
    elsewhere = elsewhere.model_copy(update={
        "nodes": [*elsewhere.nodes, extra],
        "edges": [*elsewhere.edges, follow("list", "detail", css("h3 a", attr="href"))]})
    found = one_problem(elsewhere, "node list", "`has_all_required` is true", f"`{name}`")
    assert "set `has_all_required` to false" in found
    assert problems(elsewhere) == [found]   # read elsewhere, so it is not also "read by no node"
    # With the flag off the same recipe is fine: the detail page carries the field.
    facts_off = elsewhere.nodes[1].facts.model_copy(update={"has_all_required": False})
    relaxed = elsewhere.model_copy(update={"nodes": [elsewhere.nodes[0],
                                                     elsewhere.nodes[1].model_copy(update={"facts": facts_off}),
                                                     *elsewhere.nodes[2:]]})
    assert problems(relaxed) == []


def test_has_all_required_counts_an_id_from_the_address():
    assert form_post_portal().nodes[1].facts.has_all_required
    assert not any(f.name is FieldName.id for f in form_post_portal().nodes[1].fields)
    assert problems(form_post_portal()) == []


def test_load_more_paging_needs_a_browser_node():
    recipe = html_table_portal()
    first = recipe.nodes[0]
    button = paging(PagingKind.load_more, next=css("button.mehr"))

    def with_list(**updates) -> AuthoredRecipe:
        return recipe.model_copy(update={"nodes": [first.model_copy(update=updates), recipe.nodes[1]]})

    found = one_problem(with_list(paging=button), "load_more paging", "browser node")
    assert "this node is html" in found
    api = json_api_portal()
    one_problem(api.model_copy(update={"nodes": [api.nodes[0].model_copy(update={"paging": button}), *api.nodes[1:]]}),
                "load_more paging", "this node is json")
    assert problems(with_list(paging=button, kind=NodeKind.browser)) == []
    # A request sent through the browser to an HTML node is not refused: the executor can do that.
    assert problems(with_list(request=get("/ausschreibungen", via=Via.browser))) == []


NESTED = [r"^(a+)+$", r"(\d*)*", r"(?:x+|y)+z", r"^(\w+\s?)*$", r"(?:a{2,})+", r"(?:(?:ab)+c)*", r"(a+?)+?",
          r"(?:\d+\.)+\d+"]  # the last one is harmless, and refused all the same: the heuristic is simple
NOT_NESTED = [r"^\d{4}-\d{3,6}$", r"/ausschreibungen/(\d{4}-\d+)", r"(\d+) Ausschreibungen gefunden",
              r"^[A-Z]+(?:-\d{1,9})+$", r"(?:ab|cd)+", r"(a+)(b+)", r"(?:a+){1,5}", r"(?:a{1,3})+", r"[(a+)+]+",
              r"\(a+\)+", r"a*a*a*b"]  # the last one is slow without nesting: not this rule's business


@pytest.mark.parametrize("pattern", NESTED)
def test_a_repeat_without_limit_inside_another_is_seen(pattern):
    assert nested_quantifier(pattern)


@pytest.mark.parametrize("pattern", NOT_NESTED)
def test_other_patterns_are_let_through(pattern):
    assert not nested_quantifier(pattern)


def test_a_nested_repeat_is_refused_wherever_a_recipe_holds_a_pattern():
    recipe = html_table_portal()
    hostile = r"^(a+)+$"
    in_shape = changed(identity=recipe.identity.model_copy(update={"shape": hostile}))
    assert "upper bound" in one_problem(in_shape, "identity.shape", "repeats without limit")
    in_address = changed(identity=recipe.identity.model_copy(update={"from_url": r"/t/((?:a+)+)$"}))
    one_problem(in_address, "identity.from_url", "repeats without limit")
    one_problem(with_list_field(field(FieldName.title, regex(r"Titel: ((?:\w+ ?)+)"))), "locator 1",
                "repeats without limit")
    one_problem(with_list_field(field(FieldName.title, css("a.titel"), pattern=hostile)), "title.pattern",
                "repeats without limit")
    # The same patterns with a bound are accepted.
    assert problems(changed(identity=identity(r"^(?:a{1,40})+$", from_url=r"/t/((?:a{1,40})+)$"))) == []
    assert problems(with_list_field(field(FieldName.title, regex(r"Titel: ((?:\w{1,60} ?)+)")))) == []
    # A pattern that is no pattern is still reported as that, once.
    assert not nested_quantifier("([0-9")
    assert len([p for p in problems(changed(identity=identity("([0-9"))) if "identity.shape" in p]) == 1
