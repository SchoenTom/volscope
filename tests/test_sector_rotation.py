"""Tests for volscope.analytics.sector_rotation."""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.sector_rotation import (
    SectorRegime,
    classify_sector_regime,
    compute_rotation_matrix,
    compute_sector_aggregates,
    compute_sector_momentum,
    get_current_rotation_snapshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_daily_vol(
    sectors: list[str],
    n_days: int = 30,
    base_iv_perc: float = 50.0,
    delta_per_sector: float = 10.0,
) -> pd.DataFrame:
    """Build a synthetic daily_vol DataFrame for testing."""
    rows = []
    start = date(2025, 1, 1)
    for i, sector in enumerate(sectors):
        for d in range(n_days):
            dt = start + timedelta(days=d)
            rows.append({
                "ticker": f"{sector[:3].upper()}{i}",
                "date": dt,
                "sector": sector,
                "iv_30d": 20.0 + i * 2,
                "iv_percentile": base_iv_perc + i * delta_per_sector + d * 0.1,
                "hv_20d": 15.0 + i,
                "put_call_ratio": 0.8 + i * 0.1,
                "total_call_volume": 1000 + i * 100,
                "total_put_volume": 800 + i * 80,
                "total_open_interest": 50000 + i * 5000,
            })
    return pd.DataFrame(rows)


def _make_agg(
    sectors: list[str],
    n_days: int = 50,
    base_perc: float = 40.0,
) -> pd.DataFrame:
    """Build a synthetic sector_daily aggregate DataFrame."""
    rows = []
    start = date(2024, 6, 1)
    for i, sector in enumerate(sectors):
        for d in range(n_days):
            dt = start + timedelta(days=d)
            rows.append({
                "sector": sector,
                "date": dt,
                "median_iv": 20.0 + i * 2,
                "median_perc": base_perc + i * 15.0 + d * 0.3,
                "median_hv": 15.0 + i,
                "mean_pcr": 0.8 + i * 0.1,
                "total_oi": 50000 + i * 5000,
                "total_vol": 10000 + i * 1000,
                "n_tickers": 5 + i,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# compute_sector_aggregates
# ---------------------------------------------------------------------------

class TestComputeSectorAggregates:
    def test_empty_input_returns_empty(self):
        out = compute_sector_aggregates(pd.DataFrame())
        assert out.empty

    def test_none_input_returns_empty(self):
        out = compute_sector_aggregates(None)
        assert out.empty

    def test_output_columns(self):
        df = _make_daily_vol(["Tech", "Energy"], n_days=5)
        out = compute_sector_aggregates(df)
        for col in ["sector", "date", "median_iv", "median_perc", "median_hv",
                    "mean_pcr", "total_oi", "total_vol", "n_tickers"]:
            assert col in out.columns, f"Missing column: {col}"

    def test_groups_by_sector_and_date(self):
        df = _make_daily_vol(["Tech", "Energy"], n_days=10)
        out = compute_sector_aggregates(df)
        # Should have 2 sectors × 10 dates = 20 rows
        assert len(out) == 20

    def test_median_perc_in_range(self):
        df = _make_daily_vol(["Tech", "Energy"], n_days=5)
        out = compute_sector_aggregates(df)
        for v in out["median_perc"].dropna():
            assert 0 <= v <= 100

    def test_n_tickers_count(self):
        """Each sector has 1 ticker in our fixture, so n_tickers should be 1."""
        df = _make_daily_vol(["Tech"], n_days=3)
        out = compute_sector_aggregates(df)
        assert (out["n_tickers"] == 1).all()

    def test_total_vol_is_call_plus_put(self):
        df = _make_daily_vol(["Tech"], n_days=3)
        out = compute_sector_aggregates(df)
        # call_volume = 1000, put_volume = 800, so total_vol = 1800 per date
        assert (out["total_vol"] == 1800).all()

    def test_missing_sector_column_treated_as_unknown(self):
        df = _make_daily_vol(["Tech"], n_days=3)
        df = df.drop(columns=["sector"])
        out = compute_sector_aggregates(df)
        assert (out["sector"] == "Unknown").all()

    def test_null_sectors_filled_as_unknown(self):
        df = _make_daily_vol(["Tech", "Energy"], n_days=3)
        df.loc[df["sector"] == "Energy", "sector"] = None
        out = compute_sector_aggregates(df)
        assert "Unknown" in out["sector"].values

    def test_sorted_by_sector_date(self):
        df = _make_daily_vol(["Utilities", "Tech", "Energy"], n_days=4)
        out = compute_sector_aggregates(df)
        # Check sorted
        dates_per_sector = out.groupby("sector")["date"].apply(list)
        for sec, dates in dates_per_sector.items():
            assert dates == sorted(dates), f"Not sorted for sector {sec}"


# ---------------------------------------------------------------------------
# compute_sector_momentum
# ---------------------------------------------------------------------------

class TestComputeSectorMomentum:
    def test_empty_input_returns_empty(self):
        out = compute_sector_momentum(pd.DataFrame())
        assert out.empty

    def test_none_returns_same(self):
        out = compute_sector_momentum(None)
        assert out is None

    def test_adds_momentum_columns(self):
        agg = _make_agg(["Tech", "Energy"], n_days=25)
        out = compute_sector_momentum(agg, windows=[5, 10])
        assert "perc_delta_5d" in out.columns
        assert "perc_delta_10d" in out.columns

    def test_first_n_rows_are_nan(self):
        """First `window` rows per sector cannot have a delta."""
        agg = _make_agg(["Tech"], n_days=20)
        out = compute_sector_momentum(agg, windows=[5])
        tech = out[out["sector"] == "Tech"].sort_values("date")
        assert tech["perc_delta_5d"].iloc[:5].isna().all()

    def test_momentum_sign_matches_trend(self):
        """For a monotonically increasing perc series, all deltas should be positive."""
        agg = _make_agg(["Tech"], n_days=30, base_perc=30.0)
        out = compute_sector_momentum(agg, windows=[5])
        tech = out[out["sector"] == "Tech"].sort_values("date")
        # Drop first 5 (NaN) and check positive
        non_nan = tech["perc_delta_5d"].dropna()
        assert (non_nan > 0).all()

    def test_custom_windows(self):
        agg = _make_agg(["Tech"], n_days=25)
        out = compute_sector_momentum(agg, windows=[3, 7])
        assert "perc_delta_3d" in out.columns
        assert "perc_delta_7d" in out.columns
        assert "perc_delta_5d" not in out.columns

    def test_preserves_all_rows(self):
        agg = _make_agg(["Tech", "Energy"], n_days=15)
        out = compute_sector_momentum(agg, windows=[5])
        assert len(out) == len(agg)


# ---------------------------------------------------------------------------
# classify_sector_regime
# ---------------------------------------------------------------------------

class TestClassifySectorRegime:
    def test_empty_returns_empty_list(self):
        assert classify_sector_regime(pd.DataFrame()) == []

    def test_none_returns_empty_list(self):
        assert classify_sector_regime(None) == []

    def test_returns_list_of_sector_regime(self):
        agg = _make_agg(["Tech", "Energy"], n_days=30)
        regimes = classify_sector_regime(agg)
        assert all(isinstance(r, SectorRegime) for r in regimes)

    def test_one_regime_per_sector(self):
        agg = _make_agg(["Tech", "Energy", "Finance"], n_days=30)
        regimes = classify_sector_regime(agg)
        sectors = [r.sector for r in regimes]
        assert len(sectors) == len(set(sectors))

    def test_regime_values_are_valid(self):
        agg = _make_agg(["Tech", "Energy"], n_days=30)
        for r in classify_sector_regime(agg):
            assert r.regime in ("HOT", "NEUTRAL", "COLD")

    def test_trend_values_are_valid(self):
        agg = _make_agg(["Tech", "Energy"], n_days=30)
        for r in classify_sector_regime(agg):
            assert r.trend in ("HEATING", "COOLING", "STABLE")

    def test_sorted_by_regime_z_descending(self):
        agg = _make_agg(["Tech", "Energy", "Finance"], n_days=30)
        regimes = classify_sector_regime(agg)
        zs = [r.regime_z for r in regimes]
        assert zs == sorted(zs, reverse=True)

    def test_high_perc_sector_gets_hot(self):
        """Build a sector with very high recent percentile relative to its history."""
        rows = []
        start = date(2024, 1, 1)
        # 200 days of low perc, then 20 days of very high perc
        for d in range(200):
            rows.append({"sector": "Volcano", "date": start + timedelta(days=d),
                         "median_perc": 20.0, "median_iv": 15.0, "median_hv": 12.0,
                         "mean_pcr": 0.8, "total_oi": 1000, "total_vol": 500, "n_tickers": 3})
        for d in range(200, 220):
            rows.append({"sector": "Volcano", "date": start + timedelta(days=d),
                         "median_perc": 95.0, "median_iv": 40.0, "median_hv": 12.0,
                         "mean_pcr": 0.8, "total_oi": 1000, "total_vol": 500, "n_tickers": 3})
        agg = pd.DataFrame(rows)
        regimes = classify_sector_regime(agg)
        assert len(regimes) == 1
        assert regimes[0].regime == "HOT"

    def test_low_perc_sector_gets_cold(self):
        rows = []
        start = date(2024, 1, 1)
        for d in range(200):
            rows.append({"sector": "Ice", "date": start + timedelta(days=d),
                         "median_perc": 80.0, "median_iv": 40.0, "median_hv": 12.0,
                         "mean_pcr": 0.8, "total_oi": 1000, "total_vol": 500, "n_tickers": 3})
        for d in range(200, 220):
            rows.append({"sector": "Ice", "date": start + timedelta(days=d),
                         "median_perc": 5.0, "median_iv": 10.0, "median_hv": 12.0,
                         "mean_pcr": 0.8, "total_oi": 1000, "total_vol": 500, "n_tickers": 3})
        agg = pd.DataFrame(rows)
        regimes = classify_sector_regime(agg)
        assert regimes[0].regime == "COLD"

    def test_insufficient_history_defaults_neutral(self):
        """Sector with only 3 rows should not crash and default to NEUTRAL."""
        rows = [
            {"sector": "Tiny", "date": date(2025, 1, 1), "median_perc": 50.0,
             "median_iv": 20.0, "median_hv": 15.0, "mean_pcr": 0.8,
             "total_oi": 1000, "total_vol": 500, "n_tickers": 2},
            {"sector": "Tiny", "date": date(2025, 1, 2), "median_perc": 52.0,
             "median_iv": 20.0, "median_hv": 15.0, "mean_pcr": 0.8,
             "total_oi": 1000, "total_vol": 500, "n_tickers": 2},
        ]
        agg = pd.DataFrame(rows)
        regimes = classify_sector_regime(agg)
        assert len(regimes) == 1
        assert regimes[0].regime == "NEUTRAL"


# ---------------------------------------------------------------------------
# compute_rotation_matrix
# ---------------------------------------------------------------------------

class TestComputeRotationMatrix:
    def test_empty_returns_empty(self):
        out = compute_rotation_matrix(pd.DataFrame())
        assert out.empty

    def test_single_sector_returns_empty(self):
        agg = _make_agg(["Tech"], n_days=30)
        out = compute_rotation_matrix(agg)
        assert out.empty

    def test_output_is_square(self):
        agg = _make_agg(["Tech", "Energy", "Finance"], n_days=40)
        matrix = compute_rotation_matrix(agg)
        if not matrix.empty:
            assert matrix.shape[0] == matrix.shape[1]

    def test_diagonal_is_zero(self):
        """A sector cannot follow itself."""
        agg = _make_agg(["Tech", "Energy"], n_days=40)
        matrix = compute_rotation_matrix(agg)
        if not matrix.empty:
            for s in matrix.index:
                if s in matrix.columns:
                    assert matrix.loc[s, s] == 0.0

    def test_probabilities_in_0_1(self):
        agg = _make_agg(["Tech", "Energy", "Finance"], n_days=60)
        matrix = compute_rotation_matrix(agg)
        if not matrix.empty:
            assert (matrix.values >= 0.0).all()
            assert (matrix.values <= 1.0).all()

    def test_no_hot_entries_gives_zeros(self):
        """If no sector ever enters HOT, all probabilities should be zero."""
        # Flat median_perc well within NEUTRAL range
        agg = _make_agg(["Tech", "Energy"], n_days=50, base_perc=50.0)
        # Override to keep very flat
        agg["median_perc"] = 50.0
        matrix = compute_rotation_matrix(agg)
        if not matrix.empty:
            assert (matrix.values == 0.0).all()


# ---------------------------------------------------------------------------
# get_current_rotation_snapshot
# ---------------------------------------------------------------------------

class TestGetCurrentRotationSnapshot:
    def test_empty_regimes_returns_empty(self):
        assert get_current_rotation_snapshot([], pd.DataFrame()) == []

    def test_empty_matrix_returns_empty(self):
        agg = _make_agg(["Tech", "Energy"], n_days=30)
        regimes = classify_sector_regime(agg)
        assert get_current_rotation_snapshot(regimes, pd.DataFrame()) == []

    def test_returns_list_of_dicts(self):
        agg = _make_agg(["Tech", "Energy", "Finance"], n_days=50)
        regimes = classify_sector_regime(agg)
        matrix = compute_rotation_matrix(agg)
        result = get_current_rotation_snapshot(regimes, matrix)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)

    def test_prediction_keys(self):
        agg = _make_agg(["Tech", "Energy"], n_days=50)
        regimes = classify_sector_regime(agg)
        matrix = compute_rotation_matrix(agg)
        for p in get_current_rotation_snapshot(regimes, matrix):
            assert "leader" in p
            assert "follower" in p
            assert "probability" in p
            assert "lead_days_estimate" in p

    def test_probability_in_0_1(self):
        agg = _make_agg(["Tech", "Energy", "Finance"], n_days=60)
        regimes = classify_sector_regime(agg)
        matrix = compute_rotation_matrix(agg)
        for p in get_current_rotation_snapshot(regimes, matrix):
            assert 0.0 <= p["probability"] <= 1.0

    def test_sorted_by_probability_descending(self):
        agg = _make_agg(["Tech", "Energy", "Finance"], n_days=60)
        regimes = classify_sector_regime(agg)
        matrix = compute_rotation_matrix(agg)
        preds = get_current_rotation_snapshot(regimes, matrix)
        probs = [p["probability"] for p in preds]
        assert probs == sorted(probs, reverse=True)

    def test_leader_differs_from_follower(self):
        agg = _make_agg(["Tech", "Energy", "Finance"], n_days=60)
        regimes = classify_sector_regime(agg)
        matrix = compute_rotation_matrix(agg)
        for p in get_current_rotation_snapshot(regimes, matrix):
            assert p["leader"] != p["follower"]

    def test_low_probability_predictions_excluded(self):
        """Predictions with probability < 0.1 should be filtered out."""
        agg = _make_agg(["Tech", "Energy"], n_days=60)
        regimes = classify_sector_regime(agg)
        matrix = compute_rotation_matrix(agg)
        for p in get_current_rotation_snapshot(regimes, matrix):
            assert p["probability"] >= 0.1
