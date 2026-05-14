"""Tests for analytics.vol_cones — Bloomberg-style realized vol cones."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.vol_cones import (
    DEFAULT_PERCENTILES,
    DEFAULT_WINDOWS,
    VolCone,
    VolConePoint,
    compute_vol_cone,
    cone_to_dataframe,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _make_random_walk(n: int = 500, seed: int = 0, sigma: float = 0.01) -> pd.Series:
    """Geometric random walk with daily sigma. Annualised vol ≈ sigma·√252·100."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, sigma, n)
    prices = 100.0 * np.exp(np.cumsum(rets))
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(prices, index=dates)


# ──────────────────────────────────────────────────────────────────────────
# Output contract
# ──────────────────────────────────────────────────────────────────────────

class TestOutput:
    def test_returns_vol_cone(self):
        cone = compute_vol_cone(_make_random_walk())
        assert isinstance(cone, VolCone)

    def test_one_point_per_window(self):
        cone = compute_vol_cone(_make_random_walk(), windows=(20, 60, 252))
        assert len(cone.points) == 3

    def test_default_windows_used(self):
        cone = compute_vol_cone(_make_random_walk(n=500))
        assert tuple(p.window for p in cone.points) == DEFAULT_WINDOWS

    def test_default_percentiles_used(self):
        cone = compute_vol_cone(_make_random_walk(n=500))
        for p in cone.points:
            assert set(p.percentiles.keys()) == set(DEFAULT_PERCENTILES)

    def test_frozen(self):
        cone = compute_vol_cone(_make_random_walk())
        with pytest.raises(Exception):
            cone.summary = "x"  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────
# Empty / short input handling
# ──────────────────────────────────────────────────────────────────────────

class TestEmptyInput:
    def test_empty_series_handled(self):
        cone = compute_vol_cone(pd.Series(dtype=float))
        assert "No price history" in cone.summary

    def test_too_few_points(self):
        prices = pd.Series([100.0, 101.0], index=pd.date_range("2024-01-01", periods=2, freq="B"))
        cone = compute_vol_cone(prices)
        assert "≥ 5" in cone.summary

    def test_short_history_zero_n(self):
        prices = _make_random_walk(n=15)
        cone = compute_vol_cone(prices, windows=(10, 60, 252))
        # window=10 should have data; 60 and 252 should have n=0
        by_w = {p.window: p for p in cone.points}
        assert by_w[10].n_observations > 0
        assert by_w[60].n_observations == 0
        assert by_w[252].n_observations == 0


# ──────────────────────────────────────────────────────────────────────────
# Math correctness
# ──────────────────────────────────────────────────────────────────────────

class TestMathCorrectness:
    def test_known_vol_recovered(self):
        # daily sigma 0.01 → ann vol ≈ 0.01 × √252 × 100 = 15.87%
        prices = _make_random_walk(n=2000, sigma=0.01)
        cone = compute_vol_cone(prices, windows=(252,))
        p252 = cone.points[0]
        # Mean of distribution should be near 15.87
        median = p252.percentiles[50]
        assert 13.0 < median < 19.0    # generous to allow random-walk variation

    def test_high_vol_shifts_distribution_up(self):
        low  = compute_vol_cone(_make_random_walk(n=600, sigma=0.005), windows=(60,))
        high = compute_vol_cone(_make_random_walk(n=600, sigma=0.02),  windows=(60,))
        assert high.points[0].percentiles[50] > low.points[0].percentiles[50]

    def test_current_perc_in_range(self):
        cone = compute_vol_cone(_make_random_walk(n=1000), windows=(30,))
        p = cone.points[0]
        if p.current_perc is not None:
            assert 0.0 <= p.current_perc <= 100.0

    def test_current_vol_finite(self):
        cone = compute_vol_cone(_make_random_walk(n=1000), windows=(20,))
        p = cone.points[0]
        assert p.current_vol is not None
        assert np.isfinite(p.current_vol)

    def test_percentiles_monotonic(self):
        cone = compute_vol_cone(_make_random_walk(n=1000), windows=(60,))
        p = cone.points[0]
        # 5 < 25 < 50 < 75 < 95
        ordered = [p.percentiles[5], p.percentiles[25], p.percentiles[50],
                   p.percentiles[75], p.percentiles[95]]
        for i in range(len(ordered) - 1):
            assert ordered[i] <= ordered[i + 1]


# ──────────────────────────────────────────────────────────────────────────
# Summary text logic
# ──────────────────────────────────────────────────────────────────────────

class TestSummary:
    def test_normal_summary_when_mid(self):
        cone = compute_vol_cone(_make_random_walk(n=1500, seed=42))
        # On a standard random walk the latest will be around the median for
        # most windows → "within normal bounds" or borderline.
        # We just guarantee the summary is a non-empty string.
        assert isinstance(cone.summary, str) and cone.summary

    def test_unavailable_when_short(self):
        cone = compute_vol_cone(pd.Series([100.0, 101.0],
                                          index=pd.date_range("2024-01-01", periods=2, freq="B")))
        assert "≥" in cone.summary or "history" in cone.summary.lower()


# ──────────────────────────────────────────────────────────────────────────
# DataFrame conversion
# ──────────────────────────────────────────────────────────────────────────

class TestDataFrame:
    def test_columns_present(self):
        cone = compute_vol_cone(_make_random_walk(n=600), windows=(20, 60))
        df = cone_to_dataframe(cone)
        assert {"window", "percentile", "vol", "is_current"} <= set(df.columns)

    def test_includes_current_rows(self):
        cone = compute_vol_cone(_make_random_walk(n=600), windows=(20, 60))
        df = cone_to_dataframe(cone)
        current_rows = df[df["is_current"]]
        assert len(current_rows) == 2     # one per window
        # current rows should have percentile=None
        assert current_rows["percentile"].isna().all()

    def test_percentile_rows_count(self):
        cone = compute_vol_cone(_make_random_walk(n=600), windows=(20,))
        df = cone_to_dataframe(cone)
        non_current = df[~df["is_current"]]
        # 1 window × 5 percentiles = 5 rows
        assert len(non_current) == 5
