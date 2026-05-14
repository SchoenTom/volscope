"""
Edge Score — composite long-vol entry score.

Answers the hedge-fund question: *"Of all tickers I track, which one has the
single best entry edge for buying vol RIGHT NOW, and why?"*

Every existing analytic in VolScope answers a piece of the puzzle:
  - IV percentile / IV rank → cheapness vs own history
  - VRP (iv_30d / hv_20d)   → cheapness vs realized
  - ML buy_prob              → P(IV falls in 10d) — inverted for long-vol entries
  - Sector regime z-score    → sector-level cheapness
  - Capital-flow score       → smart-money accumulation/distribution
  - 25Δ skew                 → put-side richness penalty

The Edge Score collapses all of them into a single 0–100 number with an
explicit weighted-average formula and exposes the per-component contributions
so the trader sees *why* a ticker is on top.

This module is pure analytics — zero UI imports. Composable from CLI, tests,
notebooks, and Streamlit alike.

Long-vol convention
-------------------
A high Edge Score means "good entry to BUY vol now (long puts / long-dated
options / knockouts that benefit from rising IV)". This matches Tom's
trading book: Sep 2027 DAX Puts, Dec 2026 Nasdaq Puts, knockouts on MSTR /
SNOW / 1810.HK. A vol seller would invert the score.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from volscope.analytics.ml_signal import MLPrediction


# ── Component weights (must sum to 1.0) ───────────────────────────────────
# Calibrated for a long-vol entry view. Percentile weighted highest because
# it's the single strongest historical predictor of mean reversion.
_W_IV_PERC = 0.30
_W_VRP     = 0.20
_W_RANK    = 0.15
_W_ML      = 0.15
_W_REGIME  = 0.10
_W_FLOW    = 0.10

assert math.isclose(_W_IV_PERC + _W_VRP + _W_RANK + _W_ML + _W_REGIME + _W_FLOW, 1.0)

# Liquidity gate — below this, flag as illiquid in the explanation
# but don't kill the score. Tom may still want to know the signal.
_MIN_OI_LIQUID = 1000


@dataclass(frozen=True)
class EdgeScore:
    """Immutable composite edge for a single ticker on a single day.

    Attributes
    ----------
    ticker      : Ticker symbol.
    score       : Composite 0–100 (higher = better long-vol entry edge).
    components  : Dict of component_name → score in 0..100. Only includes
                  components that had data; missing ones absent (not zero).
    weights     : Dict of component_name → weight actually used (renormalised
                  to sum to 1 across present components).
    drivers     : Top 1–2 component names that contributed most to the score.
    one_liner   : Human-readable explanation, e.g.
                  "perc 14 · VRP 0.86× · ML 28% · COLD sector — strong edge".
    confidence  : N components present / 6 (max). 1.0 = full data.
    illiquid    : True if total_open_interest < _MIN_OI_LIQUID.
    """

    ticker:     str
    score:      float
    components: dict[str, float] = field(default_factory=dict)
    weights:    dict[str, float] = field(default_factory=dict)
    drivers:    tuple[str, ...]  = ()
    one_liner:  str              = ""
    confidence: float            = 0.0
    illiquid:   bool             = False


def _safe(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# ── Per-component score builders (each returns 0..100 or None) ────────────

def _iv_perc_component(perc: Optional[float]) -> Optional[float]:
    """100 − percentile. Low percentile → high cheapness score."""
    if perc is None:
        return None
    return _clip(100.0 - perc)


def _vrp_component(iv_30d: Optional[float], hv_20d: Optional[float]) -> Optional[float]:
    """
    VRP = iv_30d / hv_20d. Below 1.0 means options are cheap vs realized.

    Maps via piecewise-linear ramp:
        VRP ≤ 0.80 → 100  (very cheap)
        VRP = 1.00 →  50  (fair)
        VRP ≥ 1.20 →   0  (rich)
    """
    if iv_30d is None or hv_20d is None or hv_20d <= 0:
        return None
    vrp = iv_30d / hv_20d
    score = 100.0 * (1.20 - vrp) / 0.40   # 0.80→100, 1.20→0
    return _clip(score)


def _rank_component(rank: Optional[float]) -> Optional[float]:
    if rank is None:
        return None
    return _clip(100.0 - rank)


def _ml_component(pred: Optional[MLPrediction]) -> Optional[float]:
    """
    ML buy_prob = P(IV falls in next 10d). For long-vol entries we want
    IV to RISE, so we invert: ml_score = 100 * (1 − buy_prob).

    Note: this is the OPPOSITE direction of the "ML BUY" badge label, which
    is calibrated for a short-vol perspective. The Edge Score is designed
    explicitly for long-vol entries (Tom's book).
    """
    if pred is None:
        return None
    return _clip(100.0 * (1.0 - pred.buy_prob))


def _regime_component(regime: Optional[str]) -> Optional[float]:
    """COLD sector → 100 (cheap), NEUTRAL → 50, HOT → 0."""
    if regime is None:
        return None
    r = str(regime).upper()
    if r == "COLD":
        return 100.0
    if r == "HOT":
        return 0.0
    if r == "NEUTRAL":
        return 50.0
    return None


def _flow_component(flow_score: Optional[float]) -> Optional[float]:
    """
    Capital-flow score is already 0..100 from analytics.capital_flow.
    Pass through unchanged with clipping.
    """
    if flow_score is None:
        return None
    return _clip(flow_score)


# ── Main entry points ─────────────────────────────────────────────────────

def compute_edge_score(
    ticker: str,
    row: Optional[pd.Series],
    ml_pred: Optional[MLPrediction] = None,
    sector_regime: Optional[str] = None,
    flow_score: Optional[float] = None,
) -> EdgeScore:
    """
    Compute the composite long-vol Edge Score for one ticker.

    Parameters
    ----------
    ticker         : Ticker symbol.
    row            : Latest daily_vol row (may be None — returns zero score).
    ml_pred        : Optional ML mean-reversion prediction.
    sector_regime  : Optional sector regime label ("HOT" | "NEUTRAL" | "COLD").
    flow_score     : Optional capital-flow composite (0..100).

    Returns
    -------
    EdgeScore
        Always a valid object — never raises. When data is missing the
        score reflects only the components that were present, with weights
        renormalised across them. confidence tracks how complete the data was.
    """
    iv_perc = _safe(row.get("iv_percentile") if row is not None else None)
    iv_30d  = _safe(row.get("iv_30d")        if row is not None else None)
    hv_20d  = _safe(row.get("hv_20d")        if row is not None else None)
    iv_rank = _safe(row.get("iv_rank")       if row is not None else None)
    total_oi = _safe(row.get("total_open_interest") if row is not None else None)

    raw: dict[str, Optional[float]] = {
        "iv_perc": _iv_perc_component(iv_perc),
        "vrp":     _vrp_component(iv_30d, hv_20d),
        "rank":    _rank_component(iv_rank),
        "ml":      _ml_component(ml_pred),
        "regime":  _regime_component(sector_regime),
        "flow":    _flow_component(flow_score),
    }
    weights_raw: dict[str, float] = {
        "iv_perc": _W_IV_PERC,
        "vrp":     _W_VRP,
        "rank":    _W_RANK,
        "ml":      _W_ML,
        "regime":  _W_REGIME,
        "flow":    _W_FLOW,
    }

    components: dict[str, float] = {k: v for k, v in raw.items() if v is not None}
    if not components:
        # No usable signals at all — treat as illiquid by default so
        # downstream rankings (find_cheapest_vol, best_setup_hero) skip
        # this row instead of surfacing it without data.
        return EdgeScore(
            ticker=ticker,
            score=0.0,
            one_liner="no data — run make scrape",
            confidence=0.0,
            illiquid=True,
        )

    # Renormalise weights across present components so missing data
    # doesn't penalise the score — it just reduces confidence.
    total_w = sum(weights_raw[k] for k in components)
    weights = {k: weights_raw[k] / total_w for k in components}

    score = sum(components[k] * weights[k] for k in components)
    score = round(_clip(score), 1)

    # Drivers: components whose weighted contribution is in the top 2.
    contribs = {k: components[k] * weights[k] for k in components}
    drivers = tuple(
        k for k, _ in sorted(contribs.items(), key=lambda kv: kv[1], reverse=True)[:2]
    )

    confidence = round(len(components) / len(raw), 2)

    one_liner = _build_one_liner(
        components, iv_perc, iv_30d, hv_20d, ml_pred, sector_regime, flow_score
    )

    illiquid = total_oi is not None and total_oi < _MIN_OI_LIQUID

    return EdgeScore(
        ticker=ticker,
        score=score,
        components={k: round(v, 1) for k, v in components.items()},
        weights={k: round(v, 3) for k, v in weights.items()},
        drivers=drivers,
        one_liner=one_liner,
        confidence=confidence,
        illiquid=illiquid,
    )


def _build_one_liner(
    components:    dict[str, float],
    iv_perc:       Optional[float],
    iv_30d:        Optional[float],
    hv_20d:        Optional[float],
    ml_pred:       Optional[MLPrediction],
    sector_regime: Optional[str],
    flow_score:    Optional[float],
) -> str:
    """Build a compact, parseable explanation for the trader."""
    parts: list[str] = []
    if "iv_perc" in components and iv_perc is not None:
        parts.append(f"perc {iv_perc:.0f}")
    if "vrp" in components and iv_30d is not None and hv_20d and hv_20d > 0:
        parts.append(f"VRP {iv_30d / hv_20d:.2f}×")
    if "ml" in components and ml_pred is not None:
        rise_prob = int(round(100 * (1.0 - ml_pred.buy_prob)))
        parts.append(f"ML rise {rise_prob}%")
    if "regime" in components and sector_regime:
        parts.append(f"{sector_regime} sector")
    if "flow" in components and flow_score is not None:
        if flow_score >= 65:
            parts.append("accumulation")
        elif flow_score <= 35:
            parts.append("distribution")
    return " · ".join(parts) if parts else "partial data"


def rank_edges(edges: list[EdgeScore]) -> list[EdgeScore]:
    """Sort a list of EdgeScores descending by score (illiquid sink to bottom)."""
    return sorted(
        edges,
        key=lambda e: (not e.illiquid, e.score, e.confidence),
        reverse=True,
    )


from volscope.utils.timing import instrumented  # noqa: E402


@instrumented("analytics.edge_table")
def compute_edge_table(
    tickers:        list[str],
    latest_rows:    dict[str, Optional[pd.Series]],
    ml_preds:       Optional[dict[str, Optional[MLPrediction]]] = None,
    sector_regimes: Optional[dict[str, Optional[str]]] = None,
    flow_scores:    Optional[dict[str, Optional[float]]] = None,
) -> list[EdgeScore]:
    """
    Compute Edge Scores for a batch of tickers and return them ranked.

    All optional dicts default to empty — call with whatever data you have.

    Parameters
    ----------
    tickers        : Tickers to score.
    latest_rows    : Dict ticker → latest daily_vol pd.Series (or None).
    ml_preds       : Optional dict ticker → MLPrediction.
    sector_regimes : Optional dict ticker → "HOT"/"NEUTRAL"/"COLD".
    flow_scores    : Optional dict ticker → 0..100 capital-flow score.

    Returns
    -------
    list[EdgeScore]
        Sorted descending by score (best edge first), illiquid tickers
        sorted to bottom regardless of raw score.
    """
    ml_preds       = ml_preds       or {}
    sector_regimes = sector_regimes or {}
    flow_scores    = flow_scores    or {}

    edges = [
        compute_edge_score(
            ticker=t,
            row=latest_rows.get(t),
            ml_pred=ml_preds.get(t),
            sector_regime=sector_regimes.get(t),
            flow_score=flow_scores.get(t),
        )
        for t in tickers
    ]
    return rank_edges(edges)
