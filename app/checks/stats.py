"""Exact tests behind the thresholds (Q10). Standard library only.

Everything is computed in whole numbers, so a result that sits exactly on the level
(three of three at a rate of 0.1 has a chance of exactly 1 in 1,000) is decided the
same way on every machine.
"""
from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from math import comb


def _exact(value: float) -> Fraction:
    """A setting written as 0.05 means 1/20, not the nearest binary float."""
    return Fraction(str(value))


def _lower_sum(n: int, k: int, rate: Fraction) -> tuple[int, int]:
    """Chance of fewer than k hits in n tries, as (numerator, denominator)."""
    a, b = rate.numerator, rate.denominator
    term = (b - a) ** n  # the chance of 0 hits, times b**n
    below = 0
    for i in range(k):
        below += term
        term = term * (n - i) * a // ((i + 1) * (b - a))
    return below, b ** n


def binomial_upper_tail(n: int, k: int, q: float) -> float:
    """Chance that k or more of n tenders do something whose chance is q each."""
    if n < 0 or not 0 <= q <= 1:
        raise ValueError("n must be 0 or more and q between 0 and 1")
    if k <= 0:
        return 1.0
    if k > n or q == 0:
        return 0.0
    if q == 1:
        return 1.0
    below, whole = _lower_sum(n, k, _exact(q))
    return float(Fraction(whole - below, whole))


@lru_cache(maxsize=4096)
def smallest_significant_count(n: int, q: float, alpha: float) -> int | None:
    """Smallest count out of n whose chance at rate q is at most alpha; None when no count is that rare."""
    if n < 0 or not 0 <= q <= 1 or not 0 < alpha < 1:
        raise ValueError("n must be 0 or more, q between 0 and 1, alpha between 0 and 1")
    if n == 0 or q == 1:
        return None
    if q == 0:
        return 1
    rate, level = _exact(q), _exact(alpha)
    a, b = rate.numerator, rate.denominator
    whole = b ** n
    term = (b - a) ** n
    below = 0
    for k in range(1, n + 1):
        below += term  # now the chance of fewer than k hits
        if (whole - below) * level.denominator <= level.numerator * whole:
            return k
        term = term * (n - k + 1) * a // (k * (b - a))
    return None


def _fisher_tail(hits_new: int, n_new: int, hits_old: int, n_old: int) -> Fraction:
    if min(hits_new, n_new, hits_old, n_old) < 0 or hits_new > n_new or hits_old > n_old:
        raise ValueError("counts must be 0 or more, and hits no more than rows")
    total, hits = n_new + n_old, hits_new + hits_old
    if hits_new == 0 or total == 0:
        return Fraction(1)
    ways = sum(comb(hits, x) * comb(total - hits, n_new - x) for x in range(hits_new, min(hits, n_new) + 1))
    return Fraction(ways, comb(total, n_new))


def fisher_exact_upper(hits_new: int, n_new: int, hits_old: int, n_old: int) -> float:
    """One-sided Fisher exact test: chance of hits_new or more among the new rows if old and new share one rate."""
    return float(_fisher_tail(hits_new, n_new, hits_old, n_old))


def fisher_significant(hits_new: int, n_new: int, hits_old: int, n_old: int, alpha: float) -> bool:
    """True when the new rows hold more hits than chance allows at level alpha."""
    return _fisher_tail(hits_new, n_new, hits_old, n_old) <= _exact(alpha)


def smallest_significant_hits(n_new: int, hits_old: int, n_old: int, alpha: float) -> int | None:
    """Fewest hits among n_new new rows that Fisher's test calls significant; None when none is."""
    for hits_new in range(1, n_new + 1):
        if fisher_significant(hits_new, n_new, hits_old, n_old, alpha):
            return hits_new
    return None
