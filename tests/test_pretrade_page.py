"""Tests for ui.views.pretrade_page — Pre-Trade card internals.

The render function itself requires Streamlit context; we test its
pure-Python helpers (strike-from-delta, IV picker, safe_float).
"""
from __future__ import annotations

import math

import pytest

from volscope.ui.views.pretrade_page import (
    _pick_iv_for_dte,
    _safe_float,
    _strike_from_delta,
)


# ──────────────────────────────────────────────────────────────────────────
# _safe_float
# ──────────────────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_valid_float(self):
        assert _safe_float(3.14) == 3.14

    def test_int(self):
        assert _safe_float(5) == 5.0

    def test_string_numeric(self):
        assert _safe_float("3.14") == 3.14

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_inf(self):
        assert _safe_float(float("inf")) is None

    def test_garbage_string(self):
        assert _safe_float("xyz") is None


# ──────────────────────────────────────────────────────────────────────────
# _pick_iv_for_dte
# ──────────────────────────────────────────────────────────────────────────

class TestPickIv:
    def test_picks_30d_for_30dte(self):
        assert _pick_iv_for_dte(30, 22.0, 25.0, 28.0) == 22.0

    def test_picks_60d_for_60dte(self):
        assert _pick_iv_for_dte(60, 22.0, 25.0, 28.0) == 25.0

    def test_picks_90d_for_90dte(self):
        assert _pick_iv_for_dte(90, 22.0, 25.0, 28.0) == 28.0

    def test_picks_closest(self):
        # 45 dte equidistant from 30/60 → ties broken by min() (first match)
        result = _pick_iv_for_dte(45, 22.0, 25.0, 28.0)
        assert result in (22.0, 25.0)

    def test_falls_back_when_all_none(self):
        assert _pick_iv_for_dte(30, None, None, None) == 30.0

    def test_skips_zero(self):
        # 0 IV is invalid (treated as missing)
        assert _pick_iv_for_dte(30, 0.0, 25.0, None) == 25.0


# ──────────────────────────────────────────────────────────────────────────
# _strike_from_delta — binary-search inverter
# ──────────────────────────────────────────────────────────────────────────

class TestStrikeFromDelta:
    def test_atm_call_near_spot(self):
        spot = 100.0
        T = 30 / 365.0
        iv = 0.25
        # Δ=0.50 call ≈ slightly OTM at low rates
        strike = _strike_from_delta(spot, T, iv, 0.50, "call")
        assert 90.0 <= strike <= 105.0

    def test_atm_put_near_spot(self):
        spot = 100.0
        T = 30 / 365.0
        iv = 0.25
        strike = _strike_from_delta(spot, T, iv, -0.50, "put")
        assert 95.0 <= strike <= 110.0

    def test_otm_put_below_spot(self):
        # Δ=-0.25 put → OTM put → strike < spot
        spot = 100.0
        T = 30 / 365.0
        iv = 0.25
        strike = _strike_from_delta(spot, T, iv, -0.25, "put")
        assert strike < spot

    def test_otm_call_above_spot(self):
        spot = 100.0
        T = 30 / 365.0
        iv = 0.25
        strike = _strike_from_delta(spot, T, iv, 0.25, "call")
        assert strike > spot

    def test_iterations_finite(self):
        # Should always terminate within bracketing
        spot = 100.0
        T = 30 / 365.0
        iv = 0.25
        strike = _strike_from_delta(spot, T, iv, -0.40, "put")
        assert math.isfinite(strike)
        assert 0 < strike < 1000.0


# ──────────────────────────────────────────────────────────────────────────
# Pillar C — Strategy Comparison
# ──────────────────────────────────────────────────────────────────────────

class TestPriceStrategy:
    def test_returns_dict_with_required_keys(self):
        from volscope.analytics.strategy_recommender import recommend_strategies
        from volscope.ui.views.pretrade_page import _price_strategy
        recs = recommend_strategies(iv_percentile=10.0)
        rec = next(r for r in recs if r.legs)
        result = _price_strategy(rec, spot=100.0, dte=60,
                                 iv_30d=22.0, iv_60d=24.0, iv_90d=26.0)
        for k in ["strike", "option_type", "delta", "vega", "theta",
                  "entry_price", "iv_used", "iv_scenarios", "pnl_curve"]:
            assert k in result

    def test_pnl_curve_length_matches_scenarios(self):
        from volscope.analytics.strategy_recommender import recommend_strategies
        from volscope.ui.views.pretrade_page import _price_strategy
        recs = recommend_strategies(iv_percentile=10.0)
        rec = next(r for r in recs if r.legs)
        result = _price_strategy(rec, spot=100.0, dte=60,
                                 iv_30d=22.0, iv_60d=None, iv_90d=None)
        assert len(result["iv_scenarios"]) == len(result["pnl_curve"])

    def test_long_put_has_negative_delta(self):
        from volscope.analytics.strategy_recommender import recommend_strategies
        from volscope.ui.views.pretrade_page import _price_strategy
        recs = recommend_strategies(iv_percentile=10.0)
        # Pick "Long Put Spread" specifically (-0.40 target delta)
        rec = next((r for r in recs if r.name == "Long Put Spread"), None)
        if rec is None:
            return  # not generated for this regime; skip
        result = _price_strategy(rec, spot=100.0, dte=60,
                                 iv_30d=22.0, iv_60d=24.0, iv_90d=26.0)
        assert result["delta"] < 0
        assert result["option_type"] == "put"

    def test_short_call_has_positive_delta(self):
        from volscope.analytics.strategy_recommender import recommend_strategies
        from volscope.ui.views.pretrade_page import _price_strategy
        recs = recommend_strategies(iv_percentile=85.0)
        rec = next((r for r in recs if r.name == "Short Iron Condor"), None)
        if rec is None:
            return
        result = _price_strategy(rec, spot=100.0, dte=45,
                                 iv_30d=30.0, iv_60d=29.0, iv_90d=28.0)
        # IC's lead is +0.16 delta (call side)
        assert result["option_type"] == "call"
        assert result["delta"] > 0

    def test_iv_used_picks_closest(self):
        from volscope.analytics.strategy_recommender import recommend_strategies
        from volscope.ui.views.pretrade_page import _price_strategy
        recs = recommend_strategies(iv_percentile=10.0)
        rec = next(r for r in recs if r.legs)
        # 60d DTE — should pick iv_60d if available
        result = _price_strategy(rec, spot=100, dte=60,
                                 iv_30d=20, iv_60d=25, iv_90d=30)
        assert result["iv_used"] == 25
