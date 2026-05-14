"""Crowded-trade composite score."""
from __future__ import annotations

import numpy as np
import pandas as pd

from volscope.utils.safe import is_missing, safe_num


def _z(value: float | None, series: pd.Series) -> float:
    if is_missing(value):
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    s = pd.Series(series).dropna()
    if s.empty:
        return 0.0
    mean = float(s.mean())
    std = float(s.std(ddof=1)) if len(s) > 1 else 0.0
    if std == 0.0:
        return 0.0
    return float((v - mean) / std)


def _z_to_score(z: float) -> float:
    """Map signed z-score to 0-100 using a smooth clip at ±3σ."""
    clipped = max(-3.0, min(3.0, z))
    return float((clipped + 3.0) / 6.0 * 100.0)


def compute_crowded_score(row: pd.Series, historical: pd.DataFrame) -> float:
    """
    Composite crowding score, 0-100, built from four equal-weight components:

        1. Put/Call ratio z-score vs 20-day history
        2. Total Open Interest vs 20-day average
        3. Total option volume (calls + puts) vs 20-day average
        4. IV-HV spread z-score vs full history

    Each component's z-score is clipped to ±3σ and mapped linearly into a
    [0, 100] band, then the four are averaged. This produces an interpretable
    scale where:

        score == 50   → every component is at its own mean (pure neutral)
        score > 50    → positioning is above average on net
        score < 50    → positioning is below average on net
        score == 100  → all four components are three standard deviations hot
        score == 0    → all four components are three standard deviations cold

    The UI maps this to four honest bands:
        <25  calm       · positioning well below average
        25-60  normal   · positioning near the long-term mean
        60-80  elevated · above-average positioning, watch for reversal
        >80  crowded    · extreme consensus, high reversal / squeeze risk

    Note that 62 ≈ z-score 0.7 on a single component, or a blend — it is
    *mildly* elevated, not a genuine crowded trade. SPY rarely crosses 70
    outside of macro stress events.
    """
    if historical is None or historical.empty:
        return 50.0

    pc = row.get("put_call_ratio")
    oi = row.get("total_open_interest")
    call_vol = safe_num(row.get("total_call_volume"), default=0.0)
    put_vol = safe_num(row.get("total_put_volume"), default=0.0)
    vol_total = call_vol + put_vol
    iv = row.get("iv_30d")
    hv = row.get("hv_20d")
    spread: float | None
    if is_missing(iv) or is_missing(hv):
        spread = None
    else:
        spread = float(iv) - float(hv)

    hist20 = historical.tail(20)
    pc_hist = hist20.get("put_call_ratio", pd.Series(dtype=float))
    oi_hist = hist20.get("total_open_interest", pd.Series(dtype=float))
    vol_hist = (
        hist20.get("total_call_volume", pd.Series(dtype=float)).fillna(0)
        + hist20.get("total_put_volume", pd.Series(dtype=float)).fillna(0)
    )
    spread_hist = (
        historical.get("iv_30d", pd.Series(dtype=float))
        - historical.get("hv_20d", pd.Series(dtype=float))
    )

    components = [
        _z_to_score(_z(pc, pc_hist)),
        _z_to_score(_z(oi, oi_hist)),
        _z_to_score(_z(vol_total, vol_hist)),
        _z_to_score(_z(spread, spread_hist)),
    ]
    return float(sum(components) / len(components))
