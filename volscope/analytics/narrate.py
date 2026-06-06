"""
Deterministic scope-narrative engine — turn a daily_vol row into one
plain-English sentence a vol trader can read above the fold.

No LLM, no I/O, no randomness: the same inputs always produce the same
sentence. The narrative answers VolScope's single question — *is this
ticker's implied volatility cheap or expensive, and what's the context?*
— by composing four signals the trader would otherwise have to read off
separate cards:

  1. IV percentile band (the headline cheap/rich verdict),
  2. IV-vs-HV spread (is the market paying up over realised?),
  3. earnings proximity (a known vol event ahead),
  4. vol-cone position (is realised vol itself stretched?).

The IVP band thresholds come from :mod:`volscope.analytics.iv_thresholds`
(the single source of truth), so the prose never disagrees with the
KPI cards. Spike-contamination (the FISV-class IVR inflation documented
in CLAUDE.md) is surfaced as a separate caveat rather than baked into the
verdict, because the honest read there is "trust IVP, not IVR".
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional

from volscope.analytics.iv_thresholds import classify_perc
from volscope.analytics.vol_cones import VolCone

# Tone drives the accent colour the UI paints the banner with.
TONE_CHEAP = "cheap"
TONE_NEUTRAL = "neutral"
TONE_RICH = "rich"
TONE_UNKNOWN = "unknown"

_BAND_TONE = {
    "VERY_CHEAP": TONE_CHEAP,
    "CHEAP": TONE_CHEAP,
    "NEUTRAL": TONE_NEUTRAL,
    "RICH": TONE_RICH,
    "VERY_RICH": TONE_RICH,
    "NO_DATA": TONE_UNKNOWN,
}

_BAND_PHRASE = {
    "VERY_CHEAP": "historically very cheap",
    "CHEAP": "historically cheap",
    "NEUTRAL": "around its historical median",
    "RICH": "historically rich",
    "VERY_RICH": "historically very rich",
}


@dataclass(frozen=True)
class ScopeNarrative:
    """A one-line trader read plus presentation metadata."""

    headline: str
    tone: str                       # one of TONE_*
    caveat: Optional[str] = None    # e.g. spike-contamination warning

    @property
    def has_content(self) -> bool:
        return bool(self.headline)


def _num(v: object) -> Optional[float]:
    """Coerce to a finite float or None (never raises)."""
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _ordinal(p: float) -> str:
    """12.0 -> '12th', 21.0 -> '21st'."""
    n = int(round(p))
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def cone_position_from_cone(cone: Optional[VolCone], window: int = 30) -> Optional[str]:
    """Reduce a VolCone to a coarse position label for the narrative.

    Returns 'stretched_high' / 'stretched_low' / 'mid' / None based on
    where current realised vol sits in its own history at the chosen
    window (defaults to the 30-day horizon that matches iv_30d).
    """
    if cone is None or not cone.points:
        return None
    # Prefer the requested window; fall back to the closest available.
    point = min(
        cone.points,
        key=lambda p: abs(p.window - window),
        default=None,
    )
    if point is None or point.current_perc is None:
        return None
    perc = point.current_perc
    if perc >= 80:
        return "stretched_high"
    if perc <= 20:
        return "stretched_low"
    return "mid"


def generate_scope_narrative(
    ticker: str,
    latest_row: Optional[Mapping[str, object]],
    days_to_earnings: Optional[int] = None,
    cone_position: Optional[str] = None,
) -> ScopeNarrative:
    """Compose the one-line narrative for a ticker's Scope page.

    Parameters
    ----------
    ticker : str
        Display symbol.
    latest_row : Mapping or None
        The most-recent ``daily_vol`` row (dict-like). Reads, all optional:
        ``iv_30d``, ``iv_percentile``, ``iv_rank``, ``hv_yz_30d`` /
        ``hv_20d``, ``contamination_level``, ``ivr_ivp_divergence``.
    days_to_earnings : int or None
        Calendar days to the next earnings print, if known.
    cone_position : str or None
        One of 'stretched_high' / 'stretched_low' / 'mid', e.g. from
        :func:`cone_position_from_cone`.

    Returns
    -------
    ScopeNarrative
        Always valid; ``has_content`` is False when there is too little
        data to say anything honest.
    """
    sym = (ticker or "This name").upper()
    if not latest_row:
        return ScopeNarrative(headline="", tone=TONE_UNKNOWN)

    ivp = _num(latest_row.get("iv_percentile"))
    iv30 = _num(latest_row.get("iv_30d"))
    hv = _num(latest_row.get("hv_yz_30d"))
    if hv is None:
        hv = _num(latest_row.get("hv_20d"))

    # Headline verdict from the IV percentile band (single source of truth).
    if ivp is None:
        if iv30 is None:
            return ScopeNarrative(headline="", tone=TONE_UNKNOWN)
        band, tone = "NO_DATA", TONE_UNKNOWN
        verdict = f"{sym} 30-day IV is {iv30:.1f}%"
    else:
        band = classify_perc(ivp)
        tone = _BAND_TONE.get(band, TONE_UNKNOWN)
        phrase = _BAND_PHRASE.get(band, "at an unclear level")
        iv_str = f" ({iv30:.1f}%)" if iv30 is not None else ""
        verdict = (
            f"{sym} IV is in the {_ordinal(ivp)} percentile{iv_str} — {phrase}"
        )

    clauses: list[str] = [verdict]

    # IV-vs-HV spread: is the market paying up over recent realised?
    if iv30 is not None and hv is not None and hv > 0:
        spread = iv30 - hv
        if abs(spread) >= 2.0:
            if spread > 0:
                clauses.append(
                    f"the market is paying ~{spread:.0f} vol points over "
                    f"30-day realised ({hv:.1f}%)"
                )
            else:
                clauses.append(
                    f"IV sits ~{abs(spread):.0f} points BELOW 30-day realised "
                    f"({hv:.1f}%) — an unusually thin risk premium"
                )

    # Vol-cone context: realised vol's own stretch.
    if cone_position == "stretched_high":
        clauses.append("realised vol itself is near the top of its cone")
    elif cone_position == "stretched_low":
        clauses.append("realised vol is compressed near the floor of its cone")

    # Earnings proximity — a scheduled vol event reframes everything.
    if days_to_earnings is not None and 0 <= days_to_earnings <= 21:
        if days_to_earnings == 0:
            clauses.append("earnings are TODAY")
        elif days_to_earnings == 1:
            clauses.append("earnings are tomorrow")
        else:
            clauses.append(f"earnings in {days_to_earnings} days")

    headline = clauses[0]
    if len(clauses) > 1:
        headline = headline + "; " + "; ".join(clauses[1:]) + "."
    else:
        headline = headline + "."

    # Spike-contamination caveat — kept separate from the verdict.
    caveat: Optional[str] = None
    contam = str(latest_row.get("contamination_level") or "").lower()
    div = _num(latest_row.get("ivr_ivp_divergence"))
    if contam in ("severe", "extreme") or (div is not None and abs(div) > 30):
        d = f" (IVR vs IVP gap {abs(div):.0f}pt)" if div is not None else ""
        caveat = (
            f"IV Rank is distorted by an outlier spike{d} — trust IV "
            f"Percentile over IV Rank here."
        )

    return ScopeNarrative(headline=headline, tone=tone, caveat=caveat)
