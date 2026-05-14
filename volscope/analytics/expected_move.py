"""
Expected Move — implied price-range estimation around an event.

Three independent estimators, reconciled into a single best estimate:

  1. **ATM Straddle Method** (industry standard for earnings moves):
        EM_$ ≈ ATM_call_price + ATM_put_price
        EM_% ≈ EM_$ / spot
     This is the "what does the market price the move at" reading. It's
     the most accurate when ATM bid/ask is tight, but requires a real
     option chain near-the-money.

  2. **IV Method** (always available given iv_30d, days_to_event):
        EM_$ ≈ spot · IV/100 · √(days_to_event / 365)
        EM_% ≈ IV/100 · √(days_to_event / 365)
     Closed-form 1σ estimate. Slightly underestimates earnings moves
     because IV30 averages over 30 days and the event is typically a
     point spike. Useful as a sanity floor.

  3. **Open-Interest "Max-Pain" Method**:
        Find the strike that minimises total-OI-weighted distance.
        The implied move is approximately spot − max_pain_strike, in % terms.
     This is a different kind of signal — it reflects where dealers
     would prefer the underlying to settle, not the realised expected
     range. Reported separately so the trader can spot disagreement.

The ``ConsensusMove`` returned by ``reconcile_estimates`` averages
methods 1 and 2 (the two that estimate the SAME quantity) and reports
the OI-derived max-pain as orthogonal context. When the two are far
apart, ``confidence`` drops, signalling "verify before trading".

Pure analytics — no UI, no DB, no I/O.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ── Output types ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StraddleEstimate:
    """ATM straddle implied move."""
    spot:               float
    atm_strike:         float
    call_mid:           float
    put_mid:            float
    em_dollar:          float       # absolute expected move in $
    em_pct:             float       # in %
    n_strikes_used:     int
    days_to_event:      int


@dataclass(frozen=True)
class IvEstimate:
    """1σ estimate from IV alone."""
    spot:           float
    iv_pct:         float
    days:           int
    em_dollar:      float
    em_pct:         float


@dataclass(frozen=True)
class MaxPainEstimate:
    """Max-pain OI-weighted strike + implied move from spot."""
    spot:           float
    max_pain_strike: float
    em_dollar:       float       # spot - max_pain
    em_pct:          float
    total_oi:        int


@dataclass(frozen=True)
class ConsensusMove:
    """Reconciled view across the three methods."""
    ticker:           str
    days_to_event:    int
    straddle:         Optional[StraddleEstimate]
    iv_based:         Optional[IvEstimate]
    max_pain:         Optional[MaxPainEstimate]
    consensus_em_pct: Optional[float]    # average of straddle + IV when both present
    disagreement:     Optional[float]    # |straddle - iv| / consensus, if both present
    confidence:       float              # 0..1
    note:             str


# ── Method 1: ATM Straddle ──────────────────────────────────────────────

def estimate_from_straddle(
    options_df:    pd.DataFrame,
    spot:          float,
    days_to_event: int,
    n_strikes:     int = 1,
) -> Optional[StraddleEstimate]:
    """Compute expected move from ATM call+put midpoint prices.

    Parameters
    ----------
    options_df : DataFrame with columns 'strike', 'option_type', 'bid', 'ask'.
                 Single-expiry slice (the expiry just after the event).
    spot       : Current underlying price.
    days_to_event : Calendar days until the event (used for context only).
    n_strikes  : Average over the closest N strikes (default 1 = pure ATM).
                 Larger N reduces noise from one wide bid/ask.

    Returns
    -------
    StraddleEstimate | None
        None when chain is empty, has no calls/puts, or ATM strike has
        invalid quotes.
    """
    if options_df is None or options_df.empty or spot <= 0:
        return None
    needed = {"strike", "option_type", "bid", "ask"}
    if not needed.issubset(options_df.columns):
        return None

    df = options_df.copy()
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["bid"]    = pd.to_numeric(df["bid"], errors="coerce")
    df["ask"]    = pd.to_numeric(df["ask"], errors="coerce")
    df = df.dropna(subset=["strike", "bid", "ask"])
    df = df[(df["bid"] > 0) & (df["ask"] > 0) & (df["ask"] >= df["bid"])]
    if df.empty:
        return None

    # Pick the n_strikes closest strikes by absolute distance to spot
    df["dist"] = (df["strike"] - spot).abs()
    closest = sorted(df["strike"].unique(), key=lambda s: abs(s - spot))[:n_strikes]
    if not closest:
        return None
    selected = df[df["strike"].isin(closest)]

    calls = selected[selected["option_type"].str.lower() == "call"]
    puts  = selected[selected["option_type"].str.lower() == "put"]
    if calls.empty or puts.empty:
        return None

    call_mid = float(((calls["bid"] + calls["ask"]) / 2).mean())
    put_mid  = float(((puts["bid"]  + puts["ask"])  / 2).mean())
    em_dollar = call_mid + put_mid
    em_pct    = em_dollar / spot * 100.0

    # The ATM strike for display: closest single strike to spot
    atm_strike = float(min(closest, key=lambda s: abs(s - spot)))

    return StraddleEstimate(
        spot=round(spot, 4),
        atm_strike=round(atm_strike, 4),
        call_mid=round(call_mid, 4),
        put_mid=round(put_mid, 4),
        em_dollar=round(em_dollar, 4),
        em_pct=round(em_pct, 3),
        n_strikes_used=len(closest),
        days_to_event=int(days_to_event),
    )


# ── Method 2: IV-based ──────────────────────────────────────────────────

def estimate_from_iv(
    spot:    float,
    iv_pct:  float,
    days:    int,
) -> Optional[IvEstimate]:
    """1σ implied move from annualised IV.

    Formula::
        EM_$ ≈ spot · IV · √(days / 365)
    """
    if spot <= 0 or iv_pct <= 0 or days <= 0:
        return None
    em_pct    = (iv_pct / 100.0) * math.sqrt(days / 365.0) * 100.0
    em_dollar = spot * em_pct / 100.0
    return IvEstimate(
        spot=round(spot, 4),
        iv_pct=round(iv_pct, 3),
        days=int(days),
        em_dollar=round(em_dollar, 4),
        em_pct=round(em_pct, 3),
    )


# ── Method 3: Max-Pain ──────────────────────────────────────────────────

def estimate_max_pain(
    options_df: pd.DataFrame,
    spot:       float,
) -> Optional[MaxPainEstimate]:
    """Max-pain strike: where total-OI cash settlement is minimised.

    Walks every traded strike, computes the dealer P&L if expiry settles
    AT that strike, and picks the minimum (= worst for option buyers,
    best for dealers).

    Parameters
    ----------
    options_df : DataFrame with columns 'strike', 'option_type',
                 'open_interest'. Single-expiry slice.
    spot       : Current underlying.

    Returns
    -------
    MaxPainEstimate | None
        None when chain has no OI data or all strikes empty.
    """
    if options_df is None or options_df.empty or spot <= 0:
        return None
    needed = {"strike", "option_type", "open_interest"}
    if not needed.issubset(options_df.columns):
        return None

    df = options_df.copy()
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df["open_interest"] = pd.to_numeric(df["open_interest"], errors="coerce").fillna(0)
    df = df.dropna(subset=["strike"])
    df = df[df["strike"] > 0]
    if df.empty or df["open_interest"].sum() <= 0:
        return None

    # For each candidate settlement price K, total cash payout is:
    #   sum over calls: max(K - strike, 0) * call_OI
    #   sum over puts : max(strike - K, 0) * put_OI
    candidates = sorted(df["strike"].unique())
    pain: dict[float, float] = {}
    calls = df[df["option_type"].str.lower() == "call"]
    puts  = df[df["option_type"].str.lower() == "put"]

    for K in candidates:
        c_pay = float(((calls["strike"].apply(lambda s: max(K - s, 0)) * calls["open_interest"]).sum()))
        p_pay = float(((puts["strike"].apply(lambda s: max(s - K, 0))  * puts["open_interest"]).sum()))
        pain[K] = c_pay + p_pay

    if not pain:
        return None
    max_pain_strike = float(min(pain, key=pain.get))
    em_dollar = abs(spot - max_pain_strike)
    em_pct    = em_dollar / spot * 100.0
    total_oi  = int(df["open_interest"].sum())

    return MaxPainEstimate(
        spot=round(spot, 4),
        max_pain_strike=round(max_pain_strike, 4),
        em_dollar=round(em_dollar, 4),
        em_pct=round(em_pct, 3),
        total_oi=total_oi,
    )


# ── Reconciler ──────────────────────────────────────────────────────────

def reconcile_estimates(
    ticker:        str,
    days_to_event: int,
    straddle:      Optional[StraddleEstimate],
    iv_based:      Optional[IvEstimate],
    max_pain:      Optional[MaxPainEstimate],
) -> ConsensusMove:
    """Average straddle + IV (the two estimating the SAME quantity).

    Max-pain estimates a different thing (dealer-preferred settle vs.
    market-implied range) so we report it as orthogonal context but
    don't fold it into the consensus average.

    Confidence rules:
      - 1.0 when straddle + IV agree within 15%
      - 0.6 when they agree within 30%
      - 0.3 when they disagree by 30-60%
      - 0.1 when only one method available
      - 0.0 when neither method available
    """
    available = [e.em_pct for e in (straddle, iv_based) if e is not None]

    if not available:
        return ConsensusMove(
            ticker=ticker, days_to_event=days_to_event,
            straddle=straddle, iv_based=iv_based, max_pain=max_pain,
            consensus_em_pct=None, disagreement=None,
            confidence=0.0, note="No method available — chain + IV both missing",
        )

    if len(available) == 1:
        em = available[0]
        return ConsensusMove(
            ticker=ticker, days_to_event=days_to_event,
            straddle=straddle, iv_based=iv_based, max_pain=max_pain,
            consensus_em_pct=round(em, 3),
            disagreement=None,
            confidence=0.1,
            note="Only one estimator — confidence low",
        )

    # Both present
    consensus = sum(available) / len(available)
    disagreement = abs(available[0] - available[1]) / consensus if consensus > 0 else 0.0

    if disagreement <= 0.15:
        confidence, note = 1.0, "Straddle + IV agree within 15%"
    elif disagreement <= 0.30:
        confidence, note = 0.6, f"Methods diverge {disagreement*100:.0f}% — verify chain liquidity"
    elif disagreement <= 0.60:
        confidence, note = 0.3, f"Methods diverge {disagreement*100:.0f}% — likely thin chain"
    else:
        confidence, note = 0.1, f"Methods diverge {disagreement*100:.0f}% — treat as no signal"

    return ConsensusMove(
        ticker=ticker, days_to_event=days_to_event,
        straddle=straddle, iv_based=iv_based, max_pain=max_pain,
        consensus_em_pct=round(consensus, 3),
        disagreement=round(disagreement, 3),
        confidence=confidence,
        note=note,
    )


# ── Convenience composer ────────────────────────────────────────────────

def compute_expected_move(
    ticker:           str,
    spot:             float,
    iv_pct:           Optional[float],
    days_to_event:    int,
    options_df:       Optional[pd.DataFrame] = None,
) -> ConsensusMove:
    """One-shot: run all three methods and reconcile.

    Most callers use this — pass what's available, get a ConsensusMove.
    """
    straddle = (
        estimate_from_straddle(options_df, spot, days_to_event)
        if options_df is not None else None
    )
    iv_est = (
        estimate_from_iv(spot, iv_pct, days_to_event)
        if iv_pct is not None and iv_pct > 0 else None
    )
    mp = (
        estimate_max_pain(options_df, spot)
        if options_df is not None else None
    )
    return reconcile_estimates(ticker, days_to_event, straddle, iv_est, mp)
