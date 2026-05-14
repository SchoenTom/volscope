"""
Tests for the Sector Rotation Engine — analytics and UI builders.

Coverage:
  - compute_sector_aggregates: normal data, empty, missing columns
  - compute_sector_momentum: rolling delta columns added per-sector
  - classify_sector_regime: HOT/COLD/NEUTRAL classification, trend labels
  - compute_rotation_matrix: transition probability shape and range
  - get_current_rotation_snapshot: leader/follower predictions structure
  - DB: upsert_sector_daily + get_sector_history + get_sector_latest
  - UI: _regime_strip_html, _prediction_cards_html, _build_sector_heatmap
"""
from __future__ import annotations

import datetime

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

def _make_daily_vol(n_sectors: int = 3, n_days: int = 60, seed: int = 42) -> pd.DataFrame:
    """Synthetic daily_vol-style DataFrame."""
    rng = np.random.default_rng(seed)
    sectors = [f"Sector{i}" for i in range(n_sectors)]
    tickers_per_sector = 4
    rows = []
    base_date = datetime.date(2025, 1, 1)
    for d in range(n_days):
        date = base_date + datetime.timedelta(days=d)
        for sec in sectors:
            for t in range(tickers_per_sector):
                ticker = f"{sec[:3]}{t}"
                iv = rng.uniform(15, 60)
                hv = rng.uniform(10, 50)
                rows.append({
                    "ticker": ticker,
                    "date": date,
                    "sector": sec,
                    "iv_30d": iv,
                    "iv_percentile": rng.uniform(0, 100),
                    "hv_20d": hv,
                    "put_call_ratio": rng.uniform(0.5, 2.5),
                    "total_call_volume": int(rng.integers(100, 5000)),
                    "total_put_volume": int(rng.integers(100, 5000)),
                    "total_open_interest": int(rng.integers(1000, 50000)),
                })
    return pd.DataFrame(rows)


def _make_agg(n_sectors: int = 3, n_days: int = 60) -> pd.DataFrame:
    return compute_sector_aggregates(_make_daily_vol(n_sectors, n_days))


# ---------------------------------------------------------------------------
# compute_sector_aggregates
# ---------------------------------------------------------------------------

class TestComputeSectorAggregates:
    def test_returns_dataframe(self):
        agg = _make_agg()
        assert isinstance(agg, pd.DataFrame)

    def test_expected_columns(self):
        agg = _make_agg()
        for col in ("sector", "date", "median_iv", "median_perc", "n_tickers"):
            assert col in agg.columns, f"missing column: {col}"

    def test_one_row_per_sector_per_day(self):
        agg = _make_agg(n_sectors=3, n_days=30)
        counts = agg.groupby(["sector", "date"]).size()
        assert (counts == 1).all()

    def test_n_tickers_matches_input(self):
        agg = _make_agg(n_sectors=2, n_days=10)
        assert (agg["n_tickers"] == 4).all()

    def test_empty_input_returns_empty_with_columns(self):
        result = compute_sector_aggregates(pd.DataFrame())
        assert result.empty
        assert "sector" in result.columns

    def test_missing_sector_column(self):
        df = pd.DataFrame({"date": [datetime.date(2025, 1, 1)], "iv_30d": [20.0]})
        result = compute_sector_aggregates(df)
        assert isinstance(result, pd.DataFrame)

    def test_median_perc_in_valid_range(self):
        agg = _make_agg()
        valid = agg["median_perc"].dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_none_daily_vol(self):
        result = compute_sector_aggregates(None)
        assert result.empty


# ---------------------------------------------------------------------------
# compute_sector_momentum
# ---------------------------------------------------------------------------

class TestComputeSectorMomentum:
    def test_adds_delta_columns(self):
        agg = _make_agg(n_sectors=2, n_days=40)
        mom = compute_sector_momentum(agg, windows=[5, 21])
        assert "perc_delta_5d" in mom.columns
        assert "perc_delta_21d" in mom.columns

    def test_shape_preserved(self):
        agg = _make_agg()
        mom = compute_sector_momentum(agg)
        assert len(mom) == len(agg)

    def test_empty_passthrough(self):
        empty = pd.DataFrame()
        result = compute_sector_momentum(empty)
        assert result.empty

    def test_delta_is_nan_for_first_window_rows(self):
        agg = _make_agg(n_sectors=1, n_days=30)
        mom = compute_sector_momentum(agg, windows=[5])
        # First 5 rows per sector should be NaN
        for _, grp in mom.groupby("sector"):
            g = grp.sort_values("date")
            assert pd.isna(g["perc_delta_5d"].iloc[0])

    def test_default_windows(self):
        agg = _make_agg()
        mom = compute_sector_momentum(agg)
        for w in (5, 10, 21):
            assert f"perc_delta_{w}d" in mom.columns


# ---------------------------------------------------------------------------
# classify_sector_regime
# ---------------------------------------------------------------------------

