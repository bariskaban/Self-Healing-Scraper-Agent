"""Models and prices (app/config.py, Q9). Run: pytest tests/test_config.py"""
import pytest

from app.config import LONG_CONTEXT_TOKENS, PRICES, ModelSettings, api_key, cost_usd, to_eur


def test_defaults_follow_q9():
    s = ModelSettings.from_env({})
    assert (s.learn, s.repair, s.check) == ("gpt-6.2-sol", "gpt-6.2-sol", "gpt-6-luna")
    assert all(s.priced().values())


def test_environment_overrides_each_job():
    s = ModelSettings.from_env({"MODEL_LEARN": "gpt-6.1-terra", "MODEL_CHECK": " gpt-5.4-mini ", "EUR_PER_USD": "0.87"})
    assert (s.learn, s.repair, s.check, s.eur_per_usd) == ("gpt-6.1-terra", "gpt-6.2-sol", "gpt-5.4-mini", 0.87)


def test_bad_settings_are_refused():
    with pytest.raises(ValueError):
        ModelSettings.from_env({"MODEL_REPAIR": "  "})
    with pytest.raises(ValueError):
        ModelSettings(eur_per_usd=0)


def test_unpriced_model_is_reported_not_guessed():
    s = ModelSettings.from_env({"MODEL_LEARN": "gpt-9-unknown"})
    assert s.priced() == {"learn": False, "repair": True, "check": True}
    assert cost_usd("gpt-9-unknown", 1000, 1000) is None


def test_q9_learn_example_costs_1_68_usd():
    # research/q09-models-cost.md: 12 calls of 30K in and 8K out on gpt-6.2-sol.
    one_call = cost_usd("gpt-6.2-sol", 30_000, 8_000)
    assert round(12 * one_call, 4) == 1.68


def test_spot_check_on_luna():
    assert round(cost_usd("gpt-6-luna", 20_000, 1_500), 5) == 0.00275


def test_cached_input_is_billed_at_the_cached_rate():
    full = cost_usd("gpt-6.2-sol", 100_000, 0)
    half_cached = cost_usd("gpt-6.2-sol", 100_000, 0, cached_input_tokens=50_000)
    assert full == pytest.approx(0.20)
    assert half_cached == pytest.approx(0.10 + 0.005)


def test_long_context_bills_the_whole_request_at_long_rates():
    just_under = cost_usd("gpt-6.2-sol", LONG_CONTEXT_TOKENS, 1_000)
    over = cost_usd("gpt-6.2-sol", LONG_CONTEXT_TOKENS + 1, 1_000)
    assert just_under == pytest.approx(272_000 * 2 / 1e6 + 1_000 * 10 / 1e6)
    assert over == pytest.approx(272_001 * 4 / 1e6 + 1_000 * 15 / 1e6)


def test_model_without_long_rates_keeps_its_rates():
    assert PRICES["gpt-5.4-mini"].long_input is None
    assert cost_usd("gpt-5.4-mini", 300_000, 0) == pytest.approx(300_000 * 0.75 / 1e6)


def test_impossible_counts_raise():
    with pytest.raises(ValueError):
        cost_usd("gpt-6-luna", 100, 10, cached_input_tokens=200)
    with pytest.raises(ValueError):
        cost_usd("gpt-6-luna", -1, 10)


def test_euros_and_unknown():
    s = ModelSettings(eur_per_usd=0.9)
    assert to_eur(1.68, s) == pytest.approx(1.512)
    assert to_eur(None, s) is None


def test_api_key_blank_is_none():
    assert api_key({}) is None
    assert api_key({"OPENAI_API_KEY": "   "}) is None
    assert api_key({"OPENAI_API_KEY": "sk-test"}) == "sk-test"
