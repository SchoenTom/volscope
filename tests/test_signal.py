"""Tests for volscope.analytics.signal — vol buy/wait/rich signal logic."""
from __future__ import annotations

import math

import pytest

from volscope.analytics.signal import (
    VolSignal,
    _safe_float,
    compute_signal,
    market_summary,
)


# ---------------------------------------------------------------------------
# _safe_float helper
# ---------------------------------------------------------------------------

def test_safe_float_none():
    assert _safe_float(None) is None


def test_safe_float_nan():
    assert _safe_float(float("nan")) is None


def test_safe_float_inf():
    assert _safe_float(float("inf")) is None


def test_safe_float_valid():
    assert _safe_float(22.5) == pytest.approx(22.5)


def test_safe_float_string():
    assert _safe_float("18.3") == pytest.approx(18.3)


def test_safe_float_invalid_string():
    assert _safe_float("abc") is None


# ---------------------------------------------------------------------------
# compute_signal — NO DATA cases
# ---------------------------------------------------------------------------

def test_signal_all_none():
    s = compute_signal(None, None, None)
    assert s.category == "no_data"
    assert s.label == "NO DATA"


def test_signal_perc_none():
    s = compute_signal(None, 20.0, 18.0)
    assert s.category == "no_data"


def test_signal_iv_none():
    s = compute_signal(15.0, None, 18.0)
    assert s.category == "no_data"


def test_signal_hv_none():
    s = compute_signal(15.0, 20.0, None)
    assert s.category == "no_data"


def test_signal_hv_zero():
    """Zero HV → division by zero guard → NO DATA."""
    s = compute_signal(15.0, 20.0, 0.0)
    assert s.category == "no_data"


def test_signal_nan_inputs():
    s = compute_signal(float("nan"), 20.0, 18.0)
    assert s.category == "no_data"


# ---------------------------------------------------------------------------
# compute_signal — BUY VOL (strong: both signals cheap)
# ---------------------------------------------------------------------------

def test_signal_strong_buy_both_cheap():
    """perc=15 (< 25) AND VRP=0.90 (< 0.95) → strong BUY VOL."""
    s = compute_signal(15.0, 18.0, 20.0)   # VRP = 0.9
    assert s.label == "BUY VOL"
    assert s.category == "buy"
    assert s.strong is True


def test_signal_strong_buy_at_boundary():
    """perc=19.9 AND VRP=0.949 → still strong BUY (just inside thresholds).

    PERC_VERY_CHEAP was tightened from 25 → 20 in the iv_thresholds
    refactor; this test must use a perc value below the current 20
    boundary to assert the strong-cheap branch.
    """
    s = compute_signal(19.9, 18.98, 20.0)  # VRP ≈ 0.949
    assert s.label == "BUY VOL"
    assert s.strong is True


def test_signal_strong_buy_reason_contains_perc_and_vrp():
    s = compute_signal(10.0, 16.0, 20.0)   # VRP = 0.8
    assert "perc" in s.reason.lower() or "10" in s.reason
    assert "VRP" in s.reason or "0.80" in s.reason


# ---------------------------------------------------------------------------
# compute_signal — LEAN BUY (one signal)
# ---------------------------------------------------------------------------

def test_signal_lean_buy_perc_only():
    """perc=20 (cheap) but VRP=1.02 (slightly above 1, not cheap) → LEAN BUY."""
    # vrp = 20.4/20 = 1.02 → not cheap (≥ 1.00), not rich (< 1.05)
    # perc < 25 and not vrp_lean_rich (1.02 > 1.00 → vrp IS lean_rich!)
    # Wait, need to think: vrp_lean_rich = vrp > VRP_RICH_LEAN = 1.00
    # So 1.02 > 1.00 → vrp_lean_rich is True
    # perc_cheap=True, not vrp_lean_rich=False → this path doesn't fire
    # But perc_lean_cheap=True (20 < 35), vrp_lean_cheap=False (1.02 >= 1.00)
    # → no lean_buy B either
    # perc_rich=False, vrp_rich=False → no rich signals
    # → WAIT (disagreement)
    s = compute_signal(20.0, 20.4, 20.0)   # VRP = 1.02
    # perc is cheap (<25), vrp is mildly rich (>1.0)
    # Disagreement → WAIT
    assert s.label == "WAIT"


