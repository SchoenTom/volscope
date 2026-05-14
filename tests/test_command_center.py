"""Tests for Command Center data layer and HTML builders."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import volscope.data.vol_index_fetcher as vif
from volscope.data.vol_index_fetcher import (
    _rank_and_pct_52w,
    bvol_snapshot,
    fetch_deribit_dvol,
    fetch_vol_index_history,
    vol_index_snapshot,
)
from volscope.ui.components.chart_builders import (
    create_command_term_structure,
    create_vrp_bar,
)
from volscope.ui.styles.theme import COLORS
from volscope.ui.views.command_center_page import (
    DEFAULT_COMMAND_TICKERS,
    _market_card_html,
    _vol_pulse_block_html,
)


# ---------------------------------------------------------------------------
# vol_index_fetcher — rank / pct helper
# ---------------------------------------------------------------------------

def test_rank_pct_low_value():
    """Current at the historical minimum → rank near 0, percentile near 0."""
    series = pd.Series(range(10, 110))   # 100 values: 10…109
    rank, pct = _rank_and_pct_52w(series, 10.0)
    assert rank is not None and rank < 2.0
    assert pct is not None and pct == 0.0


def test_rank_pct_high_value():
    """Current at the historical maximum → rank near 100, high percentile."""
    series = pd.Series(range(10, 110))
    rank, pct = _rank_and_pct_52w(series, 109.0)
    assert rank is not None and rank > 98.0
    assert pct is not None and pct > 98.0


def test_rank_pct_short_series_returns_none():
    """Series with fewer than 10 values → (None, None)."""
    series = pd.Series([15.0, 20.0, 18.0])
    rank, pct = _rank_and_pct_52w(series, 18.0)
    assert rank is None
    assert pct is None


def test_rank_pct_midpoint():
    """Midpoint of a 0–100 series gives rank ≈ 50, pct ≈ 50."""
    series = pd.Series(list(range(101)))   # 0, 1, …, 100
    rank, pct = _rank_and_pct_52w(series, 50.0)
    assert rank is not None and abs(rank - 50.0) < 1.0
    assert pct is not None and abs(pct - 50.0) < 2.0


# ---------------------------------------------------------------------------
# vol_index_fetcher — fetch_vol_index_history
# ---------------------------------------------------------------------------

def test_fetch_vol_index_history_returns_series(monkeypatch):
    """Mock yfinance; function returns a non-empty Series."""
    fake_hist = pd.DataFrame(
        {"Close": [15.0, 16.0, 17.0]},
        index=pd.date_range("2024-01-01", periods=3),
    )
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = fake_hist
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = fake_ticker

    monkeypatch.setattr(vif, "_log_or_raise", lambda *a, **kw: None, raising=False)

    with patch.dict("sys.modules", {"yfinance": fake_yf}):
        s = fetch_vol_index_history("^VIX", period="1y")

    assert isinstance(s, pd.Series)
    assert len(s) == 3
    assert float(s.iloc[-1]) == pytest.approx(17.0)


def test_fetch_vol_index_history_fallback_list(monkeypatch):
    """When first symbol fails, second in list is tried."""
    call_log: list[str] = []

    def fake_history(period=None, **kwargs):
        sym = call_log[-1]
        if sym == "FAIL":
            return pd.DataFrame()           # empty → triggers fallback
        return pd.DataFrame(
            {"Close": [20.0]},
            index=pd.date_range("2024-01-01", periods=1),
        )

    fake_ticker = MagicMock()
    fake_ticker.history.side_effect = fake_history
    fake_yf = MagicMock()

    def _ticker(sym):
        call_log.append(sym)
        return fake_ticker

    fake_yf.Ticker.side_effect = _ticker

    with patch.dict("sys.modules", {"yfinance": fake_yf}):
        s = fetch_vol_index_history(["FAIL", "^VIX"], period="1y")

    assert "FAIL" in call_log
    assert "^VIX" in call_log
    assert not s.empty


def test_fetch_vol_index_history_all_fail():
    """If yfinance raises on all symbols, returns empty Series."""
    with patch.dict("sys.modules", {"yfinance": None}):
        # None in sys.modules forces ImportError on `import yfinance`
        s = fetch_vol_index_history("^VIX")
    assert isinstance(s, pd.Series)
    assert s.empty


# ---------------------------------------------------------------------------
# vol_index_fetcher — vol_index_snapshot
# ---------------------------------------------------------------------------

def test_vol_index_snapshot_structure(monkeypatch):
    """snapshot returns dict with all required keys."""
    fake_series = pd.Series(
        list(range(50, 150)),   # 100 values: 50…149
        index=pd.date_range("2023-01-01", periods=100),
        dtype=float,
    )
    monkeypatch.setattr(vif, "fetch_vol_index_history", lambda sym, period="1y": fake_series)

    snap = vol_index_snapshot("VIX", "^VIX")

    required = {"name", "level", "rank_52w", "pct_52w", "change_1w", "regime"}
    assert required.issubset(snap.keys())
    assert snap["name"] == "VIX"
    assert snap["level"] is not None
    assert snap["regime"] in {"CHEAP", "NORMAL", "RICH", "NO DATA"}


def test_vol_index_snapshot_no_data(monkeypatch):
    """Empty series → snapshot with all numerics None and regime NO DATA."""
    monkeypatch.setattr(
        vif, "fetch_vol_index_history", lambda sym, period="1y": pd.Series(dtype=float)
    )
    snap = vol_index_snapshot("VDAX", "^VDAX")
    assert snap["level"] is None
    assert snap["regime"] == "NO DATA"


def test_vol_index_snapshot_cheap_regime(monkeypatch):
    """Series where current (last) is at the historical minimum → CHEAP regime."""
    vals = list(range(21, 120)) + [20]   # 100 entries; iloc[-1] = 20 = min
    fake_series = pd.Series(
        vals,
        index=pd.date_range("2023-01-01", periods=100),
        dtype=float,
    )
    monkeypatch.setattr(
        vif, "fetch_vol_index_history_with_source",
        lambda sym, period="1y": (fake_series, "^VIX"),
    )

    snap = vol_index_snapshot("VIX", "^VIX")
    assert snap["regime"] == "CHEAP"
    assert snap["source"] == "^VIX"


def test_vol_index_snapshot_rich_regime(monkeypatch):
    """Series where current is at its historical max → RICH regime."""
    vals = list(range(20, 120))  # 20…119; iloc[-1] = 119 (max)
    fake_series = pd.Series(
        vals,
        index=pd.date_range("2023-01-01", periods=100),
        dtype=float,
    )
    monkeypatch.setattr(
        vif, "fetch_vol_index_history_with_source",
        lambda sym, period="1y": (fake_series, "^VIX"),
    )

    snap = vol_index_snapshot("VIX", "^VIX")
    assert snap["regime"] == "RICH"


def test_vol_index_snapshot_1w_change(monkeypatch):
    """change_1w equals difference between last and 5-sessions-ago values."""
    vals = [10.0] * 95 + [11.0, 12.0, 13.0, 14.0, 20.0]  # last-5 = 11.0
    fake_series = pd.Series(
        vals,
        index=pd.date_range("2023-01-01", periods=100),
        dtype=float,
    )
    monkeypatch.setattr(
        vif, "fetch_vol_index_history_with_source",
        lambda sym, period="1y": (fake_series, "^VIX"),
    )

    snap = vol_index_snapshot("VIX", "^VIX")
    # 20.0 − 11.0 = 9.0
    assert snap["change_1w"] is not None
    assert abs(snap["change_1w"] - 9.0) < 1e-9


# ---------------------------------------------------------------------------
# vol_index_fetcher — fetch_deribit_dvol
# ---------------------------------------------------------------------------

def _make_deribit_response(closes: list[float]) -> dict:
    """Build a minimal Deribit API response dict."""
    import time
    now_ms = int(time.time() * 1000)
    day_ms = 86_400_000
    rows = [[now_ms - day_ms * (len(closes) - i), 0, 0, 0, c] for i, c in enumerate(closes)]
    return {"result": {"data": rows}}


def test_fetch_deribit_dvol_structure(monkeypatch):
    """Mock requests; returns a non-empty Series with correct values."""
    closes = [55.0, 58.0, 60.0, 62.0, 65.0]
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = _make_deribit_response(closes)

    fake_requests = MagicMock()
    fake_requests.get.return_value = fake_resp

    with patch.dict("sys.modules", {"requests": fake_requests}):
        s = fetch_deribit_dvol("BTC")

    assert isinstance(s, pd.Series)
    assert len(s) == 5
    assert float(s.iloc[-1]) == pytest.approx(65.0)


def test_fetch_deribit_dvol_empty_on_network_error(monkeypatch):
    """requests.get raises → empty Series, no crash."""
    fake_requests = MagicMock()
    fake_requests.get.side_effect = ConnectionError("network down")

    with patch.dict("sys.modules", {"requests": fake_requests}):
        s = fetch_deribit_dvol("BTC")

    assert isinstance(s, pd.Series)
    assert s.empty


def test_bvol_snapshot_structure(monkeypatch):
    """bvol_snapshot returns dict with all required keys."""
    closes = list(range(40, 140))  # 100 values
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = _make_deribit_response(closes)

    fake_requests = MagicMock()
    fake_requests.get.return_value = fake_resp

    with patch.dict("sys.modules", {"requests": fake_requests}):
        snap = bvol_snapshot()

    required = {"name", "level", "rank_52w", "pct_52w", "change_1w", "regime"}
    assert required.issubset(snap.keys())
    assert snap["name"] == "BVOL-BTC"


def test_bvol_snapshot_no_data(monkeypatch):
    """Empty Deribit response → all numerics None, regime NO DATA."""
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = {"result": {"data": []}}

    fake_requests = MagicMock()
    fake_requests.get.return_value = fake_resp

    with patch.dict("sys.modules", {"requests": fake_requests}):
        snap = bvol_snapshot()

    assert snap["level"] is None
    assert snap["regime"] == "NO DATA"


# ---------------------------------------------------------------------------
# HTML builders — _market_card_html
# ---------------------------------------------------------------------------

def test_market_card_no_data():
    """ticker with None row renders without crash and shows ticker name."""
    html = _market_card_html("QQQ", None)
    assert "QQQ" in html
    assert "volscope-card" in html


def test_market_card_full_data():
    """Fully populated row renders all fields correctly."""
    row = pd.Series({
        "iv_30d": 22.4,
        "iv_60d": 24.0,
        "hv_20d": 18.0,
        "iv_percentile": 35.0,
        "iv_rank": 40.0,
        "company_name": "Invesco QQQ",
    })
    html = _market_card_html("QQQ", row)
    assert "QQQ" in html
    assert "22.4%" in html
    assert "18.0%" in html
    assert "Invesco QQQ" in html
    assert "contango" in html   # iv_60d(24.0) > iv_30d(22.4)


def test_market_card_vrp_cheap():
    """VRP < 0.9 → green color class for VRP value."""
    row = pd.Series({"iv_30d": 15.0, "hv_20d": 20.0, "iv_percentile": 10.0})
    html = _market_card_html("SPY", row)
    # VRP = 15/20 = 0.75 < 0.9 → accent (green) color
    assert COLORS["accent"] in html


def test_market_card_vrp_rich():
    """VRP > 1.1 → red color class for VRP value."""
    row = pd.Series({"iv_30d": 30.0, "hv_20d": 20.0, "iv_percentile": 85.0})
    html = _market_card_html("GME", row)
    # VRP = 30/20 = 1.5 > 1.1 → warn (red) color
    assert COLORS["warn"] in html


def test_market_card_backwardation():
    """iv_60d < iv_30d → 'backwardation' label in card."""
    row = pd.Series({"iv_30d": 25.0, "iv_60d": 20.0, "hv_20d": 18.0, "iv_percentile": 70.0})
    html = _market_card_html("MSTR", row)
    assert "backwardation" in html


def test_market_card_cheap_border():
    """Low percentile → volscope-card-cheap CSS class."""
    row = pd.Series({"iv_30d": 12.0, "hv_20d": 14.0, "iv_percentile": 5.0})
    html = _market_card_html("TLT", row)
    assert "volscope-card-cheap" in html


def test_market_card_rich_border():
    """High percentile → volscope-card-rich CSS class."""
    row = pd.Series({"iv_30d": 40.0, "hv_20d": 25.0, "iv_percentile": 95.0})
    html = _market_card_html("UVXY", row)
    assert "volscope-card-rich" in html


# ---------------------------------------------------------------------------
# HTML builders — _vol_pulse_block_html
# ---------------------------------------------------------------------------

def test_vol_pulse_block_no_data():
    """NO DATA snap renders without crash."""
    snap = {
        "name": "VIX",
        "level": None,
        "rank_52w": None,
        "pct_52w": None,
        "change_1w": None,
        "regime": "NO DATA",
    }
    html = _vol_pulse_block_html(snap)
    assert "VIX" in html
    assert "NO DATA" in html


def test_vol_pulse_block_full_data():
    """Populated snap renders numeric values in the HTML."""
    snap = {
        "name": "VIX",
        "level": 18.5,
        "rank_52w": 42.0,
        "pct_52w": 38.0,
        "change_1w": -1.2,
        "regime": "NORMAL",
    }
    html = _vol_pulse_block_html(snap)
    assert "18.5" in html
    assert "NORMAL" in html
    assert "-1.2" in html


def test_vol_pulse_block_positive_change():
    """Positive 1w change → warn (red) color in HTML."""
    snap = {
        "name": "VDAX-New",
        "level": 25.0,
        "rank_52w": 80.0,
        "pct_52w": 82.0,
        "change_1w": 3.0,
        "regime": "RICH",
    }
    html = _vol_pulse_block_html(snap)
    assert COLORS["warn"] in html


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def test_create_command_term_structure_no_data():
    """Empty dict → figure renders without crash, title mentions no data."""
    fig = create_command_term_structure({})
    assert "no data" in fig.layout.title.text.lower()


def test_create_command_term_structure_with_data():
    """Populated dict → at least one trace per ticker."""
    data = {
        "QQQ":  {"iv_30d": 20.0, "iv_60d": 22.0},
        "MSTR": {"iv_30d": 80.0, "iv_60d": 75.0},
    }
    fig = create_command_term_structure(data)
    names = [t.name for t in fig.data]
    assert "QQQ" in names
    assert "MSTR" in names


def test_create_command_term_structure_missing_field():
    """Ticker missing iv_60d is skipped gracefully."""
    data = {
        "QQQ":  {"iv_30d": 20.0},              # missing iv_60d
        "SNOW": {"iv_30d": 35.0, "iv_60d": 38.0},
    }
    fig = create_command_term_structure(data)
    names = [t.name for t in fig.data]
    assert "SNOW" in names
    assert "QQQ" not in names


def test_create_vrp_bar_no_data():
    """Empty dict → figure with 'no data' title, no crash."""
    fig = create_vrp_bar({})
    assert "no data" in fig.layout.title.text.lower()


def test_create_vrp_bar_ratio_computation():
    """iv_30d / hv_20d for each ticker is reflected in bar x values."""
    data = {
        "SPY":  {"iv_30d": 15.0, "hv_20d": 12.0},   # ratio ≈ 1.25
        "AAPL": {"iv_30d": 25.0, "hv_20d": 30.0},   # ratio ≈ 0.83
    }
    fig = create_vrp_bar(data)
    assert len(fig.data) == 1  # one Bar trace
    bar = fig.data[0]
    ratios = dict(zip(bar.y, bar.x))
    assert abs(ratios["SPY"]  - 15.0 / 12.0) < 1e-6
    assert abs(ratios["AAPL"] - 25.0 / 30.0) < 1e-6


def test_create_vrp_bar_zero_hv_skipped():
    """Ticker with hv_20d = 0 is silently skipped (avoids division by zero)."""
    data = {
        "SPY":  {"iv_30d": 15.0, "hv_20d": 0.0},
        "QQQ":  {"iv_30d": 20.0, "hv_20d": 15.0},
    }
    fig = create_vrp_bar(data)
    bar = fig.data[0]
    assert "SPY" not in list(bar.y)
    assert "QQQ" in list(bar.y)


# ---------------------------------------------------------------------------
# DEFAULT_COMMAND_TICKERS
# ---------------------------------------------------------------------------

def test_default_command_tickers_not_empty():
    assert len(DEFAULT_COMMAND_TICKERS) > 0


def test_default_command_tickers_no_duplicates():
    assert len(DEFAULT_COMMAND_TICKERS) == len(set(DEFAULT_COMMAND_TICKERS))
