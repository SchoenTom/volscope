"""
Signal hard-gates — Phase 1 scaffold.

Eight binary filters. Any failure blocks the trade and logs the reason.
Filters are pure functions on a single signal candidate; the caller is
responsible for assembling the inputs (chain liquidity, calendar dates,
HMM regime probability, factor history).

Spec is in the masterplan section "Hard gates."
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Direction = Literal["short_vol", "long_vol"]


@dataclass(frozen=True)
class GateResult:
    """Result of a single gate check. ``passed`` False ⇒ ``reason`` is set."""
    name: str
    passed: bool
    reason: str = ""


def gate_persistence(signal_today: bool, signal_yesterday: bool) -> GateResult:
    """Require the signal to have been live for at least 2 consecutive days."""
    if signal_today and signal_yesterday:
        return GateResult("persistence", True)
    return GateResult("persistence", False, "signal not persistent across 2 days")


def gate_volume(today_volume: float, adv_20d: float, min_ratio: float = 0.5) -> GateResult:
    """Today's option volume must be at least 50% of 20-day ADV."""
    if adv_20d <= 0:
        return GateResult("volume", False, "ADV unavailable")
    ratio = today_volume / adv_20d
    if ratio >= min_ratio:
        return GateResult("volume", True)
    return GateResult("volume", False, f"volume {ratio:.0%} of ADV (<{min_ratio:.0%})")


def gate_open_interest(oi_at_target: int, min_oi: int = 500) -> GateResult:
    """OI at target strikes must be >=500 (preferred 1000+)."""
    if oi_at_target >= min_oi:
        return GateResult("open_interest", True)
    return GateResult("open_interest", False, f"OI {oi_at_target} < {min_oi}")


def gate_bid_ask_spread(spread: float, mid: float,
                        max_pct: float = 0.10) -> GateResult:
    """Bid-ask spread must be <= 10% of mid; <= 5% preferred (warn-not-fail)."""
    if mid <= 0:
        return GateResult("bas", False, "no mid price")
    pct = spread / mid
    if pct <= max_pct:
        return GateResult("bas", True)
    return GateResult("bas", False, f"spread {pct:.0%} of mid > {max_pct:.0%}")


def gate_earnings(today: date, next_earnings: date | None,
                  blackout_days: int = 14,
                  source_confidence: float = 1.0) -> GateResult:
    """
    Block short-vol entries within 14 days of earnings (21 if confidence <1.0).

    Per Patell & Wolfson (1979/1981): IV does NOT mean-revert into
    earnings — it expands. Selling premium here is structurally
    negative-edge. This is the most important single gate.
    """
    if next_earnings is None:
        return GateResult("earnings", True, "no upcoming earnings known")
    eff_blackout = blackout_days if source_confidence >= 1.0 else max(blackout_days, 21)
    cutoff = today + timedelta(days=eff_blackout)
    if next_earnings > cutoff:
        return GateResult("earnings", True)
    days_to = (next_earnings - today).days
    return GateResult("earnings", False,
                      f"earnings in {days_to}d (need >= {eff_blackout}d)")


def gate_macro_calendar(today: date,
                        macro_dates: list[date],
                        window: int = 3) -> GateResult:
    """No new entries within ±3 days of FOMC / CPI / NFP."""
    for d in macro_dates:
        if abs((d - today).days) <= window:
            return GateResult("macro", False,
                              f"macro event {d.isoformat()} within ±{window}d")
    return GateResult("macro", True)


def gate_regime(p_calm: float, direction: Direction,
                min_p_calm_for_short: float = 0.6) -> GateResult:
    """HMM regime gate. Short-vol requires p_calm >= 0.6."""
    if direction == "short_vol":
        if p_calm >= min_p_calm_for_short:
            return GateResult("regime", True)
        return GateResult("regime", False,
                          f"p_calm {p_calm:.2f} < {min_p_calm_for_short:.2f} (stress)")
    return GateResult("regime", True)   # long-vol is regime-agnostic here


def gate_consensus(ivr: float, ivp: float, direction: Direction) -> GateResult:
    """
    IVR + IVP must agree.

    Short vol: BOTH ivr>50 AND ivp>70.
    Long vol:  BOTH ivr<30 AND ivp<30.
    If |ivr − ivp| > 30: single-spike contamination — trust IVP and BLOCK
    unless ivp alone clears the relevant threshold.
    """
    if direction == "short_vol":
        if abs(ivr - ivp) > 30:
            return GateResult("consensus", False,
                              f"single-spike contamination (|ivr-ivp| = {abs(ivr-ivp):.0f})")
        if ivr > 50 and ivp > 70:
            return GateResult("consensus", True)
        return GateResult("consensus", False,
                          f"need ivr>50 AND ivp>70 (got {ivr:.0f}, {ivp:.0f})")
    # long_vol
    if abs(ivr - ivp) > 30:
        return GateResult("consensus", False,
                          f"single-spike contamination (|ivr-ivp| = {abs(ivr-ivp):.0f})")
    if ivr < 30 and ivp < 30:
        return GateResult("consensus", True)
    return GateResult("consensus", False,
                      f"need ivr<30 AND ivp<30 (got {ivr:.0f}, {ivp:.0f})")


def run_all_gates(*, signal_today: bool, signal_yesterday: bool,
                  today_volume: float, adv_20d: float,
                  oi_at_target: int, spread: float, mid: float,
                  today: date, next_earnings: date | None,
                  source_confidence: float, macro_dates: list[date],
                  p_calm: float, ivr_value: float, ivp_value: float,
                  direction: Direction) -> tuple[bool, list[GateResult]]:
    """Run all 8 gates and return (overall_pass, list_of_results)."""
    results = [
        gate_persistence(signal_today, signal_yesterday),
        gate_volume(today_volume, adv_20d),
        gate_open_interest(oi_at_target),
        gate_bid_ask_spread(spread, mid),
        gate_earnings(today, next_earnings, source_confidence=source_confidence),
        gate_macro_calendar(today, macro_dates),
        gate_regime(p_calm, direction),
        gate_consensus(ivr_value, ivp_value, direction),
    ]
    return all(r.passed for r in results), results