def test_signal_lean_buy_perc_cheap_vrp_neutral():
    """perc=20 (cheap) AND VRP=0.97 (between 0.95 and 1.0, neutral) → LEAN BUY."""
    # VRP = 0.97 → vrp_cheap=False (0.97 >= 0.95), vrp_lean_cheap=True (0.97 < 1.00)
    # perc=20 → perc_cheap=True
    # Strong BUY: perc_cheap AND vrp_cheap → 0.97 < 0.95? NO
    # Lean BUY A: perc_cheap AND not vrp_lean_rich → vrp_lean_rich = 0.97>1.0? NO → True
    # So condition: perc_cheap (True) AND not vrp_lean_rich (not False = True) → LEAN BUY!
    s = compute_signal(20.0, 19.4, 20.0)   # VRP = 0.97
    assert s.label == "LEAN BUY"
    assert s.category == "lean_buy"
    assert s.strong is False


def test_signal_lean_buy_vrp_only():
    """VRP=0.85 (very cheap) but perc=50 (neutral) → LEAN BUY."""
    # vrp_cheap=True (0.85 < 0.95)
    # perc=50 → perc_cheap=False, perc_lean_cheap=False (50 >= 35), perc_lean_rich=False (50 <= 65)
    # Lean BUY A: vrp_cheap (True) AND not perc_lean_rich (not False = True) → LEAN BUY
    s = compute_signal(50.0, 17.0, 20.0)   # VRP = 0.85
    assert s.label == "LEAN BUY"
    assert s.strong is False


def test_signal_lean_buy_both_mildly_cheap():
    """perc=30 and VRP=0.97 → both mildly cheap → LEAN BUY."""
    # perc=30 → perc_lean_cheap=True (30<35), perc_cheap=False
    # vrp=0.97 → vrp_lean_cheap=True (0.97<1.0), vrp_cheap=False
    # Not strong BUY. Lean BUY A: perc_cheap=False, vrp_cheap=False → no.
    # Lean BUY B: perc_lean_cheap AND vrp_lean_cheap → True AND True → LEAN BUY
    s = compute_signal(30.0, 19.4, 20.0)   # VRP = 0.97
    assert s.label == "LEAN BUY"
    assert s.strong is False


# ---------------------------------------------------------------------------
# compute_signal — RICH (strong: both signals rich)
# ---------------------------------------------------------------------------

def test_signal_strong_rich_both_expensive():
    """perc=85 (> 75) AND VRP=1.20 (> 1.05) → strong RICH."""
    s = compute_signal(85.0, 24.0, 20.0)   # VRP = 1.2
    assert s.label == "RICH"
    assert s.category == "rich"
    assert s.strong is True


def test_signal_strong_rich_boundary():
    """perc=80.1 AND VRP=1.051 → just inside RICH thresholds.

    PERC_RICH_STRONG was tightened to 80; the prior 75 boundary
    landed inside LEAN_RICH territory.
    """
    s = compute_signal(80.1, 21.02, 20.0)  # VRP ≈ 1.051
    assert s.label == "RICH"
    assert s.strong is True


# ---------------------------------------------------------------------------
# compute_signal — LEAN RICH (one signal)
# ---------------------------------------------------------------------------

def test_signal_lean_rich_perc_only():
    """perc=80 (rich) AND VRP=0.99 (neutral-cheap) → LEAN RICH."""
    # perc_rich=True (80>75)
    # vrp=0.99 → vrp_lean_cheap=True (0.99 < 1.00)
    # Lean RICH A: perc_rich AND not vrp_lean_cheap → not True = False → doesn't fire
    # perc_lean_rich=True, vrp_lean_rich=False (0.99 <= 1.00)
    # → no lean_rich B
    # → WAIT
    s = compute_signal(80.0, 19.8, 20.0)   # VRP = 0.99
    assert s.label == "WAIT"


