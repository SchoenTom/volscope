"""
External BSM validation against ``py_vollib`` (industry reference).

VolScope's option-pricing engine must reproduce a textbook reference to
within machine epsilon for prices and Greeks, and to within solver
tolerance for the IV round-trip. This test pins that promise.

If ``py_vollib`` is not installed, the test is skipped — production
deployments do not need it; CI does.
"""
from __future__ import annotations

import math

import pytest

from volscope.analytics.black_scholes import (
    bs_delta,
    bs_gamma,
    bs_price,
    bs_theta,
    bs_vega,
    implied_volatility,
)


pv = pytest.importorskip("py_vollib.black_scholes")
pvg = pytest.importorskip("py_vollib.black_scholes.greeks.analytical")
pviv = pytest.importorskip("py_vollib.black_scholes.implied_volatility")


# ── Reference cases ─────────────────────────────────────────────────────

# Each tuple = (S, K, T, r, sigma, option_type)
REFERENCE_CASES = [
    (100.0, 100.0,  1.00, 0.05, 0.20, "call"),
    (100.0, 100.0,  1.00, 0.05, 0.20, "put"),
    (100.0, 110.0,  0.50, 0.04, 0.30, "call"),
    (100.0,  90.0,  0.50, 0.04, 0.30, "put"),
    ( 45.32, 80.0,  2.00, 0.04, 0.302, "call"),   # PYPL deck
    ( 50.0,  50.0,  0.10, 0.03, 0.40, "call"),
    (200.0, 150.0,  1.50, 0.05, 0.25, "call"),
    (  1.0, 100.0,  1.00, 0.05, 0.50, "call"),    # deep OTM
    (100.0,   1.0,  1.00, 0.05, 0.50, "call"),    # deep ITM
]


def _flag(option_type: str) -> str:
    return option_type[0]


# ── Price ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("S", "K", "T", "r", "sigma", "option_type"),
    REFERENCE_CASES,
)
def test_bs_price_matches_pyvollib(S, K, T, r, sigma, option_type):
    """Price must reproduce py_vollib to within machine epsilon."""
    vs = bs_price(S, K, T, r, sigma, 0.0, option_type)
    pvref = pv.black_scholes(_flag(option_type), S, K, T, r, sigma)
    assert vs == pytest.approx(pvref, abs=1e-10), (
        f"VS={vs}, py_vollib={pvref} for ({S},{K},{T},{r},{sigma},{option_type})"
    )


# ── Greeks ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("S", "K", "T", "r", "sigma", "option_type"),
    REFERENCE_CASES,
)
def test_bs_delta_matches_pyvollib(S, K, T, r, sigma, option_type):
    vs = bs_delta(S, K, T, r, sigma, 0.0, option_type)
    pvref = pvg.delta(_flag(option_type), S, K, T, r, sigma)
    assert vs == pytest.approx(pvref, abs=1e-10)


@pytest.mark.parametrize(
    ("S", "K", "T", "r", "sigma", "option_type"),
    REFERENCE_CASES,
)
def test_bs_vega_matches_pyvollib(S, K, T, r, sigma, option_type):
    """py_vollib returns vega per 1 % change in σ; we return per 1.00."""
    vs = bs_vega(S, K, T, r, sigma, 0.0)
    pvref = pvg.vega(_flag(option_type), S, K, T, r, sigma) * 100.0
    assert vs == pytest.approx(pvref, abs=1e-10)


@pytest.mark.parametrize(
    ("S", "K", "T", "r", "sigma", "option_type"),
    REFERENCE_CASES,
)
def test_bs_gamma_matches_pyvollib(S, K, T, r, sigma, option_type):
    vs = bs_gamma(S, K, T, r, sigma, 0.0)
    pvref = pvg.gamma(_flag(option_type), S, K, T, r, sigma)
    assert vs == pytest.approx(pvref, abs=1e-10)


