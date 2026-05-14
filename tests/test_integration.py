"""End-to-end integration: seed a temp DB with synthetic OHLCV, render charts."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.historical_vol import hv_close_to_close
from volscope.analytics.vol_metrics import iv_percentile, iv_rank
from volscope.data.database import VolScopeDB
from volscope.ui.components.chart_builders import (
    create_iv_hv_chart,
    create_iv_range_bar,
    create_percentile_chart,
    create_spread_chart,
)


def _synthetic_ohlcv(n: int = 120, sigma: float = 0.25) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dt = 1 / 252
    z = rng.standard_normal(n)
    r = (0.05 - 0.5 * sigma * sigma) * dt + sigma * np.sqrt(dt) * z
    prices = 100.0 * np.exp(np.cumsum(r))
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": prices,
            "High": prices * 1.005,
            "Low": prices * 0.995,
            "Close": prices,
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


@pytest.fixture
def seeded_db():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "volscope-test.db")
    db = VolScopeDB(path)
    df = _synthetic_ohlcv()
    hv = hv_close_to_close(df["Close"], 20)
    for i, (ts, close) in enumerate(df["Close"].items()):
        if i < 25:
            continue
        hist = hv.iloc[max(0, i - 60) : i].dropna().tolist()
        val = float(hv.iloc[i])
        db.upsert_daily(
            "SPY",
            ts.date(),
            spot_price=float(close),
            iv_30d=val,
            hv_20d=val,
            iv_rank=iv_rank(val, hist),
            iv_percentile=iv_percentile(val, hist),
            sector="Index ETF",
        )
    yield db
    db.close()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def test_end_to_end(seeded_db):
    history = seeded_db.get_ticker_history("SPY")
    assert not history.empty

    fig1 = create_iv_hv_chart(history, "SPY")
    fig2 = create_spread_chart(history)
    fig3 = create_percentile_chart(history)
    assert len(fig1.data) >= 1
    assert len(fig2.data) >= 1
    assert len(fig3.data) >= 1

    latest = seeded_db.get_all_latest()
    assert len(latest) == 1
    assert latest.iloc[0]["ticker"] == "SPY"
    assert "Index ETF" == latest.iloc[0]["sector"]


def test_get_available_tickers(seeded_db):
    assert seeded_db.get_available_tickers() == ["SPY"]


def test_none_inputs_do_not_crash_charts():
    empty = pd.DataFrame()
    assert create_iv_hv_chart(empty, "X") is not None
    assert create_spread_chart(empty) is not None
    assert create_percentile_chart(empty) is not None
    assert create_iv_range_bar(empty) is not None


def test_iv_range_bar_with_data(seeded_db):
    history = seeded_db.get_ticker_history("SPY")
    fig = create_iv_range_bar(history)
    assert len(fig.data) >= 2  # range line + current-IV marker
    title = fig.layout.title.text or ""
    assert any(word in title for word in ("CHEAP", "RICH", "NORMAL"))


def test_upsert_merges_partial_updates():
    """A partial upsert (only IV fields) must NOT wipe HV that was written before."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "volscope-merge.db")
    db = VolScopeDB(path)
    today = date(2026, 4, 14)

    # Step 1: seed full row with HV values.
    db.upsert_daily(
        "AAPL",
        today,
        spot_price=170.0,
        hv_20d=22.0,
        hv_60d=24.0,
        hv_yz_20d=21.5,
        sector="Mega Cap Tech",
    )

    # Step 2: daily scrape only writes IV fields. HV must survive.
    db.upsert_daily(
        "AAPL",
        today,
        iv_30d=27.5,
        iv_60d=28.0,
        put_call_ratio=0.85,
    )

    row = db.get_ticker_history("AAPL").iloc[0]
    assert row["hv_20d"] == 22.0
    assert row["hv_60d"] == 24.0
    assert row["hv_yz_20d"] == 21.5
    assert row["iv_30d"] == 27.5
    assert row["spot_price"] == 170.0
    assert row["sector"] == "Mega Cap Tech"

    db.close()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
