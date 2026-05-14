"""
Single source of truth for VolScope terminology.

Every widget that needs ``help="..."`` should reach for ``tooltip(term)``
here, not hard-code a definition. One fix point, no drift across 17
Streamlit pages. Adding a new term: append to ``GLOSSARY`` + the
tests/test_glossary.py asserts it's referenced somewhere.

Style guide for definitions:
- One sentence, ≤ 100 chars where possible.
- Lead with the term name; close with the operational meaning.
- No flowery language; no exclamation marks.
"""
from __future__ import annotations

GLOSSARY: dict[str, str] = {
    # ── Volatility ────────────────────────────────────────────────
    "IV": "Implied Volatility — vol implied by current option prices.",
    "IV30": "30-day at-the-money implied volatility.",
    "IV60": "60-day at-the-money implied volatility.",
    "IV90": "90-day at-the-money implied volatility.",
    "HV": "Historical Volatility — annualised σ of realised daily returns.",
    "HV20": "20-day historical volatility (Yang-Zhang).",
    "RV": "Realised Volatility — synonym for HV in most contexts.",
    "IVR": (
        "IV Rank — where current IV sits in its 52-week MIN-MAX range "
        "(0-100). Vulnerable to single-spike contamination."
    ),
    "IVP": (
        "IV Percentile — fraction of trailing days with IV below today's "
        "(0-100). Rank-based; spike-immune."
    ),
    "VRP": (
        "Volatility Risk Premium — IV minus realised vol. Positive ~85% "
        "of months (Bali 2008)."
    ),
    "Skew": (
        "25-Δ Risk Reversal — IV(25Δ call) − IV(25Δ put). Negative is "
        "the normal equity skew (puts richer than calls)."
    ),
    "Robust IVR": (
        "IV Rank computed with 5th/95th percentile bounds instead of "
        "MIN/MAX. Use when standard IVR is contaminated by a single spike."
    ),
    # ── Greeks ─────────────────────────────────────────────────────
    "Delta": (
        "Δ — sensitivity of option price to a $1 change in the underlying. "
        "Calls: 0 to 1; puts: -1 to 0."
    ),
    "Gamma": (
        "Γ — rate of change of delta. Highest near ATM near expiry; "
        "magnifies P&L swings inside 21 DTE."
    ),
    "Vega": (
        "ν — sensitivity to a 1.00 change in implied volatility. Long "
        "options have positive vega."
    ),
    "Theta": (
        "Θ — time decay. Value lost per day. Short premium trades collect "
        "theta; long trades pay it."
    ),
    "Rho": (
        "ρ — sensitivity to a 1% change in the risk-free rate. Usually "
        "the smallest greek."
    ),
    # ── Market structure ──────────────────────────────────────────
    "DTE": "Days to Expiration.",
    "ATM": "At-The-Money — strike near current spot.",
    "ITM": "In-The-Money — call: strike below spot; put: strike above spot.",
    "OTM": "Out-of-the-Money — call: strike above spot; put: strike below spot.",
    "BAS": "Bid-Ask Spread.",
    "OI": "Open Interest — number of outstanding option contracts at a strike.",
    "ADV": "Average Daily Volume.",
    "Term Structure": (
        "Slope of the IV curve across expiries. Contango means far-dated "
        "IV exceeds near-dated; backwardation means the reverse (a near-"
        "term stress signal)."
    ),
    # ── Regime + signal engine ────────────────────────────────────
    "Regime": (
        "HMM-detected market state: calm (low realised vol) or stress "
        "(elevated realised vol). 2-state Gaussian model."
    ),
    "p_calm": (
        "Probability the most recent observation belongs to the calm "
        "regime. Short-vol entries require p_calm > 0.6."
    ),
    "Composite Score": (
        "0-100 weighted blend of IVR / IVP / VRP / term / skew / "
        "momentum / regime. Maps to sizing fraction."
    ),
    "TRIPLE_CHEAP": (
        "Signal type: IV Perc < 20 AND IV/HV < 0.75. Options are "
        "objectively cheap. Favours long-vol entries."
    ),
    "TRIPLE_RICH": (
        "Signal type: IV Perc > 80 AND IV/HV > 1.20. Options are "
        "objectively rich. Favours short-vol entries (with gates)."
    ),
    # ── Risk + execution ──────────────────────────────────────────
    "POP": (
        "Probability of Profit — chance the trade closes profitable. "
        "Approximate for combos."
    ),
    "POT": (
        "Probability of Touch — chance the underlying touches a price "
        "before expiry. ≈ 2 × (1 − N(d2)) for an OTM strike."
    ),
    "Kelly": (
        "Position sizing fraction = μ/σ². Quarter-Kelly (0.25) is the "
        "production-safe default; full Kelly breaks on fat tails."
    ),
    "BPR": "Buying Power Reduction — capital tied up by a trade.",
    "PT": "Profit Target — close at X% of max profit. 50% is the canonical short-vol target.",
    "Earnings Blackout": (
        "14-day window before earnings where short-vol entries are "
        "blocked (IV expands into the event, then crushes after)."
    ),
    # ── Bot specific ──────────────────────────────────────────────
    "Quality Score": (
        "0-100 composite. Deducts for IVR/IVP contamination + recent "
        "structural break + insufficient data. ≥70 trade · 40-69 caution · <40 block."
    ),
    "Structural Break": (
        "Permanent regime shift in IV (forecast reset, M&A, FDA). "
        "Pre-break history is NOT predictive of current state."
    ),
    "Contamination": (
        "When |IVR − IVP| > 30 — a single extreme spike inflated the "
        "52-week range. Trust IVP over IVR."
    ),
    "Audit Chain": (
        "SHA-256 prev_hash chain of every signal / order / fill / kill. "
        "Tamper-evident. Used for §147 AO 10-year compliance."
    ),
    "Kill Switch": (
        "Three manual + five auto trip paths that halt new entries + "
        "selectively close undefined-risk positions."
    ),
}


def tooltip(term: str) -> str:
    """
    Return the canonical tooltip for ``term``. Empty string if unknown.

    Used in widget calls::

        st.selectbox("Strategy", ..., help=tooltip("IVR"))

    A missing term silently returns "" — never crashes the UI — but
    tests in tests/test_glossary.py assert every reachable
    ``tooltip(...)`` call passes a key that exists.
    """
    return GLOSSARY.get(term, "")


__all__ = ["GLOSSARY", "tooltip"]