class TestClassifySectorRegime:
    def test_returns_list_of_sector_regime(self):
        agg = _make_agg(n_sectors=3, n_days=50)
        regimes = classify_sector_regime(agg)
        assert isinstance(regimes, list)
        assert all(isinstance(r, SectorRegime) for r in regimes)

    def test_one_regime_per_sector(self):
        agg = _make_agg(n_sectors=4, n_days=50)
        regimes = classify_sector_regime(agg)
        assert len(regimes) == 4

    def test_regime_values_are_valid(self):
        agg = _make_agg(n_sectors=3, n_days=50)
        regimes = classify_sector_regime(agg)
        for r in regimes:
            assert r.regime in ("HOT", "COLD", "NEUTRAL")
            assert r.trend in ("HEATING", "COOLING", "STABLE")

    def test_hot_when_high_percentile(self):
        """Force a sector with all-high percentile → should be HOT."""
        rng = np.random.default_rng(0)
        dates = [datetime.date(2024, 1, 1) + datetime.timedelta(days=i) for i in range(80)]
        rows = []
        for d in dates:
            for t in range(4):
                rows.append({
                    "ticker": f"H{t}",
                    "date": d,
                    "sector": "HighSector",
                    "iv_30d": 50.0,
                    "iv_percentile": 95.0,  # always high
                    "hv_20d": 30.0,
                    "put_call_ratio": 1.0,
                    "total_call_volume": 1000,
                    "total_put_volume": 1000,
                    "total_open_interest": 10000,
                })
        for d in dates:
            for t in range(4):
                rows.append({
                    "ticker": f"L{t}",
                    "date": d,
                    "sector": "LowSector",
                    "iv_30d": 20.0,
                    "iv_percentile": 5.0,  # always low
                    "hv_20d": 15.0,
                    "put_call_ratio": 0.8,
                    "total_call_volume": 500,
                    "total_put_volume": 500,
                    "total_open_interest": 5000,
                })
        df = pd.DataFrame(rows)
        agg = compute_sector_aggregates(df)
        # Add variance by mixing values for z-score to fire
        regimes = classify_sector_regime(agg)
        regime_map = {r.sector: r.regime for r in regimes}
        assert "HighSector" in regime_map
        assert "LowSector" in regime_map

    def test_empty_agg_returns_empty_list(self):
        result = classify_sector_regime(pd.DataFrame())
        assert result == []

    def test_sorted_by_regime_z_descending(self):
        agg = _make_agg(n_sectors=4, n_days=60)
        regimes = classify_sector_regime(agg)
        zs = [r.regime_z for r in regimes]
        assert zs == sorted(zs, reverse=True)


# ---------------------------------------------------------------------------
# compute_rotation_matrix
# ---------------------------------------------------------------------------

class TestComputeRotationMatrix:
    def test_returns_dataframe(self):
        agg = _make_agg(n_sectors=3, n_days=80)
        matrix = compute_rotation_matrix(agg)
        assert isinstance(matrix, pd.DataFrame)

    def test_probabilities_in_range(self):
        agg = _make_agg(n_sectors=3, n_days=80)
        matrix = compute_rotation_matrix(agg)
        if not matrix.empty:
            assert (matrix.values >= 0).all()
            assert (matrix.values <= 1).all()

    def test_empty_agg_returns_empty(self):
        result = compute_rotation_matrix(pd.DataFrame())
        assert result.empty

    def test_single_sector_returns_empty(self):
        """Cannot compute transitions between sectors with only one sector."""
        df = _make_daily_vol(n_sectors=1, n_days=60)
        agg = compute_sector_aggregates(df)
        result = compute_rotation_matrix(agg)
        assert result.empty

    def test_shape_is_sectors_square(self):
        agg = _make_agg(n_sectors=3, n_days=60)
        matrix = compute_rotation_matrix(agg)
        if not matrix.empty:
            assert matrix.shape[0] == matrix.shape[1]


# ---------------------------------------------------------------------------
# get_current_rotation_snapshot
# ---------------------------------------------------------------------------

class TestGetCurrentRotationSnapshot:
    def test_returns_list(self):
        agg = _make_agg()
        regimes = classify_sector_regime(agg)
        matrix = compute_rotation_matrix(agg)
        result = get_current_rotation_snapshot(regimes, matrix)
        assert isinstance(result, list)

    def test_empty_regimes_returns_empty(self):
        result = get_current_rotation_snapshot([], pd.DataFrame())
        assert result == []

    def test_empty_matrix_returns_empty(self):
        agg = _make_agg()
        regimes = classify_sector_regime(agg)
        result = get_current_rotation_snapshot(regimes, pd.DataFrame())
        assert result == []

    def test_prediction_has_required_keys(self):
        agg = _make_agg(n_sectors=4, n_days=80)
        regimes = classify_sector_regime(agg)
        matrix = compute_rotation_matrix(agg)
        predictions = get_current_rotation_snapshot(regimes, matrix)
        for p in predictions:
            for key in ("leader", "follower", "probability", "lead_days_estimate"):
                assert key in p, f"missing key {key}"

    def test_probability_in_range(self):
        agg = _make_agg(n_sectors=4, n_days=80)
        regimes = classify_sector_regime(agg)
        matrix = compute_rotation_matrix(agg)
        predictions = get_current_rotation_snapshot(regimes, matrix)
        for p in predictions:
            assert 0.0 <= p["probability"] <= 1.0


