"""
Property test: VolScope BSM agrees with py_vollib_vectorized at 1e-8.

py_vollib_vectorized is the canonical reference implementation —
maintained by Iadarola, numpy-vectorized, used in production by
many quant shops. Agreement at 1e-8 is the "we cross-checked against
the canonical reference" claim that makes our BSM defensible.

Phase 0.5 deliverable A3 (per docs/roadmap/MASTERPIECE_BACKLOG.md).
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

pytest.importorskip("py_vollib_vectorized")

import py_vollib_vectorized as pvv   # noqa: E402

from volscope.analytics.black_scholes import bs_price   # noqa: E402


@pytest.mark.property
@given(
    S=st.floats(min_value=20.0, max_value=500.0,
                  allow_nan=False, allow_infinity=False),
    K=st.floats(min_value=20.0, max_value=500.0,
                  allow_nan=False, allow_infinity=False),
    T=st.floats(min_value=0.01, max_value=2.0,
                  allow_nan=False, allow_infinity=False),
    r=st.floats(min_value=0.0, max_value=0.10,
                  allow_nan=False, allow_infinity=False),
    sigma=st.floats(min_value=0.05, max_value=2.0,
                      allow_nan=False, allow_infinity=False),
    flag=st.sampled_from(["c", "p"]),
)
@settings(max_examples=1000, deadline=None)
def test_bs_price_agrees_with_pyvollib(S, K, T, r, sigma, flag):
    """VolScope BSM price agrees with py_vollib's BSM at 1e-8."""
    option_type = "call" if flag == "c" else "put"
    ours = bs_price(S, K, T, r, sigma, q=0.0, option_type=option_type)
    # py_vollib uses Black-Scholes (no dividend); pass q=0
    series = pvv.vectorized_black_scholes(
        flag=flag, S=S, K=K, t=T, r=r, sigma=sigma, return_as="numpy"
    )
    theirs = float(series[0])
    assert abs(ours - theirs) < 1e-8, (
        f"BSM disagrees with py_vollib: ours={ours:.10f} "
        f"theirs={theirs:.10f} diff={ours - theirs:+.2e} "
        f"S={S} K={K} T={T} r={r} sigma={sigma} flag={flag}"
    )


@pytest.mark.property
def test_pyvollib_smoke():
    """Sanity check: the py_vollib_vectorized API is callable + returns numeric."""
    s = pvv.vectorized_black_scholes(
        flag="c", S=100, K=100, t=0.5, r=0.05, sigma=0.20, return_as="numpy"
    )
    assert s.shape[0] == 1
    assert 4.0 < float(s[0]) < 8.0   # rough range for ATM 6-month call
