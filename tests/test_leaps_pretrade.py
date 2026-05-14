"""Tests for the LEAPS pre-trade checklist."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.leaps_convergence import suggest_leaps
from volscope.analytics.leaps_pretrade import (
    build_order_templates,
    evaluate_earnings_blackout,
    evaluate_liquidity,
    run_pretrade_checks,
)


def _pypl_suggestion():
    return suggest_leaps(
        ticker="PYPL", spot=45.32, iv=0.302,
        target_dte_days=730, today=date(2026, 5, 10),
    )


def _ok_underlying_row() -> pd.Series:
    """A fresh, complete daily_vol row that should pass every gate."""
    return pd.Series({
        "ticker":              "PYPL",
        "date":                date.today(),
        "iv_30d":              30.2,
        "iv_60d":              30.1,
        "hv_20d":              44.7,
        "hv_60d":              30.0,
        "hv_yz_20d":           42.1,
        "iv_rank":             12.0,
        "iv_percentile":       29.0,
        "spot_price":          45.32,
        "iv_hv_spread":        -14.5,
        "put_call_ratio":      0.85,
        "total_call_volume":   12_000,
        "total_put_volume":    10_200,
        "total_open_interest": 220_000,
        "sector":              "Financial Services",
    })


# ── Liquidity ───────────────────────────────────────────────────────────

def test_liquidity_green_with_tight_chain():
    s = _pypl_suggestion()
    chain = pd.Series({
        "bid": 2.45, "ask": 2.55, "open_interest": 1_500, "volume": 200,
    })
    row = evaluate_liquidity(s, chain, _ok_underlying_row())
    assert row.level == "GREEN"


def test_liquidity_red_with_no_two_sided_market():
    s = _pypl_suggestion()
    chain = pd.Series({"bid": 0.0, "ask": 0.0, "open_interest": 0, "volume": 0})
    row = evaluate_liquidity(s, chain, _ok_underlying_row())
    assert row.level == "RED"


def test_liquidity_red_with_wide_spread():
    s = _pypl_suggestion()
    chain = pd.Series({"bid": 1.00, "ask": 2.00, "open_interest": 1_000, "volume": 100})
    row = evaluate_liquidity(s, chain, _ok_underlying_row())
    assert row.level == "RED"


def test_liquidity_falls_back_to_amber_when_chain_absent():
    """No chain data → the gate must not block the trade silently."""
    s = _pypl_suggestion()
    row = evaluate_liquidity(s, chain_row=None, underlying_row=_ok_underlying_row())
    assert row.level == "AMBER"
    assert "chain" in row.one_liner.lower()


# ── Earnings blackout ───────────────────────────────────────────────────

def test_earnings_recent_post_event_is_info():
    s = _pypl_suggestion()
    today = date(2026, 5, 10)
    last_er = today - timedelta(days=5)
    row = evaluate_earnings_blackout(s, last_er, today=today)
    assert row.level == "INFO"
    assert "ago" in row.one_liner


def test_earnings_within_blackout_window_is_amber():
    s = _pypl_suggestion()
    today = date(2026, 5, 10)
    next_er = today + timedelta(days=4)
    row = evaluate_earnings_blackout(s, next_er, today=today, blackout_days=7)
    assert row.level == "AMBER"


def test_earnings_far_future_is_green():
    s = _pypl_suggestion()
    today = date(2026, 5, 10)
    next_er = today + timedelta(days=120)
    row = evaluate_earnings_blackout(s, next_er, today=today)
    assert row.level == "GREEN"


def test_earnings_none_is_info():
    s = _pypl_suggestion()
    row = evaluate_earnings_blackout(s, None)
    assert row.level == "INFO"


# ── Order templates ─────────────────────────────────────────────────────

def test_order_templates_include_all_three_brokers():
    s = _pypl_suggestion()
    templates = build_order_templates(s, contracts=10)
    assert "Interactive Brokers" in templates
    assert "Tastyworks" in templates
    assert "Trade Republic / Optionsschein" in templates
    # Every template must mention the contract count, strike, and expiry.
    expiry_iso = s.expiry.isoformat()
    for name, text in templates.items():
        assert "10" in text
        assert f"{int(s.strike)}" in text
        assert expiry_iso in text or "Laufzeit" in text


# ── Orchestrator ────────────────────────────────────────────────────────

def test_run_pretrade_checks_returns_three_rows_and_unblocked_when_clean():
    s = _pypl_suggestion()
    today = date(2026, 5, 10)
    checklist = run_pretrade_checks(
        suggestion=s,
        underlying_row=_ok_underlying_row(),
        history=None,
        chain_row=pd.Series({
            "bid": 2.45, "ask": 2.55, "open_interest": 1_500, "volume": 200,
        }),
        next_earnings_date=today + timedelta(days=120),
        contracts=1,
        today=today,
    )
    assert len(checklist.rows) == 3
    assert not checklist.blocked
    assert checklist.green_count() >= 2


def test_run_pretrade_checks_blocks_on_red_liquidity():
    s = _pypl_suggestion()
    checklist = run_pretrade_checks(
        suggestion=s,
        underlying_row=_ok_underlying_row(),
        chain_row=pd.Series({"bid": 0.0, "ask": 0.0, "open_interest": 0, "volume": 0}),
        next_earnings_date=None,
        contracts=1,
    )
    assert checklist.blocked
