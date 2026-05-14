"""
Optionsschein lookup — characterise a warrant by its market-economic
parameters rather than its WKN/ISIN.

Optionsscheine (and US-listed warrants) issued by Citi, HSBC, SocGen,
Vontobel etc. on the same underlying with similar strike/expiry/type
behave nearly identically: their delta, gamma, vega and IV track each
other within bid/ask noise. The user's claim — "all scheine should
react similarly" — is correct for vanillas; for knock-outs the barrier
adds a discontinuity but Greeks away from the barrier still track.

This module looks up the *closest match* on Yahoo's listed options chain
and returns its parameters as the proxy for the user's warrant. We
deliberately DO NOT scrape issuer chains (no API, behind JS); Yahoo
listed chains are good enough as a model surrogate because:

  - Yahoo's chains are at standard strikes (5/10/25 increment)
  - Implied vol on those is computed by Yahoo from CBOE / SIX
  - The issuer warrant's own IV mark is generally within ~1pt of the
    Yahoo chain IV at the same strike/expiry (issuer profit margin)

If no listed chain is available (DAX certain expiries, exotic
underlyings) the helper falls back to a BSM-derived IV using the
ticker's own daily_vol history.

Outputs are pure dataclasses — no DB writes, no UI imports.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ── Domain types ─────────────────────────────────────────────────────────

# Instrument families. The user trades all of these:
#   "vanilla"   — plain call or put
#   "knockout"  — knock-out warrant / certificate; has a barrier; once spot
#                 touches barrier, position dies (worth zero)
#   "inline"    — range warrant; pays out only if spot stays in [lo, hi]
#   "discount"  — discount certificate; capped upside
INSTRUMENT_TYPES = ("vanilla", "knockout", "inline", "discount")


@dataclass(frozen=True)
class OptionsscheinSpec:
    """Characteristic-based description of one Optionsschein.

    `wkn` is *informational only* — never used for lookup. The user can
    leave it blank.

    For knockout warrants:
      - `strike` is the financing level (Basispreis)
      - `barrier` is the knock-out barrier
      - `option_type` indicates the direction ("call" = long delta, "put" = short)
    """
    underlying:      str
    option_type:     str            # "call" | "put"
    strike:          float
    expiry:          date           # for knockouts: 'open-end' → use date(2099,12,31)
    instrument_type: str = "vanilla"  # vanilla | knockout | inline | discount
    barrier:         Optional[float] = None      # for knockouts / inlines
    upper_barrier:   Optional[float] = None      # for inlines (lower = barrier)
    cap:             Optional[float] = None      # for discount certificates
    contracts:       int = 1
    entry_date:      Optional[date] = None
    entry_premium:   Optional[float] = None      # price paid per warrant
    entry_iv:        Optional[float] = None      # in % — if unknown, looked up
    wkn:             str = ""                    # informational
    issuer:          str = ""                    # informational
    leverage:        Optional[float] = None      # for issuer KO warrants


@dataclass(frozen=True)
class ChainMatch:
    """The Yahoo-chain match used as IV / Greeks proxy."""
    matched_strike:  float
    matched_expiry:  date
    matched_iv:      float           # in %
    spot_at_lookup:  float
    strike_diff_pct: float           # how far the matched strike is from requested
    expiry_diff_days: int            # how many days from requested expiry
    source:          str = "yahoo_chain"


# ── Public API ───────────────────────────────────────────────────────────

def find_chain_match(
    optionsschein:  OptionsscheinSpec,
    options_df:     pd.DataFrame,
    spot:           float,
    max_strike_pct: float = 0.05,
    max_expiry_days: int = 14,
) -> Optional[ChainMatch]:
    """Find the closest match in a Yahoo options chain DataFrame.

    Parameters
    ----------
    optionsschein  : The user's warrant spec.
    options_df     : DataFrame with columns ``strike``, ``iv``, ``expiry``,
                     ``option_type``. Typically the result of
                     ``yfinance.Ticker(...).option_chain(expiry).calls/puts``.
    spot           : Current spot price of underlying.
    max_strike_pct : Reject matches further than this % from desired strike.
    max_expiry_days : Reject matches further than this many days from desired expiry.

    Returns
    -------
    ChainMatch | None
        None if no acceptable match exists. Caller should fall back to
        ``bsm_iv_proxy`` which uses the underlying's stored IV history.
    """
    if options_df is None or options_df.empty:
        return None
    df = options_df.copy()
    needed = {"strike", "iv", "expiry", "option_type"}
    if not needed.issubset(df.columns):
        return None
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
    df = df.dropna(subset=["strike", "iv"])
    df = df[df["option_type"].str.lower() == optionsschein.option_type.lower()]
    if df.empty:
        return None

    # Score each row by combined strike+expiry distance
    df["strike_diff_pct"] = (df["strike"] - optionsschein.strike).abs() / max(1.0, optionsschein.strike)
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    df["expiry_diff_days"] = (
        df["expiry"].map(lambda d: abs((d - optionsschein.expiry).days)
                          if optionsschein.expiry else 0)
    )

    df = df[df["strike_diff_pct"] <= max_strike_pct]
    df = df[df["expiry_diff_days"] <= max_expiry_days]
    if df.empty:
        return None

    # Composite score: 1 strike-pct ≈ 30 expiry days roughly equally penalised
    df["score"] = df["strike_diff_pct"] * 100 + df["expiry_diff_days"] / 30.0
    best = df.sort_values("score").iloc[0]

    return ChainMatch(
        matched_strike=float(best["strike"]),
        matched_expiry=best["expiry"],
        matched_iv=float(best["iv"]),
        spot_at_lookup=spot,
        strike_diff_pct=float(best["strike_diff_pct"]),
        expiry_diff_days=int(best["expiry_diff_days"]),
        source="yahoo_chain",
    )


def bsm_iv_proxy_from_history(
    history:   pd.DataFrame,
    target_dte: int,
) -> Optional[float]:
    """Fallback: pick the closest IV term-point from the ticker's vol history.

    Returns the most-recent ``iv_30d / iv_60d / iv_90d / iv_180d`` whose
    DTE bucket is closest to ``target_dte``. None if no usable column.
    """
    if history is None or history.empty:
        return None
    latest = history.sort_values("date").iloc[-1]
    candidates = [(30, "iv_30d"), (60, "iv_60d"), (90, "iv_90d"), (180, "iv_180d")]
    best = None
    best_diff = float("inf")
    for d, col in candidates:
        if col not in latest.index:
            continue
        try:
            v = float(latest[col])
            if math.isnan(v) or v <= 0:
                continue
            diff = abs(d - target_dte)
            if diff < best_diff:
                best = v
                best_diff = diff
        except (TypeError, ValueError):
            continue
    return best


def historical_iv_at(
    history:   pd.DataFrame,
    target_dt: date,
    target_dte: int,
) -> Optional[float]:
    """Return the ticker's IV on the given historical date, term-bucket aware.

    Used to backfill ``entry_iv`` when the user logs a position whose entry
    date is in the past. Tries iv_30d/60d/90d/180d ordered by closest DTE.
    """
    if history is None or history.empty:
        return None
    df = history.copy()
    if "date" not in df.columns:
        return None
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df_at = df[df["date"] <= target_dt]
    if df_at.empty:
        return None
    row = df_at.sort_values("date").iloc[-1]
    candidates = [(30, "iv_30d"), (60, "iv_60d"), (90, "iv_90d"), (180, "iv_180d")]
    best = None
    best_diff = float("inf")
    for d, col in candidates:
        if col not in row.index:
            continue
        try:
            v = float(row[col])
            if math.isnan(v) or v <= 0:
                continue
            diff = abs(d - target_dte)
            if diff < best_diff:
                best = v
                best_diff = diff
        except (TypeError, ValueError):
            continue
    return best


def compute_entry_iv_percentile(
    history:    pd.DataFrame,
    entry_iv:   float,
    entry_date: date,
    lookback:   int = 252,
) -> Optional[float]:
    """How rich/cheap was IV when the user entered, relative to past year?

    Returns a 0..100 percentile using the IV column with the most data
    available. Higher = entry was at richer IV (worse for long-vol entry).
    """
    if history is None or history.empty or "date" not in history.columns:
        return None
    df = history.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[df["date"] <= entry_date]
    if df.empty or "iv_30d" not in df.columns:
        return None
    arr = df["iv_30d"].dropna().tail(lookback).to_numpy()
    if len(arr) < 5:
        return None
    below = float(np.sum(arr < entry_iv))
    equal = float(np.sum(arr == entry_iv))
    return float((below + 0.5 * equal) / arr.size * 100.0)


# ── Optionsschein-specific helpers ───────────────────────────────────────

def days_to_expiry(spec: OptionsscheinSpec, asof: Optional[date] = None) -> int:
    """Calendar days from `asof` (default today) to the expiry."""
    asof = asof or date.today()
    return max(0, (spec.expiry - asof).days)


def is_knockout_dead(spec: OptionsscheinSpec, current_spot: float) -> bool:
    """True if a knock-out has been triggered (spot crossed barrier)."""
    if spec.instrument_type != "knockout" or spec.barrier is None:
        return False
    if spec.option_type == "call":
        # Long-call knockouts: barrier BELOW strike, spot must stay above
        return current_spot <= spec.barrier
    # Long-put knockouts: barrier ABOVE strike, spot must stay below
    return current_spot >= spec.barrier


def distance_to_barrier_pct(
    spec: OptionsscheinSpec,
    current_spot: float,
) -> Optional[float]:
    """Signed % distance to the knock-out barrier. Negative = already breached.

    Positive = safe, growing magnitude = farther from barrier.
    """
    if spec.barrier is None or current_spot <= 0:
        return None
    if spec.option_type == "call":
        return (current_spot - spec.barrier) / current_spot * 100.0
    return (spec.barrier - current_spot) / current_spot * 100.0
