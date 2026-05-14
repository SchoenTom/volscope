"""Tests for analytics.megascan — universe rankings + KPIs + master export."""
from __future__ import annotations

import io
import time

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.megascan import (
    MASTER_CSV_COLUMNS,
    PageData,
    RANKINGS,
    RankingSpec,
    UniverseKPI,
    apply_ranking,
    build_full_page_data,
    build_master_csv,
    universe_kpis,
)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────

def _make_universe(n: int = 50, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sectors = ["Tech", "Energy", "Bank", "Pharma", "ETF"]
    rows = []
    for i in range(n):
        rows.append({
            "ticker":      f"T{i:03d}",
            "sector":      sectors[i % len(sectors)],
            "company_name": f"Company {i}",
            "iv_30d":      rng.uniform(15, 60),
            "iv_60d":      rng.uniform(15, 60),
            "iv_90d":      rng.uniform(15, 60),
            "iv_180d":     rng.uniform(15, 60),
            "iv_skew_25d": rng.uniform(-5, 10),
            "hv_20d":      rng.uniform(10, 50),
            "hv_60d":      rng.uniform(10, 50),
            "iv_rank":     rng.uniform(0, 100),
            "iv_percentile": rng.uniform(0, 100),
            "iv_change_1d":  rng.normal(0, 2),
            "iv_change_30d": rng.normal(0, 5),
            "perc_trend_30d": rng.normal(0, 10),
            "put_call_ratio":     rng.uniform(0.3, 2.0),
            "total_open_interest": int(rng.uniform(100, 500_000)),
            "total_call_volume":   int(rng.uniform(0, 100_000)),
            "total_put_volume":    int(rng.uniform(0, 100_000)),
            "crowded_score": rng.uniform(0, 100),
            "flow_score":    rng.uniform(0, 100),
            "edge_score":    rng.uniform(0, 100),
            "edge_components_json": "{}",
            "quality_overall": "OK",
        })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# RANKINGS table
# ──────────────────────────────────────────────────────────────────────────

class TestRankingsTable:
    def test_six_rankings(self):
        assert len(RANKINGS) == 6

    def test_distinct_titles(self):
        titles = [r.title for r in RANKINGS]
        assert len(set(titles)) == len(titles)

    def test_each_is_frozen(self):
        with pytest.raises(Exception):
            RANKINGS[0].title = "x"  # type: ignore[misc]

    def test_filter_names_known(self):
        for r in RANKINGS:
            assert r.filter_name in {"liquid", "with_iv"}


# ──────────────────────────────────────────────────────────────────────────
# apply_ranking
# ──────────────────────────────────────────────────────────────────────────

class TestApplyRanking:
    def test_returns_at_most_n_rows(self):
        df = _make_universe(n=50)
        for spec in RANKINGS:
            result = apply_ranking(df, spec)
            assert len(result) <= spec.n

    def test_cheapest_is_ascending_by_percentile(self):
        df = _make_universe(n=50)
        cheap = apply_ranking(df, RANKINGS[0])
        # Should be sorted ascending by iv_percentile
        if len(cheap) > 1:
            ivp = cheap["iv_percentile"].values
            assert all(ivp[i] <= ivp[i + 1] for i in range(len(ivp) - 1))

    def test_richest_is_descending(self):
        df = _make_universe(n=50)
        rich = apply_ranking(df, RANKINGS[1])
        if len(rich) > 1:
            ivp = rich["iv_percentile"].values
            assert all(ivp[i] >= ivp[i + 1] for i in range(len(ivp) - 1))

    def test_cheapest_filters_illiquid(self):
        df = _make_universe(n=20)
        # Force some rows illiquid
        df.loc[0:5, "total_open_interest"] = 50  # below threshold
        df.loc[0:5, "iv_percentile"] = 1  # would otherwise rank top
        cheap = apply_ranking(df, RANKINGS[0])
        # The illiquid sub-1 percentiles should NOT appear
        if not cheap.empty:
            for _, row in cheap.iterrows():
                assert row["total_open_interest"] >= 1000

    def test_movers_up_descending_by_change(self):
        df = _make_universe(n=50)
        movers = apply_ranking(df, RANKINGS[2])
        if len(movers) > 1:
            chg = movers["iv_change_1d"].values
            assert all(chg[i] >= chg[i + 1] for i in range(len(chg) - 1))

    def test_movers_down_ascending(self):
        df = _make_universe(n=50)
        movers = apply_ranking(df, RANKINGS[3])
        if len(movers) > 1:
            chg = movers["iv_change_1d"].values
            assert all(chg[i] <= chg[i + 1] for i in range(len(chg) - 1))

    def test_empty_input_returns_empty(self):
        empty = pd.DataFrame()
        for spec in RANKINGS:
            result = apply_ranking(empty, spec)
            assert result.empty

    def test_missing_sort_key_returns_empty(self):
        df = pd.DataFrame({"ticker": ["A", "B"]})
        for spec in RANKINGS:
            result = apply_ranking(df, spec)
            assert result.empty


# ──────────────────────────────────────────────────────────────────────────
# universe_kpis
# ──────────────────────────────────────────────────────────────────────────

class TestUniverseKpis:
    def test_returns_five(self):
        kpis = universe_kpis(_make_universe(n=50))
        assert len(kpis) == 5

    def test_top_cheap_has_min_percentile(self):
        df = _make_universe(n=50)
        kpis = universe_kpis(df)
        cheap = next((k for k in kpis if k.label == "TOP CHEAP"), None)
        assert cheap is not None
        if cheap.target is not None:
            # The selected ticker must have the min iv_percentile among liquid
            liquid = df[df["total_open_interest"] >= 1000]
            min_perc = liquid["iv_percentile"].min()
            row = df[df["ticker"] == cheap.target].iloc[0]
            assert float(row["iv_percentile"]) == pytest.approx(min_perc, abs=0.001)

    def test_top_rich_has_max_percentile(self):
        df = _make_universe(n=50)
        kpis = universe_kpis(df)
        rich = next((k for k in kpis if k.label == "TOP RICH"), None)
        if rich and rich.target is not None:
            liquid = df[df["total_open_interest"] >= 1000]
            row = df[df["ticker"] == rich.target].iloc[0]
            assert float(row["iv_percentile"]) == pytest.approx(liquid["iv_percentile"].max(), abs=0.001)

    def test_kpis_are_frozen(self):
        kpis = universe_kpis(_make_universe(n=10))
        with pytest.raises(Exception):
            kpis[0].label = "x"  # type: ignore[misc]

    def test_empty_universe_returns_five_with_dashes(self):
        kpis = universe_kpis(pd.DataFrame())
        assert len(kpis) == 5
        # All values should be "—" (no data)
        for k in kpis:
            assert k.value == "—"

    def test_biggest_mover_uses_abs_change(self):
        df = _make_universe(n=20, seed=42)
        # Force a very negative change on a known ticker
        df.loc[df.index[0], "iv_change_1d"] = -50.0
        df.loc[df.index[0], "ticker"] = "BIG_DROP"
        kpis = universe_kpis(df)
        mover = next(k for k in kpis if k.label == "BIG MOVER")
        # The big drop wins on absolute magnitude
        assert mover.target == "BIG_DROP"


# ──────────────────────────────────────────────────────────────────────────
# Master CSV
# ──────────────────────────────────────────────────────────────────────────

class TestMasterCsv:
    def test_columns_exactly(self):
        df = _make_universe(n=10)
        csv = build_master_csv(df)
        cols = pd.read_csv(io.StringIO(csv), nrows=0).columns.tolist()
        assert tuple(cols) == MASTER_CSV_COLUMNS

    def test_24_columns(self):
        # Spec contract: 24 columns
        assert len(MASTER_CSV_COLUMNS) == 24

    def test_partial_input_still_24_columns(self):
        # Source missing some fields → CSV still has all 24, padded with NA
        df = pd.DataFrame({
            "ticker": ["A", "B"],
            "iv_30d": [20, 30],
        })
        csv = build_master_csv(df)
        cols = pd.read_csv(io.StringIO(csv), nrows=0).columns.tolist()
        assert tuple(cols) == MASTER_CSV_COLUMNS

    def test_n_rows_matches_input(self):
        df = _make_universe(n=15)
        csv = build_master_csv(df)
        out = pd.read_csv(io.StringIO(csv))
        assert len(out) == 15

    def test_empty_input(self):
        csv = build_master_csv(pd.DataFrame())
        cols = pd.read_csv(io.StringIO(csv), nrows=0).columns.tolist()
        assert tuple(cols) == MASTER_CSV_COLUMNS


# ──────────────────────────────────────────────────────────────────────────
# Page data composer
# ──────────────────────────────────────────────────────────────────────────

class TestPageData:
    def test_returns_page_data(self):
        pd_obj = build_full_page_data(_make_universe(n=20))
        assert isinstance(pd_obj, PageData)

    def test_has_six_rankings(self):
        pd_obj = build_full_page_data(_make_universe(n=20))
        assert len(pd_obj.rankings) == 6

    def test_has_five_kpis(self):
        pd_obj = build_full_page_data(_make_universe(n=20))
        assert len(pd_obj.kpis) == 5

    def test_csv_text_has_header(self):
        pd_obj = build_full_page_data(_make_universe(n=20))
        first_line = pd_obj.csv_text.splitlines()[0]
        assert first_line.startswith("ticker,")

    def test_scatter_df_has_xy(self):
        pd_obj = build_full_page_data(_make_universe(n=20))
        assert {"x", "y", "ticker"} <= set(pd_obj.scatter_df.columns)


# ──────────────────────────────────────────────────────────────────────────
# Performance SLA — Pillar 4 budget
# ──────────────────────────────────────────────────────────────────────────

class TestPerfSla:
    def test_megascan_render_under_1500ms_p95(self):
        """All Mega-Scan data prep must be < 1500ms p95 on 300 tickers."""
        df = _make_universe(n=300)
        samples = []
        for _ in range(5):
            t0 = time.perf_counter()
            build_full_page_data(df)
            samples.append((time.perf_counter() - t0) * 1000)
        p95 = sorted(samples)[int(0.95 * len(samples))]
        assert p95 < 1500, f"p95 = {p95:.0f}ms (budget 1500ms)"
