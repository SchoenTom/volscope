"""Front-month vs Back-month IV decomposition — extract event premium.

Pre-earnings option chains carry a "term-structure inversion":
the FRONT-month IV is inflated by the binary event-risk premium,
while the BACK-month IV reflects the underlying name's natural
post-event volatility. The difference is the market's *priced*
contribution of the event itself.

For Snowflake pre-earnings (2026-05-27 print):

    Front (May 30, ~3 DTE)   IV ≈ 95 %    ← contains earnings risk
    Back  (Sep 19, ~120 DTE) IV ≈ 50 %    ← post-event normal vol
    Event premium            ≈ 45 vol-pts

This number is more actionable than the raw IV-Rank/Percentile
when the operator is sizing an earnings-week long-vol vs short-vol
trade. A 45-pt event-attributed premium tells you the market is
pricing this print as the second-richest in the past N quarters —
without that decomposition you only see "IV is elevated" which is
true every earnings cycle.

Method: variance is additive over time under BSM. If front-IV
covers (T_front), back-IV covers (T_back), then a *pure* event-
risk component is:

    σ_event² ≈ (σ_front² × T_front − σ_back² × T_back) / T_event

where T_event is the time devoted to the event (typically ≈ 1 day
in trading-day units). This isolates the event vol from the
ambient diffusion vol.

References:
  - Dubinsky & Johannes (2006), "Earnings Announcements and
    Equity Options"
  - Carr & Wu (2016), "Decomposing Long-Run Variance Risk Premium"
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

__all__ = ["FrontBackDecomposition", "decompose_front_back_iv"]


@dataclass(frozen=True)
class FrontBackDecomposition:
    """Result of a front-vs-back IV decomposition for one ticker / event."""
    front_iv:           float    # annualised, percent (e.g. 95.0)
    front_dte:          int
    back_iv:            float
    back_dte:           int
    raw_spread:         float    # front_iv − back_iv (vol points)
    event_premium_iv:   Optional[float]   # isolated event-day IV in vol pts
    event_dte_days:     float    # default 1 trading day
    interpretation:     str      # operator-readable summary

    def is_elevated(self, threshold: float = 20.0) -> bool:
        """True if raw_spread crosses the operator's "earnings-rich" line."""
        return self.raw_spread >= threshold


def decompose_front_back_iv(
    *,
    front_iv: float,
    front_dte: int,
    back_iv: float,
    back_dte: int,
    event_dte_days: float = 1.0,
) -> Optional[FrontBackDecomposition]:
    """Decompose front + back month IVs into an isolated event-premium IV.

    All inputs are in *standard market units*: IV is annualised in %,
    DTE is calendar (not trading) days. Set ``event_dte_days``
    conservatively (default 1 trading day = ~1.4 calendar days)
    when extracting the earnings-day vol component.

    Returns
    -------
    None if inputs are degenerate (negative DTE, zero spread, etc).
    """
    if front_iv is None or back_iv is None:
        return None
    if front_dte is None or back_dte is None:
        return None
    if front_dte <= 0 or back_dte <= 0:
        return None
    if front_iv <= 0 or back_iv <= 0:
        return None  # non-positive IV is degenerate — variance term goes negative
    if back_dte <= front_dte:
        return None  # back must be strictly later than front
    if event_dte_days <= 0:
        return None

    # Convert to fraction-of-year and decimals
    t_front = front_dte / 365.0
    t_back  = back_dte / 365.0
    t_event = event_dte_days / 365.0

    sigma_front = front_iv / 100.0
    sigma_back  = back_iv  / 100.0

    # Variance additivity: σ²·T over [0, T] = σ_event² · T_event + σ_diffusion² · (T - T_event)
    # For the front month we assume the back-month vol IS the diffusion
    # vol (the no-event annualised vol). Then:
    #
    #   σ_front² · T_front = σ_event² · T_event
    #                      + σ_back² · (T_front − T_event)
    #
    # Solving for σ_event²:
    #
    #   σ_event² = (σ_front² · T_front − σ_back² · (T_front − T_event)) / T_event
    diffusion_window = t_front - t_event
    if diffusion_window <= 0:
        # Front expiry covers ONLY the event day → event_iv IS front_iv
        event_var = sigma_front ** 2
    else:
        event_var = (
            (sigma_front ** 2) * t_front
            - (sigma_back ** 2) * diffusion_window
        ) / t_event

    event_iv: Optional[float] = None
    if event_var > 0:
        event_iv = float(math.sqrt(event_var) * 100.0)

    raw_spread = float(front_iv - back_iv)

    # Operator-readable interpretation
    if event_iv is None:
        interp = (
            f"Back-IV exceeds front-IV ({back_iv:.0f}% > {front_iv:.0f}%) — "
            f"no isolated event premium. Term structure is downward-sloping; "
            f"check for stale chain data or a non-event-driven regime."
        )
    elif raw_spread >= 30:
        interp = (
            f"Front ({front_iv:.0f}%) - Back ({back_iv:.0f}%) = {raw_spread:.0f} "
            f"vol-pts. Isolated event IV ≈ {event_iv:.0f}% — rich. Market is "
            f"pricing this print as a binary catalyst; short premium expects a "
            f"large gap, long premium needs a >{event_iv * math.sqrt(event_dte_days/365.0):.1f}% move."
        )
    elif raw_spread >= 15:
        interp = (
            f"Front ({front_iv:.0f}%) - Back ({back_iv:.0f}%) = {raw_spread:.0f} "
            f"vol-pts. Event IV ≈ {event_iv:.0f}% — normal earnings premium for "
            f"this name."
        )
    else:
        interp = (
            f"Front ({front_iv:.0f}%) - Back ({back_iv:.0f}%) = {raw_spread:.0f} "
            f"vol-pts. Event premium is muted ({event_iv:.0f}%) — either no "
            f"earnings in front cycle or unusually-quiet expectations."
        )

    return FrontBackDecomposition(
        front_iv=float(front_iv),
        front_dte=int(front_dte),
        back_iv=float(back_iv),
        back_dte=int(back_dte),
        raw_spread=raw_spread,
        event_premium_iv=event_iv,
        event_dte_days=float(event_dte_days),
        interpretation=interp,
    )
