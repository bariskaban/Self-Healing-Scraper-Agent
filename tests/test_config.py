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


# The table of research/q09-models-cost.md ("Model facts"), typed in again here, so that a slip
# in app/config.py fails a test: (input, cached input, output) and the same over 272K input.
# gpt-6-sol's long rates are the file's "2x in, 1.5x out", with the cached rate doubled too.
Q9_TABLE = {
    "gpt-6.2-sol": ((2, 0.10, 10), (4, 0.20, 15)),
    "gpt-6.1-sol": ((2, 0.10, 10), (4, 0.20, 15)),
    "gpt-6-sol": ((2, 0.20, 10), (4, 0.40, 15)),
    "gpt-6.1-terra": ((1, 0.05, 5), (2, 0.10, 7.50)),
    "gpt-6-luna": ((0.10, 0.01, 0.50), (0.20, 0.02, 0.75)),
    "gpt-6.2-astra": ((8, 0.40, 40), (16, 0.80, 60)),
    "gpt-5.6-terra": ((2, 0.20, 12), (4, 0.40, 18)),
    "gpt-5.6-luna": ((0.20, 0.02, 1.20), (0.40, 0.04, 1.80)),
    "gpt-5.4-mini": ((0.75, 0.075, 4.50), (None, None, None)),
}


def test_price_table_is_q9s_table_with_its_date():
    from datetime import date

    from app.config import PRICES_AS_OF, PRICES_SOURCE

    got = {m: ((p.input, p.cached_input, p.output), (p.long_input, p.long_cached_input, p.long_output))
           for m, p in PRICES.items()}
    assert got == Q9_TABLE
    assert PRICES_AS_OF == date(2026, 11, 20)  # the day Q9 read the pricing page
    assert PRICES_SOURCE.startswith("https://developers.openai.com/")


def test_long_context_also_changes_the_cached_rate():
    # 300K input of which 200K cached, 10K output: (100K x 4 + 200K x 0.20 + 10K x 15) / 1M.
    assert cost_usd("gpt-6.2-sol", 300_000, 10_000, cached_input_tokens=200_000) == pytest.approx(0.59)


def test_the_272k_rule_is_per_request_not_per_run():
    # Q9's learn is 360K input over 12 calls; no single call is over 272K, so none is billed long.
    per_call = sum(cost_usd("gpt-6.2-sol", 30_000, 8_000) for _ in range(12))
    assert per_call == pytest.approx(1.68)
    assert cost_usd("gpt-6.2-sol", 360_000, 96_000) == pytest.approx(2.88)  # what a run total would give


def test_reasoning_tokens_are_not_a_separate_charge():
    # Q9: 8K output = 3K visible + 5K reasoning. The caller passes output_tokens as OpenAI reports it.
    assert cost_usd("gpt-6.2-sol", 0, 8_000) == pytest.approx(0.08)


def test_negative_output_or_cached_counts_raise():
    with pytest.raises(ValueError):
        cost_usd("gpt-6-luna", 10, -1)
    with pytest.raises(ValueError):
        cost_usd("gpt-6-luna", 10, 10, cached_input_tokens=-1)


@pytest.mark.parametrize("raw", ["", "abc", "0,87"])
def test_bad_eur_rate_names_the_variable(raw):
    with pytest.raises(ValueError, match="EUR_PER_USD"):
        ModelSettings.from_env({"EUR_PER_USD": raw})


def test_settings_and_errors_never_show_the_key():
    key = "sk-test-not-a-real-key-0123456789"
    with pytest.raises(ValueError) as error:
        ModelSettings.from_env({"OPENAI_API_KEY": key, "EUR_PER_USD": "abc"})
    settings = ModelSettings.from_env({"OPENAI_API_KEY": key})
    assert key not in f"{settings!r} {settings} {error.value!r} {settings.priced()}"


def test_import_needs_no_key_and_no_openai(monkeypatch):
    import importlib
    import sys

    import app.config

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delitem(sys.modules, "openai", raising=False)
    importlib.reload(app.config)
    assert "openai" not in sys.modules
    assert app.config.api_key() is None
