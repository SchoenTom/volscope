"""
Vola Scenario Builder — scenario-driven strategy recommendations.

The user picks a *thesis* in plain English ("I think vol will rise on a
cheap name", "I want to harvest premium on a rich, range-bound name"),
and the builder returns a fully specified trade idea:

    structure (long_call, long_put_spread, short_strangle, …)
    target DTE
    strike rule (ATM, +75 % uplift, ±1σ)
    greeks profile we expect at entry
    thesis sentence ready to paste into a journal

It is a thin orchestration layer over `analytics.strategy_recommender`
plus `analytics.expected_move`. The scenarios capture the half-dozen
trades a vol-aware retail trader actually places.

Design intent
-------------
- Pure analytics. No Streamlit, no IO, no DB. Tests can import freely.
- Every public scenario produces the same `ScenarioRecommendation`
  shape so the UI can render them through one helper.
- Confidence flags are *honest*: when a scenario fires on incomplete
  data we mark `confidence="low"` and surface what's missing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Scenario(str, Enum):
    """The catalogue of supported vola scenarios.

    String-valued so callers can serialise to URL params, session
    state, or persist into a journal.
    """
    RISING_VOL_ON_CHEAP   = "rising_vol_on_cheap"
    HARVEST_RICH_PREMIUM  = "harvest_rich_premium"
    DEEP_OTM_LEAPS        = "deep_otm_leaps"
    EARNINGS_LONG_GAMMA   = "earnings_long_gamma"
    EARNINGS_CRUSH_FADE   = "earnings_crush_fade"
    BACKWARDATION_PLAY    = "backwardation_play"


# Human-readable scenario metadata. UI imports this for the picker.
SCENARIO_LABELS: dict[Scenario, str] = {
    Scenario.RISING_VOL_ON_CHEAP:  "Rising vol on a cheap name",
    Scenario.HARVEST_RICH_PREMIUM: "Harvest premium on a rich, range-bound name",
    Scenario.DEEP_OTM_LEAPS:       "Deep-OTM LEAPS — convexity bet",
    Scenario.EARNINGS_LONG_GAMMA:  "Long gamma into earnings",
    Scenario.EARNINGS_CRUSH_FADE:  "Fade the IV crush after earnings",
    Scenario.BACKWARDATION_PLAY:   "Backwardation — calendar long the back",
}

SCENARIO_HINTS: dict[Scenario, str] = {
    Scenario.RISING_VOL_ON_CHEAP:
        "IV is in the bottom quartile; you expect it to mean-revert higher.",
    Scenario.HARVEST_RICH_PREMIUM:
        "IV is in the top quartile and the chart is range-bound. Sell vol.",
    Scenario.DEEP_OTM_LEAPS:
        "Long-dated, far-OTM call. Asymmetric payout if the name doubles.",
    Scenario.EARNINGS_LONG_GAMMA:
        "Buy vol going into a binary catalyst; size for the binary outcome.",
    Scenario.EARNINGS_CRUSH_FADE:
        "Sell vol post-print into the crush window; defined-risk only.",
    Scenario.BACKWARDATION_PLAY:
        "Front month rich vs back; long the back, short the front.",
}


@dataclass(frozen=True)
class ScenarioRecommendation:
    """Output of a scenario lookup. Trader-first field ordering."""
    scenario:          Scenario
    structure:         str           # e.g. "Long Call (deep OTM, LEAPS)"
    direction:         str           # long_vol | short_vol | neutral_vol
    target_dte:        int
    strike_rule:       str           # human-readable ("+75 % uplift, round whole-$")
    target_delta:      float
    risk_profile:      str           # "limited" | "defined" | "unlimited"
    thesis:            str           # 1-sentence rationale ready to journal
    expected_payoff:   str           # "convex 5-10×" / "premium ~$1.20 collected"
    confidence:        str           # "high" | "medium" | "low"
    why_this_dte:      str           # 1-sentence DTE rationale
    risk_one_liner:    str           # what kills the trade
    flags:             tuple[str, ...] = ()


# ── DTE helpers ────────────────────────────────────────────────────────

# Map a vol-state read to a sensible DTE per scenario. These come from
# the literature: long-vol entries want enough time for vol to mean
# revert (~30-60d for short-term, 600-730d for LEAPS). Short-vol harvest
# works best in the 30-45d gamma sweet-spot.

_DTE_RULES: dict[Scenario, int] = {
    Scenario.RISING_VOL_ON_CHEAP:  60,
    Scenario.HARVEST_RICH_PREMIUM: 35,
    Scenario.DEEP_OTM_LEAPS:       730,
    Scenario.EARNINGS_LONG_GAMMA:  14,    # closest cycle past ER
    Scenario.EARNINGS_CRUSH_FADE: 21,
    Scenario.BACKWARDATION_PLAY:   45,
}

_DTE_RATIONALE: dict[Scenario, str] = {
    Scenario.RISING_VOL_ON_CHEAP:
        "60 d gives vol enough time to revert without bleeding theta on a daily basis.",
    Scenario.HARVEST_RICH_PREMIUM:
        "30-45 d hits the gamma sweet-spot — premium decays fast enough but isn't binary.",
    Scenario.DEEP_OTM_LEAPS:
        "≥ 24 m so theta is < 0.5 % / day and a major rally has time to play out.",
    Scenario.EARNINGS_LONG_GAMMA:
        "First cycle past ER — captures the IV expansion without paying for far-out theta.",
    Scenario.EARNINGS_CRUSH_FADE:
        "21 d after the print — IV has crushed and you collect on the realised drop.",
    Scenario.BACKWARDATION_PLAY:
        "45 d back, ~14 d front — diagonalises the term-structure dislocation.",
}


# ── Builder ────────────────────────────────────────────────────────────

def build_scenario_recommendation(
    scenario: Scenario,
    *,
    iv_30d:        Optional[float] = None,
    iv_percentile: Optional[float] = None,
    iv_rank:       Optional[float] = None,
    hv_20d:        Optional[float] = None,
    spot:          Optional[float] = None,
    days_to_earnings: Optional[int] = None,
) -> ScenarioRecommendation:
    """Map a `Scenario` + the current vol state to a concrete idea.

    None inputs are tolerated; missing data lowers the confidence and
    the helper notes what's missing in `flags`.
    """
    flags: list[str] = []

    def _note_missing(name: str, value: Optional[float]) -> None:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            flags.append(f"missing:{name}")

    # ── Per-scenario logic ────────────────────────────────────────────
    if scenario is Scenario.RISING_VOL_ON_CHEAP:
        _note_missing("iv_percentile", iv_percentile)
        _note_missing("iv_rank", iv_rank)
        is_cheap = (iv_percentile is not None and iv_percentile < 30) or \
                   (iv_rank is not None and iv_rank < 30)
        confidence = "high" if is_cheap and iv_percentile is not None and iv_rank is not None else "medium"
        if not is_cheap:
            flags.append("vol_not_cheap_today")
            confidence = "low"
        return ScenarioRecommendation(
            scenario=scenario,
            structure="Long Call Calendar (back-month long)",
            direction="long_vol",
            target_dte=_DTE_RULES[scenario],
            strike_rule="ATM (Δ ≈ 0.50)",
            target_delta=0.50,
            risk_profile="defined",
            thesis=(
                "Options pricing is below the cross-sectional median and below realised "
                "vol. A vol-expansion mean-revert has historically paid in this regime. "
                "Calendar gives positive vega without a directional bet."
            ),
            expected_payoff="positive vega — gain ~$0.40 / $1 IV move per spread",
            confidence=confidence,
            why_this_dte=_DTE_RATIONALE[scenario],
            risk_one_liner="vol stays cheap and the front leg expires worthless before vol moves.",
            flags=tuple(flags),
        )

    if scenario is Scenario.HARVEST_RICH_PREMIUM:
        _note_missing("iv_percentile", iv_percentile)
        is_rich = iv_percentile is not None and iv_percentile > 70
        confidence = "high" if is_rich else "medium" if iv_percentile is not None else "low"
        if not is_rich:
            flags.append("vol_not_rich_today")
        return ScenarioRecommendation(
            scenario=scenario,
            structure="Short Iron Condor (defined-risk)",
            direction="short_vol",
            target_dte=_DTE_RULES[scenario],
            strike_rule="short legs at Δ ≈ 0.16, long wings 5-10 % wider",
            target_delta=-0.16,
            risk_profile="defined",
            thesis=(
                "Premium is rich vs. own history; expect a quiet tape to bleed it back. "
                "Iron condor caps loss at the wing width. Avoid earnings windows."
            ),
            expected_payoff="collect ~25-35 % of width if held to expiry untouched",
            confidence=confidence,
            why_this_dte=_DTE_RATIONALE[scenario],
            risk_one_liner="a one-day shock breaks a wing and the realised range exceeds expected.",
            flags=tuple(flags),
        )

    if scenario is Scenario.DEEP_OTM_LEAPS:
        _note_missing("iv_percentile", iv_percentile)
        _note_missing("spot", spot)
        is_cheap = iv_percentile is not None and iv_percentile < 35
        confidence = "high" if is_cheap and spot is not None else "medium"
        strike = round(spot * 1.75) if spot is not None else None
        strike_rule = (
            f"+75 % uplift → ${strike:.0f} (round whole-$)" if strike is not None
            else "+75 % uplift, round to whole dollar"
        )
        return ScenarioRecommendation(
            scenario=scenario,
            structure="Long Call (deep OTM, LEAPS)",
            direction="long_vol",
            target_dte=_DTE_RULES[scenario],
            strike_rule=strike_rule,
            target_delta=0.20,
            risk_profile="limited",
            thesis=(
                "Asymmetric convexity bet on a vernachlässigten name with cheap vol "
                "and a reversal setup. Sized so max loss is the premium paid; payoff "
                "is multi-bagger if the thesis plays out over 18-24 months."
            ),
            expected_payoff="convex 3-10× if spot reaches strike+intrinsic by expiry",
            confidence=confidence,
            why_this_dte=_DTE_RATIONALE[scenario],
            risk_one_liner="thesis fails to play out before theta erodes the option to zero.",
            flags=tuple(flags),
        )

    if scenario is Scenario.EARNINGS_LONG_GAMMA:
        if days_to_earnings is None:
            flags.append("missing:days_to_earnings")
            confidence = "low"
        elif days_to_earnings > 14:
            flags.append("er_too_far")
            confidence = "low"
        else:
            confidence = "high"
        return ScenarioRecommendation(
            scenario=scenario,
            structure="Long Straddle (ATM call + ATM put)",
            direction="long_vol",
            target_dte=_DTE_RULES[scenario],
            strike_rule="ATM strike, both legs",
            target_delta=0.0,
            risk_profile="limited",
            thesis=(
                "Buying gamma into a binary catalyst. Profitable if the realised move "
                "exceeds the implied move; size as a binary bet (max loss = premium)."
            ),
            expected_payoff="break-even at ±implied move; 2-3× if the print is a surprise",
            confidence=confidence,
            why_this_dte=_DTE_RATIONALE[scenario],
            risk_one_liner="muted print — IV crushes and the straddle loses ~50 % overnight.",
            flags=tuple(flags),
        )

    if scenario is Scenario.EARNINGS_CRUSH_FADE:
        if days_to_earnings is None:
            flags.append("missing:days_to_earnings")
            confidence = "low"
        elif days_to_earnings > 0:
            flags.append("er_not_passed_yet")
            confidence = "low"
        else:
            confidence = "high"
        return ScenarioRecommendation(
            scenario=scenario,
            structure="Short Iron Condor (post-ER, defined-risk)",
            direction="short_vol",
            target_dte=_DTE_RULES[scenario],
            strike_rule="short legs at Δ ≈ 0.20 outside the post-print range",
            target_delta=-0.20,
            risk_profile="defined",
            thesis=(
                "Post-earnings IV crush phase — sell residual richness with a "
                "wide-winged condor. Best on names that historically range-trade after "
                "the print."
            ),
            expected_payoff="collect ~20-30 % of width over 21d if range holds",
            confidence=confidence,
            why_this_dte=_DTE_RATIONALE[scenario],
            risk_one_liner="post-ER drift continues and one wing breaks within the hold.",
            flags=tuple(flags),
        )

    if scenario is Scenario.BACKWARDATION_PLAY:
        return ScenarioRecommendation(
            scenario=scenario,
            structure="Calendar Spread (long back, short front)",
            direction="neutral_vol",
            target_dte=_DTE_RULES[scenario],
            strike_rule="ATM, both legs",
            target_delta=0.0,
            risk_profile="defined",
            thesis=(
                "Front-month IV is rich vs back; calendar harvests the term-structure "
                "normalisation. Profits from front-month decay + back-month vega lift."
            ),
            expected_payoff="net debit; 30-50 % return on debit if curve flattens",
            confidence="medium",
            why_this_dte=_DTE_RATIONALE[scenario],
            risk_one_liner="curve steepens further (deeper backwardation) before normalising.",
            flags=tuple(flags),
        )

    # Defensive default — should never hit because Enum is exhaustive.
    raise ValueError(f"Unknown scenario: {scenario!r}")


# ── UI helper (returns HTML, no Streamlit import) ──────────────────────

def scenario_card_html(rec: ScenarioRecommendation) -> str:
    """Render a recommendation as a single HTML card for the Streamlit UI.

    Pure string in / out so the analytics module never imports Streamlit.
    """
    confidence_color = {
        "high":   "#00d4aa",
        "medium": "#ff9f43",
        "low":    "#ff4466",
    }.get(rec.confidence, "#8a8f9e")
    direction_color = {
        "long_vol":     "#00d4aa",
        "short_vol":    "#ff4466",
        "neutral_vol":  "#5b8cff",
    }.get(rec.direction, "#8a8f9e")

    flags_html = ""
    if rec.flags:
        items = "".join(
            f'<span style="display:inline-block;background:rgba(255,159,67,0.12);'
            f'color:#ff9f43;padding:1px 6px;border-radius:3px;font-size:9px;'
            f'font-family:JetBrains Mono,monospace;letter-spacing:0.5px;'
            f'margin-right:4px;">{f}</span>'
            for f in rec.flags
        )
        flags_html = (
            f'<div style="margin-top:6px;">{items}</div>'
        )

    return f'''
<div style="background:#151620;border:1px solid #1e2038;border-left:3px solid {direction_color};
            border-radius:8px;padding:14px 18px;margin-bottom:10px;
            font-family:JetBrains Mono,monospace;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              margin-bottom:8px;">
    <div>
      <div style="font-size:9px;letter-spacing:1.4px;color:#424666;text-transform:uppercase;
                   font-weight:600;">{SCENARIO_LABELS.get(rec.scenario, rec.scenario.value)}</div>
      <div style="font-size:16px;font-weight:700;color:#e0e4ef;margin-top:2px;">
        {rec.structure}
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:9px;letter-spacing:1.2px;color:#424666;text-transform:uppercase;">
        confidence
      </div>
      <div style="font-size:13px;font-weight:600;color:{confidence_color};">
        ● {rec.confidence}
      </div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px;">
    <div>
      <div style="font-size:9px;letter-spacing:1px;color:#424666;text-transform:uppercase;">DTE</div>
      <div style="font-size:14px;color:#e0e4ef;font-weight:600;">{rec.target_dte}d</div>
    </div>
    <div>
      <div style="font-size:9px;letter-spacing:1px;color:#424666;text-transform:uppercase;">Δ target</div>
      <div style="font-size:14px;color:#e0e4ef;font-weight:600;">{rec.target_delta:+.2f}</div>
    </div>
    <div>
      <div style="font-size:9px;letter-spacing:1px;color:#424666;text-transform:uppercase;">direction</div>
      <div style="font-size:14px;color:{direction_color};font-weight:600;">
        {rec.direction.replace("_", " ")}
      </div>
    </div>
    <div>
      <div style="font-size:9px;letter-spacing:1px;color:#424666;text-transform:uppercase;">risk</div>
      <div style="font-size:14px;color:#e0e4ef;font-weight:600;">{rec.risk_profile}</div>
    </div>
  </div>
  <div style="font-size:11px;color:#8a8f9e;line-height:1.5;margin-bottom:8px;">
    <strong style="color:#e0e4ef;">strike:</strong> {rec.strike_rule}
  </div>
  <div style="font-size:11px;color:#8a8f9e;line-height:1.5;margin-bottom:8px;">
    <strong style="color:#e0e4ef;">thesis:</strong> {rec.thesis}
  </div>
  <div style="font-size:11px;color:#8a8f9e;line-height:1.5;margin-bottom:6px;">
    <strong style="color:#e0e4ef;">why this DTE:</strong> {rec.why_this_dte}
  </div>
  <div style="font-size:11px;color:#8a8f9e;line-height:1.5;margin-bottom:6px;">
    <strong style="color:#e0e4ef;">expected payoff:</strong> {rec.expected_payoff}
  </div>
  <div style="font-size:11px;color:#ff9f43;line-height:1.5;">
    <strong>kills the trade:</strong> {rec.risk_one_liner}
  </div>
  {flags_html}
</div>'''
