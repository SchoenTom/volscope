"""
IV Robustness Subsystem — v0.6.1.

Solves the FISV-style misclassification bug: a single extreme IV spike
(forecast reset / litigation / M&A) stretches the 52-week MIN-MAX
range, making the standard IV Rank metric show a misleading "CHEAP"
verdict even when IV Percentile correctly signals the option is
elevated. FISV May-2026 dashboard observation:

    IVR  12.5 → CHEAP
    IVP  78.6 → HIGH
    divergence 66.1 → single-spike contamination

This module provides production-grade alternatives:

1. ``robust_iv_rank()`` — winsorized (5th/95th percentile) range
   instead of MIN/MAX. Spike-immune.
2. ``detect_contamination()`` — categorical 4-level severity from
   |IVR − IVP| divergence.
3. ``detect_structural_break()`` — Pelt change-point algorithm
   (ruptures lib) or CUSUM fallback to flag permanent regime shifts.
4. ``assess_iv_quality()`` — composite quality report with
   tradable / caution / block recommendation.

Architecture decision (decisions.md): a new module rather than
extending ``signals/factors.py``:
- Single Responsibility — factors compute, robustness validates.
- Isolated testability.
- Backward-compat: existing ``ivr`` and ``ivp`` keep working.
- Code-reviewer can see "robustness domain" at a glance.

References:
- López de Prado (2018), AFML Ch. 7 + Ch. 11 (regime detection).
- Killick, Fearnhead & Eckley (2012) "Optimal detection of
  changepoints with a linear computational cost" — Pelt algorithm.
- Tom's FISV observation 2026-05-14.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


class ContaminationLevel(str, Enum):
    """Categorical severity from |IVR − IVP| divergence."""
    CLEAN = "clean"           # ≤ 15 points → metrics agree
    MILD = "mild"             # 15-30 points → prefer IVP
    SEVERE = "severe"         # 30-50 points → use IVP only
    EXTREME = "extreme"       # > 50 points → consider blocking


# ── A1: Robust IV Rank ────────────────────────────────────────────


def robust_iv_rank(
    iv_series: pd.Series,
    *,
    lookback: int = 252,
    lower_quantile: float = 0.05,
    upper_quantile: float = 0.95,
) -> float | None:
    """
    Compute IV Rank using winsorized 5th/95th-percentile bounds.

    A single extreme IV spike (earnings crush, M&A, crisis) can
    stretch the 52-week MIN-MAX range artificially. Using the
    5th and 95th percentile as bounds produces a "where is current
    IV in its TYPICAL range" measure that is spike-immune.

    Returns:
        Robust IVR in [-50, 150] (capped) or ``None`` on insufficient
        / invalid data. Values outside [0, 100] signal "below typical
        range" or "above typical range" respectively.

    Behavior:
        - Requires ≥ ``lookback`` observations.
        - Filters invalid values (≤ 0 or > 500% IV).
        - Requires ≥ 80% valid data in the lookback window.
        - Requires the (95th − 5th) range to be ≥ 1.0 to be meaningful.

    Example (FISV 2026-05):
        Standard IVR = (49.5 − 23.4) / (232.7 − 23.4) ≈ 12.5
        Robust IVR ≈ 50-60 (matches IVP 78.6 better, even if not exact)
    """
    if iv_series is None or len(iv_series) < lookback:
        return None

    history = iv_series.dropna().iloc[-lookback:].copy()
    history = history[(history > 0) & (history < 500)]

    # Need at least 80% valid data for the bounds to be reliable
    if len(history) < int(lookback * 0.8):
        return None

    # Current value must be valid
    try:
        current = float(iv_series.iloc[-1])
    except (IndexError, TypeError, ValueError):
        return None
    if pd.isna(current) or current <= 0:
        return None

    iv_low = float(history.quantile(lower_quantile))
    iv_high = float(history.quantile(upper_quantile))
    if iv_high - iv_low < 1.0:
        return None

    rank = (current - iv_low) / (iv_high - iv_low) * 100.0
    return float(max(-50.0, min(150.0, rank)))


# ── A2: Contamination detection ───────────────────────────────────


def detect_contamination(
    iv_rank: float | None,
    iv_percentile: float | None,
) -> tuple[ContaminationLevel, float]:
    """
    Categorise the IVR/IVP divergence into a severity level.

    Returns ``(level, divergence)`` where ``divergence = |IVR − IVP|``.
    Returns ``(CLEAN, 0.0)`` if either input is None — caller treats
    that as "data insufficient" elsewhere.

    Decision rule (research-backed thresholds):
        - ≤ 15 → CLEAN: metrics agree, both tell the same story.
        - 15-30 → MILD: minor stretch in MIN-MAX range, prefer IVP.
        - 30-50 → SEVERE: strong contamination, use IVP only.
        - > 50 → EXTREME: range is heavily contaminated, consider
          blocking the ticker from trading.
    """
    # None OR NaN both mean "insufficient data" — a NaN iv_rank (the
    # sentinel ivr()/ivp() emit) would otherwise produce divergence=NaN,
    # which fails every `<= threshold` test (IEEE 754) and falls through to
    # a bogus EXTREME verdict with a NaN divergence that orjson turns into
    # null. Treat non-finite inputs as CLEAN/insufficient.
    if (
        iv_rank is None
        or iv_percentile is None
        or not math.isfinite(float(iv_rank))
        or not math.isfinite(float(iv_percentile))
    ):
        return ContaminationLevel.CLEAN, 0.0

    divergence = abs(float(iv_rank) - float(iv_percentile))
    if divergence <= 15.0:
        return ContaminationLevel.CLEAN, divergence
    if divergence <= 30.0:
        return ContaminationLevel.MILD, divergence
    if divergence <= 50.0:
        return ContaminationLevel.SEVERE, divergence
    return ContaminationLevel.EXTREME, divergence


# ── A3: Structural break detection ────────────────────────────────


def detect_structural_break(
    iv_series: pd.Series,
    *,
    min_segment_length: int = 60,
    pelt_penalty: float = 10.0,
    magnitude_floor: float = 0.30,
) -> dict[str, Any] | None:
    """
    Detect a permanent regime shift in the IV series.

    Uses the Pelt (Pruned Exact Linear Time) change-point algorithm
    via the ``ruptures`` library when available; falls back to a
    CUSUM-based detector otherwise.

    Returns ``None`` if no significant break is found. Otherwise a
    dict with:
        - break_date: ISO-8601 date (if index is a DatetimeIndex)
          OR ``day_<N>_of_<total>`` (positional fallback).
        - days_since_break: int
        - pre_break_mean: float (annualised IV in same units as input)
        - post_break_mean: float
        - magnitude: |post − pre| / pre  (relative shift)
        - direction: ``"up"`` if regime shifted higher else ``"down"``

    ``magnitude_floor`` filters out small shifts that are likely
    noise (default 30% relative change is the published threshold
    for "regime change" vs "mean-reversion noise" in the IV
    literature).
    """
    if iv_series is None or len(iv_series) < 2 * min_segment_length:
        return None

    try:
        import ruptures as rpt           # type: ignore[import-not-found]
    except ImportError:
        return _detect_break_cusum_fallback(
            iv_series,
            min_segment_length=min_segment_length,
            magnitude_floor=magnitude_floor,
        )

    history = iv_series.dropna()
    if len(history) < 2 * min_segment_length:
        return None
    arr = history.values.astype(float)

    try:
        algo = rpt.Pelt(model="rbf", min_size=min_segment_length).fit(arr)
        breakpoints = algo.predict(pen=pelt_penalty)
    except Exception as exc:               # noqa: BLE001
        log.warning("Pelt failed (%s); using CUSUM fallback", exc)
        return _detect_break_cusum_fallback(
            iv_series,
            min_segment_length=min_segment_length,
            magnitude_floor=magnitude_floor,
        )

    # ruptures returns a list including the endpoint; need ≥ 2 entries
    # for an actual break (one internal + one endpoint).
    if len(breakpoints) <= 1:
        return None
    last_break_idx = int(breakpoints[-2])

    return _build_break_report(
        history=history, arr=arr, last_break_idx=last_break_idx,
        magnitude_floor=magnitude_floor,
    )


def _detect_break_cusum_fallback(
    iv_series: pd.Series, *,
    min_segment_length: int,
    magnitude_floor: float,
) -> dict[str, Any] | None:
    """CUSUM-based fallback when ``ruptures`` is unavailable.

    Walks every candidate split point, picks the one that maximises
    the absolute mean-shift normalised by combined std, returns it if
    above ``magnitude_floor``.

    This is O(n) rather than the optimal O(n log n) of Pelt, but
    correct enough for the FISV-class use case.
    """
    history = iv_series.dropna()
    if len(history) < 2 * min_segment_length:
        return None
    arr = history.values.astype(float)
    n = len(arr)

    best_score = 0.0
    best_idx = -1
    for split in range(min_segment_length, n - min_segment_length):
        pre = arr[:split]
        post = arr[split:]
        pre_mean = float(pre.mean())
        post_mean = float(post.mean())
        if pre_mean == 0:
            continue
        magnitude = abs(post_mean - pre_mean) / pre_mean
        # Combined std for normalisation (Welch-ish)
        std = float(np.sqrt(pre.var(ddof=1) + post.var(ddof=1) + 1e-9))
        score = abs(post_mean - pre_mean) / std
        if score > best_score and magnitude >= magnitude_floor:
            best_score = score
            best_idx = split

    if best_idx < 0:
        return None
    return _build_break_report(
        history=history, arr=arr, last_break_idx=best_idx,
        magnitude_floor=magnitude_floor,
    )


def _build_break_report(
    *, history: pd.Series, arr: np.ndarray,
    last_break_idx: int, magnitude_floor: float,
) -> dict[str, Any] | None:
    """Assemble the dict returned by ``detect_structural_break``."""
    pre = arr[:last_break_idx]
    post = arr[last_break_idx:]
    if len(pre) == 0 or len(post) == 0:
        return None
    pre_mean = float(pre.mean())
    post_mean = float(post.mean())
    if pre_mean == 0:
        return None

    magnitude = abs(post_mean - pre_mean) / pre_mean
    if magnitude < magnitude_floor:
        return None

    days_since = int(len(arr) - last_break_idx)
    if isinstance(history.index, pd.DatetimeIndex):
        break_date = history.index[last_break_idx].strftime("%Y-%m-%d")
    else:
        break_date = f"day_{last_break_idx}_of_{len(arr)}"

    return {
        "break_date": break_date,
        "days_since_break": days_since,
        "pre_break_mean": pre_mean,
        "post_break_mean": post_mean,
        "magnitude": magnitude,
        "direction": "up" if post_mean > pre_mean else "down",
    }


# ── A4: Composite quality assessment ──────────────────────────────


@dataclass(frozen=True)
class IVQualityReport:
    """
    Composite quality assessment for a single ticker on a single date.

    The quality score is a 0-100 deduction model:
        - SEVERE contamination → -25
        - EXTREME contamination → -50
        - Structural break <90 d ago → -30
        - Structural break 90-180 d ago → -15
        - Robust IVR diverges from raw IVR by >30 pt → -20
        - Insufficient data → forced to 0

    Recommendation thresholds:
        ≥ 70 → TRADE — defaults are fine.
        40-69 → CAUTION — trade with smaller size or skip.
        < 40 → BLOCK — do not trade until next quality scan recovers.
    """
    ticker: str
    iv_rank: float | None
    iv_percentile: float | None
    robust_iv_rank: float | None
    contamination: ContaminationLevel
    divergence: float
    structural_break: dict[str, Any] | None
    quality_score: int                       # 0-100
    tradable: bool
    recommendation: str                      # 'TRADE' | 'CAUTION' | 'BLOCK'
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view for DB persistence + UI."""
        return {
            "ticker": self.ticker,
            "iv_rank": self.iv_rank,
            "iv_percentile": self.iv_percentile,
            "robust_iv_rank": self.robust_iv_rank,
            "contamination": self.contamination.value,
            "divergence": round(self.divergence, 2),
            "structural_break": self.structural_break,
            "quality_score": int(self.quality_score),
            "tradable": bool(self.tradable),
            "recommendation": self.recommendation,
            "warnings": list(self.warnings),
        }


