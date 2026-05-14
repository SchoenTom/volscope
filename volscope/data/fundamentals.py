"""
Per-ticker fundamentals: trailing-twelve-month dividend yield and sector.

Both are fetched best-effort from yfinance with safe fallbacks. The TTM yield
is computed from the actual `Ticker.dividends` series rather than the slow and
flaky `Ticker.info["dividendYield"]` field.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from volscope.data.ticker_universe import sector_of

log = logging.getLogger(__name__)


def fetch_ttm_dividend_yield(yf_ticker, current_price: float) -> float:
    """
    Trailing 12-month dividend yield as a fraction (e.g., 0.013 for 1.3%).
    Returns 0.0 on any failure or implausible value.
    """
    if current_price is None or current_price <= 0:
        return 0.0
    try:
        divs = yf_ticker.dividends
    except Exception as exc:
        log.debug("dividends fetch failed: %s", exc)
        return 0.0
    if divs is None or len(divs) == 0:
        return 0.0

    try:
        if isinstance(divs.index, pd.DatetimeIndex):
            tz = divs.index.tz
            cutoff = pd.Timestamp.now(tz=tz) - pd.Timedelta(days=365)
            ttm = divs[divs.index >= cutoff]
        else:
            ttm = divs.tail(4)
    except Exception:
        ttm = divs.tail(4)

    if len(ttm) == 0:
        return 0.0
    _s = ttm.sum()
    annual = float(_s.iloc[0]) if isinstance(_s, pd.Series) else float(_s)
    if annual <= 0:
        return 0.0
    yield_ = annual / current_price
    if not (0.0 <= yield_ < 0.25):
        return 0.0
    return yield_


def fetch_sector(ticker: str, yf_ticker=None) -> Optional[str]:
    """
    Sector lookup with hybrid resolution: hardcoded universe first, then
    yfinance.info as a fallback. Returns None if both fail.
    """
    s = sector_of(ticker)
    if s is not None:
        return s
    if yf_ticker is None:
        return None
    try:
        info = yf_ticker.info or {}
    except Exception:
        return None
    sector = info.get("sector")
    return sector if isinstance(sector, str) else None
