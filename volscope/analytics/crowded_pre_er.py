"""
Pre-earnings crowded-score percentile.

The bare ``crowded_score`` is a 0..100 number derived from same-day
flow signals (PCR, OI, vol, IV-HV spread). For an earnings event we
want one extra dimension: *how this ticker's pre-ER crowding compares
to its OWN historical pre-ER crowding*. A score of 76 might be calm
for one ticker and a once-a-year extreme for another.

We snapshot the crowded score on each session inside the 7-day window
before every historical earnings event, build a per-ticker
distribution, and return today's percentile within that distribution.

The window is `[ER-7d, ER-1d]` — captures the pre-print build-up
without bleeding into the post-print decay regime.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from volscope.analytics.crowded_trades import compute_crowded_score

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrowdedPreER:
    ticker:                  str
    score_today:             float       # 0..100
    historical_n_events:     int
    historical_median:       float
    historical_p75:          float
    historical_p90:          float
    percentile_today:        float       # 0..100, today's spot within history
    band:                    str          # "calm" | "normal" | "elevated" | "exceptional"


def _band_for_percentile(pct: float) -> str:
    if pct >= 90:
        return "exceptional"
    if pct >= 75:
        return "elevated"
    if pct >= 50:
        return "normal"
    return "calm"


def _percentile_of(value: float, series: pd.Series) -> float:
    """Compute the percentile rank of ``value`` within ``series``."""
    arr = series.dropna().to_numpy()
    if arr.size == 0:
        return 50.0
    return float((arr <= value).sum() / arr.size) * 100.0


def compute_pre_er_crowded(
    db,
    ticker: str,
    *,
    asof: Optional[date] = None,
    window_days: int = 7,
    min_events: int = 3,
) -> Optional[CrowdedPreER]:
    """End-to-end: pulls history + earnings and returns the dataclass.

    Returns ``None`` when fewer than ``min_events`` historical earnings
    are available, OR when there is no usable crowded score today.
    """
    asof = asof or date.today()

    try:
        hist = db.get_ticker_history(ticker)
    except Exception:
        return None
    if hist is None or hist.empty or "date" not in hist.columns:
        return None
    hist = hist.copy()
    hist["date"] = pd.to_datetime(hist["date"]).dt.date

    # Today's crowded score — uses the latest row + recent context
    today_row = hist.iloc[-1]
    if hist.shape[0] < 20:
        return None
    today_score = compute_crowded_score(today_row, hist)
    if today_score is None or math.isnan(today_score):
        return None

    # Historical pre-ER snapshots
    try:
        er_df = db.con.execute(
            """
            SELECT earnings_date FROM earnings
            WHERE ticker = ? AND earnings_date < ?
            ORDER BY earnings_date DESC LIMIT 12
            """,
            [ticker, asof],
        ).fetchdf()
    except Exception:
        er_df = pd.DataFrame()

    samples: list[float] = []
    if er_df is not None and not er_df.empty:
        for er_d in pd.to_datetime(er_df["earnings_date"]).dt.date:
            window_start = er_d - timedelta(days=window_days)
            window_end = er_d - timedelta(days=1)
            window_rows = hist[(hist["date"] >= window_start)
                                & (hist["date"] <= window_end)]
            for _, row in window_rows.iterrows():
                # Score uses the historical-frame UP TO that day to
                # avoid look-ahead bias in the z-scores
                frame = hist[hist["date"] <= row["date"]].tail(60)
                if frame.shape[0] < 20:
                    continue
                try:
                    s = compute_crowded_score(row, frame)
                    if s is not None and not math.isnan(float(s)):
                        samples.append(float(s))
                except Exception as exc:
                    log.debug("%s pre-ER sample skip: %s", ticker, exc)
                    continue

    if len(samples) < min_events:
        return None

    series = pd.Series(samples)
    median = float(series.median())
    p75 = float(series.quantile(0.75))
    p90 = float(series.quantile(0.90))
    pct_today = _percentile_of(float(today_score), series)
    return CrowdedPreER(
        ticker=ticker,
        score_today=float(today_score),
        historical_n_events=int(series.size),
        historical_median=median,
        historical_p75=p75,
        historical_p90=p90,
        percentile_today=pct_today,
        band=_band_for_percentile(pct_today),
    )
