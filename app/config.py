"""Models and prices (Q9, research/q09-models-cost.md). Nothing else reads a model name or a price.

The model per job comes from the environment, with the defaults Q9 recommends: learn and repair
on gpt-6.2-sol, spot checks on gpt-6-luna. Prices were copied from OpenAI's pricing page on the
date in PRICES_AS_OF; update the table and the date together.

Token counting follows OpenAI's Responses API usage: `input_tokens` includes the cached ones
(`input_tokens_details.cached_tokens`), and `output_tokens` includes reasoning tokens.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

PRICES_AS_OF = date(2026, 11, 20)
PRICES_SOURCE = "https://developers.openai.com/api/docs/pricing"

# One request whose input passes this is billed at the long-context rates for all of it (Q9).
LONG_CONTEXT_TOKENS = 272_000


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens. The long_* rates apply to a whole request over LONG_CONTEXT_TOKENS."""

    input: float
    cached_input: float
    output: float
    long_input: float | None = None
    long_cached_input: float | None = None
    long_output: float | None = None


PRICES: dict[str, Price] = {
    "gpt-6.2-sol": Price(2.00, 0.10, 10.00, 4.00, 0.20, 15.00),
    "gpt-6.1-sol": Price(2.00, 0.10, 10.00, 4.00, 0.20, 15.00),
    "gpt-6-sol": Price(2.00, 0.20, 10.00, 4.00, 0.40, 15.00),
    "gpt-6.1-terra": Price(1.00, 0.05, 5.00, 2.00, 0.10, 7.50),
    "gpt-6-luna": Price(0.10, 0.01, 0.50, 0.20, 0.02, 0.75),
    "gpt-6.2-astra": Price(8.00, 0.40, 40.00, 16.00, 0.80, 60.00),
    "gpt-5.6-terra": Price(2.00, 0.20, 12.00, 4.00, 0.40, 18.00),
    "gpt-5.6-luna": Price(0.20, 0.02, 1.20, 0.40, 0.04, 1.80),
    "gpt-5.4-mini": Price(0.75, 0.075, 4.50),  # accepts at most 272K input tokens
}


@dataclass(frozen=True)
class ModelSettings:
    """Which model does which job, and the rate for showing costs in euros. Built with `from_env()`."""

    learn: str = "gpt-6.2-sol"
    repair: str = "gpt-6.2-sol"
    check: str = "gpt-6-luna"
    # USD -> EUR for the dashboard and the README. Set EUR_PER_USD to the ECB reference rate of
    # the hand-in day; the default is only a placeholder.
    eur_per_usd: float = 0.90

    def __post_init__(self) -> None:
        for job in ("learn", "repair", "check"):
            if not getattr(self, job).strip():
                raise ValueError(f"model for {job} must not be empty")
        if not 0 < self.eur_per_usd < 10:
            raise ValueError("EUR_PER_USD must be a positive rate below 10")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ModelSettings":
        """Defaults overridden by MODEL_LEARN, MODEL_REPAIR, MODEL_CHECK and EUR_PER_USD.

        A blank variable keeps the default. A rate that is not a number, or not a sensible one,
        raises ValueError naming the variable."""
        env = os.environ if environ is None else environ
        defaults = cls()

        def named(variable: str, default: str) -> str:
            # A variable that is set but blank (`-e MODEL_LEARN=`) counts as not set.
            return env.get(variable, "").strip() or default

        return cls(
            learn=named("MODEL_LEARN", defaults.learn),
            repair=named("MODEL_REPAIR", defaults.repair),
            check=named("MODEL_CHECK", defaults.check),
            eur_per_usd=_rate(env.get("EUR_PER_USD"), defaults.eur_per_usd),
        )

    def priced(self) -> dict[str, bool]:
        """For each job, whether its model has a price in the table (a startup check can warn)."""
        return {job: getattr(self, job) in PRICES for job in ("learn", "repair", "check")}


def _rate(raw: str | None, default: float) -> float:
    """EUR_PER_USD as a number. An error names the variable, so an operator can tell what to fix."""
    if raw is None or not raw.strip():  # not set, or set but blank
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"EUR_PER_USD must be a number such as 0.87, got {raw!r}") from None


def api_key(environ: Mapping[str, str] | None = None) -> str | None:
    """OPENAI_API_KEY, or None when it is missing or blank. Never logged."""
    value = (os.environ if environ is None else environ).get("OPENAI_API_KEY", "").strip()
    return value or None


def cost_usd(model: str, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> float | None:
    """What one model call cost in USD, or None when the model has no price (unknown is not zero).

    `input_tokens` includes the cached ones; `output_tokens` includes reasoning tokens.
    """
    price = PRICES.get(model)
    if price is None:
        return None
    if min(input_tokens, output_tokens, cached_input_tokens) < 0 or cached_input_tokens > input_tokens:
        raise ValueError("token counts must be non-negative, and cached tokens at most the input tokens")
    long = input_tokens > LONG_CONTEXT_TOKENS and price.long_input is not None
    rate_in = price.long_input if long else price.input
    rate_cached = price.long_cached_input if long else price.cached_input
    rate_out = price.long_output if long else price.output
    uncached = input_tokens - cached_input_tokens
    return (uncached * rate_in + cached_input_tokens * rate_cached + output_tokens * rate_out) / 1_000_000


def to_eur(usd: float | None, settings: ModelSettings | None = None) -> float | None:
    """USD shown in euros at the configured rate; None stays None."""
    if usd is None:
        return None
    return usd * (settings or ModelSettings.from_env()).eur_per_usd
