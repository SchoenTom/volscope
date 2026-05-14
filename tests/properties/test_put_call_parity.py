"""
Property test: European put-call parity holds for ALL admissible inputs.

    C − P = S · e^(−qT) − K · e^(−rT)

This is the single most important BSM invariant. If it fails for any
parameter combination, the BSM implementation has a bug. We run 1000
randomised cases via Hypothesis.

Tolerance: 1e-4 absolute (BSM-internal CDF evaluations are ~1e-12;
1e-4 is generous and catches real bugs without flaking on FP noise).

Phase 0.5 seed test. Full property-test suite (greeks bounds,
analytical-vs-numerical delta, IV solver round-trip, HV estimator
efficiency) lands in v0.6.0.
"""
from __future__ import annotations

import math

import pytest
from hypothesis import given, settings, strategies as st

from volscope.analytics.black_scholes import bs_price


@pytest.mark.property
@given(
    S=st.floats(min_value=10.0, max_value=1000.0,
                  allow_nan=False, allow_infinity=False),
    K=st.floats(min_value=10.0, max_value=1000.0,
                  allow_nan=False, allow_infinity=False),
    T=st.floats(min_value=0.01, max_value=2.0,
                  allow_nan=False, allow_infinity=False),
    r=st.floats(min_value=-0.02, max_value=0.15,
                  allow_nan=False, allow_infinity=False),
    sigma=st.floats(min_value=0.05, max_value=2.0,
                      allow_nan=False, allow_infinity=False),
    q=st.floats(min_value=0.0, max_value=0.10,
                  allow_nan=False, allow_infinity=False),
)
@settings(max_examples=1000, deadline=None)
def test_put_call_parity(S, K, T, r, sigma, q):
    """C − P must equal S·e^(−qT) − K·e^(−rT) for all admissible inputs."""
    c = bs_price(S, K, T, r, sigma, q, "call")
    p = bs_price(S, K, T, r, sigma, q, "put")
    lhs = c - p
    rhs = S * math.exp(-q * T) - K * math.exp(-r * T)
    assert math.isclose(lhs, rhs, abs_tol=1e-4, rel_tol=1e-6), (
        f"\n  inputs: S={S} K={K} T={T:.4f} r={r} σ={sigma} q={q}\n"
        f"  C - P  = {lhs:.6f}\n"
        f"  S·e⁻qT - K·e⁻rT = {rhs:.6f}\n"
        f"  diff   = {lhs - rhs:+.6e}"
    )


@pytest.mark.property
@given(
    S=st.floats(min_value=20.0, max_value=500.0,
                  allow_nan=False, allow_infinity=False),
    K=st.floats(min_value=20.0, max_value=500.0,
                  allow_nan=False, allow_infinity=False),
    T=st.floats(min_value=0.05, max_value=2.0,
                  allow_nan=False, allow_infinity=False),
    r=st.floats(min_value=0.0, max_value=0.10,
                  allow_nan=False, allow_infinity=False),
    sigma=st.floats(min_value=0.05, max_value=1.5,
                      allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500, deadline=None)
def test_call_price_within_arbitrage_bounds(S, K, T, r, sigma):
    """
    Call price must lie between intrinsic and stock price:

        max(S - K·e^(−rT), 0) ≤ C ≤ S
    """
    c = bs_price(S, K, T, r, sigma, 0.0, "call")
    lower = max(S - K * math.exp(-r * T), 0.0)
    upper = S
    assert lower - 1e-6 <= c <= upper + 1e-6, (
        f"call price {c:.4f} outside [{lower:.4f}, {upper:.4f}] "
        f"for S={S} K={K} T={T} r={r} σ={sigma}"
    )


@pytest.mark.property
@given(
    S=st.floats(min_value=20.0, max_value=500.0,
                  allow_nan=False, allow_infinity=False),
    K=st.floats(min_value=20.0, max_value=500.0,
                  allow_nan=False, allow_infinity=False),
    T=st.floats(min_value=0.05, max_value=2.0,
                  allow_nan=False, allow_infinity=False),
    sigma_lo=st.floats(min_value=0.05, max_value=0.50,
                          allow_nan=False, allow_infinity=False),
    bump=st.floats(min_value=0.05, max_value=0.50,
                     allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200, deadline=None)
def test_call_price_monotone_increasing_in_sigma(S, K, T, sigma_lo, bump):
    """For a call, higher σ → higher price (vega > 0)."""
    sigma_hi = sigma_lo + bump
    c_lo = bs_price(S, K, T, 0.03, sigma_lo, 0.0, "call")
    c_hi = bs_price(S, K, T, 0.03, sigma_hi, 0.0, "call")
    assert c_hi >= c_lo - 1e-6, (
        f"vega < 0 detected: σ {sigma_lo}→{sigma_hi}, "
        f"price {c_lo:.4f}→{c_hi:.4f}"
    )
