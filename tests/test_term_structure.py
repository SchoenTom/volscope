"""Tests for the IV term structure chart."""
from __future__ import annotations

import pandas as pd
import pytest

from volscope.ui.components.chart_builders import create_term_structure_chart


def _row(iv30: float, iv60: float) -> pd.DataFrame:
    return pd.DataFrame({"iv_30d": [iv30], "iv_60d": [iv60]})


class TestTermStructure:
    def test_empty_df_returns_figure(self):
        fig = create_term_structure_chart(pd.DataFrame())
        assert fig is not None
        # No traces on an empty render.
        assert len(fig.data) == 0

    def test_missing_columns_returns_figure(self):
        df = pd.DataFrame({"iv_30d": [20.0]})
        fig = create_term_structure_chart(df)
        assert len(fig.data) == 0

    def test_null_values_returns_figure(self):
        df = pd.DataFrame({"iv_30d": [None], "iv_60d": [None]})
        fig = create_term_structure_chart(df)
        assert len(fig.data) == 0

    def test_contango_when_longer_dated_richer(self):
        fig = create_term_structure_chart(_row(15.0, 18.0))
        title = fig.layout.title.text or ""
        assert "CONTANGO" in title

    def test_backwardation_when_near_dated_richer(self):
        fig = create_term_structure_chart(_row(30.0, 25.0))
        title = fig.layout.title.text or ""
        assert "BACKWARDATION" in title

    def test_flat_when_close(self):
        fig = create_term_structure_chart(_row(20.0, 20.2))
        title = fig.layout.title.text or ""
        assert "FLAT" in title

    def test_plots_two_points(self):
        fig = create_term_structure_chart(_row(15.0, 18.0))
        assert len(fig.data) == 1
        trace = fig.data[0]
        assert len(trace.x) == 2
        assert list(trace.x) == [30, 60]
        assert list(trace.y) == [15.0, 18.0]

    def test_uses_latest_row(self):
        df = pd.DataFrame(
            {"iv_30d": [10.0, 20.0], "iv_60d": [12.0, 22.0]}
        )
        fig = create_term_structure_chart(df)
        # Should plot the LAST row (20, 22), not the first.
        assert list(fig.data[0].y) == [20.0, 22.0]
