"""
Implied (option-priced) expected move around an earnings event.

Two computation paths, picked automatically by DTE-to-earnings:

  Method A — BSM ATM straddle (preferred when DTE ≤ 14)
      We synthesise an ATM straddle expiring on the first session
      AFTER the earnings using ``bs_price``. The straddle premium is
      the market-priced 1-day move under the binary-event premium.

  Method B — IV-scale (used when DTE > 14)
      ``move ≈ iv_30d × sqrt(DTE_to_post_ER / 365)``. Honest about
      uncertainty when the IV-30d isn't a clean proxy yet.

Both methods produce an ``ImpliedMove`` dataclass.

The ``cross_check_iv_method_pct`` field always carries the *other*
method's number so a tooltip can show the user both estimates side
by side.

The skew adjustment: when ``iv_skew_25d`` is present we shift the
upper/lower bounds asymmetrically — a +3 pt put-skew biases the
upper-bound smaller and the lower-bound larger by an empirical
fraction (40 % of skew per 10pt IV). This produces the "▲+5.8
▼-4.2" UI pattern the trader expects.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from volscope.analytics.black_scholes import bs_price

_RISK_FREE = 0.04
_TRADING_DAYS_PER_YEAR = 252.0


@dataclass(frozen=True)
class ImpliedMove:
    ticker:        str
    earnings_date: date
    days_to_er:    int
    spot:          float
    iv_used:       float           # IV % used as input

    move_pct:      float            # symmetric ± in %
    move_dollars:  float
    upper_bound:   float
    lower_bound:   float
    upper_pct:     float            # skew-adjusted upper
    lower_pct:     float            # skew-adjusted lower (signed negative)

    method:        str              # "atm_straddle_bsm" | "atm_iv_scale"
    cross_check_iv_method_pct: float  # always populated for the tooltip
    confidence:    str              # "high" | "medium" | "low"
    flags:         tuple[str, ...] = ()


def _atm_straddle_bsm(spot: float, iv_pct: float, dte_days: int) -> float:
    """Synthesise the ATM straddle premium via BSM and return the
    premium / spot ratio (i.e. the implied 1-day move as a fraction)."""
    if spot <= 0 or iv_pct <= 0 or dte_days <= 0:
        return 0.0
    T = max(1, dte_days) / 365.0
    sigma = iv_pct / 100.0
    call = bs_price(spot, spot, T, _RISK_FREE, sigma, 0.0, "call")
    put = bs_price(spot, spot, T, _RISK_FREE, sigma, 0.0, "put")
    return (call + put) / spot


def _iv_scale(iv_pct: float, dte_days: int) -> float:
    """The naive `iv × sqrt(t/365)` projection — yields a 1-fraction."""
    if iv_pct <= 0 or dte_days <= 0:
        return 0.0
    return (iv_pct / 100.0) * math.sqrt(max(1, dte_days) / 365.0)


def compute_implied_move(
    db,
    ticker: str,
    earnings_date: date,
    *,
    asof: Optional[date] = None,
) -> Optional[ImpliedMove]:
    """End-to-end: pulls the freshest ``daily_vol`` row for ``ticker``,
    decides which method to use, returns a fully-populated record.

    Returns ``None`` only when there is no usable price/IV row for the
    ticker at all.
    """
    asof = asof or date.today()
    try:
        hist = db.get_ticker_history(ticker)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    latest = hist.iloc[-1]
    spot = _f(latest.get("spot_price"))
    iv = _f(latest.get("iv_30d"))
    if spot is None or iv is None or spot <= 0 or iv <= 0:
        return None

    dte = max(1, (earnings_date - asof).days)
    flags: list[str] = []

    # Method choice + cross-check
    method = "atm_straddle_bsm" if dte <= 14 else "atm_iv_scale"
    if method == "atm_straddle_bsm":
        primary_frac = _atm_straddle_bsm(spot, iv, dte)
        secondary_frac = _iv_scale(iv, dte)
    else:
        primary_frac = _iv_scale(iv, dte)
        secondary_frac = _atm_straddle_bsm(spot, iv, dte)

    move_pct = primary_frac * 100.0
    move_dollars = primary_frac * spot

    # Skew-adjustment: shift the upper/lower bounds by the put-call
    # delta-skew. Empirical: 40 % of |skew| per 10pt IV biases the
    # corresponding tail.
    skew_pt = _f(latest.get("iv_skew_25d")) or 0.0
    skew_bias = (skew_pt / 10.0) * 0.40 * move_pct
    upper_pct = +move_pct - max(0.0, skew_bias)
    lower_pct = -move_pct - max(0.0, skew_bias)
    upper_bound = spot * (1 + upper_pct / 100.0)
    lower_bound = spot * (1 + lower_pct / 100.0)

    # Confidence — high when we have skew + DTE ≤ 14; medium otherwise.
    if abs(skew_pt) > 0.1 and dte <= 14:
        confidence = "high"
    elif dte <= 14:
        confidence = "medium"
    else:
        confidence = "low"
        flags.append("dte_too_far_for_straddle_proxy")

    return ImpliedMove(
        ticker=ticker,
        earnings_date=earnings_date,
        days_to_er=dte,
        spot=spot,
        iv_used=iv,
        move_pct=move_pct,
        move_dollars=move_dollars,
        upper_bound=upper_bound,
        lower_bound=lower_bound,
        upper_pct=upper_pct,
        lower_pct=lower_pct,
        method=method,
        cross_check_iv_method_pct=secondary_frac * 100.0,
        confidence=confidence,
        flags=tuple(flags),
    )


# ── Calibration: implied vs realised across past N earnings ─────────

@dataclass(frozen=True)
class ImpliedRealisedCalibration:
    ticker:           str
    n_events:         int
    avg_implied_pct:  float
    avg_realised_pct: float       # |actual|, signed not preserved
    ratio:            float        # avg_realised / avg_implied
    band:             str          # "underprices" | "fair" | "overprices"
    last_implied_pct: Optional[float] = None
    last_realised_pct: Optional[float] = None


def calibrate_implied_vs_realised(
    db,
    ticker: str,
    *,
    min_events: int = 3,
) -> Optional[ImpliedRealisedCalibration]:
    """Read historical implied + actual rows from the ``earnings``
    table (populated by ``scrape_earnings_meta``). Returns ``None``
    when fewer than ``min_events`` historical events have both fields.
    """
    try:
        df = db.con.execute(
            """
            SELECT earnings_date, last_implied_pct, last_reaction_pct
            FROM earnings
            WHERE ticker = ? AND earnings_date <= CURRENT_DATE
              AND last_implied_pct IS NOT NULL
              AND last_reaction_pct IS NOT NULL
            ORDER BY earnings_date DESC
            """,
            [ticker],
        ).fetchdf()
    except Exception:
        return None
    if df is None or df.empty or len(df) < min_events:
        return None
    df = df.head(8).copy()
    avg_impl = float(df["last_implied_pct"].mean())
    avg_real = float(df["last_reaction_pct"].abs().mean())
    if avg_impl <= 0:
        return None
    ratio = avg_real / avg_impl
    if ratio > 1.10:
        band = "underprices"
    elif ratio < 0.90:
        band = "overprices"
    else:
        band = "fair"
    return ImpliedRealisedCalibration(
        ticker=ticker,
        n_events=int(len(df)),
        avg_implied_pct=avg_impl,
        avg_realised_pct=avg_real,
        ratio=ratio,
        band=band,
        last_implied_pct=_f(df["last_implied_pct"].iloc[0]),
        last_realised_pct=_f(df["last_reaction_pct"].iloc[0]),
    )


# ── Helpers ──────────────────────────────────────────────────────────

def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None
