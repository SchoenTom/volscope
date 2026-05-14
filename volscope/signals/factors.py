"""
Vol-state factor library — Phase 1 scaffold.

Each function takes a pandas Series (or a small DataFrame) and returns
a scalar in [0, 100] or a raw ratio. These are the *atomic* signals
the composite scorer (composite.py) blends with weights.

Sources cited in the masterplan:
- IVR/IVP definitions: tastytrade Market Measures + MenthorQ 10-yr SPY study
- IV/HV ratio (VRP proxy): Barclays Volatility Risk Premium white paper
  (+4.2 vol points avg, positive 86% of months)
- Term structure: front-month vs back-month IV; backwardation (negative)
  is the strongest single signal for spiking realised vol
- 25Δ risk reversal: call IV minus put IV — positive = call-rich

All factors are computed point-in-time. Look-ahead bias is the silent
killer of options backtests, so windows are RIGHT-aligned: the value
on date t uses only data <= t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


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


def iv_hv_ratio(iv_30d: float, hv_20d: float) -> float:
    """
    IV/HV ratio — direct VRP proxy.

    Ratio > 1 means options price in MORE volatility than has been
    realised. Bali et al. (2008): 85% of months show IV ≥ HV.

    Above 1.20 is "rich"; below 0.75 is "cheap."
    """
    if hv_20d <= 0 or pd.isna(hv_20d) or pd.isna(iv_30d):
        return float("nan")
    return float(iv_30d) / float(hv_20d)


def term_slope(iv_30d: float, iv_90d: float) -> float:
    """
    Term-structure slope — iv30/iv90 − 1.

    Negative = backwardation (front month richer than back month). This
    is the single strongest signal of an imminent vol spike: dealers are
    pricing near-term tail risk that doesn't extend out the curve.

    Block all new short-vol entries when slope < -0.05 (≥5% inverted).
    """
    if iv_90d <= 0 or pd.isna(iv_90d) or pd.isna(iv_30d):
        return float("nan")
    return float(iv_30d) / float(iv_90d) - 1.0


def skew_25d_rr(iv_25d_call: float, iv_25d_put: float) -> float:
    """
    25-delta risk reversal — call IV minus put IV.

    Normal equity markets have put-rich skew (negative RR). Positive RR
    (calls richer than puts) is unusual and often precedes a vol crush
    on the upside — useful as a filter, not a primary signal.
    """
    if pd.isna(iv_25d_call) or pd.isna(iv_25d_put):
        return float("nan")
    return float(iv_25d_call) - float(iv_25d_put)


def hv_momentum(hv_5d: float, hv_30d: float) -> float:
    """
    HV momentum — short-window realised vol vs longer window.

    Ratio > 1.5 → vol is accelerating; pause short premium until it
    stabilises (avoid being on the wrong side of a regime shift).
    Ratio < 0.7 → vol is collapsing; favour buy-vol entries.
    """
    if hv_30d <= 0 or pd.isna(hv_30d) or pd.isna(hv_5d):
        return float("nan")
    return float(hv_5d) / float(hv_30d)


def factor_vector(*, iv_30d: float, iv_90d: float, hv_5d: float,
                  hv_20d: float, hv_30d: float, iv_history_252d: pd.Series,
                  iv_25d_call: float = float("nan"),
                  iv_25d_put: float = float("nan")) -> dict[str, float]:
    """
    Compute the full factor vector for a single ticker on a single date.

    Returns a dict that composite.py consumes directly. Any factor that
    can't be computed (missing data) is NaN; the composite scorer treats
    NaN factors as 0-weight (graceful degradation, not a crash).
    """
    return {
        "ivr": ivr(iv_history_252d),
        "ivp": ivp(iv_history_252d),
        "iv_hv": iv_hv_ratio(iv_30d, hv_20d),
        "term": term_slope(iv_30d, iv_90d),
        "skew": skew_25d_rr(iv_25d_call, iv_25d_put),
        "hv_mom": hv_momentum(hv_5d, hv_30d),
    }
