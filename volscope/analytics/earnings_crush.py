"""
Earnings IV crush estimator.

For each historical earnings event in the DB, measure iv_30d roughly 5
trading days before vs 1 trading day after, then compute the crush % as:
    crush = (iv_after - iv_before) / iv_before * 100

Negative crush % = IV dropped (typical post-earnings). Positive = IV rose.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class CrushEstimate:
    avg_crush_pct: Optional[float]   # e.g. -35.2 means IV dropped ~35%
    min_crush_pct: Optional[float]   # worst (most negative = biggest drop)
    max_crush_pct: Optional[float]   # best (least negative = smallest drop)
    n_events: int
    next_earnings_date: Optional[date]
    days_to_earnings: Optional[int]


def _find_nearest_iv(history: pd.DataFrame, target_date: date, window: int = 5) -> Optional[float]:
    """
    Find the iv_30d closest to `target_date` within ±`window` trading rows.
    """
    if history.empty or "iv_30d" not in history.columns:
        return None
    h = history.copy()
    if not pd.api.types.is_datetime64_any_dtype(h["date"]):
        h["date"] = pd.to_datetime(h["date"])
    h = h.dropna(subset=["iv_30d"]).sort_values("date")
    target_ts = pd.Timestamp(target_date)
    window_start = target_ts - pd.Timedelta(days=window * 2)
    window_end   = target_ts + pd.Timedelta(days=window * 2)
    nearby = h[(h["date"] >= window_start) & (h["date"] <= window_end)]
    if nearby.empty:
        return None
    nearby = nearby.copy()
    nearby["dist"] = (nearby["date"] - target_ts).abs()
    best = nearby.nsmallest(1, "dist")
    val = best["iv_30d"].iloc[0]
    return None if pd.isna(val) else float(val)


def compute_crush_estimate(db, ticker: str) -> CrushEstimate:
    """
    Compute IV crush statistics from the last 4 earnings events in the DB.

    Requires:
      - `db.get_ticker_history(ticker)` returning daily_vol rows with iv_30d
      - `db.get_upcoming_earnings(ticker, from_date)` for past + future earnings

    Returns a CrushEstimate with avg/min/max crush and next earnings info.
    """
    from datetime import date as _date
    today = _date.today()

    try:
        history = db.get_ticker_history(ticker)
    except Exception:
        return CrushEstimate(None, None, None, 0, None, None)

    # Get all past earnings events (most recent 4)
    try:
        all_earnings = db.con.execute(
            "SELECT * FROM earnings WHERE ticker = ? ORDER BY earnings_date DESC LIMIT 8",
            [ticker],
        ).fetchdf()
    except Exception:
        all_earnings = pd.DataFrame()

    # Separate past vs upcoming
    past_events: list[date] = []
    next_er_date: Optional[date] = None
    days_to_er: Optional[int] = None

    if not all_earnings.empty:
        for _, row in all_earnings.iterrows():
            er_date_raw = row["earnings_date"]
            try:
                er_date = pd.Timestamp(er_date_raw).date()
            except Exception:
                continue
            if er_date < today:
                past_events.append(er_date)
            elif next_er_date is None or er_date < next_er_date:
                next_er_date = er_date

    if next_er_date is not None:
        days_to_er = (next_er_date - today).days

    # Compute crush for last 4 past events
    crush_values: list[float] = []
    for er_date in past_events[:4]:
        pre_date  = er_date - timedelta(days=5)
        post_date = er_date + timedelta(days=2)
        iv_pre  = _find_nearest_iv(history, pre_date,  window=5)
        iv_post = _find_nearest_iv(history, post_date, window=5)
        if iv_pre is None or iv_post is None or iv_pre <= 0:
            continue
        crush = (iv_post - iv_pre) / iv_pre * 100.0
        if not math.isnan(crush):
            crush_values.append(crush)

    if not crush_values:
        return CrushEstimate(None, None, None, 0, next_er_date, days_to_er)

    avg_crush = sum(crush_values) / len(crush_values)
    return CrushEstimate(
        avg_crush_pct=round(avg_crush, 1),
        min_crush_pct=round(min(crush_values), 1),
        max_crush_pct=round(max(crush_values), 1),
        n_events=len(crush_values),
        next_earnings_date=next_er_date,
        days_to_earnings=days_to_er,
    )


def crush_badge_html(est: CrushEstimate, mono_font: str = "JetBrains Mono, monospace") -> str:
    """
    Return a compact HTML string for showing crush info in a card or badge.

    Examples:
      ⚠ ER in 5d · avg −35%
      ⚠ ER tomorrow · avg −28%, range −15% to −45%
    """
    if est.days_to_earnings is None:
        return ""

    d = est.days_to_earnings
    if d < 0:
        return ""
    if d == 0:
        er_str = "ER today"
    elif d == 1:
        er_str = "ER tomorrow"
    else:
        er_str = f"ER in {d}d"

    crush_str = ""
    if est.avg_crush_pct is not None:
        sign = "+" if est.avg_crush_pct > 0 else ""
        crush_str = f" · avg {sign}{est.avg_crush_pct:.0f}%"
        if est.min_crush_pct is not None and est.max_crush_pct is not None:
            crush_str += f", range {est.min_crush_pct:.0f}% to {est.max_crush_pct:.0f}%"

    return (
        f'<span style="font-family:{mono_font};font-size:10px;font-weight:600;'
        f'color:#ff9f43;">⚠ {er_str}{crush_str}</span>'
    )
