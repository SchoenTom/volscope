"""Tests for analytics.iv_smile — Bloomberg HIVG-style smile analytics."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.iv_smile import (
    SmileComparison,
    SmileFit,
    SmilePoint,
    SmileSnapshot,
    build_smile,
    compare_smiles,
    smile_to_dataframe,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _make_smile_df(spot=100.0, atm_iv=22.0, slope=-5.0, n=11) -> pd.DataFrame:
    """Build a synthetic smile: IV(K) = atm_iv + slope × ln(K/spot) + noise."""
    rng = np.random.default_rng(0)
    strikes = np.linspace(spot * 0.7, spot * 1.3, n)
    log_m = np.log(strikes / spot)
    ivs = atm_iv + slope * log_m + rng.normal(0, 0.3, n)
    return pd.DataFrame({
        "strike": np.tile(strikes, 2),
        "iv":     np.tile(ivs, 2),
        "option_type": ["call"] * n + ["put"] * n,
    })


# ──────────────────────────────────────────────────────────────────────────
# Output contract
# ──────────────────────────────────────────────────────────────────────────

class TestOutputContract:
    def test_returns_snapshot(self):
        df = _make_smile_df()
        snap = build_smile(df, spot=100.0)
        assert isinstance(snap, SmileSnapshot)

    def test_points_length_matches_unique_strikes(self):
        df = _make_smile_df(n=11)
        snap = build_smile(df, spot=100.0)
        assert len(snap.points) == 11

    def test_fit_present_when_enough_points(self):
        df = _make_smile_df()
        snap = build_smile(df, spot=100.0)
        assert isinstance(snap.fit, SmileFit)

    def test_frozen(self):
        df = _make_smile_df()
        snap = build_smile(df, spot=100.0)
        with pytest.raises(Exception):
            snap.spot = 0  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────
# Empty / degenerate input
# ──────────────────────────────────────────────────────────────────────────

class TestEmptyInput:
    def test_empty_df(self):
        snap = build_smile(pd.DataFrame(), spot=100.0)
        assert snap.points == ()
        assert snap.fit is None

    def test_none_df(self):
        snap = build_smile(None, spot=100.0)
        assert snap.points == ()
        assert snap.fit is None

    def test_zero_spot(self):
        df = _make_smile_df()
        snap = build_smile(df, spot=0.0)
        assert snap.points == ()

    def test_missing_iv_column(self):
        df = pd.DataFrame({"strike": [100.0, 110.0]})
        snap = build_smile(df, spot=100.0)
        assert snap.fit is None

    def test_all_iv_below_threshold_dropped(self):
        df = pd.DataFrame({
            "strike": [90, 100, 110],
            "iv":     [0.5, 0.3, 0.8],   # all below _IV_MIN_PCT=1.0
            "option_type": ["call"] * 3,
        })
        snap = build_smile(df, spot=100.0)
        assert snap.points == ()

    def test_too_few_points_no_fit(self):
        df = pd.DataFrame({
            "strike": [100.0, 100.0],
            "iv":     [22.0, 23.0],
            "option_type": ["call", "put"],
        })
        snap = build_smile(df, spot=100.0)
        # Two strikes after groupby = 1 unique strike → < 3 → no fit
        assert snap.fit is None


# ──────────────────────────────────────────────────────────────────────────
# Math correctness
# ──────────────────────────────────────────────────────────────────────────

class TestMathCorrectness:
    def test_slope_recovered_negative(self):
        # Build a clean put-skew smile (slope=-5)
        df = _make_smile_df(slope=-5.0)
        snap = build_smile(df, spot=100.0)
        assert snap.fit.slope < -2.0   # generous tol for noise

    def test_slope_recovered_positive(self):
        df = _make_smile_df(slope=+5.0)
        snap = build_smile(df, spot=100.0)
        assert snap.fit.slope > 2.0

    def test_intercept_close_to_atm(self):
        df = _make_smile_df(atm_iv=22.0)
        snap = build_smile(df, spot=100.0)
        assert abs(snap.fit.intercept_atm_iv - 22.0) < 1.5

    def test_r_squared_high_for_clean_data(self):
        # Use very small noise to test R² approaches 1
        rng = np.random.default_rng(0)
        strikes = np.linspace(80.0, 120.0, 11)
        log_m = np.log(strikes / 100.0)
        ivs = 22.0 + (-5.0) * log_m + rng.normal(0, 0.05, 11)
        df = pd.DataFrame({"strike": strikes, "iv": ivs,
                          "option_type": ["call"] * 11})
        snap = build_smile(df, spot=100.0)
        assert snap.fit.r_squared > 0.9

    def test_log_moneyness_zero_for_atm_strike(self):
        df = pd.DataFrame({
            "strike": [100.0, 110.0, 90.0],
            "iv":     [22.0, 24.0, 25.0],
            "option_type": ["call", "call", "put"],
        })
        snap = build_smile(df, spot=100.0)
        atm_pt = next(p for p in snap.points if p.strike == 100.0)
        assert math.isclose(atm_pt.log_moneyness, 0.0, abs_tol=1e-9)


# ──────────────────────────────────────────────────────────────────────────
# Smile comparison
# ──────────────────────────────────────────────────────────────────────────

class TestComparison:
    def test_returns_comparison(self):
        a = build_smile(_make_smile_df(), spot=100.0)
        b = build_smile(_make_smile_df(), spot=100.0)
        cmp = compare_smiles(a, b)
        assert isinstance(cmp, SmileComparison)

    def test_unchanged_yields_stable_message(self):
        df = _make_smile_df()
        snap_a = build_smile(df, spot=100.0)
        snap_b = build_smile(df, spot=100.0)
        cmp = compare_smiles(snap_a, snap_b)
        assert "stable" in cmp.interpretation.lower()

    def test_skew_flattening_detected(self):
        # prior was steep (slope=-8), today is mild (slope=-2)
        steep = build_smile(_make_smile_df(slope=-8.0), spot=100.0)
        mild  = build_smile(_make_smile_df(slope=-2.0), spot=100.0)
        cmp = compare_smiles(today=mild, prior=steep)
        # slope_change should be positive (flattening)
        assert cmp.slope_change > 0
        assert "flatten" in cmp.interpretation.lower() or "steepen" in cmp.interpretation.lower()

    def test_atm_rise_detected(self):
        old = build_smile(_make_smile_df(atm_iv=20.0), spot=100.0)
        new = build_smile(_make_smile_df(atm_iv=28.0), spot=100.0)
        cmp = compare_smiles(today=new, prior=old)
        assert cmp.atm_iv_change > 0

    def test_missing_fit_returns_insufficient_data(self):
        good = build_smile(_make_smile_df(), spot=100.0)
        bad  = build_smile(pd.DataFrame(), spot=100.0)
        cmp = compare_smiles(good, bad)
        assert "Insufficient" in cmp.interpretation


# ──────────────────────────────────────────────────────────────────────────
# DataFrame conversion
# ──────────────────────────────────────────────────────────────────────────

class TestDataFrame:
    def test_columns(self):
        snap = build_smile(_make_smile_df(), spot=100.0)
        df = smile_to_dataframe(snap)
        assert {"strike", "iv", "log_moneyness"} <= set(df.columns)

    def test_empty_returns_empty(self):
        snap = build_smile(pd.DataFrame(), spot=100.0)
        df = smile_to_dataframe(snap)
        assert df.empty
