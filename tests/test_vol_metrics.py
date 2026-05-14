"""Tests for IV rank/percentile/regime/spread metrics."""
import numpy as np
import pytest

from volscope.analytics.vol_metrics import (
    iv_hv_spread,
    iv_percentile,
    iv_rank,
    vol_regime,
)


class TestIVRank:
    def test_midpoint(self):
        assert abs(iv_rank(50, list(range(0, 101))) - 50.0) < 1.0

    def test_min(self):
        assert iv_rank(0, list(range(0, 101))) == 0.0

    def test_max(self):
        assert iv_rank(100, list(range(0, 101))) == 100.0

    def test_flat_history(self):
        assert iv_rank(20, [10, 10, 10]) == 50.0

    def test_empty_history(self):
        assert iv_rank(20, []) == 50.0

    def test_nan_in_history(self):
        result = iv_rank(50, [0, 50, 100, np.nan])
        assert 0 <= result <= 100

    def test_range_always_0_100(self):
        hist = np.linspace(10, 50, 100)
        for v in [5, 10, 30, 50, 55]:
            r = iv_rank(v, hist)
            assert 0 <= r <= 100


class TestIVPercentile:
    def test_above_all(self):
        assert iv_percentile(200, [10, 20, 30]) == 100.0

    def test_below_all(self):
        assert iv_percentile(0, [10, 20, 30]) == 0.0

    def test_middle(self):
        val = iv_percentile(25, [10, 20, 30, 40])
        assert 45 <= val <= 55

    def test_empty_history(self):
        assert iv_percentile(10, []) == 50.0

    def test_all_same(self):
        # Midpoint-method ties: equal values count 0.5 each → 50%.
        # Pure < comparison would yield 0% which falsely triggers CHEAP
        # signal during dead markets.
        assert iv_percentile(10, [10, 10, 10]) == 50.0

    def test_partial_ties_above(self):
        # 1 below, 2 equal, 0 above → (1 + 2*0.5) / 3 = 0.667 → 66.7%
        assert iv_percentile(10, [5, 10, 10]) == pytest.approx(66.667, abs=0.01)

    def test_partial_ties_below(self):
        # 0 below, 1 equal, 2 above → (0 + 0.5) / 3 → 16.7%
        assert iv_percentile(10, [10, 15, 20]) == pytest.approx(16.667, abs=0.01)


class TestVolRegime:
    def test_normal(self):
        hist = np.random.default_rng(0).normal(20, 2, 200)
        result = vol_regime(20.0, hist)
        assert result["regime"] == "NORMAL"
        assert "z_score" in result

    def test_high(self):
        hist = np.random.default_rng(0).normal(20, 2, 200)
        result = vol_regime(30.0, hist)
        assert result["regime"] == "HIGH"

    def test_low(self):
        hist = np.random.default_rng(0).normal(20, 2, 200)
        result = vol_regime(10.0, hist)
        assert result["regime"] == "LOW"

    def test_empty_history(self):
        result = vol_regime(20.0, [])
        assert result["regime"] == "NORMAL"


class TestIVHVSpread:
    def test_rich(self):
        result = iv_hv_spread(30.0, 20.0)
        assert result["signal"] == "RICH"
        assert result["spread"] == 10.0
        assert abs(result["ratio"] - 1.5) < 1e-9

    def test_cheap(self):
        result = iv_hv_spread(15.0, 25.0)
        assert result["signal"] == "CHEAP"

    def test_neutral(self):
        result = iv_hv_spread(20.5, 20.0)
        assert result["signal"] == "NEUTRAL"

    def test_zero_hv(self):
        result = iv_hv_spread(20.0, 0.0)
        assert result["signal"] == "NEUTRAL"
        assert result["spread"] is None

    def test_with_history_z(self):
        hist = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = iv_hv_spread(25.0, 20.0, spread_history=hist)
        assert result["z_score"] is not None
