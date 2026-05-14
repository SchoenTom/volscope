"""Tests for signals/filters.py — every gate has + and - test cases."""
from __future__ import annotations

from datetime import date, timedelta

from volscope.signals.filters import (
    gate_bid_ask_spread, gate_consensus, gate_earnings,
    gate_macro_calendar, gate_open_interest, gate_persistence,
    gate_regime, gate_volume, run_all_gates,
)


def test_persistence():
    assert gate_persistence(True, True).passed
    assert not gate_persistence(True, False).passed
    assert not gate_persistence(False, True).passed


def test_volume():
    assert gate_volume(today_volume=1500, adv_20d=2000).passed   # 75% > 50%
    assert not gate_volume(today_volume=500, adv_20d=2000).passed
    assert not gate_volume(today_volume=1000, adv_20d=0).passed


def test_open_interest():
    assert gate_open_interest(500).passed
    assert not gate_open_interest(499).passed


def test_bid_ask_spread():
    assert gate_bid_ask_spread(spread=0.10, mid=2.00).passed     # 5% < 10%
    assert not gate_bid_ask_spread(spread=0.30, mid=2.00).passed # 15% > 10%
    assert not gate_bid_ask_spread(spread=0.10, mid=0.0).passed


def test_earnings():
    today = date(2026, 5, 14)
    far = today + timedelta(days=30)
    near = today + timedelta(days=5)
    assert gate_earnings(today, far).passed
    assert not gate_earnings(today, near).passed
    assert gate_earnings(today, None).passed                    # no known er = pass


def test_earnings_widens_window_on_low_confidence():
    today = date(2026, 5, 14)
    twenty_days_out = today + timedelta(days=20)                 # > 14, < 21
    assert gate_earnings(today, twenty_days_out,
                          source_confidence=1.0).passed         # 14d window OK
    assert not gate_earnings(today, twenty_days_out,
                              source_confidence=0.7).passed     # widened to 21d


def test_macro_calendar():
    today = date(2026, 5, 14)
    fomc_close = today + timedelta(days=2)
    fomc_far = today + timedelta(days=10)
    assert not gate_macro_calendar(today, [fomc_close]).passed
    assert gate_macro_calendar(today, [fomc_far]).passed
    assert gate_macro_calendar(today, []).passed


def test_regime():
    assert gate_regime(p_calm=0.7, direction="short_vol").passed
    assert not gate_regime(p_calm=0.4, direction="short_vol").passed
    assert gate_regime(p_calm=0.4, direction="long_vol").passed  # long-vol agnostic


def test_consensus_short_vol():
    assert gate_consensus(ivr=60, ivp=75, direction="short_vol").passed
    assert not gate_consensus(ivr=40, ivp=75, direction="short_vol").passed
    # single-spike contamination
    assert not gate_consensus(ivr=10, ivp=75, direction="short_vol").passed


def test_consensus_long_vol():
    assert gate_consensus(ivr=20, ivp=15, direction="long_vol").passed
    assert not gate_consensus(ivr=40, ivp=15, direction="long_vol").passed


def test_run_all_gates_all_pass():
    today = date(2026, 5, 14)
    ok, results = run_all_gates(
        signal_today=True, signal_yesterday=True,
        today_volume=2000, adv_20d=2000, oi_at_target=1000,
        spread=0.05, mid=2.00, today=today,
        next_earnings=today + timedelta(days=30),
        source_confidence=1.0, macro_dates=[], p_calm=0.8,
        ivr_value=60, ivp_value=75, direction="short_vol",
    )
    assert ok, [r for r in results if not r.passed]


def test_run_all_gates_blocks_on_earnings():
    today = date(2026, 5, 14)
    ok, results = run_all_gates(
        signal_today=True, signal_yesterday=True,
        today_volume=2000, adv_20d=2000, oi_at_target=1000,
        spread=0.05, mid=2.00, today=today,
        next_earnings=today + timedelta(days=5),
        source_confidence=1.0, macro_dates=[], p_calm=0.8,
        ivr_value=60, ivp_value=75, direction="short_vol",
    )
    assert not ok
    assert any(r.name == "earnings" and not r.passed for r in results)
