"""
Golden BSM regression — Hull values.

Each test case is a published worked example from Hull (*Options,
Futures, and Other Derivatives*, 10th ed) or an OptionsAlpha /
QuantLib reference. Tolerance is tight (1e-2 absolute) — these catch
any silent regression in the BSM price formula or _d1_d2 helper.

VolScope uses continuous-dividend (q-continuous) convention. Hull's
worked examples use the same.

Citation column is in the docstring of each test case.
"""
from __future__ import annotations

import math

import pytest

from volscope.analytics.black_scholes import bs_price


# Format: (S, K, T, r, sigma, q, option_type, expected_price, citation)
HULL_GOLDENS = [
    # ── Hull Ch. 15 (Black-Scholes basics) ────────────────────────
    (42, 40, 0.5, 0.10, 0.20, 0.0, "call", 4.7594, "Hull Ex 15.6 — ATM call"),
    (42, 40, 0.5, 0.10, 0.20, 0.0, "put",  0.8086, "Hull Ex 15.6 — ATM put"),
    (49, 50, 20/52, 0.05, 0.20, 0.0, "call", 2.4005,
     "Hull Ex 15.7 — Slightly OTM call, 20 weeks"),
    (50, 50, 0.5, 0.05, 0.30, 0.0, "call", 4.8174,
     "Hull-style ATM call σ=30%"),
    (50, 50, 0.5, 0.05, 0.30, 0.0, "put",  3.5832,
     "Hull-style ATM put σ=30%"),

    # ── Hull Ch. 19 (Greeks worked examples, q=0) ─────────────────
    (49, 50, 0.3846, 0.05, 0.20, 0.0, "call", 2.4005,
     "Hull §19 reference for delta examples"),

    # ── Dividend cases (q > 0) ────────────────────────────────────
    (50, 50, 0.5, 0.05, 0.30, 0.02, "call", 4.5295,
     "Hull-style with q=2% — call lower vs no-div"),
    (50, 50, 0.5, 0.05, 0.30, 0.02, "put", 3.7898,
     "Hull-style with q=2% — put higher vs no-div"),

    # ── Regression goldens (locked, pinned via VolScope's own engine) ──
    # These were not in Hull verbatim — they're our v0.5.0 baseline
    # values, kept here as regression tripwires. Full QuantLib /
    # py_vollib cross-check on these specific cases lands in v0.6.0 A1
    # per docs/roadmap/MASTERPIECE_BACKLOG.md.
    (100, 100, 0.25, 0.03, 0.10, 0.0, "call", 2.3830,
     "Low-IV σ=10% ATM 3-month call — regression lock"),
    (100, 100, 0.25, 0.03, 1.00, 0.0, "call", 20.0433,
     "High-IV σ=100% ATM 3-month call — regression lock"),
    (100, 80, 2.0, 0.04, 0.25, 0.0, "call", 29.4167,
     "Deep ITM 2-year call — regression lock"),
    (100, 120, 2.0, 0.04, 0.25, 0.0, "call", 10.0085,
     "OTM 2-year call — regression lock"),
    (100, 80, 2.0, 0.04, 0.25, 0.0, "put",  3.2660,
     "Deep OTM 2-year put — regression lock"),
    (100, 120, 2.0, 0.04, 0.25, 0.0, "put",  20.7824,
     "ITM 2-year put — regression lock"),
    (100, 100, 7/365, 0.03, 0.20, 0.0, "call", 1.1336,
     "1-week ATM call σ=20% — regression lock"),
    (100, 100, 7/365, 0.03, 0.20, 0.0, "put",  1.0761,
     "1-week ATM put σ=20% — regression lock"),

    # ── Zero-rate environment (recent EU) ─────────────────────────
    (100, 100, 0.25, 0.0, 0.20, 0.0, "call", 3.9876,
     "r=0% ATM 3-month call σ=20%"),
    (100, 100, 0.25, 0.0, 0.20, 0.0, "put",  3.9876,
     "r=0% ATM 3-month put (parity)"),
]


@pytest.mark.golden
@pytest.mark.parametrize(
    "S,K,T,r,sigma,q,option_type,expected,citation",
    HULL_GOLDENS,
    ids=[c[8] for c in HULL_GOLDENS],
)
def test_bs_price_matches_hull(S, K, T, r, sigma, q, option_type, expected, citation):
    """Every Hull/literature reference value within 0.01 of our BSM."""
    actual = bs_price(S, K, T, r, sigma, q, option_type)
    assert math.isclose(actual, expected, abs_tol=0.01), (
        f"\n  {citation}\n"
        f"  inputs:   S={S} K={K} T={T:.4f} r={r} σ={sigma} q={q} type={option_type}\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual:.4f}\n"
        f"  diff:     {actual - expected:+.4f}"
    )


@pytest.mark.golden
def test_zero_T_equals_intrinsic():
    """At expiration, price = intrinsic value."""
    assert bs_price(110, 100, 0, 0.05, 0.20, 0, "call") == 10.0
    assert bs_price(90, 100, 0, 0.05, 0.20, 0, "call") == 0.0
    assert bs_price(90, 100, 0, 0.05, 0.20, 0, "put") == 10.0
    assert bs_price(110, 100, 0, 0.05, 0.20, 0, "put") == 0.0


@pytest.mark.golden
def test_zero_sigma_equals_discounted_intrinsic():
    """At σ=0 a call is worth max(0, S·e^{-qT} − K·e^{-rT})."""
    actual = bs_price(110, 100, 1.0, 0.05, 1e-6, 0, "call")
    expected = max(0.0, 110 - 100 * math.exp(-0.05))
    assert math.isclose(actual, expected, abs_tol=0.01)


@pytest.mark.golden
def test_unknown_option_type_returns_none():
    # Analytics rule: bad input returns None, never raises.
    assert bs_price(100, 100, 0.5, 0.05, 0.20, 0, "swaption") is None
