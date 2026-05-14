"""
Strategy Recommender — vol-state to multi-leg structure mapping.

VolScope already knows whether vol is *cheap* or *rich* (Edge Score, VRP,
ML signal). The next hedge-fund-grade question is: *given that, which
options structure should I actually trade?* This module makes that
mapping explicit.

Inputs (all already available from earlier analytics modules):
  - edge_score         : 0..100 long-vol entry edge
  - iv_percentile      : 0..100, current vs own annual history
  - skew_25            : 25Δ skew in vol points (put_iv − call_iv at ±25Δ)
  - term_slope         : iv_60d − iv_30d (positive = contango, negative = backwardation)
  - days_to_earnings   : days until next ER, or None
  - has_long_history   : True if backtest history is sufficient

Output: a ranked list of ``StrategyRec`` objects. Each rec includes the
structure name, a 1-sentence thesis, an estimated risk profile, and
hint parameters (delta target, days-to-expiry target). The UI layer
combines these recs with live option-chain data to produce concrete
strikes.

This module is pure rules — no ML, no DB, no scraper. Add ML scoring
later by passing a ``ml_buy_prob`` and weighting the recs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Structure catalogue ──────────────────────────────────────────────────

# Each catalogue entry maps to a hedge-fund-recognisable name + hint params.

@dataclass(frozen=True)
class StrategyRec:
    """One strategy recommendation.

    Attributes
    ----------
    name           : Strategy label (e.g., "Long Put Spread", "Short Iron Condor").
    thesis         : 1-sentence rationale explaining when to use it.
    risk_profile   : "limited" | "defined" | "unlimited".
    direction      : "long_vol" | "short_vol" | "neutral_vol".
    target_delta   : Suggested delta for the leading leg, e.g. -0.30 for long put.
    target_dte     : Suggested days-to-expiry for primary leg.
    legs           : List of leg descriptions (used by Pre-Trade UI).
    score          : Recommendation score 0..100.
    flags          : Optional warnings ("earnings within 5 days", ...).
    """
    name:         str
    thesis:       str
    risk_profile: str
    direction:    str
    target_delta: float
    target_dte:   int
    legs:         tuple[str, ...]
    score:        float
    flags:        tuple[str, ...] = ()


# ── Configuration thresholds ─────────────────────────────────────────────

_PERC_VERY_CHEAP    = 20.0
_PERC_CHEAP         = 35.0
_PERC_RICH          = 65.0
_PERC_VERY_RICH     = 80.0

_SKEW_PUT_RICH      = 4.0    # vol pts; high put-side richness
_SKEW_NEUTRAL_BAND  = 1.5
_TERM_BACKWARDATION = -2.0
_TERM_CONTANGO      = +2.0

_ER_NEAR_DAYS       = 7

_EDGE_STRONG        = 70.0
_EDGE_LEAN          = 55.0


# ── Main entry point ─────────────────────────────────────────────────────

from volscope.utils.timing import instrumented  # noqa: E402


@instrumented("analytics.strategy_recommender")
def recommend_strategies(
    edge_score:       Optional[float] = None,
    iv_percentile:    Optional[float] = None,
    skew_25:          Optional[float] = None,
    term_slope:       Optional[float] = None,
    days_to_earnings: Optional[int] = None,
    has_long_history: bool = True,
) -> list[StrategyRec]:
    """Return ranked StrategyRecs for the given vol state.

    Always returns a non-empty list (worst case: a single "WAIT" placeholder).
    Higher-score recs sort first.
    """
    es = _safe_float(edge_score)
    pc = _safe_float(iv_percentile)
    sk = _safe_float(skew_25)
    ts = _safe_float(term_slope)

    flags = _compute_flags(days_to_earnings)
    has_er_near = "earnings_near" in flags

    recs: list[StrategyRec] = []

    # ── Long-vol structures (cheap regime) ───────────────────────────
    if pc is not None and pc < _PERC_VERY_CHEAP:
        recs.append(_long_put_spread(es, pc, flags))
        recs.append(_long_calendar(es, ts, flags))
        if sk is not None and sk < _SKEW_NEUTRAL_BAND:
            recs.append(_long_risk_reversal(es, sk, flags))
    elif pc is not None and pc < _PERC_CHEAP:
        recs.append(_long_put_spread(es, pc, flags, lean=True))
        if ts is not None and ts < _TERM_BACKWARDATION:
            recs.append(_calendar_backwardation_play(ts, flags))

    # ── Short-vol structures (rich regime) ──────────────────────────
    if pc is not None and pc > _PERC_VERY_RICH:
        recs.append(_short_iron_condor(es, pc, flags))
        recs.append(_short_strangle(es, pc, flags))
    elif pc is not None and pc > _PERC_RICH and not has_er_near:
        recs.append(_short_iron_condor(es, pc, flags, lean=True))

    # ── Skew-driven trades ──────────────────────────────────────────
    if sk is not None and sk > _SKEW_PUT_RICH:
        recs.append(_short_risk_reversal(sk, flags))

    # ── Term-structure trades ───────────────────────────────────────
    if ts is not None and ts > _TERM_CONTANGO and pc is not None and _PERC_CHEAP <= pc <= _PERC_RICH:
        recs.append(_calendar_carry_play(ts, flags))

    # ── Earnings-driven trades (regardless of regime) ────────────────
    if has_er_near and pc is not None and pc < _PERC_CHEAP:
        recs.append(_earnings_long_straddle(pc, days_to_earnings, flags))
    elif has_er_near and pc is not None and pc > _PERC_RICH:
        recs.append(_earnings_iron_condor(pc, days_to_earnings, flags))

    # ── Empty fallback ──────────────────────────────────────────────
    if not recs:
        recs.append(_wait_rec(es, pc, flags))

    if not has_long_history:
        recs = [
            StrategyRec(
                name=r.name, thesis=r.thesis, risk_profile=r.risk_profile,
                direction=r.direction, target_delta=r.target_delta,
                target_dte=r.target_dte, legs=r.legs,
                score=max(0.0, r.score - 10.0),
                flags=r.flags + ("limited backtest history",),
            )
            for r in recs
        ]

    recs.sort(key=lambda r: r.score, reverse=True)
    return recs


# ── Strategy builders ────────────────────────────────────────────────────

def _long_put_spread(
    edge: Optional[float],
    perc: Optional[float],
    flags: tuple[str, ...],
    lean: bool = False,
) -> StrategyRec:
    perc_v = perc if perc is not None else 50.0
    score = 70.0 + max(0.0, (40.0 - perc_v) * 1.0) + (
        15.0 if (edge is not None and edge >= _EDGE_STRONG) else 0.0
    )
    if lean:
        score *= 0.7
    return StrategyRec(
        name="Long Put Spread",
        thesis=(
            "Buy a put spread (long ATM, short OTM) — defined-risk long-vol "
            "expression for cheap-IV regimes."
        ),
        risk_profile="defined",
        direction="long_vol",
        target_delta=-0.40,
        target_dte=60,
        legs=(
            "Long put @ −40Δ",
            "Short put @ −15Δ (same expiry)",
        ),
        score=min(100.0, score),
        flags=flags,
    )


def _long_calendar(
    edge: Optional[float],
    term_slope: Optional[float],
    flags: tuple[str, ...],
) -> StrategyRec:
    score = 55.0
    if term_slope is not None and term_slope > _TERM_CONTANGO:
        score += 20.0
    return StrategyRec(
        name="Long Calendar Spread",
        thesis=(
            "Sell near-month, buy back-month at same strike — collect near-term "
            "theta, retain long-vega for the medium term."
        ),
        risk_profile="defined",
        direction="neutral_vol",
        target_delta=-0.50,   # ATM
        target_dte=30,
        legs=(
            "Short put/call @ −50Δ, 30 DTE",
            "Long put/call same strike, 90 DTE",
        ),
        score=min(100.0, score),
        flags=flags,
    )


def _long_risk_reversal(
    edge: Optional[float],
    skew: Optional[float],
    flags: tuple[str, ...],
) -> StrategyRec:
    score = 60.0
    if skew is not None and skew < 0:
        score += 15.0    # negative skew → puts cheap → more attractive RR
    return StrategyRec(
        name="Long Risk Reversal",
        thesis=(
            "Long put + short call (same delta) — synthetic short on the "
            "underlying with cheap skew tailwind."
        ),
        risk_profile="unlimited",
        direction="long_vol",
        target_delta=-0.30,
        target_dte=60,
        legs=(
            "Long put @ −25Δ",
            "Short call @ +25Δ (same expiry)",
        ),
        score=min(100.0, score),
        flags=flags,
    )


def _short_iron_condor(
    edge: Optional[float],
    perc: Optional[float],
    flags: tuple[str, ...],
    lean: bool = False,
) -> StrategyRec:
    perc_v = perc if perc is not None else 50.0
    score = 65.0 + max(0.0, (perc_v - 60.0) * 0.8)
    if lean:
        score *= 0.7
    return StrategyRec(
        name="Short Iron Condor",
        thesis=(
            "Sell call spread + put spread, same expiry — bet on mean reversion "
            "from rich IV; defined risk, theta-positive."
        ),
        risk_profile="defined",
        direction="short_vol",
        target_delta=0.16,
        target_dte=45,
        legs=(
            "Short call @ +16Δ",
            "Long call @ +5Δ",
            "Short put @ −16Δ",
            "Long put @ −5Δ (all same expiry)",
        ),
        score=min(100.0, score),
        flags=flags,
    )


def _short_strangle(
    edge: Optional[float],
    perc: Optional[float],
    flags: tuple[str, ...],
) -> StrategyRec:
    return StrategyRec(
        name="Short Strangle",
        thesis=(
            "Sell call + put at ±20Δ — undefined risk, max premium collection "
            "in extreme-IV regimes; require strict stops."
        ),
        risk_profile="unlimited",
        direction="short_vol",
        target_delta=0.20,
        target_dte=45,
        legs=(
            "Short call @ +20Δ",
            "Short put @ −20Δ (same expiry)",
        ),
        score=70.0,
        flags=flags + ("undefined risk — use stops",),
    )


def _short_risk_reversal(
    skew: Optional[float],
    flags: tuple[str, ...],
) -> StrategyRec:
    return StrategyRec(
        name="Short Risk Reversal",
        thesis=(
            "Sell rich put-side skew, buy cheap call-side — bet on skew "
            "normalisation when 25Δ skew >> historical mean."
        ),
        risk_profile="unlimited",
        direction="neutral_vol",
        target_delta=0.25,
        target_dte=45,
        legs=(
            "Short put @ −25Δ",
            "Long call @ +25Δ (same expiry)",
        ),
        score=60.0 + (10.0 if skew is not None and skew > _SKEW_PUT_RICH * 1.5 else 0.0),
        flags=flags + ("unlimited downside if underlying rallies hard",),
    )


def _calendar_backwardation_play(
    term_slope: Optional[float],
    flags: tuple[str, ...],
) -> StrategyRec:
    return StrategyRec(
        name="Calendar — Backwardation Reversion",
        thesis=(
            "Term structure inverted (near > far) — sell expensive near-month, "
            "buy cheap back-month, expect normalisation."
        ),
        risk_profile="defined",
        direction="neutral_vol",
        target_delta=-0.50,
        target_dte=30,
        legs=(
            "Short put/call ATM, 30 DTE",
            "Long put/call ATM, 60 DTE",
        ),
        score=65.0,
        flags=flags,
    )


def _calendar_carry_play(
    term_slope: Optional[float],
    flags: tuple[str, ...],
) -> StrategyRec:
    return StrategyRec(
        name="Calendar — Contango Carry",
        thesis=(
            "Steep contango — sell near-term theta, buy back-month vega; "
            "harvest the difference."
        ),
        risk_profile="defined",
        direction="neutral_vol",
        target_delta=-0.50,
        target_dte=30,
        legs=(
            "Short ATM put/call 30 DTE",
            "Long ATM put/call 90 DTE",
        ),
        score=58.0,
        flags=flags,
    )


def _earnings_long_straddle(
    perc: Optional[float],
    dte: Optional[int],
    flags: tuple[str, ...],
) -> StrategyRec:
    return StrategyRec(
        name="Earnings Long Straddle",
        thesis=(
            "Pre-earnings IV is cheap relative to historical crush — buy "
            "ATM straddle, exit on vol spike or move."
        ),
        risk_profile="defined",
        direction="long_vol",
        target_delta=-0.50,
        target_dte=int(max(7, (dte or 7) + 5)),
        legs=(
            "Long ATM call",
            "Long ATM put (same expiry, post-earnings)",
        ),
        score=72.0,
        flags=flags + ("position sized small — earnings binary risk",),
    )


def _earnings_iron_condor(
    perc: Optional[float],
    dte: Optional[int],
    flags: tuple[str, ...],
) -> StrategyRec:
    return StrategyRec(
        name="Earnings Iron Condor",
        thesis=(
            "Pre-earnings IV richly priced — sell vol via condor, exit "
            "post-earnings on crush."
        ),
        risk_profile="defined",
        direction="short_vol",
        target_delta=0.16,
        target_dte=int(max(7, (dte or 7) + 2)),
        legs=(
            "Short call @ +16Δ",
            "Long call @ +5Δ",
            "Short put @ −16Δ",
            "Long put @ −5Δ",
        ),
        score=68.0,
        flags=flags + ("close before move materialises if crush incomplete",),
    )


def _wait_rec(
    edge: Optional[float],
    perc: Optional[float],
    flags: tuple[str, ...],
) -> StrategyRec:
    return StrategyRec(
        name="WAIT",
        thesis=(
            "Vol regime is mid-range — no clear edge; wait for a cheap or "
            "rich trigger before deploying capital."
        ),
        risk_profile="limited",
        direction="neutral_vol",
        target_delta=0.0,
        target_dte=0,
        legs=(),
        score=0.0,
        flags=flags,
    )


# ── Helpers ──────────────────────────────────────────────────────────────

def _compute_flags(days_to_earnings: Optional[int]) -> tuple[str, ...]:
    flags: list[str] = []
    if days_to_earnings is not None and 0 <= days_to_earnings <= _ER_NEAR_DAYS:
        flags.append("earnings_near")
    return tuple(flags)


def _safe_float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


# ── Display helper ───────────────────────────────────────────────────────

_BADGE_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


def strategy_card_html(rec: StrategyRec) -> str:
    """Render one StrategyRec as a compact card (for Discover / Pre-Trade)."""
    direction_color = {
        "long_vol":    "#00d4aa",
        "short_vol":   "#ff9f43",
        "neutral_vol": "#7db4ff",
    }.get(rec.direction, "#8a8f9e")

    legs_html = "".join(
        f'<div style="color:#e0e4ef;font-size:10px;">• {leg}</div>'
        for leg in rec.legs
    ) or '<div style="color:#8a8f9e;font-size:10px;">— no legs (WAIT) —</div>'

    flags_html = ""
    if rec.flags:
        flags_html = (
            '<div style="margin-top:5px;color:#ff9f43;font-size:9px;">'
            + " · ".join(rec.flags) + "</div>"
        )

    return (
        f'<div style="font-family:{_BADGE_MONO};background:#15162088;'
        f'border:1px solid #1e2038;border-left:3px solid {direction_color};'
        f'border-radius:6px;padding:10px 12px;margin-bottom:8px;">'
        f'<div style="display:flex;justify-content:space-between;margin-bottom:4px;">'
        f'<span style="color:{direction_color};font-weight:700;font-size:12px;">{rec.name}</span>'
        f'<span style="color:{direction_color};font-size:9px;background:{direction_color}22;'
        f'padding:1px 6px;border-radius:3px;">{rec.score:.0f}</span>'
        f'</div>'
        f'<div style="color:#e0e4ef;font-size:11px;margin-bottom:6px;">{rec.thesis}</div>'
        f'<div style="color:#8a8f9e;font-size:10px;margin-bottom:4px;">'
        f'risk: {rec.risk_profile} · target Δ={rec.target_delta:+.2f} · '
        f'DTE≈{rec.target_dte}d</div>'
        f'{legs_html}{flags_html}'
        f'</div>'
    )
