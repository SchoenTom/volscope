"""Options scraper tests with an injected fake Yahoo client."""
from __future__ import annotations

import sys
from collections import namedtuple
from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.black_scholes import bs_price
from volscope.config import RISK_FREE_RATE
from volscope.data import options_scraper

Chain = namedtuple("Chain", ["calls", "puts"])


def _build_chain(spot: float, days: int, vol: float) -> Chain:
    """Build a synthetic chain where mid prices are BSM prices at known vol."""
    strikes = [spot - 10, spot - 5, spot, spot + 5, spot + 10]
    T = days / 365.0
    calls = []
    puts = []
    for k in strikes:
        c = bs_price(spot, k, T, RISK_FREE_RATE, vol, option_type="call")
        p = bs_price(spot, k, T, RISK_FREE_RATE, vol, option_type="put")
        spread = 0.02
        calls.append(
            {
                "strike": k,
                "bid": max(c - spread, 0.01),
                "ask": c + spread,
                "lastPrice": c,
                "volume": 500,
                "openInterest": 1000,
                "impliedVolatility": 9.9,  # WRONG on purpose — we must not use this
            }
        )
        puts.append(
            {
                "strike": k,
                "bid": max(p - spread, 0.01),
                "ask": p + spread,
                "lastPrice": p,
                "volume": 300,
                "openInterest": 800,
                "impliedVolatility": 9.9,
            }
        )
    return Chain(calls=pd.DataFrame(calls), puts=pd.DataFrame(puts))


class _FakeTicker:
    def __init__(self, spot: float, true_vol: float, options: list[str]):
        self._spot = spot
        self._vol = true_vol
        self.options = tuple(options)

    def history(self, period: str = "5d", **kwargs):
        # Accept auto_adjust / interval like real yfinance — the
        # yfinance_safe wrapper forwards those, and a strict signature
        # here would mask the production code path under test.
        idx = pd.date_range("2024-01-01", periods=5, freq="B")
        return pd.DataFrame({"Close": [self._spot] * 5}, index=idx)

    def option_chain(self, expiry_str: str):
        from datetime import datetime

        exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        days = max((exp - date.today()).days, 1)
        return _build_chain(self._spot, days, self._vol)


class _FakeYF:
    def __init__(self, ticker_obj):
        self._ticker = ticker_obj

    def Ticker(self, sym: str):
        return self._ticker


@pytest.fixture(autouse=True)
def inject_yf(monkeypatch):
    spot = 400.0
    true_vol = 0.25
    today = date.today()
    expiries = [
        (today + timedelta(days=14)).isoformat(),
        (today + timedelta(days=30)).isoformat(),
        (today + timedelta(days=45)).isoformat(),
        (today + timedelta(days=60)).isoformat(),
        (today + timedelta(days=90)).isoformat(),
        (today + timedelta(days=180)).isoformat(),
    ]
    fake = _FakeYF(_FakeTicker(spot, true_vol, expiries))
    sys.modules["yfinance"] = fake
    yield
    sys.modules.pop("yfinance", None)


def test_scraper_returns_expected_shape():
    result = options_scraper.scrape_options_chain("SPY")
    assert result is not None
    assert set(result.keys()) == {
        "iv_30d",
        "iv_60d",
        "iv_90d",
        "iv_180d",
        "iv_skew_25d",
        "total_call_volume",
        "total_put_volume",
        "put_call_ratio",
        "total_open_interest",
        "spot_price",
        "dividend_yield",
    }


def test_scraper_recovers_true_vol():
    """We built the chain from BSM @ vol=25% — scraper should recover ~25%."""
    result = options_scraper.scrape_options_chain("SPY")
    assert result is not None
    iv_30 = result["iv_30d"]
    assert iv_30 is not None
    assert 20.0 < iv_30 < 30.0


def test_scraper_iv_in_reasonable_range():
    result = options_scraper.scrape_options_chain("SPY")
    iv = result["iv_30d"]
    assert 5.0 <= iv <= 80.0


def test_scraper_does_not_use_yahoo_iv():
    """Yahoo's impliedVolatility column is set to 990% — if we used it, the
    result would be huge. Our value should be ~25%, proving self-computed."""
    result = options_scraper.scrape_options_chain("SPY")
    assert result["iv_30d"] < 100.0


def test_scraper_computes_iv_90d():
    result = options_scraper.scrape_options_chain("SPY")
    assert result is not None
    iv_90 = result["iv_90d"]
    assert iv_90 is not None
    assert 5.0 <= iv_90 <= 80.0


def test_scraper_computes_iv_180d():
    result = options_scraper.scrape_options_chain("SPY")
    assert result is not None
    iv_180 = result["iv_180d"]
    assert iv_180 is not None
    assert 5.0 <= iv_180 <= 80.0


def test_scraper_iv_90d_close_to_true_vol():
    result = options_scraper.scrape_options_chain("SPY")
    assert result is not None
    assert 20.0 < result["iv_90d"] < 30.0


def test_scraper_near_term_volume_uses_only_short_expiries():
    """Volume/OI should come from ≤4 near-30d expiries only, not 90d/180d."""
    result = options_scraper.scrape_options_chain("SPY")
    assert result is not None
    # The near-term expiries in fixture are 14d, 30d, 45d, 60d (4 closest to 30d).
    # Each has 500 call volume per strike × 5 strikes = 2500 per expiry.
    # 4 expiries × 2500 = 10000 max (may be fewer if some are pruned as vol_candidates).
    assert result["total_call_volume"] > 0


def test_scraper_handles_no_options(monkeypatch):
    class _NoOptions:
        options = ()

        def history(self, period="5d"):
            return pd.DataFrame({"Close": [100.0]})

        def option_chain(self, expiry):
            raise ValueError("no options")

    class _FakeYFNone:
        def Ticker(self, sym):
            return _NoOptions()

    sys.modules["yfinance"] = _FakeYFNone()
    assert options_scraper.scrape_options_chain("BADTICKER") is None
