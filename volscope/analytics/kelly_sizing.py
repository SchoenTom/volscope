"""
Kelly-Criterion position sizing — backtest-conditional bet fractions.

Existing ``position_sizing.py`` returns binary multipliers (BUY=1.0,
LEAN=0.5, WAIT/RICH=0.0). For a hedge-fund-grade tool we need optimal
sizing under uncertainty: given a backtest hit-rate at the current
edge-score level, what fraction of the bankroll maximises expected log
wealth?

Kelly formula (binary outcome, fixed payoff ratio b = win/loss):

    f* = (b · p − q) / b      where p = P(win), q = 1 − p

Real-world adaptation:
  - We work with VEGA P&L on options, so 'win' and 'loss' magnitudes
    come from the backtest's empirical distribution, not a fixed b.
  - We use a fractional-Kelly multiplier (0.25 by default) because full
    Kelly is too aggressive for an LLM-piloted system without ground-truth
    of the backtest's stationarity.
  - Negative f* clamps to 0 (no position, not short-vol).

This module is pure analytics — no UI imports. Composable from
notebooks, tests, and the Streamlit Position Sizer expander on the
Command Center page.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# ── Configuration ────────────────────────────────────────────────────────

# Fractional Kelly — full Kelly assumes the payoff distribution is
# stationary, which is rarely true on options vol. 0.25× is a common
# professional convention (Ed Thorp, "A Man for All Markets").
_KELLY_FRACTION = 0.25

# Below this many backtest observations, the hit-rate estimate is too
# noisy to act on — we return Kelly = 0 with low confidence.
_MIN_BACKTEST_N = 30


# ── Output type ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class KellyResult:
    """Immutable Kelly sizing recommendation.

    Attributes
    ----------
    full_kelly       : Raw Kelly fraction (can be > 1 or < 0).
    fractional_kelly : full_kelly × _KELLY_FRACTION, clamped to [0, 0.5].
    p_win            : Estimated P(win) from backtest.
    payoff_ratio     : Estimated avg_win / avg_loss (b parameter).
    n_observations   : Backtest sample size.
    confidence       : 0..1, function of n_observations vs target 200.
    notes            : Short string explaining unusual results.
    """
    full_kelly:       float
    fractional_kelly: float
    p_win:            float
    payoff_ratio:     float
    n_observations:   int
    confidence:       float
    notes:            str


# ── Kelly mathematics ────────────────────────────────────────────────────

def kelly_fraction(p_win: float, payoff_ratio: float) -> float:
    """Compute raw Kelly fraction from probability and payoff ratio.

    Parameters
    ----------
    p_win        : P(win) ∈ [0, 1]
    payoff_ratio : Average win size / average loss size (positive).

    Returns
    -------
    float
        Kelly fraction f* = (b·p − q) / b. Negative when no edge.
    """
    if payoff_ratio <= 0 or not (0.0 <= p_win <= 1.0):
        return 0.0
    q = 1.0 - p_win
    return (payoff_ratio * p_win - q) / payoff_ratio


def _payoff_from_winners_losers(winners: list[float], losers: list[float]) -> float:
    """Compute average-win / average-loss from two lists of magnitudes.
    Both inputs are absolute magnitudes (positive numbers)."""
    if not winners or not losers:
        return 0.0
    avg_win  = sum(winners) / len(winners)
    avg_loss = sum(losers)  / len(losers)
    if avg_loss <= 0:
        return 0.0
    return avg_win / avg_loss


# ── Main entry point ─────────────────────────────────────────────────────

def compute_kelly_sizing(
    backtest_hits:  Optional[list[bool]] = None,
    backtest_pnls:  Optional[list[float]] = None,
    fallback_p_win: Optional[float] = None,
    fallback_payoff: Optional[float] = None,
) -> KellyResult:
    """Compute Kelly-sized bet fraction for the current edge level.

    Two callable patterns:

    1. From a backtest sample — pass ``backtest_hits`` (booleans, win=True)
       AND ``backtest_pnls`` (signed % P&L; positive = win, negative = loss).
       Both lists must be the same length.
    2. From summary statistics — pass ``fallback_p_win`` and
       ``fallback_payoff`` directly (used for the ML-signal-only path
       where we don't have full P&L history).

    When both forms are given, the backtest sample wins.

    Parameters
    ----------
    backtest_hits  : List of bool — outcomes of past trades at this edge level.
    backtest_pnls  : List of float — signed % P&L matching ``backtest_hits``.
    fallback_p_win : Used when backtest sample is empty.
    fallback_payoff: Used when backtest sample is empty.

    Returns
    -------
    KellyResult
        Always a valid object — never raises. Safe to render directly.
    """
    n = 0
    p_win = 0.0
    payoff = 0.0
    notes = ""

    if backtest_hits and backtest_pnls and len(backtest_hits) == len(backtest_pnls):
        n = len(backtest_hits)
        if n < _MIN_BACKTEST_N:
            notes = f"only {n} obs (need {_MIN_BACKTEST_N}+) — Kelly forced to 0"
        else:
            n_wins = sum(1 for h in backtest_hits if h)
            p_win = n_wins / n
            winners = [abs(p) for h, p in zip(backtest_hits, backtest_pnls) if h]
            losers  = [abs(p) for h, p in zip(backtest_hits, backtest_pnls) if not h]
            payoff = _payoff_from_winners_losers(winners, losers)
            if payoff <= 0:
                notes = "no losers in backtest — payoff ratio undefined"
    elif fallback_p_win is not None and fallback_payoff is not None:
        p_win = max(0.0, min(1.0, fallback_p_win))
        payoff = max(0.0, fallback_payoff)
        n = 0
        notes = "summary-stats path — confidence reduced"
    else:
        notes = "insufficient inputs"

    full_k = kelly_fraction(p_win, payoff)
    frac_k = max(0.0, min(0.5, full_k * _KELLY_FRACTION))

    confidence = 0.0
    if n >= _MIN_BACKTEST_N:
        confidence = min(1.0, n / 200.0)
    elif n == 0 and fallback_p_win is not None:
        confidence = 0.3

    if full_k <= 0 and not notes:
        notes = "no edge — Kelly = 0"

    return KellyResult(
        full_kelly=round(full_k, 4),
        fractional_kelly=round(frac_k, 4),
        p_win=round(p_win, 4),
        payoff_ratio=round(payoff, 3),
        n_observations=n,
        confidence=round(confidence, 2),
        notes=notes,
    )


# ── Display helper ───────────────────────────────────────────────────────

_BADGE_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


def kelly_summary_html(result: KellyResult, max_alloc_usd: float) -> str:
    """Compact HTML summary for the Position Sizer panel.

    Parameters
    ----------
    result        : KellyResult.
    max_alloc_usd : Capital ceiling for sizing reference.

    Returns
    -------
    str
        Self-contained <div> HTML fragment.
    """
    suggested_usd = max_alloc_usd * result.fractional_kelly
    color = "#00d4aa" if result.fractional_kelly > 0.05 else (
        "#7db4ff" if result.fractional_kelly > 0.0 else "#8a8f9e"
    )
    return (
        f'<div style="font-family:{_BADGE_MONO};font-size:11px;'
        f'background:#15162088;border:1px solid #1e2038;border-left:3px solid {color};'
        f'border-radius:6px;padding:10px 12px;">'
        f'<div style="color:{color};font-weight:700;margin-bottom:4px;">'
        f'Kelly · {result.fractional_kelly*100:.1f}% of cap</div>'
        f'<div style="color:#8a8f9e;">'
        f'p_win {result.p_win:.0%} · payoff {result.payoff_ratio:.2f}× · '
        f'n={result.n_observations} · conf {result.confidence:.0%}'
        f'</div>'
        f'<div style="color:#e0e4ef;margin-top:4px;">'
        f'≈ ${suggested_usd:,.0f} suggested at {result.fractional_kelly*100:.1f}% allocation'
        f'</div>'
        f'{(f"<div style=\"color:#ff9f43;margin-top:3px;font-size:10px;\">{result.notes}</div>" if result.notes else "")}'
        f'</div>'
    )
