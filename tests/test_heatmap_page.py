"""Tests for the Heatmap page — figure builder and color mapping."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from volscope.ui.views.heatmap_page import _build_heatmap_figure, _percentile_color


# ---------------------------------------------------------------------------
# _percentile_color
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# _build_heatmap_figure
# ---------------------------------------------------------------------------

def _make_universe(n: int = 10, with_sector: bool = True) -> pd.DataFrame:
    import random
    rows = []
    sectors = ["Tech", "Finance", "Energy", "Health", "Consumer"]
    for i in range(n):
        rows.append({
            "ticker": f"T{i:03d}",
            "iv_30d": 20.0 + i,
            "iv_percentile": (i / max(n - 1, 1)) * 100,
            "sector": sectors[i % len(sectors)] if with_sector else None,
        })
    return pd.DataFrame(rows)


class TestBuildHeatmapFigure:
    def test_empty_df_returns_empty_figure(self):
        fig = _build_heatmap_figure(pd.DataFrame(), group_by_sector=False)
        assert fig is not None

    def test_per_ticker_mode_has_one_trace(self):
        fig = _build_heatmap_figure(_make_universe(10), group_by_sector=False)
        assert len(fig.data) == 1

    def test_sector_mode_has_one_trace(self):
        fig = _build_heatmap_figure(_make_universe(20), group_by_sector=True)
        assert len(fig.data) == 1

    def test_figure_height_scales_with_rows(self):
        small = _build_heatmap_figure(_make_universe(5), group_by_sector=False)
        large = _build_heatmap_figure(_make_universe(60), group_by_sector=False)
        assert large.layout.height >= small.layout.height

    def test_title_contains_heatmap(self):
        fig = _build_heatmap_figure(_make_universe(5), group_by_sector=False)
        assert "HEATMAP" in fig.layout.title.text

    def test_sector_mode_title_indicates_sector(self):
        fig = _build_heatmap_figure(_make_universe(20), group_by_sector=True)
        assert "sector" in fig.layout.title.text.lower()

    def test_no_sector_column_uses_unknown(self):
        df = _make_universe(5, with_sector=False)
        fig = _build_heatmap_figure(df, group_by_sector=True)
        # Should not crash; Unknown sector used
        assert fig is not None

    def test_text_grid_contains_tickers(self):
        df = _make_universe(5)
        fig = _build_heatmap_figure(df, group_by_sector=False)
        all_text = [cell for row in fig.data[0].text for cell in row]
        assert any(t.startswith("T0") for t in all_text if t)

    def test_z_vals_shape_matches_text_shape(self):
        fig = _build_heatmap_figure(_make_universe(15), group_by_sector=False)
        z = fig.data[0].z
        text = fig.data[0].text
        assert len(z) == len(text)
        assert all(len(z[i]) == len(text[i]) for i in range(len(z)))
