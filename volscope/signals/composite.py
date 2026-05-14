"""
Composite signal scorer — Phase 1 scaffold.

Blends the atomic factors from factors.py into a single 0-100 score
and maps that score to a position-sizing fraction.

Weights trace to research consensus (see masterplan):
    ivr  0.15
    ivp  0.20
    vrp  0.20    (= IV/HV ratio, normalised)
    term 0.15
    skew 0.05
    mom  0.10
    reg  0.15    (HMM p_calm; gating, but also contributes to score)

The score is a weighted sum where each axis is FIRST normalised to a
[0, 100] sub-score with a direction-aware mapping (high IVR good for
short-vol; low IVR good for long-vol). The caller passes ``direction``
to flip the mapping.

NaN-tolerant: any factor that's NaN drops out and its weight is
redistributed proportionally. This is "graceful degradation" — never
crash on a partial chain.
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np

Direction = Literal["short_vol", "long_vol"]

_WEIGHTS: dict[str, float] = {
    "ivr":  0.15,
    "ivp":  0.20,
    "vrp":  0.20,
    "term": 0.15,
    "skew": 0.05,
    "mom":  0.10,
    "reg":  0.15,
}


def _sub_score(value: float, *, low: float, high: float,
               direction: Direction, name: str) -> float:
    """
    Map a raw factor value to a [0, 100] sub-score.

    ``low``/``high`` define the "neutral" band: below ``low`` favours
    long-vol; above ``high`` favours short-vol. Inside the band the
    score is 50 (no signal).
    """
    if not math.isfinite(value):
        return float("nan")
    if direction == "short_vol":
        if value <= low:
            return 0.0
        if value >= high:
            return 100.0
        return float((value - low) / (high - low) * 100.0)
    # long_vol
    if value >= high:
        return 0.0
    if value <= low:
        return 100.0
    return float((high - value) / (high - low) * 100.0)


def composite_score(factors: dict[str, float], *,
                    direction: Direction,
                    p_calm: float = float("nan")) -> float:
    """
    Compute a 0-100 composite score for the given direction.

    Higher = stronger evidence for ``direction``. NaN factors drop out
    and weights renormalise. Returns NaN if every factor is NaN.

    Mapping rules per axis (cited in masterplan):
    - IVR: short-vol favours >50; long-vol favours <30
    - IVP: short-vol favours >70; long-vol favours <30
    - VRP (IV/HV): short-vol favours >1.20; long-vol favours <0.75
    - Term slope: short-vol favours >0 (contango); long-vol favours <0
    - Skew (25Δ RR): short-vol favours <-5 (put-rich = compensation);
      long-vol favours >5
    - HV momentum: short-vol favours <1.0 (vol cooling);
      long-vol favours >1.5 (vol heating)
    - Regime (p_calm): short-vol favours high p_calm; long-vol either way
    """
    subs: dict[str, float] = {}
    if "ivr" in factors:
        subs["ivr"] = _sub_score(factors["ivr"], low=30, high=50,
                                  direction=direction, name="ivr")
    if "ivp" in factors:
        subs["ivp"] = _sub_score(factors["ivp"], low=30, high=70,
                                  direction=direction, name="ivp")
    if "iv_hv" in factors:
        subs["vrp"] = _sub_score(factors["iv_hv"], low=0.75, high=1.20,
                                  direction=direction, name="vrp")
    if "term" in factors:
        subs["term"] = _sub_score(factors["term"], low=-0.05, high=0.05,
                                  direction=direction, name="term")
    if "skew" in factors:
        subs["skew"] = _sub_score(factors["skew"], low=-5.0, high=5.0,
                                  direction="long_vol" if direction == "short_vol"
                                  else "short_vol", name="skew")
    if "hv_mom" in factors:
        subs["mom"] = _sub_score(factors["hv_mom"], low=1.0, high=1.5,
                                  direction="long_vol" if direction == "short_vol"
                                  else "short_vol", name="mom")
    if math.isfinite(p_calm):
        if direction == "short_vol":
            subs["reg"] = float(np.clip(p_calm * 100.0, 0.0, 100.0))
        else:
            subs["reg"] = 50.0   # long-vol agnostic to regime

    finite_subs = {k: v for k, v in subs.items() if math.isfinite(v)}
    if not finite_subs:
        return float("nan")
    used_weights = {k: _WEIGHTS[k] for k in finite_subs}
    w_total = sum(used_weights.values())
    return float(sum(finite_subs[k] * used_weights[k] for k in finite_subs) / w_total)


def size_from_score(score: float) -> float:
    """
    Map a composite score to a position-sizing fraction in [0, 1].

    <50  → 0    (no trade)
    50-65 → 0.25
    65-80 → 0.50
    80-90 → 0.75
    >=90 → 1.00
    """
    if not math.isfinite(score) or score < 50:
        return 0.0
    if score < 65:
        return 0.25
    if score < 80:
        return 0.50
    if score < 90:
        return 0.75
    return 1.00
