"""Tests for analytics.portfolio_risk — Greeks aggregation + Monte Carlo VaR."""
from __future__ import annotations

import math

import pytest

from volscope.analytics.portfolio_risk import (
    GreeksSnapshot,
    PortfolioLeg,
    VarResult,
    concentration_by_ticker,
    leg_greeks,
    monte_carlo_var,
    portfolio_greeks,
)


def _leg(ticker="QQQ", spot=400.0, strike=380.0, dte=60, iv=22.0,
         option_type="put", quantity=1):
    return PortfolioLeg(
        ticker=ticker, spot=spot, strike=strike, days_to_expiry=dte,
        iv=iv, option_type=option_type, quantity=quantity,
    )


# ──────────────────────────────────────────────────────────────────────────
# leg_greeks
# ──────────────────────────────────────────────────────────────────────────

class TestLegGreeks:
    def test_returns_snapshot(self):
        g = leg_greeks(_leg())
        assert isinstance(g, GreeksSnapshot)

    def test_long_put_negative_delta(self):
        g = leg_greeks(_leg(option_type="put", quantity=1))
        assert g.delta < 0

    def test_long_call_positive_delta(self):
        g = leg_greeks(_leg(option_type="call", strike=420.0, quantity=1))
        assert g.delta > 0

    def test_short_put_positive_delta(self):
        g = leg_greeks(_leg(option_type="put", quantity=-1))
        assert g.delta > 0

    def test_long_position_positive_vega(self):
        g = leg_greeks(_leg(quantity=1))
        assert g.vega > 0

    def test_short_position_negative_vega(self):
        g = leg_greeks(_leg(quantity=-1))
        assert g.vega < 0

    def test_quantity_scales_linearly(self):
        g1 = leg_greeks(_leg(quantity=1))
        g2 = leg_greeks(_leg(quantity=2))
        assert math.isclose(g2.delta, 2 * g1.delta, rel_tol=0.01)
        assert math.isclose(g2.vega,  2 * g1.vega,  rel_tol=0.01)


# ──────────────────────────────────────────────────────────────────────────
# portfolio_greeks
# ──────────────────────────────────────────────────────────────────────────

class TestPortfolioGreeks:
    def test_empty_returns_zero(self):
        g = portfolio_greeks([])
        assert g.delta == 0.0
        assert g.vega == 0.0

    def test_sums_legs(self):
        legs = [_leg(quantity=1), _leg(quantity=2)]
        agg = portfolio_greeks(legs)
        single = leg_greeks(_leg(quantity=1))
        # 1 + 2 = 3 contracts
        assert math.isclose(agg.delta, 3 * single.delta, rel_tol=0.01)

    def test_offsetting_legs_cancel(self):
        legs = [_leg(quantity=1), _leg(quantity=-1)]
        agg = portfolio_greeks(legs)
        assert math.isclose(agg.delta, 0.0, abs_tol=0.01)
        assert math.isclose(agg.vega, 0.0, abs_tol=0.01)

    def test_notional_sums(self):
        legs = [_leg(quantity=1), _leg(quantity=1)]
        agg = portfolio_greeks(legs)
        assert agg.notional == 2 * 400.0 * 100


# ──────────────────────────────────────────────────────────────────────────
# Concentration
# ──────────────────────────────────────────────────────────────────────────

class TestConcentration:
    def test_empty_returns_empty_df(self):
        df = concentration_by_ticker([])
        assert df.empty

    def test_groups_by_ticker(self):
        legs = [
            _leg(ticker="QQQ", quantity=1),
            _leg(ticker="QQQ", quantity=2),
            _leg(ticker="MSTR", spot=300.0, strike=280.0, quantity=1),
        ]
        df = concentration_by_ticker(legs)
        assert len(df) == 2
        qqq_row = df[df["ticker"] == "QQQ"].iloc[0]
        assert qqq_row["n_legs"] == 2

    def test_sorted_by_abs_vega(self):
        legs = [
            _leg(ticker="A", quantity=1),
            _leg(ticker="B", quantity=10),
        ]
        df = concentration_by_ticker(legs)
        # B has 10x vega → should come first
        assert df.iloc[0]["ticker"] == "B"


# ──────────────────────────────────────────────────────────────────────────
# Monte Carlo VaR
# ──────────────────────────────────────────────────────────────────────────

class TestMonteCarloVar:
    def test_empty_portfolio_returns_zero(self):
        v = monte_carlo_var([])
        assert v.var_95 == 0.0
        assert v.n_paths == 0

    def test_returns_var_result(self):
        legs = [_leg()]
        v = monte_carlo_var(legs, n_paths=200, seed=42)
        assert isinstance(v, VarResult)

    def test_var_non_negative(self):
        legs = [_leg()]
        v = monte_carlo_var(legs, n_paths=200, seed=42)
        assert v.var_95 >= 0

    def test_cvar_at_least_var(self):
        legs = [_leg()]
        v = monte_carlo_var(legs, n_paths=500, seed=42)
        # CVaR is the mean of worst tail → must be at least VaR
        assert v.cvar_95 >= v.var_95 - 0.01  # tiny tolerance for sample noise

    def test_seed_reproducible(self):
        legs = [_leg()]
        v1 = monte_carlo_var(legs, n_paths=200, seed=99)
        v2 = monte_carlo_var(legs, n_paths=200, seed=99)
        assert v1.var_95 == v2.var_95

    def test_seed_difference_changes_result(self):
        legs = [_leg()]
        v1 = monte_carlo_var(legs, n_paths=200, seed=1)
        v2 = monte_carlo_var(legs, n_paths=200, seed=2)
        assert v1.var_95 != v2.var_95   # extremely unlikely to coincide

    def test_horizon_days_recorded(self):
        legs = [_leg()]
        v = monte_carlo_var(legs, horizon_days=10, n_paths=100, seed=1)
        assert v.horizon_days == 10

    def test_short_position_can_have_unbounded_loss(self):
        # Short call: loss grows when spot rallies
        legs = [_leg(option_type="call", strike=420.0, quantity=-5)]
        v = monte_carlo_var(legs, n_paths=500, seed=42)
        assert v.var_95 > 0   # short calls have downside risk

    def test_doubled_position_higher_var_than_single(self):
        # Doubling a directional position must increase VaR. This is the
        # cleanest sanity check on the MC: linear scaling of risk with
        # position size (modulo MC noise).
        single = monte_carlo_var(
            [_leg(option_type="put", strike=380, quantity=1)],
            n_paths=400, seed=42,
        )
        doubled = monte_carlo_var(
            [_leg(option_type="put", strike=380, quantity=2)],
            n_paths=400, seed=42,
        )
        assert doubled.var_95 > single.var_95


# ──────────────────────────────────────────────────────────────────────────
# Frozen guards
# ──────────────────────────────────────────────────────────────────────────

class TestFrozen:
    def test_leg_frozen(self):
        l = _leg()
        with pytest.raises(Exception):
            l.spot = 999.0  # type: ignore[misc]

    def test_greeks_frozen(self):
        g = portfolio_greeks([_leg()])
        with pytest.raises(Exception):
            g.delta = 0.0  # type: ignore[misc]

    def test_var_frozen(self):
        v = monte_carlo_var([_leg()], n_paths=50, seed=1)
        with pytest.raises(Exception):
            v.var_95 = 999.0  # type: ignore[misc]
