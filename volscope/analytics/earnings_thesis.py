"""
Auto-generated one-sentence thesis for each Earnings Hub tile.

No LLM, no inference — pure template combination of the four key
signals (implied move, skew, crowded band, calibration ratio). The
output reads like something a vol-trader would say in their morning
meeting, which is the bar.

Why this exists: a tile's four numbers are evidence; the recommendation
is a verdict; the thesis is the *story* that joins them. Traders
remember the story, not the numbers.

The function returns a 1-2 sentence English string. ``None`` when no
signals are strong enough to support any narrative (avoids fabricating
prose).
"""
from __future__ import annotations

from typing import Optional


def auto_thesis(
    *,
    ticker: str,
    implied_move_pct: Optional[float],
    skew_pt: Optional[float],
    crowded_band: Optional[str],
    crowded_pct: Optional[float],
    calibration_ratio: Optional[float],
    iv_rank: Optional[float],
    crush_avg_pct: Optional[float],
    n_calibration_events: int = 0,
) -> Optional[str]:
    """Build a trader-grade one-sentence story from the signals.

    Decision tree:
      1. Calibration extreme (ratio > 1.20 or < 0.80) → lead with that
      2. Skew extreme (|skew| > 4) + crowded → lead with sentiment
      3. IV rank extreme (> 80 or < 15) → lead with vol pricing
      4. Default → narrate the move + crush
    """
    move = implied_move_pct or 0
    sk = skew_pt or 0
    cband = crowded_band or "normal"
    cpct = crowded_pct or 50
    ratio = calibration_ratio
    rank = iv_rank or 50
    crush = crush_avg_pct

    # Path 1 — calibration-led narrative
    if ratio is not None and n_calibration_events >= 3:
        if ratio > 1.20:
            return (
                f"Over the last {n_calibration_events} prints {ticker} has "
                f"moved {ratio:.0%} of what the market priced — implied "
                f"{move:.1f}% may again undersell the realised range, "
                f"favouring long-vol structures."
            )
        if ratio < 0.80:
            return (
                f"{ticker} has consistently moved less than implied over "
                f"the last {n_calibration_events} prints ({ratio:.0%} of "
                f"implied). Premium harvest is the historical edge here."
            )

    # Path 2 — extreme skew + crowdedness
    if abs(sk) >= 4 and cband in ("elevated", "exceptional"):
        side = "downside protection" if sk > 0 else "upside calls"
        contrarian = "upside calls" if sk > 0 else "downside puts"
        return (
            f"Crowded positioning ({cpct:.0f}th percentile of own history) "
            f"+ extreme {side} demand ({sk:+.1f}pt skew) → "
            f"{contrarian} are cheap, contrarian setup."
        )

    # Path 3 — extreme IV rank
    if rank > 80:
        if crush is not None and crush < -30:
            return (
                f"IV rank {rank:.0f} (top 20% of own history) and prior "
                f"prints have crushed vol by ~{abs(crush):.0f}%. "
                f"Premium-seller setup with defined-risk wings."
            )
        return (
            f"IV rank {rank:.0f} — vol is priced rich relative to own "
            f"history. Premium-seller bias unless catalysts unique."
        )
    if rank < 15:
        return (
            f"IV rank {rank:.0f} — implied {move:.1f}% sits near the "
            f"floor of {ticker}'s own range, leaving room for vol "
            f"expansion into the print."
        )

    # Path 4 — straightforward narration
    if move >= 8:
        return (
            f"Market pricing a sizable {move:.1f}% move; "
            f"{cband} crowdedness keeps the setup clean for either "
            f"long-vol gamma or defined-risk fade."
        )
    if move > 0:
        crush_clause = (
            f" Post-print crush averages {abs(crush):.0f}%."
            if crush is not None else ""
        )
        return (
            f"Modest {move:.1f}% implied move, {cband} positioning."
            f"{crush_clause}"
        )

    return None