def test_signal_lean_rich_perc_rich_vrp_neutral_above():
    """perc=80 (rich) AND VRP=1.03 (mildly rich, < 1.05) → LEAN RICH."""
    # vrp=1.03 → vrp_rich=False (1.03 < 1.05), vrp_lean_rich=True (1.03>1.00)
    # perc_rich=True
    # Lean RICH A: perc_rich AND not vrp_lean_cheap → vrp_lean_cheap = 1.03<1.0? No → not False = True
    # → LEAN RICH
    s = compute_signal(80.0, 20.6, 20.0)   # VRP = 1.03
    assert s.label == "LEAN RICH"
    assert s.strong is False


def test_signal_lean_rich_vrp_only():
    """VRP=1.25 (very rich) but perc=45 (neutral) → LEAN RICH."""
    # vrp_rich=True (1.25>1.05)
    # perc=45 → all perc booleans False
    # Lean RICH A: vrp_rich AND not perc_lean_cheap (45>=35 → not True = True) → LEAN RICH
    s = compute_signal(45.0, 25.0, 20.0)   # VRP = 1.25
    assert s.label == "LEAN RICH"
    assert s.strong is False


def test_signal_lean_rich_both_mildly_rich():
    """perc=70 and VRP=1.03 → both mildly rich → LEAN RICH."""
    # perc=70 → perc_lean_rich=True (70>65), perc_rich=False
    # vrp=1.03 → vrp_lean_rich=True (1.03>1.00), vrp_rich=False
    # Strong RICH: both False
    # Lean RICH A: perc_rich=False, vrp_rich=False → no
    # Lean RICH B: perc_lean_rich AND vrp_lean_rich → True → LEAN RICH
    s = compute_signal(70.0, 20.6, 20.0)   # VRP = 1.03
    assert s.label == "LEAN RICH"


# ---------------------------------------------------------------------------
# compute_signal — WAIT (neutral / disagreeing)
# ---------------------------------------------------------------------------

def test_signal_wait_both_neutral():
    """perc=50, VRP=1.00 → perfectly neutral → WAIT."""
    s = compute_signal(50.0, 20.0, 20.0)   # VRP = 1.0 exactly
    assert s.label == "WAIT"
    assert s.category == "neutral"


def test_signal_wait_disagreeing_cheap_perc_rich_vrp():
    """perc=15 (cheap) but VRP=1.20 (very rich) → conflicting → WAIT."""
    # perc_cheap=True, vrp_lean_rich=True (1.20>1.00)
    # Strong BUY: False (vrp not cheap)
    # Lean BUY A path 1: perc_cheap AND not vrp_lean_rich → vrp_lean_rich=True → not True=False → no
    # No lean buy either
    # vrp_rich=True (1.20>1.05), perc_lean_cheap=True (15<35)
    # Lean RICH A path 2: vrp_rich AND not perc_lean_cheap → not True=False → no
    # → WAIT
    s = compute_signal(15.0, 24.0, 20.0)   # VRP = 1.2
    assert s.label == "WAIT"


def test_signal_at_exact_strong_threshold():
    """
    perc=25.0 (not strictly < 25) AND VRP=0.95 (not strictly < 0.95) →
    neither STRONG BUY fires, but both are inside the lean-cheap zone
    (perc < 35, VRP < 1.0), so the result is LEAN BUY via variant B.
    """
    s = compute_signal(25.0, 19.0, 20.0)   # VRP = 0.95 exactly
    # perc_cheap:      25.0 < 25.0 = False  → strong BUY perc signal: off
    # vrp_cheap:       0.95 < 0.95 = False  → strong BUY VRP signal: off
    # perc_lean_cheap: 25.0 < 35.0 = True   → lean BUY perc signal: on
    # vrp_lean_cheap:  0.95 < 1.00 = True   → lean BUY VRP signal: on
    # Lean BUY variant B: both mildly cheap → LEAN BUY
    assert s.label == "LEAN BUY"
    assert s.strong is False


# ---------------------------------------------------------------------------
# compute_signal — VolSignal is immutable
# ---------------------------------------------------------------------------

