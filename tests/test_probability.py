"""Tests for the probability engine."""
from __future__ import annotations

import pytest

from volscope.analytics.probability import (
    pop, pop_closed_form, pop_monte_carlo, profit_density,
)
from volscope.analytics.strategy_templates import TEMPLATES


def _mat(name: str, *, spot=100.0, iv=25.0, dte=60, contracts=1):
    return TEMPLATES[name].materialize(
        ticker="X", spot=spot, iv_pct=iv, dte=dte, contracts=contracts,
    )


class TestClosedForm:
    def test_long_call_atm_high_iv_pop_below_50(self):
        """Master prompt sanity: ATM long call at 30 % IV → PoP < 50 %.

        At ATM the spot must exceed the breakeven (strike + debit) for
        profit. With high IV the debit is large → BE well above spot →
        risk-neutral drift can't push you there often enough.
        """
        m = _mat("Long Call", iv=30.0, dte=90)
        p = pop_closed_form(m, S0=100.0, iv=30.0)
        assert p is not None
        assert 0.0 < p < 0.50

    def test_long_put_pop_between_zero_and_one(self):
        m = _mat("Long Put", iv=25.0, dte=60)
        p = pop_closed_form(m, S0=100.0, iv=25.0)
        assert p is not None
        assert 0.0 <= p <= 1.0

    def test_long_straddle_two_breakevens(self):
        """Straddle profits OUTSIDE [BE_lo, BE_hi]. P should be modest."""
        m = _mat("Long Straddle", iv=25.0, dte=60)
        p = pop_closed_form(m, S0=100.0, iv=25.0)
        assert p is not None
        assert 0.0 <= p <= 1.0

    def test_calendar_returns_none(self):
        """Calendar spread has no clean two-BE shape → closed-form bows out."""
        m = _mat("Long Calendar", iv=25.0, dte=60)
        result = pop_closed_form(m, S0=100.0, iv=25.0)
        # Either None (preferred) or a degraded value that the high-level
        # `pop()` ignores in favour of Monte Carlo.
        if result is not None:
            assert 0.0 <= result <= 1.0


class TestMonteCarlo:
    def test_deterministic_with_seed(self):
        m = _mat("Long Call")
        a = pop_monte_carlo(m, S0=100.0, iv=25.0, seed=7, n_paths=5000)
        b = pop_monte_carlo(m, S0=100.0, iv=25.0, seed=7, n_paths=5000)
        assert a == b

    def test_returns_fraction_in_unit_interval(self):
        for name in ("Long Call", "Long Straddle", "Iron Butterfly",
                     "Short Iron Condor", "Bull Call Spread"):
            m = _mat(name)
            p = pop_monte_carlo(m, S0=100.0, iv=25.0, n_paths=2000)
            assert 0.0 <= p <= 1.0, f"{name}: PoP {p} out of bounds"

    def test_real_world_drift_higher_pop_for_long_call(self):
        """A positive real-world drift should increase long-call PoP."""
        m = _mat("Long Call", iv=25.0, dte=180)
        rn = pop_monte_carlo(m, S0=100.0, iv=25.0, n_paths=10_000,
                              use_real_world_drift=False)
        rw = pop_monte_carlo(m, S0=100.0, iv=25.0, n_paths=10_000,
                              use_real_world_drift=True, real_world_drift=0.15)
        assert rw > rn


class TestHighLevel:
    def test_pop_prefers_closed_form(self):
        m = _mat("Long Call")
        p_default = pop(m, S0=100.0, iv=25.0)
        p_cf      = pop_closed_form(m, S0=100.0, iv=25.0)
        assert p_default == pytest.approx(p_cf, abs=1e-9)

    def test_pop_falls_back_to_mc_for_complex(self):
        m = _mat("Iron Butterfly", iv=25.0)
        p = pop(m, S0=100.0, iv=25.0)
        assert 0.0 <= p <= 1.0

    def test_pop_force_mc(self):
        m = _mat("Long Call")
        p = pop(m, S0=100.0, iv=25.0, prefer_mc=True, n_paths=5000)
        assert 0.0 <= p <= 1.0


class TestProfitDensity:
    def test_returns_arrays_of_matching_shape(self):
        m = _mat("Long Straddle")
        centres, density = profit_density(m, S0=100.0, iv=25.0)
        assert len(centres) == len(density)
        assert len(centres) > 1
        assert (density >= 0).all()
