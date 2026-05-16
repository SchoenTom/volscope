"""Single-source-of-truth glossary for VolScope KPI tooltips.

Every page that displays one of these KPIs should pull its tooltip
text from here via ``glossary(key)``. Centralisation guarantees:

  - One sentence per term, written in plain language (newbie-readable)
  - Consistent wording across pages (no two places explaining IV
    Rank differently)
  - Easy expansion: add a term once, every page that calls
    ``glossary('iv_rank')`` picks up the new text

Usage::

    from volscope.ui.components.glossary import glossary
    st.dataframe(df, help=glossary("iv_rank"))

For interactive tooltips on custom HTML, pass ``title="…"`` to the
rendered element with the glossary value.

Style guide:
  - One short paragraph (≤ 2 sentences)
  - First sentence = what the term IS (the math, plain)
  - Second sentence = how to READ the current value (operator's
    decision rule)
  - No jargon without inline definition
"""
from __future__ import annotations

GLOSSARY: dict[str, str] = {
    # ── Vol metrics ─────────────────────────────────────────────────
    "iv_rank": (
        "IV Rank — where today's implied volatility sits in the last 52 "
        "weeks' range, 0–100. >50 = options are pricier than this name's "
        "own mid-year level; <30 = options are cheap by its own history."
    ),
    "iv_percentile": (
        "IV Percentile — the share of trading days in the last 252 where "
        "IV was BELOW today's level (0–100). 80 means today is in the "
        "richest 20% of the past year; 20 means in the cheapest fifth."
    ),
    "iv_30d": (
        "IV-30d — the option market's expected annualised vol over the "
        "next 30 days, computed from the at-the-money 30-day chain. "
        "Higher = market is paying up for protection / speculation."
    ),
    "iv_60d": (
        "IV-60d — annualised expected vol over the next 60 days from "
        "the 60-day ATM chain. Compared with IV-30d this isolates the "
        "term-structure slope: IV30 > IV60 = front-loaded event risk."
    ),
    "iv_90d": (
        "IV-90d — annualised expected vol from the 90-day ATM chain. "
        "The back-month anchor for earnings-premium decomposition: "
        "back-IV reflects post-event diffusion vol."
    ),
    "iv_skew_25d": (
        "25-delta skew — IV(25Δ Put) − IV(25Δ Call) in vol points. "
        "Positive = market pricing puts richer than calls (downside fear); "
        "+30 and above is extreme put-skew typical of pre-earnings prints."
    ),
    "iv_hv_spread": (
        "IV − HV spread — implied vol minus realised vol, in vol points. "
        "Positive = options are pricier than recent realised moves (short-"
        "premium edge); negative = realised has been higher than implied "
        "(long-premium edge)."
    ),
    "iv_hv_spread_matched": (
        "Matched-horizon IV − HV spread — uses 30-day IV against "
        "30-day Yang-Zhang HV (same time-horizon both sides). The "
        "academically-correct version of the IV/HV spread; less noisy "
        "than the 30d-vs-20d default."
    ),
    "hv_20d": (
        "HV-20d — annualised vol of close-to-close log returns over the "
        "last 20 trading days. The simplest realised-vol baseline; "
        "compared with IV gives the variance risk premium."
    ),
    "hv_yz_20d": (
        "HV (Yang-Zhang, 20d) — Yang-Zhang 2000 estimator using OHLC. "
        "Drift-independent and uses intraday high/low, so it has lower "
        "variance than close-to-close. Default HV in VolScope."
    ),
    "hv_yz_30d": (
        "HV (Yang-Zhang, 30d) — 30-day matched-horizon companion to "
        "IV-30d. The apples-to-apples partner for IV in spread-based "
        "decisions; used for iv_hv_spread_matched."
    ),

    # ── Vol regime ──────────────────────────────────────────────────
    "vol_regime": (
        "Vol Regime — six-state HMM classifier: CRUSHED, CHEAP, FAIR, "
        "RICH, EXTREME, CRISIS. Computed from IV-30, HV, IV-Rank + a "
        "VIX>40-OR-|IV-HV|>15 override. Tells you the trading-style "
        "appropriate for current conditions."
    ),

    # ── Expected move ──────────────────────────────────────────────
    "expected_move": (
        "Expected Move — the one-σ daily move priced into the option "
        "chain: spot × ATM-IV × √(DTE/365). The straddle break-even; "
        "moves outside this band were not expected by the option market."
    ),
    "expected_move_skew_adjusted": (
        "Skew-adjusted Expected Move — asymmetric one-σ move using the "
        "25Δ Call IV upside and 25Δ Put IV downside separately. Puts the "
        "market's downside-vs-upside imbalance directly into the move "
        "band — symmetric EM hides this."
    ),
    "event_premium_iv": (
        "Event-premium IV — the implied vol attributed to a single event "
        "day, isolated from ambient diffusion vol via variance additivity "
        "(σ²_front · T_front − σ²_back · T_diffusion = σ²_event · T_event). "
        "Above 100 = market pricing a binary catalyst."
    ),

    # ── Position metrics ───────────────────────────────────────────
    "aufgeld": (
        "Aufgeld — premium-over-intrinsic as a percent of spot. For a "
        "long call: (strike + premium − spot) / spot × 100. Measures how "
        "far the underlying must move to break even at expiry."
    ),
    "aufgeld_pa": (
        "Aufgeld p.a. — Aufgeld × 365 / DTE. Annualises the time-decay "
        "cost; lets you compare premium expensiveness across tenors on "
        "equal footing."
    ),
    "break_even": (
        "Break-even spot — the underlying price at expiry where the "
        "option's payoff exactly equals what you paid. For a long call: "
        "strike + premium. The move-percent you need from today's spot "
        "to recover the premium."
    ),
    "delta": (
        "Delta — change in option price per $1 change in the underlying, "
        "in 0..1 (calls) or −1..0 (puts). 0.25 ≈ 1-in-4 chance of "
        "expiring in-the-money under BSM."
    ),

    # ── Position sizing ────────────────────────────────────────────
    "kelly_fraction": (
        "Kelly fraction — the position-size proportion that maximises "
        "long-run log-wealth growth given an edge. VolScope uses "
        "quarter-Kelly (0.25) by default to compress drawdowns at the "
        "cost of 50 % of theoretical growth — empirically more survivable."
    ),

    # ── OI metrics ─────────────────────────────────────────────────
    "max_pain": (
        "Max-pain strike — the strike at which total intrinsic option "
        "payoff is minimised. Empirically option markets tend to drift "
        "toward max-pain on expiry (statistically weak, operationally "
        "useful as a short-premium magnet)."
    ),
    "put_call_ratio": (
        "Put / Call ratio — total put OI divided by total call OI. "
        ">1 = more put-positioning (bearish hedging); ~0.7 is the "
        "long-run baseline for large-cap US equities."
    ),
    "total_open_interest": (
        "Open Interest — number of option contracts currently held by "
        "market participants. Big OI = deep liquidity + meaningful "
        "positioning; small OI = stale or illiquid chain."
    ),
}


def glossary(key: str) -> str:
    """Return the tooltip text for a KPI key, or empty string if unknown.

    Empty-string fallback means a missing tooltip degrades silently —
    the page renders without a "?" icon rather than crashing.
    """
    return GLOSSARY.get(key, "")
