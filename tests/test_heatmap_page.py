"""Tests for the Heatmap page — figure builder and color mapping.

v0.8.0 redesign replaced the original grid `_build_heatmap_figure(df,
group_by_sector)` with `_build_treemap_figure(df, color_metric,
color_range)`. The old test suite was deleted because its 20 cases
all asserted against the dead signature. The `_percentile_color`
unit tests below survive — that helper is unchanged.
"""
from __future__ import annotations

import pandas as pd
import pytest

from volscope.ui.views.heatmap_page import _build_treemap_figure, _percentile_color


class TestPercentileColor:
    def test_cheap_range(self):
        assert _percentile_color(10.0) == "#00d4aa"

    def test_below_normal_range(self):
        assert _percentile_color(30.0) == "#5bc8b0"

    def test_neutral_range(self):
        assert _percentile_color(50.0) == "#8a8f9e"

    def test_elevated_range(self):
        assert _percentile_color(70.0) == "#ff9f43"

    def test_rich_range(self):
        assert _percentile_color(90.0) == "#ff4466"

    def test_exact_boundary_20(self):
        # 20 falls into "below normal" bucket (< 20 is cheap, >= 20 is below_normal)
        assert _percentile_color(20.0) == "#5bc8b0"

    def test_exact_boundary_80(self):
        assert _percentile_color(80.0) == "#ff4466"

    def test_none_returns_border_color(self):
        from volscope.ui.styles.theme import COLORS
        assert _percentile_color(None) == COLORS.get("border", "#2a2d3e")

    def test_nan_returns_border_color(self):
        from volscope.ui.styles.theme import COLORS
        assert _percentile_color(float("nan")) == COLORS.get("border", "#2a2d3e")

    def test_clamps_below_zero(self):
        assert _percentile_color(-5.0) == "#00d4aa"

    def test_clamps_above_100(self):
        assert _percentile_color(105.0) == "#ff4466"


def _make_universe(n: int = 10) -> pd.DataFrame:
    sectors = ["Tech", "Finance", "Energy", "Health", "Consumer"]
    rows = []
    for i in range(n):
        rows.append({
            "ticker": f"T{i:03d}",
            "iv_30d": 20.0 + i,
            "iv_percentile": (i / max(n - 1, 1)) * 100,
            "hv_20d": 18.0 + i * 0.8,
            "hv_yz_30d": 17.0 + i * 0.9,
            "iv_hv_spread": 2.0 + i * 0.2,
            "iv_hv_spread_matched": 3.0 + i * 0.2,
            "total_open_interest": 1000 * (i + 1),
            "iv_change_1d": (-2 + i * 0.3),
            "iv_change_30d": (-5 + i * 0.8),
            "sector": sectors[i % len(sectors)],
        })
    return pd.DataFrame(rows)


class TestBuildTreemapFigure:
    def test_empty_df_returns_empty_figure(self):
        fig = _build_treemap_figure(pd.DataFrame())
        assert fig is not None

    def test_universe_renders_one_treemap_trace(self):
        fig = _build_treemap_figure(_make_universe(15))
        assert len(fig.data) == 1
        assert fig.data[0].type == "treemap"

    def test_treemap_has_sector_parents_plus_tickers(self):
        # Hierarchy: sector nodes (parent="") + ticker nodes (parent=sector)
        fig = _build_treemap_figure(_make_universe(15))
        labels = list(fig.data[0].labels)
        parents = list(fig.data[0].parents)
        # 15 tickers + their (≤5) sectors
        assert len(labels) >= 15
        # Some labels must have parent="" (sector roots)
        assert "" in parents

    def test_change_mode_uses_symmetric_color_range(self):
        df = _make_universe(20)
        fig = _build_treemap_figure(df, color_metric="iv_change_30d", color_range=(-5.0, 5.0))
        marker = fig.data[0].marker
        # Symmetric range around 0 → cmid is 0 for change-mode
        assert marker.cmid == 0

    def test_drops_rows_with_null_iv_30d(self):
        df = _make_universe(10)
        df.loc[3, "iv_30d"] = None  # one ticker with NULL IV — must be filtered
        fig = _build_treemap_figure(df)
        ticker_labels = [
            lbl for lbl, par in zip(fig.data[0].labels, fig.data[0].parents)
            if par != ""
        ]
        assert "T003" not in ticker_labels
