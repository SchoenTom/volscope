"""Tests for on-demand ticker resolution (volscope.data.ticker_resolver)."""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

from volscope.data import price_fetcher as pf
from volscope.data.database import VolScopeDB
from volscope.data.ticker_resolver import (
    ResolveResult,
    normalize_ticker,
    resolve_and_ingest,
)


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "resolver-test.db")
    d = VolScopeDB(path)
    yield d
    d.close()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _synthetic_ohlcv(n: int = 180) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    dt = 1 / 252
    sigma = 0.25
    z = rng.standard_normal(n)
    r = (0.05 - 0.5 * sigma * sigma) * dt + sigma * np.sqrt(dt) * z
    close = 100.0 * np.exp(np.cumsum(r))
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.004,
            "Low": close * 0.996,
            "Close": close,
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


class TestNormalizeTicker:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("spy", "SPY"),
            (" AAPL ", "AAPL"),
            ("brk.b", "BRK.B"),
            ("^vix", "^VIX"),
            ("BRK-B", "BRK-B"),
        ],
    )
    def test_valid(self, raw, expected):
        assert normalize_ticker(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["", "   ", None, "toolongticker", "!!", "a b", "SPY;DROP"],
    )
    def test_invalid(self, raw):
        assert normalize_ticker(raw) is None


class TestResolveAndIngest:
    def test_happy_path_writes_rows(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", lambda t, period="2y": _synthetic_ohlcv(180))
        result = resolve_and_ingest(db, "pltr")
        assert isinstance(result, ResolveResult)
        assert result.ok is True
        assert result.ticker == "PLTR"
        assert result.rows_written > 60
        assert "PLTR" in db.get_available_tickers()

    def test_idempotent_no_refetch(self, db, monkeypatch):
        calls = {"n": 0}

        def fake(t, period="2y"):
            calls["n"] += 1
            return _synthetic_ohlcv(180)

        monkeypatch.setattr(pf, "fetch_ohlcv", fake)
        resolve_and_ingest(db, "ASML")
        first = calls["n"]
        result2 = resolve_and_ingest(db, "ASML")
        assert result2.ok is True
        assert result2.rows_written == 0
        assert "already" in result2.message.lower()
        assert calls["n"] == first  # no second Yahoo call

    def test_empty_yahoo_response(self, db, monkeypatch):
        monkeypatch.setattr(
            pf, "fetch_ohlcv", lambda t, period="2y": pd.DataFrame()
        )
        result = resolve_and_ingest(db, "FAKEFAKE")
        assert result.ok is False
        assert "no yahoo data" in result.message.lower()

    def test_too_short_history(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", lambda t, period="2y": _synthetic_ohlcv(10))
        result = resolve_and_ingest(db, "NEWIPO")
        assert result.ok is False
        assert "bars" in result.message.lower()

    def test_rejects_invalid_format(self, db):
        result = resolve_and_ingest(db, "not a ticker!")
        assert result.ok is False
        assert "invalid" in result.message.lower()

    def test_sidebar_helper_exists(self):
        # Makes sure the sidebar imports the resolver so the wiring doesn't rot.
        from volscope.ui.components.sidebar import resolve_and_ingest as sidebar_resolver

        assert sidebar_resolver is resolve_and_ingest


class TestSuffixFallback:
    """
    The real user bug: typing "1810" should resolve to Xiaomi on Hong Kong.
    We simulate Yahoo by failing bare lookups and only returning data for the
    suffixed form.
    """

    def _fake_yahoo(self, good_symbols: set[str]):
        def fake(ticker: str, period: str = "2y"):
            if ticker in good_symbols:
                return _synthetic_ohlcv(180)
            return pd.DataFrame()

        return fake

    def test_digit_ticker_falls_back_to_hk(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", self._fake_yahoo({"1810.HK"}))
        result = resolve_and_ingest(db, "1810")
        assert result.ok, f"expected ok, got: {result.message}"
        assert result.ticker == "1810.HK"
        assert "1810.HK" in db.get_available_tickers()
        assert "1810" not in db.get_available_tickers()  # bare form not stored

    def test_digit_ticker_prefers_hk_over_others(self, db, monkeypatch):
        # Both .HK and .TW have data; HK must win because it comes first.
        monkeypatch.setattr(pf, "fetch_ohlcv", self._fake_yahoo({"1810.HK", "1810.TW"}))
        result = resolve_and_ingest(db, "1810")
        assert result.ticker == "1810.HK"

    def test_digit_ticker_falls_through_to_tw(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", self._fake_yahoo({"2330.TW"}))
        result = resolve_and_ingest(db, "2330")
        assert result.ok
        assert result.ticker == "2330.TW"

    def test_alpha_ticker_falls_back_to_london(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", self._fake_yahoo({"LLOY.L"}))
        result = resolve_and_ingest(db, "LLOY")
        assert result.ok
        assert result.ticker == "LLOY.L"

    def test_us_ticker_does_not_trigger_fallback(self, db, monkeypatch):
        # AAPL has bare data; no suffix should be appended.
        monkeypatch.setattr(pf, "fetch_ohlcv", self._fake_yahoo({"AAPL"}))
        result = resolve_and_ingest(db, "AAPL")
        assert result.ok
        assert result.ticker == "AAPL"

    def test_qualified_ticker_no_fallback(self, db, monkeypatch):
        # User already typed ".HK" — we must not append a second suffix.
        monkeypatch.setattr(pf, "fetch_ohlcv", self._fake_yahoo(set()))
        result = resolve_and_ingest(db, "9999.HK")
        assert result.ok is False
        # Error message should not mention a list of suffixes since none were tried.
        assert "tried" not in result.message

    def test_all_suffixes_fail_returns_error_listing_tried(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", self._fake_yahoo(set()))
        result = resolve_and_ingest(db, "9999")
        assert result.ok is False
        assert "tried" in result.message
        assert ".HK" in result.message

    def test_index_ticker_no_fallback(self, db, monkeypatch):
        # ^GSPC exists bare; no suffix should ever be tried.
        monkeypatch.setattr(pf, "fetch_ohlcv", self._fake_yahoo({"^GSPC"}))
        result = resolve_and_ingest(db, "^gspc")
        assert result.ok
        assert result.ticker == "^GSPC"

    def test_crypto_pair_no_fallback(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", self._fake_yahoo({"BTC-USD"}))
        result = resolve_and_ingest(db, "btc-usd")
        assert result.ok
        assert result.ticker == "BTC-USD"


class TestCompanyNameStorage:
    def test_company_name_is_persisted(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", lambda t, period="2y": _synthetic_ohlcv(180))
        # Patch the name fetcher on the resolver module directly.
        import volscope.data.ticker_resolver as tr

        monkeypatch.setattr(tr, "_fetch_company_name", lambda t: "Palantir Technologies")
        result = resolve_and_ingest(db, "PLTR")
        assert result.ok
        assert db.get_company_name("PLTR") == "Palantir Technologies"

    def test_company_name_none_is_fine(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", lambda t, period="2y": _synthetic_ohlcv(180))
        import volscope.data.ticker_resolver as tr

        monkeypatch.setattr(tr, "_fetch_company_name", lambda t: None)
        result = resolve_and_ingest(db, "XYZ")
        assert result.ok
        assert db.get_company_name("XYZ") is None