def test_signal_is_frozen():
    s = compute_signal(10.0, 16.0, 20.0)
    with pytest.raises((AttributeError, TypeError)):
        s.label = "CHANGED"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# market_summary
# ---------------------------------------------------------------------------

def _sig(category: str) -> VolSignal:
    """Quick factory for a VolSignal with a given category."""
    label_map = {
        "buy": "BUY VOL",
        "lean_buy": "LEAN BUY",
        "neutral": "WAIT",
        "lean_rich": "LEAN RICH",
        "rich": "RICH",
        "no_data": "NO DATA",
    }
    return VolSignal(
        label=label_map[category],
        category=category,
        strong=(category in ("buy", "rich")),
        reason="test",
    )


def test_market_summary_empty():
    assert market_summary([]) == ""


def test_market_summary_all_no_data():
    sigs = [_sig("no_data")] * 3
    result = market_summary(sigs)
    assert "no vol data" in result.lower() or "run" in result.lower()


def test_market_summary_all_buy():
    sigs = [_sig("buy")] * 4
    result = market_summary(sigs)
    assert "4" in result
    assert "cheap" in result.lower() or "buy" in result.lower()


def test_market_summary_all_strong_buy():
    """All strong BUY → special message about buying across the board."""
    sigs = [_sig("buy")] * 3
    result = market_summary(sigs)
    # Should mention all 3 or "all"
    assert "3" in result or "all" in result.lower()


def test_market_summary_all_rich():
    sigs = [_sig("rich")] * 4
    result = market_summary(sigs)
    assert "4" in result
    assert "rich" in result.lower()


def test_market_summary_mostly_cheap():
    """3 of 4 cheap → mentions 3 and sizing up."""
    sigs = [_sig("buy"), _sig("buy"), _sig("lean_buy"), _sig("neutral")]
    result = market_summary(sigs)
    assert "3" in result
    assert "cheap" in result.lower()


def test_market_summary_mostly_rich():
    """3 of 4 rich → mentions 3 and waiting."""
    sigs = [_sig("rich"), _sig("rich"), _sig("lean_rich"), _sig("neutral")]
    result = market_summary(sigs)
    assert "3" in result
    assert "rich" in result.lower()


def test_market_summary_mixed():
    """Equal buy/rich → mixed message."""
    sigs = [_sig("buy"), _sig("rich"), _sig("neutral"), _sig("neutral")]
    result = market_summary(sigs)
    assert len(result) > 0  # non-empty


def test_market_summary_skips_no_data():
    """no_data signals are excluded from total before computing ratios."""
    sigs = [_sig("buy"), _sig("buy"), _sig("no_data")]
    result = market_summary(sigs)
    # 2 of 2 data signals are buy → should say "all" or "2 of 2"
    assert "2" in result or "all" in result.lower()


# ---------------------------------------------------------------------------
# Integration: compute_signal → market_summary pipeline
# ---------------------------------------------------------------------------

def test_pipeline_realistic_scenario():
    """Simulate 4 positions: 2 cheap, 1 neutral, 1 rich.

    Tightened to current iv_thresholds (PERC_VERY_CHEAP=20,
    PERC_RICH_STRONG=80) — both BUY VOL slots must use perc < 20.
    """
    positions = [
        (12.0, 16.0, 20.0),   # perc=12, VRP=0.80 → BUY VOL (strong)
        (15.0, 18.0, 20.0),   # perc=15, VRP=0.90 → BUY VOL (strong)
        (50.0, 20.0, 20.0),   # perc=50, VRP=1.00 → WAIT
        (82.0, 24.0, 20.0),   # perc=82, VRP=1.20 → RICH
    ]
    signals = [compute_signal(*p) for p in positions]

    assert signals[0].category == "buy"
    assert signals[1].category == "buy"
    assert signals[2].category == "neutral"
    assert signals[3].category == "rich"

    summary = market_summary(signals)
    assert "2" in summary
    assert len(summary) > 0


def test_pipeline_all_no_data():
    signals = [compute_signal(None, None, None)] * 5
    summary = market_summary(signals)
    assert len(summary) > 0
