"""
Earnings calendar — next-N-days lookup across tracked tickers.

Composes ``db.get_upcoming_earnings`` per ticker into a sorted timeline,
ready for rendering on Command Center / Portfolio. Distinct from
``earnings_watch`` (which produces alert-style commentary): this is a
pure list view of "what's coming and when".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class EarningsEvent:
    """One upcoming earnings event for one ticker."""
    ticker:           str
    earnings_date:    date
    days_to_earnings: int


def upcoming_earnings(
    db,
    tickers:          list[str],
    horizon_days:     int = 14,
    today:            Optional[date] = None,
) -> list[EarningsEvent]:
    """Return upcoming earnings within the horizon, sorted by date.

    Parameters
    ----------
    db            : VolScopeDB instance.
    tickers       : Tickers to scan.
    horizon_days  : Only return earnings <= this many calendar days out.
    today         : Reference date (default: real today).
    """
    today = today or date.today()
    out: list[EarningsEvent] = []
    for ticker in tickers:
        try:
            df = db.get_upcoming_earnings(ticker, today)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        try:
            er_dt = pd.to_datetime(df.iloc[0]["earnings_date"]).date()
        except Exception:
            continue
        dte = (er_dt - today).days
        if dte < 0 or dte > horizon_days:
            continue
        out.append(EarningsEvent(
            ticker=ticker,
            earnings_date=er_dt,
            days_to_earnings=dte,
        ))
    out.sort(key=lambda e: e.days_to_earnings)
    return out


def severity_for_dte(dte: int) -> str:
    """Map days-to-earnings to a severity label for color routing."""
    if dte <= 0:
        return "alert"
    if dte <= 2:
        return "warn"
    if dte <= 7:
        return "watch"
    return "info"