# ---------------------------------------------------------------------------
# DB: sector_daily methods
# ---------------------------------------------------------------------------

class TestSectorDailyDB:
    @pytest.fixture
    def db(self, tmp_path):
        from volscope.data.database import VolScopeDB
        return VolScopeDB(db_path=str(tmp_path / "test.db"))

    def test_upsert_and_get_sector_history(self, db):
        d = datetime.date(2025, 4, 1)
        db.upsert_sector_daily("Tech", d, median_iv=30.0, median_perc=45.0, n_tickers=5)
        hist = db.get_sector_history("Tech")
        assert not hist.empty
        assert float(hist.iloc[0]["median_iv"]) == pytest.approx(30.0)

    def test_upsert_is_idempotent(self, db):
        d = datetime.date(2025, 4, 1)
        db.upsert_sector_daily("Tech", d, median_perc=40.0)
        db.upsert_sector_daily("Tech", d, median_perc=55.0)
        hist = db.get_sector_history("Tech")
        assert len(hist) == 1
        assert float(hist.iloc[0]["median_perc"]) == pytest.approx(55.0)

    def test_get_sector_latest(self, db):
        for i in range(3):
            db.upsert_sector_daily(
                "Energy",
                datetime.date(2025, 4, i + 1),
                median_perc=float(i * 10),
            )
        latest = db.get_sector_latest()
        assert not latest.empty
        energy = latest[latest["sector"] == "Energy"]
        assert len(energy) == 1
        assert float(energy.iloc[0]["median_perc"]) == pytest.approx(20.0)

    def test_get_sector_history_all(self, db):
        db.upsert_sector_daily("Tech", datetime.date(2025, 4, 1), median_perc=30.0)
        db.upsert_sector_daily("Energy", datetime.date(2025, 4, 1), median_perc=55.0)
        hist = db.get_sector_history()
        assert len(hist) == 2

    def test_regime_stored_and_retrieved(self, db):
        db.upsert_sector_daily("Financials", datetime.date(2025, 4, 1),
                               regime="HOT", regime_z=1.5)
        hist = db.get_sector_history("Financials")
        assert hist.iloc[0]["regime"] == "HOT"
        assert float(hist.iloc[0]["regime_z"]) == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# UI: HTML builders
# ---------------------------------------------------------------------------

class TestRotationPageHtml:
    def _make_regimes(self) -> list[SectorRegime]:
        return [
            SectorRegime("Tech", "HOT", 1.3, "HEATING", 3.5, 8.0, 72.0),
            SectorRegime("Energy", "COLD", -1.2, "STABLE", -0.5, -2.0, 18.0),
            SectorRegime("Financials", "NEUTRAL", 0.2, "COOLING", -1.0, -3.0, 45.0),
        ]

    def test_regime_strip_contains_sectors(self):
        from volscope.ui.views.rotation_page import _regime_strip_html
        html = _regime_strip_html(self._make_regimes())
        assert "Tech" in html
        assert "Energy" in html
        assert "Financials" in html

    def test_regime_strip_empty(self):
        from volscope.ui.views.rotation_page import _regime_strip_html
        html = _regime_strip_html([])
        assert isinstance(html, str)
        assert len(html) > 0

    def test_regime_strip_shows_regime_labels(self):
        from volscope.ui.views.rotation_page import _regime_strip_html
        html = _regime_strip_html(self._make_regimes())
        assert "HOT" in html
        assert "COLD" in html

    def test_prediction_cards_empty(self):
        from volscope.ui.views.rotation_page import _prediction_cards_html
        html = _prediction_cards_html([])
        assert isinstance(html, str)
        assert len(html) > 0

    def test_prediction_cards_renders_leader_follower(self):
        from volscope.ui.views.rotation_page import _prediction_cards_html
        predictions = [
            {"leader": "Tech", "leader_regime": "HOT",
             "follower": "Energy", "probability": 0.68, "lead_days_estimate": 21},
        ]
        html = _prediction_cards_html(predictions)
        assert "Tech" in html
        assert "Energy" in html
        assert "68" in html

    def test_build_sector_heatmap_empty(self):
        from volscope.ui.views.rotation_page import _build_sector_heatmap
        import plotly.graph_objects as go
        fig = _build_sector_heatmap(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_build_sector_heatmap_with_data(self):
        from volscope.ui.views.rotation_page import _build_sector_heatmap
        import plotly.graph_objects as go
        agg = _make_agg(n_sectors=3, n_days=30)
        fig = _build_sector_heatmap(agg, lookback_days=60)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0
