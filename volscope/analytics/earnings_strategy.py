"""
Earnings-aware strategy recommendation.

Given the four pre-earnings signals (implied move, skew, crowded
band, calibration ratio) we pick ONE structure with a strong rationale.

Decision matrix:

  implied < 0.85 × realised (8q)  AND  crowded ∈ {calm, normal}
      → Long Straddle  (cheap gamma into a known catalyst)

  iv_rank > 80  AND  crowded = calm
      → Short Iron Condor  (fade rich vol, defined risk)

  skew > +4pt  AND  crowded ∈ {elevated, exceptional}
      → Long Call  (contrarian: fade put panic)

  skew < -4pt  AND  crowded ∈ {elevated, exceptional}
      → Long Put  (contrarian: fade call euphoria)

  default
      → Wait
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EarningsRec:
    """One ranked earnings recommendation."""
    structure:       str
    direction:       str          # long_vol | short_vol | bullish | bearish | neutral
    confidence:      str          # "high" | "medium" | "low"
    thesis:          str
    kills_the_trade: str          # one-line risk
    template_name:   Optional[str] = None  # links to TEMPLATES dict


def _struct_to_template(structure: str) -> Optional[str]:
    """Map our human-readable structure to a TEMPLATES key so the
    Earnings Hub can hand it straight to ``paper_buy_strategy``."""
    return {
        "Long Straddle":      "Long Straddle",
        "Short Iron Condor":  "Short Iron Condor",
        "Long Call":          "Long Call",
        "Long Put":           "Long Put",
        "Long Strangle":      "Long Strangle",
        "Wait":               None,
    }.get(structure)


def recommend_for_earnings(
    *,
    implied_move_pct: Optional[float],
    skew_pt:          Optional[float],
    crowded_band:     Optional[str],
    iv_rank:          Optional[float],
    calibration_ratio: Optional[float] = None,
) -> EarningsRec:
    """Pure function — pick a structure from the four pre-ER signals.

    All inputs can be ``None``; the function falls back to "Wait" with
    `confidence="low"` when too much is missing.
    """
    # Long-straddle setup: cheap implied vs realised + uncrowded
    if (
        calibration_ratio is not None
        and calibration_ratio > 1.15
        and crowded_band in ("calm", "normal")
    ):
        return EarningsRec(
            structure="Long Straddle",
            direction="long_vol",
            confidence="high" if calibration_ratio > 1.30 else "medium",
            thesis=(
                f"Realised moves average {calibration_ratio:.0%} of "
                "implied — the market is systematically underpricing "
                "this print. ATM straddle captures the gap with "
                "limited downside (max loss = premium paid)."
            ),
            kills_the_trade=(
                "muted print — IV crushes and the straddle loses 30-50 %"
                " overnight even if direction was right."
            ),
            template_name=_struct_to_template("Long Straddle"),
        )

    # Short-vol setup: rich IV-rank + calm crowdedness
    if (
        iv_rank is not None and iv_rank > 80
        and crowded_band == "calm"
    ):
        return EarningsRec(
            structure="Short Iron Condor",
            direction="short_vol",
            confidence="medium",
            thesis=(
                f"IV-rank at {iv_rank:.0f} (top 20 % of own history) "
                "with calm crowdedness — the market is paying up for "
                "vol without obvious catalysts. Defined-risk condor "
                "harvests the premium."
            ),
            kills_the_trade=(
                "one-day shock breaks a wing and realised range "
                "exceeds short strikes."
            ),
            template_name=_struct_to_template("Short Iron Condor"),
        )

    # Contrarian-fade skew: extreme put-skew + high crowdedness
    if (
        skew_pt is not None and skew_pt > 4
        and crowded_band in ("elevated", "exceptional")
    ):
        return EarningsRec(
            structure="Long Call",
            direction="bullish",
            confidence="medium",
            thesis=(
                f"Put skew +{skew_pt:.1f}pt with crowded positioning "
                "({crowded_band}). Market is paying for downside "
                "protection that historically rarely fires. "
                "Asymmetric OTM call is the contrarian fade."
            ).format(crowded_band=crowded_band),
            kills_the_trade=(
                "the panic was justified — actual print is a miss and "
                "spot gaps below the put strikes."
            ),
            template_name=_struct_to_template("Long Call"),
        )

    if (
        skew_pt is not None and skew_pt < -4
        and crowded_band in ("elevated", "exceptional")
    ):
        return EarningsRec(
            structure="Long Put",
            direction="bearish",
            confidence="medium",
            thesis=(
                f"Call skew {skew_pt:.1f}pt with crowded positioning "
                "({crowded_band}). Bullish euphoria has compressed "
                "downside premium. Cheap-protection long put."
            ).format(crowded_band=crowded_band),
            kills_the_trade=(
                "the euphoria was justified — actual print is a beat "
                "and spot gaps above the call strikes."
            ),
            template_name=_struct_to_template("Long Put"),
        )

    return EarningsRec(
        structure="Wait",
        direction="neutral",
        confidence="low",
        thesis=(
            "No clear edge — implied move, skew, and crowdedness "
            "are all near baseline. Skip the trade."
        ),
        kills_the_trade="—",
        template_name=None,
    )
