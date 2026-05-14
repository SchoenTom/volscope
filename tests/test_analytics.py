"""Tests for analytics engine (spread, opportunity, crowded)."""
import numpy as np
import pandas as pd
import pytest

from volscope.analytics.crowded_trades import compute_crowded_score
from volscope.analytics.opportunity import (
    find_cheapest_vol,
    find_daily_outliers,
    find_richest_premium,
)
from volscope.analytics.spread_analysis import (
    compute_iv_hv_timeseries,
    detect_spread_extremes,
)


@pytest.fixture
def latest_data():
    return pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"],
            "iv_30d": [10.0, 15.0, 20.0, 35.0, 55.0, 80.0],
            "hv_20d": [12.0, 14.0, 22.0, 30.0, 40.0, 60.0],
            "iv_percentile": [5.0, 15.0, 30.0, 60.0, 85.0, 98.0],
            "iv_rank": [6.0, 18.0, 32.0, 64.0, 87.0, 99.0],
            "put_call_ratio": [0.8, 1.0, 1.2, 1.1, 1.5, 2.5],
            "total_call_volume": [1000, 2000, 3000, 4000, 5000, 6000],
            "total_put_volume": [800, 2000, 3600, 4400, 7500, 15000],
            "total_open_interest": [10000, 20000, 30000, 40000, 50000, 60000],
        }
    )


class TestSpread:
    def test_compute_iv_hv_timeseries_empty(self):
        df = compute_iv_hv_timeseries(pd.Series(dtype=float), pd.Series(dtype=float))
        assert df.empty

    def test_compute_iv_hv_timeseries_basic(self):
        iv = pd.Series(np.linspace(10, 30, 120))
        hv = pd.Series(np.linspace(12, 25, 120))
        df = compute_iv_hv_timeseries(iv, hv)
        assert {"spread", "ratio", "z_score"}.issubset(df.columns)
        assert len(df) == 120

    def test_detect_extremes_empty(self):
        assert detect_spread_extremes(pd.Series(dtype=float)).empty


class TestOpportunity:
    def test_cheapest_returns_lowest_percentile(self, latest_data):
        out = find_cheapest_vol(latest_data, n=3)
        assert list(out["ticker"]) == ["AAA", "BBB", "CCC"]
        assert "context" in out.columns
        # AAA has iv_percentile=5 → remainder 95 → extreme-floor context.
        assert "historical floor" in out.iloc[0]["context"]

    def test_richest_extreme_context(self, latest_data):
        out = find_richest_premium(latest_data, n=1)
        # FFF has iv_percentile=98 → extreme-premium context.
        assert "extreme premium" in out.iloc[0]["context"]

    def test_cheapest_penalizes_positive_spread(self):
        """Dual-signal ranking: a ticker that's low percentile but with IV
        well above HV is less 'cheap' than one with coherent signals."""
        df = pd.DataFrame(
            {
                "ticker": ["COHERENT", "MIXED"],
                "iv_30d": [10.0, 12.0],
                "hv_20d": [12.0, 4.0],  # COHERENT: spread -2. MIXED: spread +8.
                "iv_percentile": [8.0, 5.0],
            }
        )
        out = find_cheapest_vol(df, n=2)
        # COHERENT wins despite higher percentile because signals agree.
        assert out.iloc[0]["ticker"] == "COHERENT"

    def test_richest_penalizes_negative_spread(self):
        df = pd.DataFrame(
            {
                "ticker": ["COHERENT", "MIXED"],
                "iv_30d": [60.0, 55.0],
                "hv_20d": [40.0, 70.0],  # COHERENT: +20. MIXED: -15.
                "iv_percentile": [90.0, 95.0],
            }
        )
        out = find_richest_premium(df, n=2)
        assert out.iloc[0]["ticker"] == "COHERENT"

    def test_richest_returns_highest_percentile(self, latest_data):
        out = find_richest_premium(latest_data, n=3)
        assert list(out["ticker"]) == ["FFF", "EEE", "DDD"]

    def test_cheapest_empty_input(self):
        out = find_cheapest_vol(pd.DataFrame(), n=5)
        assert out.empty

    def test_daily_outliers(self, latest_data):
        prev = latest_data.copy()
        prev["iv_30d"] = prev["iv_30d"] - pd.Series([1.0, 0.5, 0.3, 10.0, 0.2, 2.0])
        out = find_daily_outliers(latest_data, prev, n=2)
        assert out.iloc[0]["ticker"] == "DDD"

    def test_daily_outliers_empty(self):
        out = find_daily_outliers(pd.DataFrame(), pd.DataFrame())
        assert out.empty

    def test_daily_outliers_normalizes_by_base(self):
        """A 5pt move on a 10% IV base should beat a 5pt move on a 100% IV base
        once the function normalizes by previous IV (relative change)."""
        latest = pd.DataFrame({"ticker": ["LO", "HI"], "iv_30d": [15.0, 105.0]})
        prev = pd.DataFrame({"ticker": ["LO", "HI"], "iv_30d": [10.0, 100.0]})
        out = find_daily_outliers(latest, prev, n=2)
        assert out.iloc[0]["ticker"] == "LO"

    def test_daily_outliers_with_history_uses_zscore(self):
        """When per-ticker history is provided, normalization is by std of diffs."""
        latest = pd.DataFrame({"ticker": ["CALM", "JUMPY"], "iv_30d": [22.0, 50.0]})
        prev = pd.DataFrame({"ticker": ["CALM", "JUMPY"], "iv_30d": [20.0, 45.0]})
        # CALM is a sleepy ticker: tiny daily diffs. JUMPY is wild: 5pt moves are normal.
        history = {
            "CALM": pd.Series([20.0 + 0.1 * i for i in range(50)]),
            "JUMPY": pd.Series([40.0 + 5.0 * (i % 3 - 1) for i in range(50)]),
        }
        out = find_daily_outliers(latest, prev, n=2, history=history)
        # The 2pt move on CALM (tiny std) should rank above the 5pt move on JUMPY (huge std).
        assert out.iloc[0]["ticker"] == "CALM"


class TestCrowded:
    def test_score_bounds(self, latest_data):
        hist = pd.DataFrame(
            {
                "put_call_ratio": np.random.default_rng(0).normal(1.0, 0.2, 100),
                "total_open_interest": np.random.default_rng(0).normal(30000, 5000, 100),
                "total_call_volume": np.random.default_rng(0).normal(3000, 500, 100),
                "total_put_volume": np.random.default_rng(0).normal(3000, 500, 100),
                "iv_30d": np.random.default_rng(0).normal(20, 3, 100),
                "hv_20d": np.random.default_rng(0).normal(18, 3, 100),
            }
        )
        row = latest_data.iloc[-1]
        score = compute_crowded_score(row, hist)
        assert 0 <= score <= 100

    def test_empty_history(self, latest_data):
        score = compute_crowded_score(latest_data.iloc[0], pd.DataFrame())
        assert score == 50.0
