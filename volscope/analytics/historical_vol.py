"""
Historical Volatility Estimators.

All functions take pandas Series of OHLC data and return annualized vol in percent
(e.g., 25.0 for 25%). Each returns a rolling pd.Series — the first (window-1)
values are NaN.

Estimators:
    hv_close_to_close(close, window, ann=252) -> pd.Series
    hv_parkinson(high, low, window, ann=252) -> pd.Series
    hv_garman_klass(open_, high, low, close, window, ann=252) -> pd.Series
    hv_yang_zhang(open_, high, low, close, window, ann=252) -> pd.Series
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def hv_close_to_close(close: pd.Series, window: int, ann: int = 252) -> pd.Series:
    """Classic log-return close-to-close vol, annualized, in percent."""
    log_ret = np.log(close / close.shift(1))
    vol = log_ret.rolling(window=window).std(ddof=1) * np.sqrt(ann) * 100.0
    return vol


def hv_parkinson(high: pd.Series, low: pd.Series, window: int, ann: int = 252) -> pd.Series:
    """Parkinson (1980) range-based estimator."""
    factor = 1.0 / (4.0 * np.log(2.0))
    log_hl_sq = np.log(high / low) ** 2
    var = log_hl_sq.rolling(window=window).mean() * factor
    return np.sqrt(var * ann) * 100.0


def hv_garman_klass(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int,
    ann: int = 252,
) -> pd.Series:
    """Garman-Klass (1980) OHLC estimator."""
    log_hl = np.log(high / low)
    log_co = np.log(close / open_)
    term = 0.5 * log_hl ** 2 - (2.0 * np.log(2.0) - 1.0) * log_co ** 2
    var = term.rolling(window=window).mean()
    # GK term can dip slightly negative when range is tight relative to drift —
    # clip to 0 so sqrt does not produce NaN on otherwise valid windows.
    var = var.clip(lower=0.0)
    return np.sqrt(var * ann) * 100.0


def hv_yang_zhang(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int,
    ann: int = 252,
) -> pd.Series:
    """Yang-Zhang (2000) — drift-independent, handles opening gaps."""
    # window < 2 makes the YZ weight k = 0.34/(1.34 + (n+1)/(n-1)) divide by
    # zero. The estimator is undefined for a 1-bar window; return NaN per the
    # analytics rule (never raise) so callers degrade gracefully.
    if window < 2:
        return pd.Series([float("nan")] * len(close), index=close.index)
    log_ho = np.log(high / open_)
    log_lo = np.log(low / open_)
    log_co = np.log(close / open_)
    log_oc_prev = np.log(open_ / close.shift(1))
    log_cc_prev = np.log(close / close.shift(1))

    # Rogers-Satchell component
    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
    rs_var = rs.rolling(window=window).mean()

    # Overnight (close-to-open) variance
    open_var = log_oc_prev.rolling(window=window).var(ddof=1)
    # Intraday (open-to-close) variance
    close_var = log_co.rolling(window=window).var(ddof=1)

    n = window
    k = 0.34 / (1.34 + (n + 1.0) / (n - 1.0))
    var = open_var + k * close_var + (1.0 - k) * rs_var
    var = var.clip(lower=0.0)
    return np.sqrt(var * ann) * 100.0
