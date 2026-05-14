"""
IV Rank, IV Percentile, Vol Regime, IV-HV Spread Analysis.

Functions:
    iv_rank(current, history) -> float                         # 0-100
    iv_percentile(current, history) -> float                   # 0-100
    vol_regime(current, history, z_thresh=1.5) -> dict
    iv_hv_spread(iv, hv, spread_history=None) -> dict
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np


def _clean(history: Iterable[float]) -> np.ndarray:
    arr = np.asarray(list(history), dtype=float)
    return arr[np.isfinite(arr)]


def iv_rank(current: float, history: Iterable[float]) -> float:
    """Where current sits in the min-max range, 0-100. 50.0 if flat history."""
    if current is None or not np.isfinite(current):
        return 50.0
    arr = _clean(history)
    if arr.size == 0:
        return 50.0
    lo, hi = float(arr.min()), float(arr.max())
    if hi == lo:
        return 50.0
    rank = (current - lo) / (hi - lo) * 100.0
    return float(max(0.0, min(100.0, rank)))


def iv_percentile(current: float, history: Iterable[float]) -> float:
    """Percentage of history below current, 0-100, midpoint-method ties.

    Pure ``<`` comparison breaks during dead markets: if IV has been
    exactly current for many days, percentile collapses to 0 even though
    the current value is at the median of its own recent history.
    Midpoint method (``count<x + 0.5 * count==x``) is the standard fix
    used in scipy.stats.percentileofscore(kind='mean').
    """
    if current is None or not np.isfinite(current):
        return 50.0
    arr = _clean(history)
    if arr.size == 0:
        return 50.0
    below = np.sum(arr < current)
    equal = np.sum(arr == current)
    return float((below + 0.5 * equal) / arr.size * 100.0)


def vol_regime(current: float, history: Iterable[float], z_thresh: float = 1.5) -> dict:
    """Classify as HIGH / LOW / NORMAL via z-score vs history."""
    arr = _clean(history)
    if arr.size == 0 or not np.isfinite(current):
        return {"regime": "NORMAL", "z_score": 0.0, "mean": 0.0, "std": 0.0}
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    if std == 0.0:
        return {"regime": "NORMAL", "z_score": 0.0, "mean": mean, "std": 0.0}
    z = (current - mean) / std
    if z > z_thresh:
        regime = "HIGH"
    elif z < -z_thresh:
        regime = "LOW"
    else:
        regime = "NORMAL"
    return {"regime": regime, "z_score": float(z), "mean": mean, "std": std}


def iv_hv_spread(iv: float, hv: float, spread_history: Optional[Iterable[float]] = None) -> dict:
    """
    Compare IV to realized (HV).

    RICH   if spread > 0 and ratio > 1.1
    CHEAP  if spread < 0 and ratio < 0.9
    NEUTRAL otherwise
    """
    if iv is None or hv is None or not np.isfinite(iv) or not np.isfinite(hv) or hv <= 0:
        return {"spread": None, "ratio": None, "signal": "NEUTRAL", "z_score": None}
    spread = float(iv - hv)
    ratio = float(iv / hv)
    if spread > 0 and ratio > 1.1:
        signal = "RICH"
    elif spread < 0 and ratio < 0.9:
        signal = "CHEAP"
    else:
        signal = "NEUTRAL"

    z_score: Optional[float] = None
    if spread_history is not None:
        arr = _clean(spread_history)
        if arr.size > 1:
            mean = float(np.mean(arr))
            std = float(np.std(arr, ddof=1))
            if std > 0:
                z_score = float((spread - mean) / std)

    return {"spread": spread, "ratio": ratio, "signal": signal, "z_score": z_score}
