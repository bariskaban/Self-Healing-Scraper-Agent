"""Step 4, the confirm step, as data: a suspect first look, a second look, and the one row that is kept."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.checks import (  # noqa: E402
    Answer, Cause, Confirmation, Effect, ListFacts, cause_of, confirm, effect_of, list_outcome,
    printed_total, transport_check,
)
from app.models import CheckResult, Severity  # noqa: E402


def test_a_suspect_that_clears_is_a_passed_info_row_with_the_first_observation():
    first = printed_total("r1", extracted=21, printed=23)
    second = printed_total("r1", extracted=23, printed=23)
    step = Confirmation(first=first, second=second)
    row = step.result
    assert step.cleared
    assert row.passed and row.severity is Severity.info and row.name == "printed_total"
    assert row.observed["first"]["extracted"] == 21 and row.observed["second"]["extracted"] == 23
    assert "The list reads 21 tenders but the portal prints 23." in row.message
    assert effect_of(row) is Effect.none


def test_a_suspect_that_repeats_is_confirmed_with_both_observations():
    first = printed_total("r1", extracted=9, printed=23)
    step = Confirmation(first=first, second=printed_total("r1", extracted=10, printed=23))
    row = step.result
    assert not step.cleared
    assert not row.passed and row.severity is Severity.fail and effect_of(row) is Effect.breakage
    assert row.observed["extracted"] == 10 and row.observed["first"]["extracted"] == 9
    assert row.observed["confirmed"] is True
    assert row.message == "The list reads 10 tenders but the portal prints 23. A second look found the same."
    assert "effect" not in row.observed and "if_confirmed" not in row.observed


def test_the_confirmed_cause_is_the_one_the_second_look_shows():
    wall = Answer(status=200, login_redirect="/anmelden", password_field=True)
    first = list_outcome("r1", ListFacts(rows=0, answer=wall))
    still = list_outcome("r1", ListFacts(rows=0, answer=wall.model_copy(update={"via": "browser"})))
    blocked = confirm(first, still)
    assert blocked.severity is Severity.block and cause_of(blocked) is Cause.block
    # The browser gets a page without the wall, and still no list: that is a breakage, not a block.
    no_rows = list_outcome("r1", ListFacts(rows=0, answer=Answer(status=200, via="browser")))
    assert effect_of(confirm(first, no_rows)) is Effect.breakage
    # The browser gets the list: the plain client's block was not the portal's last word.
    assert confirm(first, list_outcome("r1", ListFacts(rows=23, answer=Answer(status=200, via="browser")))).passed


def test_a_maintenance_page_seen_twice_is_an_outage_not_a_breakage():
    first = list_outcome("r1", ListFacts(rows=0, answer=Answer(status=200, maintenance=True)))
    row = confirm(first, first)
    assert effect_of(row) is Effect.outage and row.severity is Severity.fail


def test_a_second_look_that_settles_it_alone_is_kept_with_the_first_attached():
    first = transport_check("r1", Answer(status=503), tries=1)
    third = transport_check("r1", Answer(status=503), tries=3)
    row = confirm(first, third)
    assert effect_of(row) is Effect.outage and row.observed["first"]["tries"] == 1
    assert row.message == third.message


def test_only_a_suspect_of_the_same_check_and_run_is_confirmed():
    suspect = printed_total("r1", extracted=9, printed=23)
    fine = printed_total("r1", extracted=23, printed=23)
    with pytest.raises(ValueError):
        confirm(fine, fine)
    with pytest.raises(ValueError):
        confirm(suspect, printed_total("r2", extracted=9, printed=23))
    with pytest.raises(ValueError):
        confirm(suspect, list_outcome("r1", ListFacts(rows=0)))


def test_a_result_built_elsewhere_is_read_by_its_severity():
    def row(severity, passed=False, observed=None):
        return CheckResult(run_id="r1", name="spot_check", passed=passed, severity=severity, observed=observed,
                           message="The model could not find the deadline on the page.")

    assert effect_of(row(Severity.fail)) is Effect.breakage
    assert effect_of(row(Severity.block)) is Effect.block
    assert effect_of(row(Severity.warn, observed="free text")) is Effect.note
    assert effect_of(row(Severity.info)) is Effect.none
    assert effect_of(row(Severity.fail, passed=True)) is Effect.none
