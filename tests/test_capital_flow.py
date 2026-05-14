"""Tests for volscope.analytics.capital_flow."""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.capital_flow import (
    FlowDivergence,
    _rolling_zscore,
    _z_to_score,
    compute_flow_components,
    compute_flow_score,
    detect_flow_divergence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_sector_hist(
    sectors: list[str],
    n_days: int = 30,
    base_iv: float = 20.0,
    base_hv: float = 15.0,
    base_pcr: float = 0.8,
    base_oi: int = 50_000,
    base_vol: int = 10_000,
) -> pd.DataFrame:
    rows = []
    start = date(2025, 1, 1)
    for i, sector in enumerate(sectors):
        for d in range(n_days):
            dt = start + timedelta(days=d)
            rows.append({
                "sector": sector,
                "date": dt,
                "median_iv": base_iv + i * 2 + d * 0.05,
                "median_hv": base_hv + i + d * 0.02,
                "mean_pcr": base_pcr + i * 0.05,
                "total_oi": base_oi + i * 5_000 + d * 100,
                "total_vol": base_vol + i * 1_000 + d * 50,
                "n_tickers": 5 + i,
            })
    return pd.DataFrame(rows)


def _make_flow_df(
    sectors: list[str],
    n_days: int = 20,
    base_score: float = 50.0,
) -> pd.DataFrame:
    rows = []
    start = date(2025, 1, 1)
    for sector in sectors:
        for d in range(n_days):
            rows.append({
                "sector": sector,
                "date": start + timedelta(days=d),
                "flow_score": base_score,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# _rolling_zscore
# ---------------------------------------------------------------------------

class TestRollingZscore:
    def test_constant_series_is_nan(self):
        s = pd.Series([5.0] * 10)
        z = _rolling_zscore(s, window=5)
        # std=0 → all NaN
        assert z.dropna().empty

    def test_rising_series_has_positive_z(self):
        s = pd.Series(range(30), dtype=float)
        z = _rolling_zscore(s, window=10)
        valid = z.dropna()
        assert len(valid) > 0
        assert float(valid.iloc[-1]) > 0

    def test_returns_series_same_length(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        z = _rolling_zscore(s, window=3)
        assert len(z) == 5

    def test_min_periods_3(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        z = _rolling_zscore(s, window=3)
        # first 2 values (need 3 for min_periods) should be NaN
        assert pd.isna(z.iloc[0])
        assert pd.isna(z.iloc[1])

    def test_negative_deviation_gives_negative_z(self):
        values = [10.0] * 15 + [5.0]
        s = pd.Series(values)
        z = _rolling_zscore(s, window=10)
        assert float(z.iloc[-1]) < 0


# ---------------------------------------------------------------------------
# _z_to_score
# ---------------------------------------------------------------------------

class TestZToScore:
    def test_zero_z_is_fifty(self):
        assert _z_to_score(0.0) == pytest.approx(50.0)

    def test_positive_three_is_100(self):
        assert _z_to_score(3.0) == pytest.approx(100.0)

    def test_negative_three_is_zero(self):
        assert _z_to_score(-3.0) == pytest.approx(0.0)

    def test_nan_returns_50(self):
        assert _z_to_score(float("nan")) == pytest.approx(50.0)

    def test_clipped_above_three(self):
        assert _z_to_score(10.0) == pytest.approx(100.0)

    def test_clipped_below_neg_three(self):
        assert _z_to_score(-10.0) == pytest.approx(0.0)

    def test_positive_one(self):
        score = _z_to_score(1.0)
        assert 60.0 < score < 70.0

    def test_negative_one(self):
        score = _z_to_score(-1.0)
        assert 30.0 < score < 40.0


# ---------------------------------------------------------------------------
# compute_flow_components
# ---------------------------------------------------------------------------

class TestComputeFlowComponents:
    def test_returns_dataframe(self):
        sh = _make_sector_hist(["Tech", "Energy"], n_days=25)
        result = compute_flow_components(sh)
        assert isinstance(result, pd.DataFrame)

    def test_contains_required_columns(self):
        sh = _make_sector_hist(["Tech"], n_days=25)
        result = compute_flow_components(sh)
        for col in ["sector", "date", "oi_change_z", "vol_oi_ratio_z", "pcr_shift_z", "iv_hv_div_z"]:
            assert col in result.columns, f"Missing column: {col}"

    def test_empty_input_returns_empty(self):
        result = compute_flow_components(pd.DataFrame())
        assert result.empty

    def test_none_input_returns_empty(self):
        result = compute_flow_components(None)
        assert result.empty

    def test_missing_sector_col_returns_empty(self):
        df = pd.DataFrame({"date": [date(2025, 1, 1)], "median_iv": [20.0]})
        result = compute_flow_components(df)
        assert result.empty

    def test_sector_count_matches(self):
        sectors = ["Tech", "Energy", "Finance"]
        sh = _make_sector_hist(sectors, n_days=25)
        result = compute_flow_components(sh)
        assert set(result["sector"].unique()) == set(sectors)

    def test_oi_change_z_is_nan_without_total_oi(self):
        sh = _make_sector_hist(["Tech"], n_days=25)
        sh_no_oi = sh.drop(columns=["total_oi"])
        result = compute_flow_components(sh_no_oi)
        assert result["oi_change_z"].isna().all()

    def test_vol_oi_ratio_z_is_nan_without_total_vol(self):
        sh = _make_sector_hist(["Tech"], n_days=25)
        sh_no_vol = sh.drop(columns=["total_vol"])
        result = compute_flow_components(sh_no_vol)
        assert result["vol_oi_ratio_z"].isna().all()

    def test_pcr_shift_z_is_nan_without_mean_pcr(self):
        sh = _make_sector_hist(["Tech"], n_days=25)
        sh_no_pcr = sh.drop(columns=["mean_pcr"])
        result = compute_flow_components(sh_no_pcr)
        assert result["pcr_shift_z"].isna().all()

    def test_iv_hv_div_z_is_nan_without_median_hv(self):
        sh = _make_sector_hist(["Tech"], n_days=25)
        sh_no_hv = sh.drop(columns=["median_hv"])
        result = compute_flow_components(sh_no_hv)
        assert result["iv_hv_div_z"].isna().all()

    def test_sorted_by_sector_date(self):
        sh = _make_sector_hist(["Energy", "Tech"], n_days=10)
        result = compute_flow_components(sh)
        # Check sorted
        for sector, grp in result.groupby("sector"):
            dates = list(grp["date"])
            assert dates == sorted(dates)

    def test_cluster_z_with_ticker_hist_map(self):
        """Volume clustering uses ticker_hist_map when provided."""
        sh = _make_sector_hist(["Tech"], n_days=25)
        ticker_df = sh.copy()
        ticker_df["ticker"] = "AAPL"
        ticker_df = ticker_df.rename(columns={"total_vol": "total_call_volume"})
        ticker_df["total_put_volume"] = 5000
        ticker_hist_map = {"AAPL": ticker_df}
        result = compute_flow_components(sh, ticker_hist_map=ticker_hist_map)
        assert "cluster_z" in result.columns

    def test_cluster_z_all_nan_without_ticker_map(self):
        sh = _make_sector_hist(["Tech"], n_days=25)
        result = compute_flow_components(sh, ticker_hist_map=None)
        # cluster_z should be all NaN since no ticker data
        assert result["cluster_z"].isna().all()

    def test_single_sector_single_day_still_returns(self):
        sh = pd.DataFrame([{
            "sector": "Tech",
            "date": date(2025, 1, 1),
            "median_iv": 20.0,
            "median_hv": 15.0,
            "mean_pcr": 0.8,
            "total_oi": 50_000,
            "total_vol": 10_000,
        }])
        result = compute_flow_components(sh)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# compute_flow_score
# ---------------------------------------------------------------------------

class TestComputeFlowScore:
    def test_returns_dataframe_with_flow_score(self):
        sh = _make_sector_hist(["Tech"], n_days=25)
        comps = compute_flow_components(sh)
        scores = compute_flow_score(comps)
        assert "flow_score" in scores.columns
        assert len(scores) == len(comps)

    def test_scores_in_valid_range(self):
        sh = _make_sector_hist(["Tech", "Energy"], n_days=25)
        comps = compute_flow_components(sh)
        scores = compute_flow_score(comps)
        valid = scores["flow_score"].dropna()
        assert (valid >= 0.0).all()
        assert (valid <= 100.0).all()

    def test_empty_components_returns_empty(self):
        result = compute_flow_score(pd.DataFrame())
        assert result.empty

    def test_none_input_returns_empty(self):
        result = compute_flow_score(None)
        assert result.empty

    def test_no_z_cols_returns_empty(self):
        df = pd.DataFrame({"sector": ["Tech"], "date": [date(2025, 1, 1)]})
        result = compute_flow_score(df)
        assert result.empty

    def test_all_nan_z_scores_return_50(self):
        df = pd.DataFrame({
            "sector": ["Tech"],
            "date": [date(2025, 1, 1)],
            "oi_change_z": [float("nan")],
            "vol_oi_ratio_z": [float("nan")],
            "pcr_shift_z": [float("nan")],
            "iv_hv_div_z": [float("nan")],
            "cluster_z": [float("nan")],
        })
        result = compute_flow_score(df)
        assert result["flow_score"].iloc[0] == pytest.approx(50.0)

    def test_high_z_scores_give_score_above_50(self):
        df = pd.DataFrame({
            "sector": ["Tech"],
            "date": [date(2025, 1, 1)],
            "oi_change_z": [3.0],
            "vol_oi_ratio_z": [3.0],
            "pcr_shift_z": [3.0],
            "iv_hv_div_z": [3.0],
            "cluster_z": [3.0],
        })
        result = compute_flow_score(df)
        assert result["flow_score"].iloc[0] == pytest.approx(100.0)

    def test_negative_z_scores_give_score_below_50(self):
        df = pd.DataFrame({
            "sector": ["Tech"],
            "date": [date(2025, 1, 1)],
            "oi_change_z": [-3.0],
            "vol_oi_ratio_z": [-3.0],
            "pcr_shift_z": [-3.0],
            "iv_hv_div_z": [-3.0],
            "cluster_z": [-3.0],
        })
        result = compute_flow_score(df)
        assert result["flow_score"].iloc[0] == pytest.approx(0.0)

    def test_partial_z_cols_still_computes(self):
        df = pd.DataFrame({
            "sector": ["Tech"],
            "date": [date(2025, 1, 1)],
            "oi_change_z": [2.0],
        })
        result = compute_flow_score(df)
        assert len(result) == 1
        assert result["flow_score"].iloc[0] > 50.0

    def test_output_sorted_by_sector_date(self):
        sh = _make_sector_hist(["Energy", "Tech"], n_days=10)
        comps = compute_flow_components(sh)
        scores = compute_flow_score(comps)
        for sector, grp in scores.groupby("sector"):
            dates = list(grp["date"])
            assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# detect_flow_divergence
# ---------------------------------------------------------------------------

class TestDetectFlowDivergence:
    def _make_divergence_flow(
        self, sector: str, n_days: int = 20, rise_at_end: float = 0.0
    ) -> pd.DataFrame:
        rows = []
        start = date(2025, 1, 1)
        for d in range(n_days):
            score = 50.0
            if d >= n_days - 5:
                score += rise_at_end
            rows.append({"sector": sector, "date": start + timedelta(days=d), "flow_score": score})
        return pd.DataFrame(rows)

    def test_returns_list(self):
        flow_df = _make_flow_df(["Tech"], n_days=20)
        result = detect_flow_divergence(flow_df)
        assert isinstance(result, list)

    def test_empty_flow_df_returns_empty(self):
        result = detect_flow_divergence(pd.DataFrame())
        assert result == []

    def test_none_returns_empty(self):
        result = detect_flow_divergence(None)
        assert result == []

    def test_accumulation_detected_when_flow_rises_price_flat(self):
        flow_df = self._make_divergence_flow("Tech", n_days=20, rise_at_end=10.0)
        result = detect_flow_divergence(flow_df, sector_hist=None, min_flow_rise=8.0)
        signals = [d.signal for d in result]
        assert "ACCUMULATION" in signals

    def test_distribution_detected_when_flow_falls_price_flat(self):
        flow_df = self._make_divergence_flow("Tech", n_days=20, rise_at_end=-10.0)
        result = detect_flow_divergence(flow_df, sector_hist=None, min_flow_rise=8.0)
        signals = [d.signal for d in result]
        assert "DISTRIBUTION" in signals

    def test_no_signal_when_change_too_small(self):
        flow_df = self._make_divergence_flow("Tech", n_days=20, rise_at_end=2.0)
        result = detect_flow_divergence(flow_df, sector_hist=None, min_flow_rise=8.0)
        assert result == []

    def test_insufficient_history_skipped(self):
        flow_df = pd.DataFrame([
            {"sector": "Tech", "date": date(2025, 1, 1), "flow_score": 50.0},
            {"sector": "Tech", "date": date(2025, 1, 2), "flow_score": 80.0},
        ])
        result = detect_flow_divergence(flow_df, flow_window=5)
        assert result == []

    def test_divergence_contains_expected_fields(self):
        flow_df = self._make_divergence_flow("Energy", n_days=20, rise_at_end=15.0)
        result = detect_flow_divergence(flow_df, sector_hist=None, min_flow_rise=10.0)
        if result:
            div = result[0]
            assert isinstance(div.sector, str)
            assert isinstance(div.flow_score, float)
            assert isinstance(div.flow_change_5d, float)
            assert div.signal in ("ACCUMULATION", "DISTRIBUTION", "NEUTRAL")

    def test_sorted_by_abs_flow_change_desc(self):
        rows = []
        start = date(2025, 1, 1)
        for sector, rise in [("Tech", 15.0), ("Energy", 25.0), ("Finance", 20.0)]:
            for d in range(20):
                score = 50.0 if d < 15 else 50.0 + rise
                rows.append({"sector": sector, "date": start + timedelta(days=d), "flow_score": score})
        flow_df = pd.DataFrame(rows)
        result = detect_flow_divergence(flow_df, sector_hist=None, min_flow_rise=10.0)
        if len(result) >= 2:
            changes = [abs(d.flow_change_5d) for d in result]
            assert changes == sorted(changes, reverse=True)

    def test_price_change_suppresses_signal(self):
        """When IV proxy changes a lot, divergence should not fire (price is moving too)."""
        rows = []
        start = date(2025, 1, 1)
        for d in range(20):
            score = 50.0 if d < 15 else 70.0
            rows.append({"sector": "Tech", "date": start + timedelta(days=d), "flow_score": score})
        flow_df = pd.DataFrame(rows)

        # Sector hist with large median_iv change (price is clearly moving)
        sh_rows = []
        for d in range(20):
            iv = 20.0 if d < 15 else 25.0  # +25% change — above max_price_change default
            sh_rows.append({"sector": "Tech", "date": start + timedelta(days=d), "median_iv": iv})
        sector_hist = pd.DataFrame(sh_rows)

        # With max_price_change=1% and IV moved 25%, no divergence should fire
        result = detect_flow_divergence(flow_df, sector_hist=sector_hist, min_flow_rise=8.0, max_price_change=1.0)
        assert result == []

    def test_multi_sector_multiple_signals(self):
        rows = []
        start = date(2025, 1, 1)
        for sector, rise in [("Tech", 15.0), ("Energy", -15.0)]:
            for d in range(20):
                score = 50.0 if d < 15 else 50.0 + rise
                rows.append({"sector": sector, "date": start + timedelta(days=d), "flow_score": score})
        flow_df = pd.DataFrame(rows)
        result = detect_flow_divergence(flow_df, min_flow_rise=10.0)
        assert len(result) >= 2
        signals = {d.sector: d.signal for d in result}
        assert signals.get("Tech") == "ACCUMULATION"
        assert signals.get("Energy") == "DISTRIBUTION"


# ---------------------------------------------------------------------------
# FlowDivergence dataclass
# ---------------------------------------------------------------------------

class TestFlowDivergence:
    def test_frozen(self):
        div = FlowDivergence(
            sector="Tech",
            date=date(2025, 1, 1),
            flow_score=65.0,
            flow_change_5d=12.3,
            price_change_5d=None,
            signal="ACCUMULATION",
        )
        with pytest.raises((AttributeError, TypeError)):
            div.sector = "Energy"  # type: ignore[misc]

    def test_none_price_change_allowed(self):
        div = FlowDivergence(
            sector="Energy",
            date=date(2025, 6, 1),
            flow_score=70.0,
            flow_change_5d=8.5,
            price_change_5d=None,
            signal="ACCUMULATION",
        )
        assert div.price_change_5d is None