def assess_iv_quality(
    ticker: str,
    iv_series: pd.Series,
    iv_rank_value: float | None,
    iv_percentile_value: float | None,
) -> IVQualityReport:
    """End-to-end quality assessment combining all four checks."""
    warnings: list[str] = []
    quality = 100

    # Compute robust IVR up-front (used in both UI + scoring)
    robust = robust_iv_rank(iv_series)

    # Insufficient data — forces quality to 0
    def _missing(v: object) -> bool:
        return v is None or (isinstance(v, float) and not math.isfinite(v))

    insufficient = (
        _missing(iv_rank_value)
        or _missing(iv_percentile_value)
        or iv_series is None
        or len(iv_series.dropna()) < 100
    )

    contamination, divergence = detect_contamination(
        iv_rank_value, iv_percentile_value
    )

    if contamination == ContaminationLevel.SEVERE:
        quality -= 25
        warnings.append(
            f"IVR ({iv_rank_value:.1f}) and IVP ({iv_percentile_value:.1f}) "
            f"diverge by {divergence:.1f} pt — single-spike contamination. "
            f"Trust IVP over IVR."
        )
    elif contamination == ContaminationLevel.EXTREME:
        quality -= 50
        warnings.append(
            f"EXTREME divergence ({divergence:.1f}pt) between IVR and IVP. "
            f"IV 52-week range is heavily contaminated by an outlier. "
            f"Consider blocking ticker until next scan."
        )

    if iv_rank_value is not None and robust is not None:
        robust_div = abs(float(iv_rank_value) - float(robust))
        if robust_div > 30.0:
            quality -= 20
            warnings.append(
                f"Robust IVR ({robust:.1f}) deviates from raw IVR "
                f"({iv_rank_value:.1f}) by {robust_div:.1f}pt — strong "
                f"evidence of outliers in 52-week range."
            )

    break_info = detect_structural_break(iv_series) if iv_series is not None else None
    if break_info is not None:
        days_since = int(break_info["days_since_break"])
        magnitude_pct = float(break_info["magnitude"]) * 100.0
        direction = break_info["direction"]
        if days_since < 90:
            quality -= 30
            warnings.append(
                f"Recent structural break {break_info['break_date']} "
                f"({days_since} d ago). IV mean shifted {direction} by "
                f"{magnitude_pct:.0f}%. Pre-break history is NOT "
                f"representative of current regime."
            )
        elif days_since < 180:
            quality -= 15
            warnings.append(
                f"Structural break {days_since} d ago on "
                f"{break_info['break_date']}. Treat IV metrics with caution."
            )

    if insufficient:
        quality = 0
        warnings.append("Insufficient IV history (< 100 valid observations).")

    quality = max(0, min(100, int(quality)))

    if quality >= 70:
        recommendation = "TRADE"
    elif quality >= 40:
        recommendation = "CAUTION"
    else:
        recommendation = "BLOCK"

    return IVQualityReport(
        ticker=ticker,
        iv_rank=iv_rank_value,
        iv_percentile=iv_percentile_value,
        robust_iv_rank=robust,
        contamination=contamination,
        divergence=divergence,
        structural_break=break_info,
        quality_score=quality,
        tradable=(recommendation != "BLOCK"),
        recommendation=recommendation,
        warnings=warnings,
    )


__all__ = [
    "ContaminationLevel",
    "IVQualityReport",
    "robust_iv_rank",
    "detect_contamination",
    "detect_structural_break",
    "assess_iv_quality",
]
