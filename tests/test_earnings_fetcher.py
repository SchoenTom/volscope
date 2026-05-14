"""Earnings fetcher tests."""
from __future__ import annotations

from datetime import date

import pandas as pd

from volscope.data.earnings_fetcher import fetch_upcoming_earnings


class _FakeTicker:
    def __init__(self, df):
        self.earnings_dates = df


def test_no_dataframe_returns_empty():
    assert fetch_upcoming_earnings(_FakeTicker(None)) == []
    assert fetch_upcoming_earnings(_FakeTicker(pd.DataFrame())) == []


def test_filters_past_dates_and_sorts():
    today = pd.Timestamp.now().normalize()
    idx = pd.DatetimeIndex(
        [
            today - pd.Timedelta(days=30),  # past — drop
            today + pd.Timedelta(days=10),
            today + pd.Timedelta(days=100),
            today + pd.Timedelta(days=200),
        ]
    )
    df = pd.DataFrame({"epsEstimate": [None] * 4}, index=idx)
    out = fetch_upcoming_earnings(_FakeTicker(df))
    assert len(out) == 3
    assert out[0] >= date.today()
    assert out == sorted(out)


def test_max_dates_caps_output():
    today = pd.Timestamp.now().normalize()
    idx = pd.DatetimeIndex([today + pd.Timedelta(days=30 * i) for i in range(1, 11)])
    df = pd.DataFrame({"epsEstimate": [None] * 10}, index=idx)
    out = fetch_upcoming_earnings(_FakeTicker(df), max_dates=4)
    assert len(out) == 4
