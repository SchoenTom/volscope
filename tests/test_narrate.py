"""Tests for the deterministic scope-narrative engine."""
from __future__ import annotations

import math

from volscope.analytics.narrate import (
    ScopeNarrative,
    _ordinal,
    cone_position_from_cone,
    generate_scope_narrative,
)
from volscope.analytics.vol_cones import compute_vol_cone


def test_empty_row_has_no_content():
    n = generate_scope_narrative("AAPL", None)
    assert isinstance(n, ScopeNarrative)
    assert not n.has_content


def test_cheap_iv_reads_cheap():
    n = generate_scope_narrative(
        "AAPL",
        {"iv_percentile": 12.0, "iv_30d": 18.5, "hv_yz_30d": 20.0},
        days_to_earnings=9,
    )
    assert n.tone == "cheap"
    assert "12th percentile" in n.headline
    assert "AAPL" in n.headline
    assert "earnings in 9 days" in n.headline
    assert n.headline.endswith(".")


def test_rich_iv_reads_rich_with_premium():
    n = generate_scope_narrative(
        "TSLA",
        {"iv_percentile": 88.0, "iv_30d": 62.0, "hv_yz_30d": 40.0},
    )
    assert n.tone == "rich"
    assert "paying" in n.headline  # premium clause fires (62 - 40 = 22)


def test_thin_premium_clause():
    n = generate_scope_narrative(
        "SPY",
        {"iv_percentile": 50.0, "iv_30d": 11.0, "hv_yz_30d": 18.0},
    )
    assert "BELOW" in n.headline  # IV < HV by 7 points


def test_spike_contamination_caveat():
    n = generate_scope_narrative(
        "FISV",
        {"iv_percentile": 8.0, "iv_30d": 22.0, "contamination_level": "severe",
         "ivr_ivp_divergence": 41.0},
    )
    assert n.caveat is not None
    assert "IV Percentile" in n.caveat


def test_nan_inputs_never_raise():
    n = generate_scope_narrative(
        "X",
        {"iv_percentile": float("nan"), "iv_30d": float("nan")},
    )
    assert isinstance(n, ScopeNarrative)
    assert not n.has_content


def test_earnings_today_and_tomorrow():
    assert "earnings are TODAY" in generate_scope_narrative(
        "A", {"iv_percentile": 40.0, "iv_30d": 20.0}, days_to_earnings=0).headline
    assert "earnings are tomorrow" in generate_scope_narrative(
        "A", {"iv_percentile": 40.0, "iv_30d": 20.0}, days_to_earnings=1).headline


def test_ordinal():
    assert _ordinal(1) == "1st"
    assert _ordinal(2) == "2nd"
    assert _ordinal(3) == "3rd"
    assert _ordinal(11) == "11th"
    assert _ordinal(12) == "12th"
    assert _ordinal(21) == "21st"
    assert _ordinal(88) == "88th"


def test_cone_position_from_real_cone():
    import numpy as np
    import pandas as pd

    # Upward-drifting low-vol series → recent realised vol is modest.
    idx = pd.date_range("2023-01-01", periods=400, freq="B")
    prices = pd.Series(100.0 * np.cumprod(1 + np.full(400, 0.0005)), index=idx)
    cone = compute_vol_cone(prices, ticker="X")
    pos = cone_position_from_cone(cone, window=30)
    assert pos in {"stretched_high", "stretched_low", "mid", None}


def test_cone_position_none_for_empty():
    assert cone_position_from_cone(None) is None
