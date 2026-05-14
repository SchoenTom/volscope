"""
IV Smile / HIVG — Bloomberg-style IV-by-strike distribution.

The HIVG function on Bloomberg shows the implied vol for every traded
strike on a given expiry, plotted as IV vs strike (or vs delta). The
canonical view is "smile" or "smirk": equity options typically show
elevated IV at low strikes (put-skew, crash protection demand) and
gentler decay at high strikes.

For VolScope this module:

  - Computes the IV-by-strike profile from the options-snapshot history
    (`options_snapshots` table) for a (ticker, expiry) pair.
  - Compares today's smile to a smile from N days ago (overlay shows
    skew changes — Bloomberg HIVG with TIME ARROW).
  - Quantifies skew steepness via a parametric fit (linear regression
    of IV on log-moneyness) — the slope is reported as the "smile
    steepness" with units of vol-pts per log-moneyness.

Use cases:
  - "DAX 30d skew flattened 3 pts in last week → call-side becoming
    relatively cheaper → consider call-side trades"
  - "MSTR 60d smile inverted (call-skew higher than put-skew) → unusual,
    investigate flow"

This module reads from a DataFrame (caller is responsible for fetching
options_snapshots rows) and is pure analytics.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ── Configuration ────────────────────────────────────────────────────────

# Reject IV outside this range as an obvious data error
_IV_MIN_PCT = 1.0
_IV_MAX_PCT = 500.0


# ── Output types ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SmilePoint:
    """One observation in the smile."""
    strike:        float
    iv:            float          # in %
    log_moneyness: float          # ln(strike / spot)


@dataclass(frozen=True)
class SmileFit:
    """Parametric fit of an IV smile.

    Slope: vol-points per unit log-moneyness. Negative slope = put-skew
    (lower strikes have higher IV) which is the equity norm.
    Intercept: implied vol at log-moneyness=0 (i.e. strike=spot, ATM).
    """
    intercept_atm_iv: float
    slope:            float
    r_squared:        float
    n_points:         int


@dataclass(frozen=True)
class SmileSnapshot:
    """All a (ticker, expiry, snapshot_date) needs for a HIVG view."""
    ticker:        str
    expiry:        object         # date-like
    snapshot_date: object         # date-like
    spot:          float
    points:        tuple[SmilePoint, ...]
    fit:           Optional[SmileFit]


@dataclass(frozen=True)
class SmileComparison:
    """Today vs prior — for HIVG with TIME ARROW."""
    today:           SmileSnapshot
    prior:           SmileSnapshot
    slope_change:    float        # today.slope − prior.slope
    atm_iv_change:   float        # today.atm_iv − prior.atm_iv (vol points)
    interpretation:  str          # 1-line trader read


# ── Builders ─────────────────────────────────────────────────────────────

def build_smile(
    options_df: pd.DataFrame,
    spot:       float,
    ticker:     str = "X",
    expiry:     Optional[object] = None,
    snapshot_date: Optional[object] = None,
) -> SmileSnapshot:
    """Build a single-snapshot smile.

    Parameters
    ----------
    options_df : pd.DataFrame
        Rows must include columns ``strike``, ``iv``, ``option_type``.
        IV in % (e.g. 22.0).
    spot       : Current spot price.
    ticker, expiry, snapshot_date : metadata pass-through.

    Returns
    -------
    SmileSnapshot
        Always valid. fit is None when < 3 points or singular regression.
    """
    if options_df is None or options_df.empty or spot <= 0:
        return SmileSnapshot(
            ticker=ticker, expiry=expiry, snapshot_date=snapshot_date,
            spot=float(spot or 0.0), points=(),
            fit=None,
        )

    df = options_df.copy()
    if "iv" not in df.columns or "strike" not in df.columns:
        return SmileSnapshot(
            ticker=ticker, expiry=expiry, snapshot_date=snapshot_date,
            spot=spot, points=(),
            fit=None,
        )
    df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    df = df.dropna(subset=["iv", "strike"])
    df = df[(df["iv"] > _IV_MIN_PCT) & (df["iv"] < _IV_MAX_PCT)]
    df = df[df["strike"] > 0]

    if df.empty:
        return SmileSnapshot(
            ticker=ticker, expiry=expiry, snapshot_date=snapshot_date,
            spot=spot, points=(),
            fit=None,
        )

    # Average call/put IV at each strike (closest-to-mid estimator)
    by_strike = df.groupby("strike", as_index=False)["iv"].mean().sort_values("strike")
    log_m = np.log(by_strike["strike"].to_numpy() / spot)
    ivs = by_strike["iv"].to_numpy()
    points = tuple(
        SmilePoint(strike=float(k), iv=float(v),
                   log_moneyness=float(np.log(k / spot)))
        for k, v in zip(by_strike["strike"], by_strike["iv"])
    )

    fit = _fit_smile(log_m, ivs)

    return SmileSnapshot(
        ticker=ticker, expiry=expiry, snapshot_date=snapshot_date,
        spot=spot, points=points, fit=fit,
    )


def _fit_smile(log_moneyness: np.ndarray, ivs: np.ndarray) -> Optional[SmileFit]:
    """Linear regression of IV ~ log_moneyness with R²."""
    if len(log_moneyness) < 3:
        return None
    x = log_moneyness
    y = ivs
    if np.std(x) == 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return SmileFit(
        intercept_atm_iv=round(float(intercept), 3),
        slope=round(float(slope), 3),
        r_squared=round(r2, 3),
        n_points=int(len(x)),
    )


# ── Comparison ───────────────────────────────────────────────────────────

def compare_smiles(today: SmileSnapshot, prior: SmileSnapshot) -> SmileComparison:
    """Bloomberg HIVG-style 'TIME ARROW' comparison.

    Computes how the slope (skew) and ATM IV have changed between two
    snapshots. Provides a trader-facing 1-line interpretation.
    """
    if today.fit is None or prior.fit is None:
        return SmileComparison(
            today=today, prior=prior,
            slope_change=0.0,
            atm_iv_change=0.0,
            interpretation="Insufficient data — can't compare smiles.",
        )

    slope_d = today.fit.slope - prior.fit.slope
    atm_d   = today.fit.intercept_atm_iv - prior.fit.intercept_atm_iv

    # Interpretation rules. Slopes are in vol-pts per log-moneyness. For a
    # typical equity, slope is negative (put-skew). A *less* negative slope
    # = skew flattened = puts cheaper relative to calls.
    if abs(slope_d) < 0.5 and abs(atm_d) < 0.5:
        interp = "Smile and ATM IV roughly stable."
    elif slope_d > 1.0:
        interp = (
            f"Skew flattened (Δslope={slope_d:+.2f}) — puts becoming "
            f"relatively cheaper vs calls."
        )
    elif slope_d < -1.0:
        interp = (
            f"Skew steepened (Δslope={slope_d:+.2f}) — put-side richness "
            f"growing; tail demand strong."
        )
    elif atm_d > 1.0:
        interp = f"ATM IV rose {atm_d:+.2f}pt — vol regime expanding."
    elif atm_d < -1.0:
        interp = f"ATM IV fell {atm_d:+.2f}pt — vol contracting."
    else:
        interp = (
            f"Mixed: slope {slope_d:+.2f}, ATM {atm_d:+.2f}pt."
        )

    return SmileComparison(
        today=today, prior=prior,
        slope_change=round(slope_d, 3),
        atm_iv_change=round(atm_d, 3),
        interpretation=interp,
    )


# ── Display helper ───────────────────────────────────────────────────────

def smile_to_dataframe(snap: SmileSnapshot) -> pd.DataFrame:
    """Long-format DataFrame for plotting (strike, iv, log_moneyness)."""
    if not snap.points:
        return pd.DataFrame(columns=["strike", "iv", "log_moneyness"])
    return pd.DataFrame([
        {"strike": p.strike, "iv": p.iv, "log_moneyness": p.log_moneyness}
        for p in snap.points
    ])
