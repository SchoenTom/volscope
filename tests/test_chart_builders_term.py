"""Tests for extended 4-point term structure charts."""
from __future__ import annotations

import pandas as pd
import pytest

from volscope.ui.components.chart_builders import (
    create_command_term_structure,
    create_term_structure_chart,
)


def _history(**kwargs) -> pd.DataFrame:
    base = {"iv_30d": None, "iv_60d": None, "iv_90d": None, "iv_180d": None}
    base.update(kwargs)
    return pd.DataFrame([base])


class TestCreateTermStructureChart:
    def test_empty_history_returns_empty_figure(self):
        fig = create_term_structure_chart(pd.DataFrame())
        assert fig is not None

    def test_two_point_curve_renders(self):
        fig = create_term_structure_chart(_history(iv_30d=18.0, iv_60d=20.0))
        assert len(fig.data) == 1
        assert list(fig.data[0].x) == [30, 60]

    def test_four_point_curve_renders(self):
        fig = create_term_structure_chart(
            _history(iv_30d=18.0, iv_60d=20.0, iv_90d=21.5, iv_180d=22.0)
        )
        assert len(fig.data) == 1
        assert list(fig.data[0].x) == [30, 60, 90, 180]
        assert list(fig.data[0].y) == pytest.approx([18.0, 20.0, 21.5, 22.0])

    def test_partial_curve_skips_none_points(self):
        fig = create_term_structure_chart(
            _history(iv_30d=18.0, iv_60d=None, iv_90d=21.5, iv_180d=22.0)
        )
        assert list(fig.data[0].x) == [30, 90, 180]

    def test_less_than_two_points_returns_empty_trace(self):
        fig = create_term_structure_chart(_history(iv_30d=18.0))
        assert len(fig.data) == 0

    def test_contango_verdict_in_title(self):
        fig = create_term_structure_chart(
            _history(iv_30d=15.0, iv_60d=18.0, iv_90d=20.0, iv_180d=22.0)
        )
        title_text = fig.layout.title.text
        assert "CONTANGO" in title_text

    def test_backwardation_verdict_in_title(self):
        fig = create_term_structure_chart(
            _history(iv_30d=25.0, iv_60d=22.0, iv_90d=20.0, iv_180d=18.0)
        )
        title_text = fig.layout.title.text
        assert "BACKWARDATION" in title_text

    def test_flat_verdict_in_title(self):
        fig = create_term_structure_chart(
            _history(iv_30d=20.0, iv_60d=20.2, iv_90d=20.1, iv_180d=20.3)
        )
        title_text = fig.layout.title.text
        assert "FLAT" in title_text


class TestCreateCommandTermStructure:
    def test_empty_dict_returns_no_data_title(self):
        fig = create_command_term_structure({})
        assert "no data" in fig.layout.title.text.lower()

    def test_two_tickers_two_traces(self):
        data = {
            "SPY": {"iv_30d": 18.0, "iv_60d": 20.0, "iv_90d": 21.0, "iv_180d": 22.0},
            "QQQ": {"iv_30d": 22.0, "iv_60d": 24.0, "iv_90d": 25.0, "iv_180d": 26.0},
        }
        fig = create_command_term_structure(data)
        assert len(fig.data) == 2

    def test_four_point_curve_per_ticker(self):
        data = {"AAPL": {"iv_30d": 20.0, "iv_60d": 21.0, "iv_90d": 22.0, "iv_180d": 23.0}}
        fig = create_command_term_structure(data)
        assert list(fig.data[0].x) == [30, 60, 90, 180]

    def test_ticker_with_partial_points(self):
        data = {"AAPL": {"iv_30d": 20.0, "iv_60d": None, "iv_90d": 22.0, "iv_180d": 23.0}}
        fig = create_command_term_structure(data)
        assert list(fig.data[0].x) == [30, 90, 180]

    def test_ticker_missing_iv_30d_skipped_if_only_one_point(self):
        data = {"AAPL": {"iv_30d": None, "iv_60d": None, "iv_90d": None, "iv_180d": 23.0}}
        fig = create_command_term_structure(data)
        assert len(fig.data) == 0

    def test_contango_color_is_accent2(self):
        from volscope.ui.components.chart_builders import COLORS
        data = {"SPY": {"iv_30d": 18.0, "iv_60d": 20.0, "iv_90d": 21.0, "iv_180d": 22.0}}
        fig = create_command_term_structure(data)
        assert fig.data[0].line.color == COLORS["accent2"]

    def test_backwardation_color_is_amber(self):
        from volscope.ui.components.chart_builders import COLORS
        data = {"SPY": {"iv_30d": 25.0, "iv_60d": 22.0, "iv_90d": 20.0, "iv_180d": 18.0}}
        fig = create_command_term_structure(data)
        assert fig.data[0].line.color == COLORS["amber"]

    def test_x_axis_includes_180d_tick(self):
        data = {"SPY": {"iv_30d": 18.0, "iv_60d": 20.0, "iv_90d": 21.0, "iv_180d": 22.0}}
        fig = create_command_term_structure(data)
        assert 180 in list(fig.layout.xaxis.tickvals)
