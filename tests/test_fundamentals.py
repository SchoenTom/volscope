"""Fundamentals (TTM dividend yield + sector hybrid) tests."""
from __future__ import annotations

import pandas as pd

from volscope.data.fundamentals import fetch_sector, fetch_ttm_dividend_yield


class _FakeTickerDivs:
    def __init__(self, series: pd.Series, info: dict | None = None):
        self.dividends = series
        self.info = info or {}


def test_ttm_yield_zero_when_no_dividends():
    yt = _FakeTickerDivs(pd.Series(dtype=float))
    assert fetch_ttm_dividend_yield(yt, 100.0) == 0.0


def test_ttm_yield_zero_when_price_invalid():
    idx = pd.date_range("2025-06-01", periods=4, freq="3MS")
    s = pd.Series([0.5, 0.5, 0.5, 0.5], index=idx)
    yt = _FakeTickerDivs(s)
    assert fetch_ttm_dividend_yield(yt, 0.0) == 0.0


def test_ttm_yield_basic_recent_dividends():
    """Four quarterly $0.50 dividends over the past year on a $100 stock → 2% yield."""
    today = pd.Timestamp.now()
    idx = pd.DatetimeIndex(
        [today - pd.Timedelta(days=d) for d in (30, 120, 210, 300)]
    )
    s = pd.Series([0.5, 0.5, 0.5, 0.5], index=idx)
    yt = _FakeTickerDivs(s)
    y = fetch_ttm_dividend_yield(yt, 100.0)
    assert abs(y - 0.02) < 1e-9


def test_ttm_yield_caps_implausible():
    today = pd.Timestamp.now()
    idx = pd.DatetimeIndex([today - pd.Timedelta(days=10)])
    # A $100 dividend on a $100 stock → 100% yield, must be rejected
    s = pd.Series([100.0], index=idx)
    yt = _FakeTickerDivs(s)
    assert fetch_ttm_dividend_yield(yt, 100.0) == 0.0


def test_sector_from_hardcoded_universe():
    assert fetch_sector("SPY") == "Index ETF"
    assert fetch_sector("AAPL") == "Mega Cap Tech"


def test_sector_falls_back_to_yfinance_info():
    yt = _FakeTickerDivs(pd.Series(dtype=float), info={"sector": "Communication Services"})
    assert fetch_sector("ZZZUNKNOWN", yt) == "Communication Services"


def test_sector_returns_none_on_total_failure():
    assert fetch_sector("ZZZUNKNOWN") is None
