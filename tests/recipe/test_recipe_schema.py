"""The recipe schema (app/recipe/schema.py). Run: pytest tests/recipe/test_recipe_schema.py"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.recipe import AuthoredRecipe, FieldName, NodeRole, PagingKind, RecipeBody, ValueType, problems, validate
from app.recipe.build import css, field, follow, get, jsonpath, label, node, paging, xpath
from tests.recipe.examples import EXAMPLES, html_table_portal


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
    recipe = html_table_portal()
    first = recipe.nodes[0]
    return recipe.model_copy(update={"nodes": [first.model_copy(update={"fields": [*first.fields[:1], spec]}),
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
