"""Earnings calendar fetcher using yfinance.Ticker.earnings_dates."""
from __future__ import annotations

import logging
from datetime import date
from typing import List

import pandas as pd

log = logging.getLogger(__name__)


def fetch_upcoming_earnings(yf_ticker, max_dates: int = 4) -> List[date]:
    """
    Return up to `max_dates` upcoming earnings dates for the ticker (sorted
    ascending), best-effort. Returns an empty list on any failure.
    """
    try:
        df = yf_ticker.earnings_dates
    except Exception as exc:
        log.debug("earnings_dates fetch failed: %s", exc)
        return []

    if df is None or df.empty:
        return []

    try:
        idx = df.index
        if isinstance(idx, pd.DatetimeIndex):
            tz = idx.tz
            today_ts = pd.Timestamp.now(tz=tz) if tz else pd.Timestamp.today()
            mask = idx >= today_ts
            upcoming = idx[mask]
        else:
            return []
    except Exception:
        return []

    out: List[date] = []
    for ts in sorted(upcoming)[:max_dates]:
        try:
            out.append(ts.date())
        except Exception:
            continue
    return out
