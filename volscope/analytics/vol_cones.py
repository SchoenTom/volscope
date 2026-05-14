"""
Vol Cones — Bloomberg-style realized-vol percentile bands across windows.

The Vol Cone (VCA on Bloomberg, "volatility cone" in academic literature
since Burghardt & Lane 1990) plots, for each of several rolling-window
sizes (typically 10/20/30/60/90/180/252d), the historical distribution
of realized vol observed in that ticker. The trader then overlays the
*current* realized vol at each window. If today's 30d realized vol sits
in the 90th percentile of all historical 30d realized vol values, the
ticker is currently exhibiting unusually high recent realized vol —
useful context for vol traders deciding whether IV is rich or cheap.

Why hedge-fund-grade: this is one of the first lookups a Bloomberg vol
trader does each morning. Without it, you're staring at "VIX = 14"
without context. With it, you immediately see whether 14 is the 5th or
95th percentile of recent SPY realized vol — the latter is rich, the
former is cheap.

This module is pure analytics — no DB writes, no UI imports.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ── Default windows ──────────────────────────────────────────────────────

# Standard hedge-fund cone windows. The trader can override.
DEFAULT_WINDOWS: tuple[int, ...] = (10, 20, 30, 60, 90, 180, 252)

# Percentile bands surfaced on the chart. 5th/25th/50th/75th/95th covers
# the visual "cone" silhouette without being noisy.
DEFAULT_PERCENTILES: tuple[int, ...] = (5, 25, 50, 75, 95)

# Trading days per year for annualisation.
_TRADING_DAYS = 252.0


# ── Output types ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VolConePoint:
    """One window's percentile statistics + current value."""
    window:        int                # trading days, e.g. 30
    current_vol:   Optional[float]    # most-recent realized vol (annualised %)
    current_perc: Optional[float]     # 0..100, where current sits in history
    percentiles:   dict[int, float]   # {5: x, 25: y, 50: z, 75: a, 95: b}
    n_observations: int               # number of valid rolling-vol points used


@dataclass(frozen=True)
class VolCone:
    """All windows for a single ticker."""
    ticker:  str
    points:  tuple[VolConePoint, ...]
    summary: str                      # 1-line trader-facing read


# ── Core math ────────────────────────────────────────────────────────────

def _rolling_realized_vol(
    log_returns: pd.Series,
    window:      int,
) -> pd.Series:
    """Annualised close-to-close realized vol over a rolling window.

    Standard CC estimator: σ_ann = stddev(returns) × √252 × 100 (in %).
    Uses ddof=1 (sample stddev) since we have a finite sample.
    """
    if window <= 1 or len(log_returns) < window:
        return pd.Series(dtype=float)
    return log_returns.rolling(window=window).std(ddof=1) * math.sqrt(_TRADING_DAYS) * 100.0


def _percentile_of(value: float, distribution: pd.Series) -> Optional[float]:
    """Where in `distribution` does `value` sit, in 0..100? Midpoint method."""
    if distribution.empty or value is None or not np.isfinite(value):
        return None
    arr = distribution.dropna().to_numpy()
    if arr.size == 0:
        return None
    below = float(np.sum(arr < value))
    equal = float(np.sum(arr == value))
    return (below + 0.5 * equal) / arr.size * 100.0


def compute_vol_cone(
    spot_history: pd.Series,
    windows:      tuple[int, ...] = DEFAULT_WINDOWS,
    percentiles:  tuple[int, ...] = DEFAULT_PERCENTILES,
    ticker:       str = "X",
) -> VolCone:
    """Build the cone for a single ticker.

    Parameters
    ----------
    spot_history : pd.Series
        Indexed by date, values are close prices. The function computes
        log-returns internally.
    windows : tuple[int, ...]
        Rolling-window sizes in trading days.
    percentiles : tuple[int, ...]
        Percentile lines to surface (e.g. 5/25/50/75/95).
    ticker : str
        Ticker symbol for display.

    Returns
    -------
    VolCone
        Always valid — empty windows produce points with n_observations=0
        and None current_vol.
    """
    if spot_history is None or spot_history.empty:
        return VolCone(
            ticker=ticker,
            points=tuple(_empty_point(w, percentiles) for w in windows),
            summary="No price history.",
        )

    spot = pd.Series(spot_history).astype(float)
    spot = spot.replace([np.inf, -np.inf], np.nan).dropna()
    if len(spot) < 5:
        return VolCone(
            ticker=ticker,
            points=tuple(_empty_point(w, percentiles) for w in windows),
            summary=f"Only {len(spot)} price points — need ≥ 5.",
        )
    log_ret = np.log(spot / spot.shift(1)).dropna()

    points: list[VolConePoint] = []
    for w in windows:
        rv = _rolling_realized_vol(log_ret, w).dropna()
        if rv.empty:
            points.append(_empty_point(w, percentiles))
            continue
        current = float(rv.iloc[-1])
        # Percentile context — exclude the latest point so we don't measure
        # against itself (saves the trader from "current at 50th by definition").
        history = rv.iloc[:-1] if len(rv) > 1 else rv
        cur_perc = _percentile_of(current, history)
        pcts = {
            int(p): float(np.percentile(rv, p))
            for p in percentiles
        }
        points.append(VolConePoint(
            window=w,
            current_vol=round(current, 2) if math.isfinite(current) else None,
            current_perc=round(cur_perc, 1) if cur_perc is not None else None,
            percentiles={p: round(v, 2) for p, v in pcts.items()},
            n_observations=int(len(rv)),
        ))

    return VolCone(
        ticker=ticker,
        points=tuple(points),
        summary=_summarise(points),
    )


def _empty_point(window: int, percentiles: tuple[int, ...]) -> VolConePoint:
    return VolConePoint(
        window=window,
        current_vol=None,
        current_perc=None,
        percentiles={int(p): 0.0 for p in percentiles},
        n_observations=0,
    )


def _summarise(points: list[VolConePoint]) -> str:
    """One-liner of where the trader is on the cone right now."""
    valid = [p for p in points if p.current_perc is not None]
    if not valid:
        return "Cone unavailable — insufficient history."
    above_75 = sum(1 for p in valid if p.current_perc >= 75)
    below_25 = sum(1 for p in valid if p.current_perc <= 25)
    if above_75 >= len(valid) * 0.6:
        return f"Realized vol elevated across {above_75}/{len(valid)} windows — IV may have room to fall."
    if below_25 >= len(valid) * 0.6:
        return f"Realized vol depressed across {below_25}/{len(valid)} windows — IV may be set to expand."
    return "Realized vol within normal bounds across windows."


# ── Display helper (for direct use in Streamlit) ─────────────────────────

def cone_to_dataframe(cone: VolCone) -> pd.DataFrame:
    """Render a cone as a long-format DataFrame for plotting.

    Columns:
        window | percentile | vol | is_current
    Where is_current=True rows have percentile=None and vol=current_vol.
    """
    rows = []
    for p in cone.points:
        for pct, v in p.percentiles.items():
            rows.append({"window": p.window, "percentile": pct,
                         "vol": v, "is_current": False})
        if p.current_vol is not None:
            rows.append({"window": p.window, "percentile": None,
                         "vol": p.current_vol, "is_current": True})
    return pd.DataFrame(rows)
