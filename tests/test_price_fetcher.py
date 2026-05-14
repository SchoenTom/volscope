"""Price fetcher tests — offline with monkeypatched yfinance."""
import pandas as pd
import pytest

import volscope.data.price_fetcher as pf


class _FakeTicker:
    def __init__(self, df):
        self._df = df

    def history(self, period: str = "2y", auto_adjust: bool = False):
        return self._df


class _FakeYF:
    def __init__(self, df):
        self._df = df

    def Ticker(self, ticker: str):
        return _FakeTicker(self._df)


@pytest.fixture
def good_df():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    return pd.DataFrame(
        {
            "Open": range(10),
            "High": range(1, 11),
            "Low": range(-1, 9),
            "Close": range(10),
            "Volume": [1000] * 10,
            "Dividends": [0] * 10,
            "Stock Splits": [0] * 10,
        },
        index=idx,
    )


def test_fetch_ohlcv_good(monkeypatch, good_df):
    monkeypatch.setattr(pf, "__name__", pf.__name__)
    import sys
    sys.modules["yfinance"] = _FakeYF(good_df)
    df = pf.fetch_ohlcv("SPY")
    assert not df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 10


def test_fetch_ohlcv_empty(monkeypatch):
    import sys
    sys.modules["yfinance"] = _FakeYF(pd.DataFrame())
    df = pf.fetch_ohlcv("BADTICKER")
    assert df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_fetch_spot_price(monkeypatch, good_df):
    import sys
    sys.modules["yfinance"] = _FakeYF(good_df)
    spot = pf.fetch_spot_price("SPY")
    assert spot is not None
    assert spot == 9.0


def test_fetch_spot_price_empty(monkeypatch):
    import sys
    sys.modules["yfinance"] = _FakeYF(pd.DataFrame())
    assert pf.fetch_spot_price("BADTICKER") is None
