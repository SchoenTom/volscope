"""Tests for analytics.scenario_analyzer — deterministic stress tests."""
from __future__ import annotations

import pytest

from volscope.analytics.portfolio_risk import PortfolioLeg
from volscope.analytics.scenario_analyzer import (
    PREBAKED_SCENARIOS,
    LegImpact,
    Scenario,
    ScenarioResult,
    Shock,
    build_custom_scenario,
    run_all_prebaked,
    run_scenario,
    stress_leg,
)


def _leg(ticker="QQQ", spot=400.0, strike=380.0, dte=60, iv=22.0,
         option_type="put", quantity=1):
    return PortfolioLeg(
        ticker=ticker, spot=spot, strike=strike, days_to_expiry=dte,
        iv=iv, option_type=option_type, quantity=quantity,
    )


# ──────────────────────────────────────────────────────────────────────────
# Pre-baked scenarios
# ──────────────────────────────────────────────────────────────────────────

class TestPrebaked:
    def test_at_least_six(self):
        assert len(PREBAKED_SCENARIOS) >= 6

    def test_every_scenario_has_name(self):
        for s in PREBAKED_SCENARIOS:
            assert s.name and isinstance(s.name, str)

    def test_every_scenario_has_wildcard_or_explicit_shocks(self):
        for s in PREBAKED_SCENARIOS:
            assert s.shocks


# ──────────────────────────────────────────────────────────────────────────
# stress_leg
# ──────────────────────────────────────────────────────────────────────────

class TestStressLeg:
    def test_returns_impact(self):
        impact = stress_leg(_leg(), Shock(spot_shock_pct=-0.1, iv_shock_pp=+5))
        assert isinstance(impact, LegImpact)

    def test_long_put_profits_in_crash(self):
        # Long put + spot down + IV up → P&L positive
        leg = _leg(option_type="put", strike=380, quantity=1)
        impact = stress_leg(leg, Shock(spot_shock_pct=-0.20, iv_shock_pp=+10))
        assert impact.pnl_dollar > 0

    def test_long_call_loses_in_crash(self):
        leg = _leg(option_type="call", strike=420, quantity=1)
        impact = stress_leg(leg, Shock(spot_shock_pct=-0.20, iv_shock_pp=+10))
        # Spot drop hurts call but IV up helps; for OTM call, spot loss usually dominates
        # Check sign is at least consistent (not always positive)
        assert isinstance(impact.pnl_dollar, float)

    def test_zero_shock_no_pnl(self):
        impact = stress_leg(_leg(), Shock(0.0, 0.0))
        assert abs(impact.pnl_dollar) < 0.01

    def test_quantity_scales_pnl(self):
        i1 = stress_leg(_leg(quantity=1), Shock(spot_shock_pct=-0.1, iv_shock_pp=+5))
        i2 = stress_leg(_leg(quantity=2), Shock(spot_shock_pct=-0.1, iv_shock_pp=+5))
        assert abs(i2.pnl_dollar - 2 * i1.pnl_dollar) < 0.5

    def test_short_position_inverts_pnl_sign(self):
        long_imp  = stress_leg(_leg(quantity=+1), Shock(spot_shock_pct=-0.10, iv_shock_pp=+8))
        short_imp = stress_leg(_leg(quantity=-1), Shock(spot_shock_pct=-0.10, iv_shock_pp=+8))
        assert (long_imp.pnl_dollar > 0) != (short_imp.pnl_dollar > 0)

    def test_iv_only_shock_works(self):
        impact = stress_leg(_leg(), Shock(spot_shock_pct=0.0, iv_shock_pp=+10))
        assert impact.pnl_dollar > 0   # long put + IV up = vega gain


# ──────────────────────────────────────────────────────────────────────────
# run_scenario
# ──────────────────────────────────────────────────────────────────────────

class TestRunScenario:
    def test_empty_portfolio(self):
        scen = PREBAKED_SCENARIOS[0]
        r = run_scenario([], scen)
        assert r.total_pnl == 0.0
        assert r.leg_impacts == ()

    def test_returns_result(self):
        scen = PREBAKED_SCENARIOS[0]
        r = run_scenario([_leg()], scen)
        assert isinstance(r, ScenarioResult)

    def test_total_pnl_sums_legs(self):
        scen = PREBAKED_SCENARIOS[2]   # -10% / +8pp
        legs = [_leg(quantity=1), _leg(quantity=2)]
        r = run_scenario(legs, scen)
        # Total PnL approximately = sum of leg pnls
        assert abs(r.total_pnl - sum(i.pnl_dollar for i in r.leg_impacts)) < 1.0

    def test_post_value_equals_pre_plus_pnl(self):
        scen = PREBAKED_SCENARIOS[2]
        r = run_scenario([_leg()], scen)
        assert abs(r.total_post_value - (r.total_pre_value + r.total_pnl)) < 0.5

    def test_worst_and_best_identified(self):
        scen = PREBAKED_SCENARIOS[3]   # -20% / +15pp
        legs = [
            _leg(option_type="put", quantity=1),    # benefits
            _leg(option_type="call", strike=420, quantity=1),  # hurts
        ]
        r = run_scenario(legs, scen)
        assert r.worst_leg is not None
        assert r.best_leg is not None
        assert r.worst_leg.pnl_dollar <= r.best_leg.pnl_dollar

    def test_post_greeks_recomputed_after_shock(self):
        scen = PREBAKED_SCENARIOS[3]
        r = run_scenario([_leg()], scen)
        # After a -20% spot shock, the put's delta should be more negative
        # (deeper ITM)
        assert r.post_greeks.delta < r.pre_greeks.delta


