"""
Daily Delta — what changed today vs yesterday across tracked positions.

A small purpose-built analyzer for the Command Center "what changed
overnight" strip. Pure analytics — takes a history dict, returns a
ranked list of deltas with severity colors and 1-line headlines.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DailyDelta:
    """One ticker's day-over-day change snapshot.

    Attributes
    ----------
    ticker     : Ticker symbol.
    iv_today   : Latest iv_30d.
    iv_yesterday : Previous-row iv_30d.
    iv_change  : iv_today − iv_yesterday (vol points).
    perc_today : Latest iv_percentile.
    perc_change : iv_percentile change.
    color      : Suggested badge color (signed by direction + magnitude).
    headline   : 1-line trader-facing summary.
    """
    ticker:        str
    iv_today:      Optional[float]
    iv_yesterday:  Optional[float]
    iv_change:     Optional[float]
    perc_today:    Optional[float]
    perc_change:   Optional[float]
    color:         str
    headline:      str


# ── Configuration ───────────────────────────────────────────────────────

# Move thresholds — calibrated against typical daily IV moves on liquid
# US single names: 90% of days are < 2pp, < 5% are > 4pp.
_BIG_MOVE_PT = 4.0       # |Δiv| above this = significant
_NOTABLE_MOVE_PT = 2.0   # |Δiv| above this = mention


def compute_daily_delta(
    ticker:  str,
    history: pd.DataFrame,
) -> Optional[DailyDelta]:
    """Compute the day-over-day delta for one ticker.

    Returns None when there's < 2 days of history (no comparison
    baseline). The "yesterday" row is the row immediately before the
    latest by date — calendar gaps (weekends, holidays) are accepted as
    yesterday since for vol context any prior trading day works.
    """
    if history is None or history.empty or "date" not in history.columns:
        return None
    df = history.sort_values("date").reset_index(drop=True)
    if len(df) < 2:
        return None

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    iv_today = _safe_float(today.get("iv_30d"))
    iv_yest  = _safe_float(yesterday.get("iv_30d"))
    perc_today = _safe_float(today.get("iv_percentile"))
    perc_yest  = _safe_float(yesterday.get("iv_percentile"))

    iv_change = (iv_today - iv_yest) if (iv_today is not None and iv_yest is not None) else None
    perc_change = (perc_today - perc_yest) if (perc_today is not None and perc_yest is not None) else None

    color, headline = _color_and_headline(ticker, iv_today, iv_change, perc_today, perc_change)

    return DailyDelta(
        ticker=ticker,
        iv_today=iv_today,
        iv_yesterday=iv_yest,
        iv_change=iv_change,
        perc_today=perc_today,
        perc_change=perc_change,
        color=color,
        headline=headline,
    )


def _color_and_headline(
    ticker:      str,
    iv_today:    Optional[float],
    iv_change:   Optional[float],
    perc_today:  Optional[float],
    perc_change: Optional[float],
) -> tuple[str, str]:
    """Convert the deltas into a badge color + headline."""
    if iv_today is None:
        return ("#8a8f9e", "no IV data")
    if iv_change is None:
        return ("#8a8f9e", f"IV {iv_today:.1f}% (no Δ baseline)")

    abs_change = abs(iv_change)
    direction = "+" if iv_change >= 0 else ""
    if abs_change >= _BIG_MOVE_PT:
        # Big move: red if up (vol expansion = stress), green if down (cheap)
        color = "#ff4466" if iv_change > 0 else "#00d4aa"
        verb = "spiked" if iv_change > 0 else "crushed"
        return (color, f"{verb} {direction}{iv_change:.1f}pt → IV {iv_today:.1f}%")
    if abs_change >= _NOTABLE_MOVE_PT:
        color = "#ff9f43" if iv_change > 0 else "#7db4ff"
        return (color, f"Δ {direction}{iv_change:.1f}pt → IV {iv_today:.1f}%")
    # Quiet day
    return ("#8a8f9e", f"IV {iv_today:.1f}% · {direction}{iv_change:.1f}pt")


def rank_daily_deltas(
    histories: dict[str, pd.DataFrame],
    n:         int = 5,
) -> list[DailyDelta]:
    """Compute deltas for each ticker, return top-N by absolute IV change."""
    out: list[DailyDelta] = []
    for ticker, hist in histories.items():
        delta = compute_daily_delta(ticker, hist)
        if delta is not None and delta.iv_change is not None:
            out.append(delta)
    out.sort(key=lambda d: abs(d.iv_change or 0), reverse=True)
    return out[:n]


# ── Helpers ─────────────────────────────────────────────────────────────

def _safe_float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None
