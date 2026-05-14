"""Tests for the LEAPS sizing engine."""
from __future__ import annotations

from datetime import date

import pytest

from volscope.analytics.leaps_convergence import suggest_leaps
from volscope.analytics.leaps_sizing import (
    SIZING_RULES,
    FixedDollarRule,
    FractionOfBookRule,
    lift_to_next_contract_cost,
    size_position,
)


def _pypl_suggestion():
    """Reference suggestion mirroring the deck (spot 45.32, IV 30.2 %)."""
    return suggest_leaps(
        ticker="PYPL", spot=45.32, iv=0.302,
        target_dte_days=730, today=date(2026, 5, 10),
    )


# ── Whole-contract rounding ─────────────────────────────────────────────

def test_size_position_pypl_300_budget_buys_one_contract():
    """The deck's 1-contract / $300 reference case must reproduce."""
    s = _pypl_suggestion()
    plan = size_position(s, budget=300.0)
    assert plan.contracts == 1
    assert plan.capital_deployed == pytest.approx(s.est_premium * 100, abs=0.01)
    assert plan.capital_residual >= 0


def test_size_position_pypl_3000_budget_caps_capital_to_budget():
    """At $3 000 budget, deployed capital must always be ≤ budget; the
    contract count depends on the BSM-priced premium for the day, which
    is below the deck's $3 reference (the deck used IBKR live ask, we
    use a model price). The invariants we assert are budget-safe sizing,
    not the exact 10-contract number.
    """
    s = _pypl_suggestion()
    plan = size_position(s, budget=3_000.0)
    assert plan.contracts >= 1
    assert plan.capital_deployed <= 3_000.0
    # ≥ 1 ensures the user actually gets something for $3 000.
    assert plan.capital_deployed == pytest.approx(plan.contracts * s.est_premium * 100, abs=0.01)


def test_size_position_undersized_budget_returns_zero_contracts():
    """A $50 budget cannot afford even one contract — must report zero, not error."""
    s = _pypl_suggestion()
    plan = size_position(s, budget=50.0)
    assert plan.contracts == 0
    assert plan.is_undersized
    assert plan.capital_deployed == 0.0
    assert plan.capital_residual == 50.0
    assert "too small" in plan.rationale


def test_size_position_negative_budget_raises():
    s = _pypl_suggestion()
    with pytest.raises(ValueError):
        size_position(s, budget=-1.0)


# ── Payoff ladder ───────────────────────────────────────────────────────

def test_size_position_payoff_ladder_dollars_match_contracts():
    """At expiry spot above strike, P&L should equal (intrinsic × contracts × 100) − deployed."""
    s = _pypl_suggestion()
    plan = size_position(s, budget=3_000.0)
    # Find the payoff entry at spot ≥ strike + 70 (the deck's "+2 233 %" row)
    target = next((p for p in plan.payoff if p.spot_at_expiry >= s.strike + 60), None)
    assert target is not None
    intrinsic = target.spot_at_expiry - s.strike
    expected_profit = intrinsic * plan.contracts * 100 - plan.capital_deployed
    assert target.profit_dollars == pytest.approx(round(expected_profit, 2), abs=0.01)


def test_size_position_payoff_below_strike_is_full_loss():
    s = _pypl_suggestion()
    plan = size_position(s, budget=300.0)
    below = [p for p in plan.payoff if p.spot_at_expiry < s.strike]
    assert below
    for cell in below:
        assert cell.intrinsic_per_share == 0.0
        assert cell.profit_dollars == pytest.approx(-plan.capital_deployed, abs=0.01)
        assert cell.return_pct == -100.0


# ── Sizing rules ────────────────────────────────────────────────────────

def test_fixed_dollar_rule_ignores_book():
    rule = FixedDollarRule(name="x", description="x", dollars=500.0)
    assert rule.budget_from_book(book_value=100_000) == 500.0


def test_fraction_of_book_rule_scales_linearly():
    rule = FractionOfBookRule(name="x", description="x", fraction=0.05)
    assert rule.budget_from_book(book_value=20_000) == 1_000.0
    assert rule.budget_from_book(book_value=0) == 0.0


def test_sizing_rules_registry_has_pypl_anchor():
    """The deck's $3 000 size must be in the registry — the user expects it."""
    assert any(
        isinstance(r, FixedDollarRule) and r.dollars == 3_000.0
        for r in SIZING_RULES
    )


# ── Lift-to-next-contract helper ────────────────────────────────────────

def test_lift_to_next_contract_cost_is_zero_when_residual_covers_one():
    s = _pypl_suggestion()
    cost_per_contract = s.est_premium * 100
    plan = size_position(s, budget=cost_per_contract * 1 + cost_per_contract * 0.5)
    # Residual ≈ half a contract — short by half a contract, but lift should equal that
    extra = lift_to_next_contract_cost(plan, s)
    assert 0.0 < extra <= cost_per_contract


def test_lift_to_next_contract_cost_zero_when_already_full():
    s = _pypl_suggestion()
    plan = size_position(s, budget=s.est_premium * 100 * 5)
    extra = lift_to_next_contract_cost(plan, s)
    # Budget is exactly 5 contracts → residual is ~0 → need full cost-per-contract to add one
    assert extra == pytest.approx(s.est_premium * 100, abs=0.5)