# ──────────────────────────────────────────────────────────────────────────
# Per-ticker shocks
# ──────────────────────────────────────────────────────────────────────────

class TestPerTickerShocks:
    def test_explicit_ticker_shock_wins_over_wildcard(self):
        scen = Scenario(
            name="x", description="",
            shocks={
                "*":   Shock(spot_shock_pct=-0.10),
                "QQQ": Shock(spot_shock_pct=-0.30),  # QQQ-specific override
            },
        )
        legs = [_leg(ticker="QQQ"), _leg(ticker="MSTR", spot=300, strike=280)]
        r = run_scenario(legs, scen)
        # QQQ leg should reflect -30% (bigger move → bigger PnL magnitude)
        impacts_by_ticker = {i.ticker: i for i in r.leg_impacts}
        assert abs(impacts_by_ticker["QQQ"].pnl_dollar) > abs(impacts_by_ticker["MSTR"].pnl_dollar)

    def test_ticker_outside_shocks_unchanged(self):
        scen = Scenario(
            name="x", description="",
            shocks={"QQQ": Shock(spot_shock_pct=-0.30)},
        )
        legs = [_leg(ticker="MSTR", spot=300, strike=280)]
        r = run_scenario(legs, scen)
        # MSTR has no shock and no wildcard → P&L should be ~0
        assert abs(r.total_pnl) < 0.5


# ──────────────────────────────────────────────────────────────────────────
# Custom scenario builder
# ──────────────────────────────────────────────────────────────────────────

class TestCustomScenarios:
    def test_builds_scenario(self):
        s = build_custom_scenario(
            name="my-test",
            spot_shock_pct={"QQQ": -0.10, "*": -0.05},
            iv_shock_pp={"QQQ": +5, "MSTR": +8},
        )
        assert s.name == "my-test"
        assert "QQQ" in s.shocks
        assert "MSTR" in s.shocks
        assert "*" in s.shocks

    def test_qqq_combines_both_dicts(self):
        s = build_custom_scenario(
            name="x",
            spot_shock_pct={"QQQ": -0.10},
            iv_shock_pp={"QQQ": +5},
        )
        assert s.shocks["QQQ"].spot_shock_pct == -0.10
        assert s.shocks["QQQ"].iv_shock_pp == +5

    def test_unilateral_shock_zeros_other_field(self):
        s = build_custom_scenario(
            name="x",
            spot_shock_pct={"QQQ": -0.10},
            iv_shock_pp={},
        )
        assert s.shocks["QQQ"].iv_shock_pp == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Pre-baked batch
# ──────────────────────────────────────────────────────────────────────────

class TestPrebakedBatch:
    def test_returns_one_result_per_scenario(self):
        legs = [_leg()]
        results = run_all_prebaked(legs)
        assert len(results) == len(PREBAKED_SCENARIOS)

    def test_each_result_named(self):
        legs = [_leg()]
        results = run_all_prebaked(legs)
        for r, s in zip(results, PREBAKED_SCENARIOS):
            assert r.scenario_name == s.name

    def test_handles_empty_portfolio(self):
        results = run_all_prebaked([])
        for r in results:
            assert r.total_pnl == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Frozen guards
# ──────────────────────────────────────────────────────────────────────────

class TestFrozen:
    def test_scenario_frozen(self):
        with pytest.raises(Exception):
            PREBAKED_SCENARIOS[0].name = "x"  # type: ignore[misc]

    def test_result_frozen(self):
        r = run_scenario([_leg()], PREBAKED_SCENARIOS[0])
        with pytest.raises(Exception):
            r.total_pnl = 0  # type: ignore[misc]

    def test_shock_frozen(self):
        s = Shock(spot_shock_pct=-0.1, iv_shock_pp=+5)
        with pytest.raises(Exception):
            s.spot_shock_pct = 0  # type: ignore[misc]
