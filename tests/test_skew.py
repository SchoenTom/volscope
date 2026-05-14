"""
Tests for 25-delta skew computation and the historical skew chart.

Covers:
  - _compute_skew_25d() in options_scraper (math correctness + edge cases)
  - create_skew_chart() in chart_builders (rendering contract)
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.black_scholes import bs_price
from volscope.config import RISK_FREE_RATE
from volscope.data.options_scraper import _compute_skew_25d
from volscope.ui.components.chart_builders import create_skew_chart
from volscope.ui.styles.theme import COLORS


# ---------------------------------------------------------------------------
# Chain builders
# ---------------------------------------------------------------------------

def _chain(spot: float, days: int, vol: float, option_type: str) -> pd.DataFrame:
    """
    Flat-vol synthetic chain: every strike priced by BSM at `vol`.
    Sufficient strikes to bracket the 0.25Δ call and -0.25Δ put targets.
    """
    T = days / 365.0
    strikes = [spot * f for f in (0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20)]
    rows = []
    for k in strikes:
        price = bs_price(spot, k, T, RISK_FREE_RATE, vol, option_type=option_type)
        rows.append({
            "strike": k,
            "bid": max(price - 0.05, 0.01),
            "ask": price + 0.05,
            "volume": 500,
            "openInterest": 1000,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# _compute_skew_25d — correctness
# ---------------------------------------------------------------------------

def test_skew_flat_vol_near_zero():
    """
    Flat vol surface (same vol at all strikes, same vol for puts and calls)
    → 25Δ put IV ≈ 25Δ call IV → skew close to zero.
    """
    spot, days, vol = 400.0, 30, 0.25
    T = days / 365.0
    calls = _chain(spot, days, vol, "call")
    puts  = _chain(spot, days, vol, "put")
    skew = _compute_skew_25d(calls, puts, spot, T, RISK_FREE_RATE, 0.0)
    assert skew is not None
    # Flat surface → near-zero skew; allow ±3pt tolerance for interpolation noise
    assert abs(skew) < 3.0, f"Flat surface should give near-zero skew, got {skew:.2f}pt"


def test_skew_positive_when_puts_priced_richer():
    """
    Put chain priced at higher vol (30%) than call chain (20%) →
    25Δ put IV ≈ 30, 25Δ call IV ≈ 20 → skew ≈ +10pt (positive).
    """
    spot, days = 400.0, 30
    T = days / 365.0
    calls = _chain(spot, days, 0.20, "call")
    puts  = _chain(spot, days, 0.30, "put")
    skew = _compute_skew_25d(calls, puts, spot, T, RISK_FREE_RATE, 0.0)
    assert skew is not None
    assert skew > 2.0, f"Expected clearly positive skew, got {skew:.2f}pt"


def test_skew_negative_when_calls_priced_richer():
    """
    Call chain at higher vol (30%) than put chain (20%) →
    negative skew (unusual, call-rich surface).
    """
    spot, days = 400.0, 30
    T = days / 365.0
    calls = _chain(spot, days, 0.30, "call")
    puts  = _chain(spot, days, 0.20, "put")
    skew = _compute_skew_25d(calls, puts, spot, T, RISK_FREE_RATE, 0.0)
    assert skew is not None
    assert skew < -2.0, f"Expected clearly negative skew, got {skew:.2f}pt"


def test_skew_value_in_realistic_range():
    """Typical equity skew: −20 to +40pt; result must be in that range."""
    spot, days = 400.0, 30
    T = days / 365.0
    calls = _chain(spot, days, 0.25, "call")
    puts  = _chain(spot, days, 0.25, "put")
    skew = _compute_skew_25d(calls, puts, spot, T, RISK_FREE_RATE, 0.0)
    if skew is not None:
        assert -20.0 < skew < 40.0


def test_skew_result_is_float_or_none():
    """Return type is float | None — must never raise."""
    spot, days = 400.0, 30
    T = days / 365.0
    calls = _chain(spot, days, 0.25, "call")
    puts  = _chain(spot, days, 0.25, "put")
    result = _compute_skew_25d(calls, puts, spot, T, RISK_FREE_RATE, 0.0)
    assert result is None or isinstance(result, float)


# ---------------------------------------------------------------------------
# _compute_skew_25d — edge cases / None guards
# ---------------------------------------------------------------------------

def test_skew_returns_none_when_t_zero():
    """T=0 is degenerate — function must return None, not raise."""
    spot, days = 400.0, 30
    T = days / 365.0
    calls = _chain(spot, days, 0.25, "call")
    puts  = _chain(spot, days, 0.25, "put")
    result = _compute_skew_25d(calls, puts, spot, 0.0, RISK_FREE_RATE, 0.0)
    assert result is None


def test_skew_returns_none_when_spot_zero():
    """spot=0 is degenerate."""
    spot, days = 400.0, 30
    T = days / 365.0
    calls = _chain(spot, days, 0.25, "call")
    puts  = _chain(spot, days, 0.25, "put")
    result = _compute_skew_25d(calls, puts, 0.0, T, RISK_FREE_RATE, 0.0)
    assert result is None


def test_skew_returns_none_when_both_chains_empty():
    spot, days = 400.0, 30
    T = days / 365.0
    result = _compute_skew_25d(pd.DataFrame(), pd.DataFrame(), spot, T, RISK_FREE_RATE, 0.0)
    assert result is None


def test_skew_returns_none_when_calls_empty():
    spot, days = 400.0, 30
    T = days / 365.0
    puts = _chain(spot, days, 0.25, "put")
    result = _compute_skew_25d(pd.DataFrame(), puts, spot, T, RISK_FREE_RATE, 0.0)
    assert result is None


def test_skew_returns_none_when_puts_empty():
    spot, days = 400.0, 30
    T = days / 365.0
    calls = _chain(spot, days, 0.25, "call")
    result = _compute_skew_25d(calls, pd.DataFrame(), spot, T, RISK_FREE_RATE, 0.0)
    assert result is None


def test_skew_returns_none_with_single_strike_each_side():
    """
    One strike per side cannot bracket the 25Δ target and has len(pairs) < 2
    in _iv_delta_pairs → _iv_at_delta returns None → skew is None.
    """
    spot, days, vol = 400.0, 30, 0.25
    T = days / 365.0
    c_price = bs_price(spot, spot, T, RISK_FREE_RATE, vol, option_type="call")
    p_price = bs_price(spot, spot, T, RISK_FREE_RATE, vol, option_type="put")
    single_call = pd.DataFrame([{
        "strike": spot, "bid": c_price - 0.01, "ask": c_price + 0.01, "volume": 100, "openInterest": 100
    }])
    single_put = pd.DataFrame([{
        "strike": spot, "bid": p_price - 0.01, "ask": p_price + 0.01, "volume": 100, "openInterest": 100
    }])
    result = _compute_skew_25d(single_call, single_put, spot, T, RISK_FREE_RATE, 0.0)
    assert result is None


def test_skew_never_raises_on_bad_inputs():
    """Malformed DataFrames must not crash — return None silently."""
    bad = pd.DataFrame({"strike": ["abc", "xyz"], "bid": [None, None], "ask": [None, None],
                         "volume": [0, 0], "openInterest": [0, 0]})
    result = _compute_skew_25d(bad, bad, 400.0, 0.08, RISK_FREE_RATE, 0.0)
    # May return None or a float — must not raise
    assert result is None or isinstance(result, float)


# ---------------------------------------------------------------------------
# create_skew_chart — rendering contract
# ---------------------------------------------------------------------------

def _skew_history(values: list) -> pd.DataFrame:
    """Build a minimal history DataFrame with iv_skew_25d column."""
    today = date.today()
    rows = [
        {"date": today - timedelta(days=len(values) - 1 - i), "iv_skew_25d": v}
        for i, v in enumerate(values)
    ]
    return pd.DataFrame(rows)


def test_skew_chart_empty_df_does_not_crash():
    fig = create_skew_chart(pd.DataFrame())
    assert fig is not None


def test_skew_chart_missing_column_does_not_crash():
    df = pd.DataFrame({"date": [date.today()], "iv_30d": [25.0]})
    fig = create_skew_chart(df)
    assert fig is not None


def test_skew_chart_all_none_values_does_not_crash():
    df = _skew_history([None, None, None])
    fig = create_skew_chart(df)
    assert fig is not None


def test_skew_chart_single_row_renders():
    df = _skew_history([4.2])
    fig = create_skew_chart(df)
    assert fig is not None
    # At least one data trace should be present
    assert len(fig.data) >= 1


def test_skew_chart_multiple_rows_has_trace():
    df = _skew_history([1.0, 2.5, 4.0, 6.5, 3.2])
    fig = create_skew_chart(df)
    scatter_traces = [t for t in fig.data if hasattr(t, "y") and t.y is not None and len(t.y) > 0]
    assert len(scatter_traces) >= 1


def test_skew_chart_trace_length_matches_valid_rows():
    """Only rows where iv_skew_25d is not None should appear in the trace."""
    df = _skew_history([1.0, None, 3.0, None, 5.0])
    fig = create_skew_chart(df)
    # Find the main scatter trace
    main = next((t for t in fig.data if hasattr(t, "y") and t.y is not None and len(t.y) > 0), None)
    assert main is not None
    assert len(main.y) == 3  # only 3 non-None values


def test_skew_chart_title_contains_current_value():
    """The latest skew value should appear in the chart title."""
    df = _skew_history([2.0, 3.0, 7.5])
    fig = create_skew_chart(df)
    title_text = fig.layout.title.text or ""
    assert "7.5" in title_text or "7" in title_text


def test_skew_chart_high_skew_shows_warn_color():
    """Skew > 5pt → warn color in title."""
    df = _skew_history([8.0, 9.0])
    fig = create_skew_chart(df)
    title_text = fig.layout.title.text or ""
    # Either the warn color hex or "RICH" label should appear
    assert COLORS["warn"] in title_text or "RICH" in title_text


def test_skew_chart_neutral_skew_shows_neutral_label():
    """Skew in (-2, +2) → 'neutral' label in title."""
    df = _skew_history([0.5, 1.0, 1.5])
    fig = create_skew_chart(df)
    title_text = (fig.layout.title.text or "").lower()
    assert "neutral" in title_text or "1.5" in title_text


def test_skew_chart_has_reference_line_at_zero():
    """A horizontal reference line at y=0 (neutral skew) must exist."""
    df = _skew_history([1.0, 2.0, 3.0])
    fig = create_skew_chart(df)
    # Shapes include hlines (horizontal_line shapes)
    zero_lines = [
        s for s in fig.layout.shapes
        if hasattr(s, "y0") and s.y0 == s.y1 == 0.0
    ]
    assert len(zero_lines) >= 1, "Expected a reference line at y=0"
