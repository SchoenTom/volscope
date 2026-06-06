"""
Canonical IV-percentile thresholds used everywhere in VolScope.

Phase 2 of the autonomous hardening marathon: the cross-page
classification inconsistency the operator flagged comes down to two
different threshold sets coexisting:

  - ``volscope.analytics.signal::_PERC_BUY_STRONG = 25``
  - ``volscope.analytics.strategy_recommender::_PERC_VERY_CHEAP = 20``

so a ticker with IVR = 22 would land on "BUY VOL / STRONG" via
``compute_signal`` (cheap) yet "CHEAP" (not VERY_CHEAP) via the
strategy recommender. Different label trees for what is conceptually
the same "how cheap is this IV?" question.

This module is the new single source of truth. Both downstream
classifiers import these constants instead of defining their own.

Convention
==========
Five bands, monotonically increasing in IV percentile:

    perc ≤ VERY_CHEAP        →   <  20      cheap-extreme  (long-vega aggressive)
    VERY_CHEAP < perc < CHEAP →  [20, 35)   cheap-lean
    CHEAP ≤ perc ≤ RICH       →  [35, 65]   neutral / fair-value
    RICH < perc < VERY_RICH   →  (65, 80]   rich-lean
    perc > VERY_RICH          →  > 80       rich-extreme  (short-vega aggressive)

These are the values the Discover treemap, Scope verdict, Heatmap
colourbar, and Pre-Trade strategy recommender all classify against.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Five-band canonical thresholds.
PERC_VERY_CHEAP: float = 20.0
PERC_CHEAP:      float = 35.0
PERC_RICH:       float = 65.0
PERC_VERY_RICH:  float = 80.0

# VRP (IV / HV) — "options pay > or < realized?".
VRP_BUY_STRONG:   float = 0.95
VRP_BUY_LEAN:     float = 1.00
VRP_RICH_LEAN:    float = 1.00
VRP_RICH_STRONG:  float = 1.05


def classify_perc(perc: float | None) -> str:
    """Return a canonical band label for ``perc``.

    Returns one of ``"VERY_CHEAP"``, ``"CHEAP"``, ``"NEUTRAL"``,
    ``"RICH"``, ``"VERY_RICH"``, or ``"NO_DATA"``.
    """
    if perc is None:
        return "NO_DATA"
    try:
        p = float(perc)
    except (TypeError, ValueError):
        return "NO_DATA"
    if p < PERC_VERY_CHEAP:
        return "VERY_CHEAP"
    if p < PERC_CHEAP:
        return "CHEAP"
    if p <= PERC_RICH:
        return "NEUTRAL"
    if p <= PERC_VERY_RICH:
        return "RICH"
    return "VERY_RICH"


# ── IV Rank / IV Percentile ────────────────────────────────────────
# Moved here from volscope/signals/factors.py during the IV-research
# refocus (the signals/ bot package was removed). These are pure-math
# IV-position helpers used by the core IV-robustness path.


def ivr(iv_series: pd.Series, window: int = 252) -> float:
    """
    IV Rank — current IV's position in its trailing 252-day range.

    Returns a percentage in [0, 100]. The MenthorQ 10-yr SPY study finds
    short-premium ROI improves dramatically when IVR > 30; peak when > 50.

    Returns NaN if the window has insufficient data or zero range.
    """
    s = iv_series.dropna().tail(window)
    if len(s) < 20:
        return float("nan")
    lo, hi = float(s.min()), float(s.max())
    if hi - lo < 1e-9:
        return float("nan")
    cur = float(s.iloc[-1])
    return float(np.clip((cur - lo) / (hi - lo) * 100.0, 0.0, 100.0))


def ivp(iv_series: pd.Series, window: int = 252) -> float:
    """
    IV Percentile — % of trailing days with IV below current.

    Slightly preferred to IVR in normal regimes (Castillo 2026) because
    it's robust to single-day spikes that compress IVR for the next year.
    """
    s = iv_series.dropna().tail(window)
    if len(s) < 20:
        return float("nan")
    cur = float(s.iloc[-1])
    return float((s < cur).sum() / len(s) * 100.0)
