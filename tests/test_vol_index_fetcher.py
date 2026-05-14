"""Tests for vol_index_fetcher — fallback chain, source tracking, snapshots."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from volscope.data.vol_index_fetcher import (
    _fetch_vdax_proxy_gdaxi_hv,
    _fetch_vdax_proxy_ewg,
    _rank_and_pct_52w,
    bvol_snapshot,
    fetch_vol_index_history,
    fetch_vol_index_history_with_source,
    vol_index_snapshot,
)


# ---------------------------------------------------------------------------
# fetch_vol_index_history_with_source
# ---------------------------------------------------------------------------

def _make_series(n: int = 50, start: float = 20.0) -> pd.Series:
    import numpy as np
    vals = start + pd.Series(range(n), dtype=float) * 0.1
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.Series(vals.values, index=idx)


class TestFetchWithSource:
    def test_single_symbol_success(self):
        good = _make_series(30)

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": good})
            series, source = fetch_vol_index_history_with_source("^VIX", period="1y")

        assert not series.empty
        assert source == "^VIX"

    def test_list_falls_through_to_second(self):
        good = _make_series(30)

        def ticker_side_effect(sym):
            mock = MagicMock()
            if sym == "^VDAX":
                mock.history.return_value = pd.DataFrame()
            else:
                mock.history.return_value = pd.DataFrame({"Close": good})
            return mock

        with patch("yfinance.Ticker", side_effect=ticker_side_effect):
            series, source = fetch_vol_index_history_with_source(
                ["^VDAX", "VDAX-NEW.DE"], period="1y"
            )

        assert not series.empty
        assert source == "VDAX-NEW.DE"

    def test_all_symbols_fail_returns_empty_and_empty_source(self):
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = pd.DataFrame()
            series, source = fetch_vol_index_history_with_source(
                ["^VDAX", "VDAX-NEW.DE"], period="1y"
            )

        assert series.empty
        assert source == ""

    def test_backward_compat_fetch_vol_index_history_returns_series(self):
        good = _make_series(20)
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = pd.DataFrame({"Close": good})
            s = fetch_vol_index_history("^VIX", period="1y")
        assert isinstance(s, pd.Series)
        assert not s.empty


# ---------------------------------------------------------------------------
# vol_index_snapshot — source field
# ---------------------------------------------------------------------------

class TestVolIndexSnapshot:
    def _patch_history(self, series: pd.Series, source: str):
        return patch(
            "volscope.data.vol_index_fetcher.fetch_vol_index_history_with_source",
            return_value=(series, source),
        )

    def test_snapshot_includes_source(self):
        s = _make_series(60, 18.0)
        with self._patch_history(s, "^VIX"):
            snap = vol_index_snapshot("VIX", "^VIX")
        assert snap["source"] == "^VIX"
        assert snap["level"] is not None
        assert snap["regime"] in ("CHEAP", "NORMAL", "RICH")

    def test_snapshot_no_data_has_source_empty(self):
        with self._patch_history(pd.Series(dtype=float), ""):
            with patch(
                "volscope.data.vol_index_fetcher._fetch_vdax_proxy_ewg",
                return_value=(pd.Series(dtype=float), ""),
            ):
                with patch(
                    "volscope.data.vol_index_fetcher._fetch_vdax_proxy_gdaxi_hv",
                    return_value=(pd.Series(dtype=float), ""),
                ):
                    snap = vol_index_snapshot("VDAX-New", ["^VDAX", "VDAX-NEW.DE"])
        assert snap["source"] == ""
        assert snap["regime"] == "NO DATA"
        assert snap["level"] is None

    def test_vdax_falls_back_to_ewg_proxy(self):
        ewg_series = _make_series(100, 15.0)
        with patch(
            "volscope.data.vol_index_fetcher.fetch_vol_index_history_with_source",
            return_value=(pd.Series(dtype=float), ""),
        ):
            with patch(
                "volscope.data.vol_index_fetcher._fetch_vdax_proxy_ewg",
                return_value=(ewg_series, "EWG proxy"),
            ):
                snap = vol_index_snapshot("VDAX-New", ["^VDAX", "VDAX-NEW.DE"])

        assert snap["source"] == "EWG proxy"
        assert snap["level"] is not None
        assert snap["regime"] != "NO DATA"

    def test_vdax_falls_back_to_dax_hv_when_ewg_fails(self):
        dax_hv_series = _make_series(80, 12.0)
        with patch(
            "volscope.data.vol_index_fetcher.fetch_vol_index_history_with_source",
            return_value=(pd.Series(dtype=float), ""),
        ):
            with patch(
                "volscope.data.vol_index_fetcher._fetch_vdax_proxy_ewg",
                return_value=(pd.Series(dtype=float), ""),
            ):
                with patch(
                    "volscope.data.vol_index_fetcher._fetch_vdax_proxy_gdaxi_hv",
                    return_value=(dax_hv_series, "DAX HV"),
                ):
                    snap = vol_index_snapshot("VDAX-New", ["^VDAX", "VDAX-NEW.DE"])

        assert snap["source"] == "DAX HV"
        assert snap["level"] is not None

    def test_non_vdax_does_not_trigger_proxy_chain(self):
        """VIX should not attempt EWG proxy even if direct symbol fails."""
        ewg_mock = MagicMock()
        with patch(
            "volscope.data.vol_index_fetcher.fetch_vol_index_history_with_source",
            return_value=(pd.Series(dtype=float), ""),
        ):
            with patch(
                "volscope.data.vol_index_fetcher._fetch_vdax_proxy_ewg",
                ewg_mock,
            ):
                snap = vol_index_snapshot("VIX", "^VIX")

        ewg_mock.assert_not_called()
        assert snap["regime"] == "NO DATA"


# ---------------------------------------------------------------------------
# _rank_and_pct_52w edge cases
# ---------------------------------------------------------------------------

class TestRankAndPct:
    def test_not_enough_data(self):
        s = pd.Series([20.0, 21.0])
        rank, pct = _rank_and_pct_52w(s, 20.5)
        assert rank is None
        assert pct is None

    def test_all_same_values(self):
        s = pd.Series([20.0] * 50)
        rank, pct = _rank_and_pct_52w(s, 20.0)
        assert rank == 50.0  # fallback when span == 0

    def test_current_at_max(self):
        import numpy as np
        s = pd.Series(range(1, 101), dtype=float)
        rank, pct = _rank_and_pct_52w(s, 100.0)
        assert rank is not None
        assert abs(rank - 100.0) < 1.0

    def test_current_at_min(self):
        s = pd.Series(range(1, 101), dtype=float)
        rank, pct = _rank_and_pct_52w(s, 1.0)
        assert rank is not None
        assert abs(rank) < 1.0


# ---------------------------------------------------------------------------
# bvol_snapshot — source field
# ---------------------------------------------------------------------------

def test_bvol_snapshot_source_deribit():
    deribit_series = _make_series(60, 50.0)
    with patch(
        "volscope.data.vol_index_fetcher.fetch_deribit_dvol",
        return_value=deribit_series,
    ):
        snap = bvol_snapshot()
    assert snap["source"] == "Deribit"
    assert snap["level"] is not None


def test_bvol_snapshot_no_data_has_empty_source():
    with patch(
        "volscope.data.vol_index_fetcher.fetch_deribit_dvol",
        return_value=pd.Series(dtype=float),
    ):
        snap = bvol_snapshot()
    assert snap["source"] == ""
    assert snap["regime"] == "NO DATA"


# ---------------------------------------------------------------------------
# _fetch_vdax_proxy_gdaxi_hv — unit test without network
# ---------------------------------------------------------------------------

def test_fetch_vdax_proxy_gdaxi_hv_returns_hv_series():
    close = _make_series(100, 20000.0)
    mock_hist = pd.DataFrame({"Close": close})
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = mock_hist
        series, source = _fetch_vdax_proxy_gdaxi_hv(period="1y")

    assert source == "DAX HV"
    assert not series.empty
    assert (series > 0).all()


def test_fetch_vdax_proxy_gdaxi_hv_empty_on_short_history():
    short_close = _make_series(10, 20000.0)
    mock_hist = pd.DataFrame({"Close": short_close})
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.history.return_value = mock_hist
        series, source = _fetch_vdax_proxy_gdaxi_hv(period="1y")

    assert series.empty
    assert source == ""
