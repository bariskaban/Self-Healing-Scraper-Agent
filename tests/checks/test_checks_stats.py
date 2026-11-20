"""The exact tests and the settings must reproduce the tables in research/q10-failure-rules.md."""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.checks import (  # noqa: E402
    DEFAULT_SETTINGS, CheckSettings, binomial_upper_tail, fisher_exact_upper, fisher_significant,
    removal_rate, smallest_significant_count, smallest_significant_hits,
)

ALPHA = 0.001
KNOWN = (3, 10, 50, 500)


@pytest.mark.parametrize("rate, counts", [
    (0.01, (2, 3, 5, 14)),   # C3, lost values
    (0.02, (3, 3, 6, 22)),   # C3, changed values
    (0.05, (3, 5, 9, 42)),   # C4, missing tenders
])
def test_thresholds_match_the_research_table(rate, counts):
    assert tuple(smallest_significant_count(n, rate, ALPHA) for n in KNOWN) == counts


def test_the_threshold_is_the_smallest_count_at_most_one_in_a_thousand():
    assert binomial_upper_tail(500, 42, 0.05) <= ALPHA < binomial_upper_tail(500, 41, 0.05)
    assert binomial_upper_tail(3, 2, 0.01) <= ALPHA < binomial_upper_tail(3, 1, 0.01)


def test_one_lost_value_on_a_single_known_tender_is_never_significant():
    assert smallest_significant_count(1, 0.01, ALPHA) is None
    assert smallest_significant_count(0, 0.05, ALPHA) is None


def test_a_result_exactly_on_the_level_counts():
    # 0.1 ** 3 is 0.0010000000000000002 in floats; the chance is exactly 1 in 1,000.
    assert smallest_significant_count(3, 0.1, ALPHA) == 3
    assert binomial_upper_tail(3, 3, 0.1) == pytest.approx(0.001)


def test_what_a_fixed_percentage_would_do_instead():
    # The research: a 30% rule fires on 14% of reads with 3 known tenders, a 50% rule on 0.7%.
    assert binomial_upper_tail(3, 1, 0.05) == pytest.approx(0.142625)
    assert binomial_upper_tail(3, 2, 0.05) == pytest.approx(0.00725)


def test_binomial_tail_edges():
    assert binomial_upper_tail(10, 0, 0.05) == 1.0
    assert binomial_upper_tail(10, 11, 0.05) == 0.0
    assert binomial_upper_tail(10, 1, 0.0) == 0.0
    assert binomial_upper_tail(10, 10, 1.0) == 1.0
    assert smallest_significant_count(10, 0.0, ALPHA) == 1
    with pytest.raises(ValueError):
        binomial_upper_tail(10, 1, 1.5)


def test_large_portals_are_computed_exactly_and_quickly():
    assert smallest_significant_count(20_000, 0.056, ALPHA) == 1223


def test_fisher_cases_from_the_research():
    assert fisher_significant(3, 3, 0, 20, ALPHA)        # 3 nulls among 3 new rows, 0 in 20 before
    assert not fisher_significant(2, 3, 0, 20, ALPHA)    # 2 among 3 is not
    assert fisher_significant(2, 3, 0, 200, ALPHA)       # with 200 earlier rows, 2 among 3 is
    assert not any(fisher_significant(k, 3, 0, 5, ALPHA) for k in range(4))  # 5 rows establish no rate


@pytest.mark.parametrize("earlier_nulls, earlier_rows, fewest", [
    (0, 5, (None, 10, 40)),
    (0, 20, (3, 6, 18)),
    (0, 200, (2, 3, 5)),
    (10, 200, (3, 5, 11)),
])
def test_fisher_table_matches_the_research(earlier_nulls, earlier_rows, fewest):
    assert tuple(smallest_significant_hits(n, earlier_nulls, earlier_rows, ALPHA) for n in (3, 10, 50)) == fewest


def test_fisher_value_and_edges():
    assert fisher_exact_upper(3, 3, 0, 20) == pytest.approx(1 / 1771)
    assert fisher_exact_upper(0, 3, 0, 20) == 1.0
    assert fisher_exact_upper(0, 0, 0, 0) == 1.0
    with pytest.raises(ValueError):
        fisher_exact_upper(4, 3, 0, 20)


def test_defaults_are_the_numbers_the_research_chose():
    s = DEFAULT_SETTINGS
    assert (s.significance, s.removal_rate_per_read) == (0.001, 0.05)
    assert (s.lost_value_rate, s.changed_value_rate) == (0.01, 0.02)
    assert (s.removal_gap_days, s.removal_lifetime_share, s.removal_open_days) == (1, 0.25, 15)
    assert (s.detail_looks_max, s.structure_floor_margin, s.stale_after_intervals) == (5, 0.1, 3)
    assert (s.outage_failed_after_minutes, s.request_tries) == (60, 3)
    assert (s.retry_pause_base_seconds, s.retry_pause_cap_seconds, s.retry_after_inline_max_seconds) == (2, 30, 60)
    assert (s.slowest_request_interval_seconds, s.repair_attempts_per_incident, s.repairs_per_day) == (10, 3, 3)
    assert (s.canary_detail_pages, s.canary_files, s.all_files_failed_min) == (2, 1, 2)


def test_settings_are_one_frozen_object_that_can_be_overridden():
    with pytest.raises(Exception):
        DEFAULT_SETTINGS.significance = 0.01
    with pytest.raises(Exception):
        CheckSettings(no_such_setting=1)
    assert CheckSettings(significance=0.01).significance == 0.01


def test_settings_can_come_from_the_environment():
    env = {"CHECKS_SIGNIFICANCE": "0.01", "CHECKS_DETAIL_LOOKS_MAX": "3", "CHECKS_REPAIRS_PER_DAY": " ",
           "SIGNIFICANCE": "0.5"}
    s = CheckSettings.from_env(env)
    assert (s.significance, s.detail_looks_max, s.repairs_per_day) == (0.01, 3, 3)
    assert CheckSettings.from_env({}) == DEFAULT_SETTINGS
    with pytest.raises(ValueError):
        CheckSettings.from_env({"CHECKS_SIGNIFICANCE": "2"})


def test_removal_rate_grows_after_a_gap_of_more_than_a_day():
    assert removal_rate(None) == 0.05
    assert removal_rate(timedelta(minutes=2)) == 0.05
    assert removal_rate(timedelta(days=1)) == 0.05
    assert removal_rate(timedelta(days=3)) == 0.056   # the research's figures
    assert removal_rate(timedelta(days=7)) == 0.126
    assert removal_rate(timedelta(days=2)) == 0.05    # never below the per-read rate
