"""OHLCV fetcher via yfinance. Returns empty DataFrame on error."""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

_EMPTY_COLS = ["Open", "High", "Low", "Close", "Volume"]


def fetch_ohlcv(ticker: str, period: str = "2y") -> pd.DataFrame:
    """
    Fetch OHLCV data for `ticker` over `period`. Always returns a DataFrame with
    columns Open/High/Low/Close/Volume, empty on failure.

    Uses the safe_history wrapper which enforces a 12-second wall-clock
    timeout — without it a slow Yahoo response can hang the caller
    indefinitely (yfinance 1.3 has no built-in timeout).
    """
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover - hard import failure
        log.error("yfinance import failed: %s", exc)
        return pd.DataFrame(columns=_EMPTY_COLS)

    from volscope.data.yfinance_safe import safe_history
    # auto_adjust=True folds splits and dividends into prices so close-to-close
    # log-returns do not contain fake ex-day jumps that would inflate HV.
    data = safe_history(yf.Ticker(ticker), period=period, auto_adjust=True)

    if data is None or data.empty:
        return pd.DataFrame(columns=_EMPTY_COLS)

    for col in _EMPTY_COLS:
        if col not in data.columns:
            return pd.DataFrame(columns=_EMPTY_COLS)

    return data[_EMPTY_COLS].dropna(how="all")


def fetch_spot_price(ticker: str) -> float | None:
    """Most recent close, or None."""
    df = fetch_ohlcv(ticker, period="5d")
    if df.empty:
        return None
    return float(df["Close"].iloc[-1])
