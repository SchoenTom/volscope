"""Skew-adjusted Expected Move — asymmetric upside/downside bands.

Standard expected-move calculations (ATM straddle, ATM IV × √T)
collapse the put-skew that pre-earnings option markets carry. A
SNOW print-day chain typically shows:

    25-delta Put IV  ≈ 110 %
    25-delta Call IV ≈ 80 %
    25-delta Skew    = +30 vol-points (PUT-skew)

The naive symmetric Expected Move (±$22 on $144 spot) hides that
the market is pricing the downside ≈ 38 % wider than the upside.

This module computes:

    upside_pct   = spot × Call-IV  × √(DTE / 365)
    downside_pct = spot × Put-IV   × √(DTE / 365)
    skew_25d     = IV(25Δ Put)     − IV(25Δ Call)

Inspired by the conversation Tom captured (2026-05-15):

> "Skewness korrigiert den Expected Move asymmetrisch. Markt sieht
>  das Downside-Risk also deutlich größer."

Citations: Bali & Hovakimian (2009), "Volatility Spreads and Expected
Stock Returns". Also: Dennis & Mayhew (2002) on the 25-delta skew
as the canonical OTM-options sentiment measure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

__all__ = ["SkewAdjustedExpectedMove", "compute_skew_adjusted_em"]


@dataclass(frozen=True)
class SkewAdjustedExpectedMove:
    """Container for a single (ticker, expiry, asof) snapshot."""
    spot:           float
    dte_days:       int
    atm_iv:         Optional[float]   # ATM IV (forward, % annualised)
    put_iv_25d:     Optional[float]   # 25-delta Put IV
    call_iv_25d:    Optional[float]   # 25-delta Call IV
    skew_25d:       Optional[float]   # = put_iv_25d − call_iv_25d (vol points)
    upside_pct:     Optional[float]   # one-sigma upside move in %
    downside_pct:   Optional[float]   # one-sigma downside move in %
    em_symmetric_pct: Optional[float] # naive ATM ± move for reference
    em_dollar_up:   Optional[float]   # one-sigma upside in $
    em_dollar_down: Optional[float]   # one-sigma downside in $

    def asymmetry_ratio(self) -> Optional[float]:
        """downside / upside. >1 means market prices more downside vol."""
        if self.upside_pct is None or self.downside_pct is None:
            return None
        if self.upside_pct <= 0:
            return None
        return self.downside_pct / self.upside_pct

    def is_put_skewed(self) -> bool:
        return bool(self.skew_25d is not None and self.skew_25d > 0)


def _interp_iv_at_delta(
    df: pd.DataFrame, *, target_delta: float, option_right: str,
) -> Optional[float]:
    """Linearly interpolate IV at a target |delta| for one side of the chain.

    Parameters
    ----------
    df : DataFrame with columns ``delta`` (signed) and ``iv``.
        For calls delta ∈ (0, 1); for puts delta ∈ (-1, 0).
    target_delta : positive scalar, e.g. 0.25 for "25-delta".
    option_right : "call" or "put".
    """
    if df is None or df.empty or "delta" not in df.columns or "iv" not in df.columns:
        return None
    work = df.copy()
    work["abs_delta"] = work["delta"].abs()
    work = work.dropna(subset=["abs_delta", "iv"])
    work = work[(work["iv"] > 0) & (work["abs_delta"] > 0) & (work["abs_delta"] <= 1)]
    if work.empty:
        return None
    work = work.sort_values("abs_delta").reset_index(drop=True)

    # Find the two strikes that bracket target_delta and linearly interp.
    target = float(target_delta)
    if work["abs_delta"].iloc[0] >= target:
        # All deltas are deeper than target — extrapolate from the first
        # row (most-OTM available).
        return float(work["iv"].iloc[0])
    if work["abs_delta"].iloc[-1] <= target:
        # Target is deeper than anything in the chain — return ATM-side row.
        return float(work["iv"].iloc[-1])

    # Bracket
    upper_idx = int((work["abs_delta"] >= target).idxmax())
    if upper_idx == 0:
        return float(work["iv"].iloc[0])
    lower_idx = upper_idx - 1
    d_lo, d_hi = float(work["abs_delta"].iloc[lower_idx]), float(work["abs_delta"].iloc[upper_idx])
    iv_lo, iv_hi = float(work["iv"].iloc[lower_idx]), float(work["iv"].iloc[upper_idx])
    span = d_hi - d_lo
    if span <= 0:
        return iv_lo
    w = (target - d_lo) / span
    return iv_lo + w * (iv_hi - iv_lo)


def compute_skew_adjusted_em(
    chain_df: pd.DataFrame,
    *,
    spot: float,
    dte_days: int,
    target_delta: float = 0.25,
) -> Optional[SkewAdjustedExpectedMove]:
    """Compute the asymmetric Expected Move from a single-expiry chain.

    Parameters
    ----------
    chain_df : DataFrame with columns
        ``strike, option_right, iv, delta, bid, ask``
        for one expiry. ``option_right`` ∈ {"call", "put"} or {"C", "P"}.
    spot : current underlying price.
    dte_days : days to expiry (≥ 1).
    target_delta : default 0.25 — the canonical OTM marker.

    Returns
    -------
    SkewAdjustedExpectedMove, or None when the inputs are degenerate
    (spot ≤ 0, dte ≤ 0, no calls AND no puts with valid IV).
    """
    if spot is None or spot <= 0 or dte_days is None or dte_days <= 0:
        return None
    if chain_df is None or chain_df.empty:
        return None

    df = chain_df.copy()
    # Normalize option_right to lowercase string
    if "option_right" not in df.columns:
        return None
    df["option_right"] = (
        df["option_right"].astype(str).str.lower().str[0].map({"c": "call", "p": "put"})
    )
    df = df.dropna(subset=["option_right"])

    calls = df[df["option_right"] == "call"]
    puts  = df[df["option_right"] == "put"]

    call_iv_25 = _interp_iv_at_delta(calls, target_delta=target_delta, option_right="call")
    put_iv_25  = _interp_iv_at_delta(puts,  target_delta=target_delta, option_right="put")

    # ATM IV ≈ mean of nearest-strike call and put. Pick rows nearest spot.
    atm_iv: Optional[float] = None
    if "strike" in df.columns:
        df["dist"] = (df["strike"] - spot).abs()
        df_atm = df.sort_values("dist").head(4)
        ivs = df_atm["iv"].dropna()
        ivs = ivs[ivs > 0]
        if not ivs.empty:
            atm_iv = float(ivs.mean())

    sqrt_t = math.sqrt(max(1, dte_days) / 365.0)

    upside_pct: Optional[float] = None
    if call_iv_25 is not None:
        upside_pct = float(call_iv_25 * sqrt_t)
    downside_pct: Optional[float] = None
    if put_iv_25 is not None:
        downside_pct = float(put_iv_25 * sqrt_t)

    em_sym_pct: Optional[float] = None
    if atm_iv is not None:
        em_sym_pct = float(atm_iv * sqrt_t)

    em_dollar_up   = (upside_pct   * spot / 100.0) if upside_pct   is not None else None
    em_dollar_down = (downside_pct * spot / 100.0) if downside_pct is not None else None

    skew_25 = (
        float(put_iv_25 - call_iv_25)
        if (put_iv_25 is not None and call_iv_25 is not None)
        else None
    )

    return SkewAdjustedExpectedMove(
        spot=float(spot),
        dte_days=int(dte_days),
        atm_iv=atm_iv,
        put_iv_25d=put_iv_25,
        call_iv_25d=call_iv_25,
        skew_25d=skew_25,
        upside_pct=upside_pct,
        downside_pct=downside_pct,
        em_symmetric_pct=em_sym_pct,
        em_dollar_up=em_dollar_up,
        em_dollar_down=em_dollar_down,
    )
