"""Tests for the Pro Chart builder."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from volscope.ui.components.pro_chart import render_pro_chart


def _ohlcv(n: int = 60, with_iv: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = 100 + np.cumsum(rng.normal(0, 1, size=n))
    df = pd.DataFrame({
        "date":   dates,
        "open":   closes - 0.5,
        "high":   closes + 1.0,
        "low":    closes - 1.0,
        "close":  closes,
        "volume": rng.integers(1_000_000, 5_000_000, size=n),
    })
    if with_iv:
        df["iv_30d"] = 20 + rng.normal(0, 3, size=n)
    return df


class TestRenderPro:
    def test_full_render(self):
        fig = render_pro_chart(_ohlcv(), "AAPL · 1Y")
        # Candlestick + volume + IV (median + 25/75 band + line) = 1 + 1 + 4
        assert len(fig.data) >= 5
        assert fig.layout.height == 700

    def test_no_iv_collapses_layout(self):
        fig = render_pro_chart(_ohlcv(with_iv=False), "X", iv_column=None)
        # 1 candle + 1 volume only
        assert len(fig.data) == 2

    def test_no_volume_collapses_layout(self):
        df = _ohlcv()
        df = df.drop(columns=["volume"])
        fig = render_pro_chart(df, "X", show_volume=False)
        assert all(t.type != "bar" for t in fig.data)

    def test_yaxis_right_for_price(self):
        fig = render_pro_chart(_ohlcv(), "X")
        assert fig.layout.yaxis.side == "right"
        # USD uses the d3 currency directive so negatives render as
        # "-$50" not "$-50". tickprefix is intentionally empty here.
        assert fig.layout.yaxis.tickformat == "$,.2f"

    def test_eur_prefix(self):
        fig = render_pro_chart(_ohlcv(), "X", currency_prefix="€")
        # Non-USD currencies still use tickprefix (d3's `$` is hard-wired
        # to dollar). The negative-display quirk is mild compared to the
        # certainty of rendering the right currency symbol.
        assert fig.layout.yaxis.tickprefix == "€"

    def test_range_selector_present(self):
        fig = render_pro_chart(_ohlcv(), "X")
        labels = [b.label for b in fig.layout.xaxis.rangeselector.buttons]
        for required in ("1M", "3M", "6M", "YTD", "1Y", "2Y", "ALL"):
            assert required in labels

    def test_range_selector_hidden_when_disabled(self):
        fig = render_pro_chart(_ohlcv(), "X", show_range_selector=False)
        rs = fig.layout.xaxis.rangeselector
        assert rs.buttons is None or len(rs.buttons) == 0

    def test_empty_dataframe_does_not_crash(self):
        fig = render_pro_chart(pd.DataFrame(), "Empty")
        assert fig is not None

    def test_weekends_hidden(self):
        fig = render_pro_chart(_ohlcv(), "X")
        breaks = fig.layout.xaxis.rangebreaks
        assert any(getattr(b, "bounds", None) == ("sat", "mon") for b in breaks)

    def test_spike_lines_configured(self):
        fig = render_pro_chart(_ohlcv(), "X")
        # Price y-axis must have spike enabled
        assert fig.layout.yaxis.showspikes is True
        assert fig.layout.xaxis.showspikes is True

    def test_height_customizable(self):
        fig = render_pro_chart(_ohlcv(), "X", height=420)
        assert fig.layout.height == 420
