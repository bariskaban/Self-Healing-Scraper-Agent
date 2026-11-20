"""A recipe's regular expressions run on bounded text, at each of the four places one is run.

Python's `re` has no timeout and the patterns are written by a model. Every test here hands a
slow pattern a long text and expects the answer at once, because the text is cut or refused
before the pattern sees it. What the bound does NOT cover is said in the last test.
Run: pytest tests/recipe/test_bounded_patterns.py
"""
from __future__ import annotations

import signal
import threading
import time
from contextlib import contextmanager

import pytest

from app.extract import ExtractSettings, ParseContext, parse
from app.recipe.build import css, field, identity, regex, value
from app.recipe.locate import find, parse_page
from app.recipe.resolve import read_fields, read_id
from app.recipe.schema import FieldName as F, NodeKind, ValueType as T
from app.recipe.settings import RecipeSettings

EXPONENTIAL = r"^(a+)+$"          # doubles its work with every further "a" before a mismatch
QUADRATIC = r"(a+)b"              # tries every start, and from each one runs to the end
SMALL = RecipeSettings(pattern_text_limit=2_000, pattern_id_limit=50, pattern_address_limit=300)


@contextmanager
def at_once(seconds: float = 2.0):
    """Fail, rather than hang, when the block takes longer: the pattern is interrupted by an alarm."""
    usable = hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()

    def too_slow(signum, frame):
        raise AssertionError(f"a recipe pattern ran for more than {seconds} seconds")

    if usable:
        before = signal.signal(signal.SIGALRM, too_slow)
        signal.setitimer(signal.ITIMER_REAL, seconds)
    began = time.monotonic()
    try:
        yield
    finally:
        if usable:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, before)
    assert time.monotonic() - began < seconds


def html(body: str, **more):
    return parse_page(f"<html><body>{body}</body></html>", NodeKind.html, "https://x.example/", "text/html", **more)


def id_fields(text: str):
    return read_fields([field(F.id, css("b"), type=T.id)], html(f"<b>{text}</b>"), ParseContext(zone=None, page_url=None, language=None))


def test_the_limits_are_settings():
    assert (RecipeSettings().pattern_text_limit, RecipeSettings().pattern_id_limit,
            RecipeSettings().pattern_address_limit) == (20_000, 200, 2_000)
    env = {"RECIPE_PATTERN_TEXT_LIMIT": "500", "RECIPE_PATTERN_ID_LIMIT": "64", "RECIPE_PATTERN_ADDRESS_LIMIT": "900"}
    assert RecipeSettings.from_env(env) == RecipeSettings(pattern_text_limit=500, pattern_id_limit=64,
                                                          pattern_address_limit=900)
    for name in ("pattern_text_limit", "pattern_id_limit", "pattern_address_limit"):
        with pytest.raises(ValueError):
            RecipeSettings(**{name: 0})


def test_identity_shape_is_not_run_on_an_id_longer_than_the_limit():
    hostile = identity(EXPONENTIAL)
    with at_once():
        read = read_id(hostile, id_fields("a" * 5_000 + "!"), None, SMALL)
    assert read.tender_id is None and "5001 characters long" in read.problem
    # An id within the limit is matched as before, also at the limit itself.
    plain = identity(r"^[A-Z]+-\d+$")
    assert read_id(plain, id_fields("NL-" + "1" * 47), None, SMALL).tender_id == "NL-" + "1" * 47
    assert read_id(plain, id_fields("NL-" + "1" * 48), None, SMALL).tender_id is None
    assert read_id(plain, id_fields("NL-" + "1" * 48), None).tender_id == "NL-" + "1" * 48  # the default is 200


def test_identity_from_url_is_not_run_on_an_address_longer_than_the_limit():
    hostile = identity(r"^.+$", from_url=r"/t/((?:a+)+)$")
    with at_once():
        read = read_id(hostile, {}, "https://x.example/t/" + "a" * 5_000 + "!", SMALL)
    assert (read.tender_id, read.problem) == (None, "no id was found")
    plain = identity(r"^\d+$", from_url=r"/t/(\d+)")
    assert read_id(plain, {}, "https://x.example/t/4711", SMALL).tender_id == "4711"
    long_address = "https://x.example/t/4711?" + "x" * 300
    assert read_id(plain, {}, long_address, SMALL).tender_id is None
    assert read_id(plain, {}, long_address).tender_id == "4711"  # the default allows 2,000 characters


def test_a_regex_locator_sees_only_the_start_of_a_long_text():
    doc = html("<p>" + "a" * 300_000 + "</p>", pattern_text_limit=SMALL.pattern_text_limit)
    with at_once():
        assert find(regex(QUADRATIC), doc) == []
    # What lies beyond the cut cannot match; what lies before it does.
    far = html("<p>Frist: 12.03.2027 " + "x" * 3_000 + " Nummer: 4711</p>", pattern_text_limit=2_000)
    assert [found.text for found in find(regex(r"Frist: (\S+)"), far)] == ["12.03.2027"]
    assert find(regex(r"Nummer: (\d+)"), far) == []
    assert [found.text for found in find(regex(r"Nummer: (\d+)"), html("<p>Nummer: 4711</p>"))] == ["4711"]
    # Inside an item of a list the limit of the item's page holds too.
    (item,) = find(css("p"), doc)
    with at_once():
        assert find(regex(QUADRATIC), item) == []


def test_a_values_pattern_sees_only_the_start_of_a_long_text():
    context = ParseContext(zone=None, page_url=None, language=None, settings=ExtractSettings(pattern_text_limit=2_000))
    with at_once():
        parsed = parse(value(T.text, pattern=QUADRATIC), "a" * 300_000, context)
    assert parsed.value is None and parsed.problem == "pattern did not match"


def test_what_the_bound_does_not_cover():
    """Said plainly, and measured: a pattern that backtracks without end needs no long text.

    `^(a+)+$` on 22 letters and a mismatch takes about four million steps, and twice as many
    with each further letter; an id of 40 such letters would hold a read up for days. The
    length limit does nothing here. Such patterns must be refused when the recipe is written
    (`problems()` in the recipe schema), or run under a real time limit.
    """
    text = "a" * 18 + "!"
    assert len(text) <= RecipeSettings().pattern_id_limit
    began = time.perf_counter()
    assert read_id(identity(EXPONENTIAL), id_fields(text), None).tender_id is None
    short = time.perf_counter() - began
    began = time.perf_counter()
    assert read_id(identity(EXPONENTIAL), id_fields("a" * 21 + "!"), None).tender_id is None
    assert time.perf_counter() - began > 2 * short  # three letters more: about eight times the work
