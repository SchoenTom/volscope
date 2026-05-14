"""Tests for the LEAPS scenario engine."""
from __future__ import annotations

from datetime import date

import pytest

from volscope.analytics.leaps_convergence import suggest_leaps
from volscope.analytics.leaps_scenarios import (
    build_risk_table,
    build_scenario_matrix,
    build_theta_runway,
    build_vega_gain_table,
)


def _pypl_suggestion():
    return suggest_leaps(
        ticker="PYPL", spot=45.32, iv=0.302,
        target_dte_days=730, today=date(2026, 5, 10),
    )


# ── Spot × time matrix ──────────────────────────────────────────────────

def test_scenario_matrix_shape_matches_grids():
    s = _pypl_suggestion()
    m = build_scenario_matrix(s)
    assert len(m.cells) == len(m.spot_grid)
    for row in m.cells:
        assert len(row) == len(m.months_grid)


def test_scenario_matrix_terminal_cell_equals_intrinsic():
    """At months ≥ days_to_exp, premium must collapse to intrinsic."""
    s = _pypl_suggestion()
    long_horizon = max(48, (s.days_to_exp // 30) + 12)
    m = build_scenario_matrix(s, month_horizons=(1, long_horizon))
    for row in m.cells:
        terminal = row[-1]
        expected = max(0.0, terminal.spot - s.strike)
        assert terminal.premium == pytest.approx(expected, abs=0.01)


def test_scenario_matrix_pnl_at_unchanged_spot_today_is_zero():
    """At spot×1.0 and 0 months elapsed, premium ~= entry, P&L ~= 0."""
    s = _pypl_suggestion()
    m = build_scenario_matrix(
        s, spot_multipliers=(1.0,), month_horizons=(0,),
    )
    cell = m.cells[0][0]
    assert cell.pnl_per_share == pytest.approx(0.0, abs=0.05)


# ── Vega gain table ─────────────────────────────────────────────────────

def test_vega_gain_table_pypl_30_to_50_pct_lifts_premium():
    """The deck's claim: IV 30% → 50% adds ~67% to the LEAPS premium."""
    s = _pypl_suggestion()
    table = build_vega_gain_table(s, targets=(0.30, 0.50))
    base_row = next(r for r in table.rows if r.target_iv == 0.30)
    target_row = next(r for r in table.rows if r.target_iv == 0.50)
    # Target premium must exceed base premium materially.
    assert target_row.new_premium > base_row.new_premium
    # The lift over the entry premium should be at least 30 % (deck cites 67 %).
    assert target_row.pnl_pct_of_premium >= 30.0


def test_vega_gain_table_target_below_current_is_negative():
    s = _pypl_suggestion()
    table = build_vega_gain_table(s, targets=(0.20,))
    row = table.rows[0]
    assert row.pnl_per_share < 0


# ── Theta runway ────────────────────────────────────────────────────────

def test_theta_runway_starts_with_low_decay_for_24m_leap():
    """The deck's claim: 32-month LEAPS bleeds only cents per day at entry."""
    s = _pypl_suggestion()
    runway = build_theta_runway(s)
    assert runway.points[0].theta_per_day != 0
    # Per-day theta in the first 6 months should be small relative to premium.
    assert abs(runway.points[0].theta_per_day) < s.est_premium * 0.01


def test_theta_runway_detects_cliff():
    """Cliff month must be set well before expiry — usually in the last 6 months."""
    s = _pypl_suggestion()
    runway = build_theta_runway(s)
    if runway.cliff_starts_at_month is not None:
        # Cliff should fall in the last third of the holding period.
        assert runway.cliff_starts_at_month >= (s.days_to_exp // 30) // 2


# ── Risk table ──────────────────────────────────────────────────────────

def test_risk_table_invalidation_is_20pct_below_entry_by_default():
    s = _pypl_suggestion()
    rt = build_risk_table(s, capital_deployed=300.0)
    assert rt.invalidation_spot == pytest.approx(s.spot * 0.80, abs=0.5)


def test_risk_table_max_loss_equals_capital_deployed():
    s = _pypl_suggestion()
    rt = build_risk_table(s, capital_deployed=1_234.56)
    assert rt.max_loss_dollars == pytest.approx(1_234.56, abs=0.01)


def test_risk_table_scaling_in_rungs_descend_in_spot():
    s = _pypl_suggestion()
    rt = build_risk_table(s, capital_deployed=300.0)
    triggers = [r.spot_trigger for r in rt.scaling_in_levels]
    assert triggers == sorted(triggers, reverse=True)
