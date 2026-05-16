"""Open-Interest heatmap — positioning visualization per strike.

For a single (ticker, expiry) chain this module computes the
strike-level OI distribution and the max-pain strike. Used by the
Options Lab "OI Map" tab.

Why this matters:
  - OI is positioning DATA (where existing money is parked), not
    vol data. Combined with skew it tells you *where* the put-hedges
    cluster vs *how* they're priced.
  - Max-pain — the strike that minimizes total contract-holder
    payoff at expiry — is a well-known earnings-week pull. The
    "market makers herd price toward max-pain" effect is debated
    statistically but operators care because it gives a single
    actionable strike for short-premium spreads.

This module returns:

  - per-strike DataFrame with call_oi, put_oi, pcr_by_strike,
    intrinsic_call_pain, intrinsic_put_pain, total_pain
  - max_pain_strike (where total_pain is minimized)
  - support / resistance strikes (highest put-OI / highest call-OI)

References:
  - Ni, Pearson, Poteshman (2005), "Stock Price Clustering on Option
    Expiration Dates" — the original max-pain empirical paper.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

__all__ = ["OIHeatmapResult", "compute_oi_heatmap"]


@dataclass(frozen=True)
class OIHeatmapResult:
    """Per-strike OI summary plus key derived levels."""
    by_strike:           pd.DataFrame  # indexed by strike
    max_pain_strike:     Optional[float]
    support_strike:      Optional[float]   # highest put-OI strike
    resistance_strike:   Optional[float]   # highest call-OI strike
    total_call_oi:       int
    total_put_oi:        int
    overall_pcr:         Optional[float]   # total put_oi / total call_oi


def _total_pain_at(strike: float, df_calls: pd.DataFrame, df_puts: pd.DataFrame) -> float:
    """Intrinsic payoff total at expiry IF spot landed at <strike>."""
    call_pain = 0.0
    put_pain = 0.0
    if not df_calls.empty:
        itm_calls = df_calls[df_calls["strike"] < strike]
        call_pain = float(((strike - itm_calls["strike"]) * itm_calls["open_interest"]).sum())
    if not df_puts.empty:
        itm_puts = df_puts[df_puts["strike"] > strike]
        put_pain = float(((itm_puts["strike"] - strike) * itm_puts["open_interest"]).sum())
    return call_pain + put_pain


def compute_oi_heatmap(chain_df: pd.DataFrame) -> Optional[OIHeatmapResult]:
    """Build the strike-level OI heatmap for one expiry.

    Parameters
    ----------
    chain_df : DataFrame with columns ``strike, option_right, open_interest``.
        Other columns ignored. ``option_right`` ∈ {C, P, call, put}.

    Returns
    -------
    OIHeatmapResult, or None when the chain has no OI data.
    """
    if chain_df is None or chain_df.empty:
        return None
    required = {"strike", "option_right", "open_interest"}
    if not required.issubset(chain_df.columns):
        return None

    df = chain_df.copy()
    df["option_right"] = df["option_right"].astype(str).str.lower().str[0]
    df = df[df["option_right"].isin(["c", "p"])]
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["open_interest"] = pd.to_numeric(df["open_interest"], errors="coerce").fillna(0)
    df = df.dropna(subset=["strike"])
    df = df[df["strike"] > 0]
    if df.empty:
        return None

    calls = df[df["option_right"] == "c"]
    puts = df[df["option_right"] == "p"]

    # Aggregate per-strike OI for each side.
    call_oi = calls.groupby("strike")["open_interest"].sum().rename("call_oi")
    put_oi  = puts.groupby("strike")["open_interest"].sum().rename("put_oi")
    by_strike = (
        pd.concat([call_oi, put_oi], axis=1)
        .fillna(0)
        .reset_index()
        .sort_values("strike")
    )
    by_strike["call_oi"] = by_strike["call_oi"].astype(int)
    by_strike["put_oi"]  = by_strike["put_oi"].astype(int)
    by_strike["pcr_by_strike"] = by_strike.apply(
        lambda r: (r["put_oi"] / r["call_oi"]) if r["call_oi"] > 0 else None,
        axis=1,
    )

    # Max-pain computed over the strike universe of THIS chain
    pain_by_strike = []
    for s in by_strike["strike"]:
        p = _total_pain_at(s, calls, puts)
        pain_by_strike.append((s, p))
    pain_df = pd.DataFrame(pain_by_strike, columns=["strike", "total_pain"])
    by_strike = by_strike.merge(pain_df, on="strike", how="left")

    max_pain_strike: Optional[float] = None
    if not pain_df.empty:
        max_pain_strike = float(pain_df.loc[pain_df["total_pain"].idxmin(), "strike"])

    total_call_oi = int(calls["open_interest"].sum())
    total_put_oi  = int(puts["open_interest"].sum())

    support_strike: Optional[float] = None
    if not puts.empty and total_put_oi > 0:
        support_strike = float(by_strike.loc[by_strike["put_oi"].idxmax(), "strike"])
    resistance_strike: Optional[float] = None
    if not calls.empty and total_call_oi > 0:
        resistance_strike = float(by_strike.loc[by_strike["call_oi"].idxmax(), "strike"])

    pcr: Optional[float] = None
    if total_call_oi > 0:
        pcr = total_put_oi / total_call_oi

    return OIHeatmapResult(
        by_strike=by_strike,
        max_pain_strike=max_pain_strike,
        support_strike=support_strike,
        resistance_strike=resistance_strike,
        total_call_oi=total_call_oi,
        total_put_oi=total_put_oi,
        overall_pcr=pcr,
    )