# ── IV solver round-trip ────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("S", "K", "T", "r", "sigma", "option_type"),
    [c for c in REFERENCE_CASES if c[5] == "call" and c[0] >= 10],
)
def test_iv_solver_round_trip_matches_input(S, K, T, r, sigma, option_type):
    """Price → IV → must reproduce the input σ within solver tolerance.

    Skips degenerately-ITM cases where the option is essentially priced
    at intrinsic — there IV is not uniquely recoverable from price (the
    vega is near-zero and any σ produces approximately the same number).
    """
    p = pv.black_scholes(_flag(option_type), S, K, T, r, sigma)
    if p < 0.01:
        pytest.skip("price too small for stable IV inversion")
    intrinsic = max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
    if p - intrinsic < 0.05:
        pytest.skip("option is at intrinsic; IV is not uniquely recoverable")
    vs_iv = implied_volatility(p, S, K, T, r, 0.0, option_type)
    assert vs_iv == pytest.approx(sigma, abs=1e-6)


# ── Properties (analytic invariants) ────────────────────────────────────

@pytest.mark.parametrize(
    ("S", "K", "T", "r", "sigma"),
    [(c[0], c[1], c[2], c[3], c[4]) for c in REFERENCE_CASES if c[0] >= 10],
)
def test_call_put_parity(S, K, T, r, sigma):
    """C - P = S - K e^(-rT) for any (S, K, T, σ, r). No dividend."""
    c = bs_price(S, K, T, r, sigma, 0.0, "call")
    p = bs_price(S, K, T, r, sigma, 0.0, "put")
    assert (c - p) == pytest.approx(S - K * math.exp(-r * T), abs=1e-9)


@pytest.mark.parametrize(
    ("S", "K", "T", "r", "sigma", "option_type"),
    REFERENCE_CASES,
)
def test_premium_at_least_intrinsic(S, K, T, r, sigma, option_type):
    """An option's value can never go below its immediate exercise value."""
    p = bs_price(S, K, T, r, sigma, 0.0, option_type)
    intrinsic = max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
    assert p >= intrinsic - 1e-9


def test_call_delta_in_unit_interval():
    for S, K, T, r, sigma, _ in REFERENCE_CASES:
        d = bs_delta(S, K, T, r, sigma, 0.0, "call")
        assert 0.0 <= d <= 1.0 + 1e-9


def test_put_delta_in_negative_unit_interval():
    for S, K, T, r, sigma, _ in REFERENCE_CASES:
        d = bs_delta(S, K, T, r, sigma, 0.0, "put")
        assert -1.0 - 1e-9 <= d <= 0.0


def test_gamma_non_negative():
    for S, K, T, r, sigma, _ in REFERENCE_CASES:
        g = bs_gamma(S, K, T, r, sigma, 0.0)
        assert g >= 0.0


def test_vega_non_negative():
    for S, K, T, r, sigma, _ in REFERENCE_CASES:
        v = bs_vega(S, K, T, r, sigma, 0.0)
        assert v >= 0.0


def test_call_premium_monotone_in_sigma():
    """A call's premium must rise as σ rises, all else equal."""
    S, K, T, r = 100.0, 100.0, 1.0, 0.05
    sigmas = [0.10, 0.20, 0.30, 0.40, 0.60, 0.80]
    prices = [bs_price(S, K, T, r, s, 0.0, "call") for s in sigmas]
    for a, b in zip(prices, prices[1:]):
        assert b >= a - 1e-9


def test_call_premium_monotone_in_t():
    """A call's premium must rise as T rises (with positive rates / no div)."""
    S, K, r, sigma = 100.0, 100.0, 0.05, 0.20
    times = [0.1, 0.5, 1.0, 2.0, 5.0]
    prices = [bs_price(S, K, t, r, sigma, 0.0, "call") for t in times]
    for a, b in zip(prices, prices[1:]):
        assert b >= a - 1e-9
