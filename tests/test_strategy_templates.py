"""Tests for analytics.strategy_templates."""
from __future__ import annotations

import pytest

from volscope.analytics.strategy_templates import (
    TEMPLATES,
    LegSpec,
    MaterializedStrategy,
    resolve_template,
)


class TestEachTemplateMaterializes:
    """Every catalogue entry must produce a valid MaterializedStrategy."""

    @pytest.mark.parametrize("name", list(TEMPLATES.keys()))
    def test_template(self, name):
        t = TEMPLATES[name]
        mat = t.materialize(ticker="TEST", spot=100.0, iv_pct=30.0, dte=60, contracts=1)
        assert isinstance(mat, MaterializedStrategy)
        assert mat.template_name == name
        assert mat.ticker == "TEST"
        assert len(mat.legs) >= 1
        # Every leg is structurally sound
        for leg in mat.legs:
            assert isinstance(leg, LegSpec)
            assert leg.action in {"buy", "sell"}
            assert leg.option_type in {"call", "put"}
            # strike==0 is the stock-leg encoding used by Covered Call
            assert leg.strike >= 0
            assert leg.contracts >= 1
            assert leg.entry_premium >= 0


class TestStraddle:
    def test_two_atm_legs(self):
        mat = TEMPLATES["Long Straddle"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        assert len(mat.legs) == 2
        strikes = sorted({l.strike for l in mat.legs})
        # ATM straddle → same strike for both legs
        assert len(strikes) == 1
        assert strikes[0] == pytest.approx(100.0, abs=1.0)
        # Both legs are buys
        assert all(l.action == "buy" for l in mat.legs)
        # Net debit positive (we pay)
        assert mat.net_debit > 0
        # Max-gain unbounded
        assert mat.max_gain is None


class TestIronCondor:
    def test_four_legs_two_sells_two_buys(self):
        mat = TEMPLATES["Short Iron Condor"].materialize(
            ticker="X", spot=100.0, iv_pct=30.0, dte=45, contracts=1,
        )
        assert len(mat.legs) == 4
        sells = [l for l in mat.legs if l.action == "sell"]
        buys = [l for l in mat.legs if l.action == "buy"]
        assert len(sells) == 2
        assert len(buys) == 2
        # Short iron condor collects premium → net credit (negative debit)
        assert mat.net_debit < 0

    def test_max_loss_bounded(self):
        mat = TEMPLATES["Short Iron Condor"].materialize(
            ticker="X", spot=100.0, iv_pct=30.0, dte=45, contracts=1,
        )
        assert mat.max_loss is not None
        assert mat.max_loss > 0


class TestSpreads:
    def test_bull_call_spread_capped(self):
        mat = TEMPLATES["Bull Call Spread"].materialize(
            ticker="X", spot=100.0, iv_pct=30.0, dte=45, contracts=1,
        )
        assert len(mat.legs) == 2
        assert mat.max_loss is not None
        assert mat.max_gain is not None
        # Max-gain greater than max-loss is not guaranteed; sanity check both positive
        assert mat.max_loss > 0
        assert mat.max_gain > 0

    def test_bear_put_spread_capped(self):
        mat = TEMPLATES["Bear Put Spread"].materialize(
            ticker="X", spot=100.0, iv_pct=30.0, dte=45, contracts=1,
        )
        assert len(mat.legs) == 2
        assert mat.max_loss is not None
        assert mat.max_gain is not None


class TestContractsScaling:
    def test_contracts_scale_premium(self):
        single = TEMPLATES["Long Straddle"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        triple = TEMPLATES["Long Straddle"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=3,
        )
        # 3× contracts → 3× net debit (allowing rounding)
        assert triple.net_debit == pytest.approx(single.net_debit * 3, rel=1e-3)


class TestInvalidInputs:
    def test_zero_spot_rejected(self):
        with pytest.raises(ValueError):
            TEMPLATES["Long Call"].materialize(
                ticker="X", spot=0.0, iv_pct=25.0, dte=30, contracts=1,
            )

    def test_zero_iv_rejected(self):
        with pytest.raises(ValueError):
            TEMPLATES["Long Call"].materialize(
                ticker="X", spot=100.0, iv_pct=0.0, dte=30, contracts=1,
            )

    def test_zero_dte_rejected(self):
        with pytest.raises(ValueError):
            TEMPLATES["Long Call"].materialize(
                ticker="X", spot=100.0, iv_pct=25.0, dte=0, contracts=1,
            )


class TestResolveTemplate:
    def test_native_name_resolves(self):
        t = resolve_template("Long Straddle")
        assert t is not None
        assert t.name == "Long Straddle"

    def test_recommender_label_routes(self):
        assert resolve_template("Long Put Spread").name == "Bear Put Spread"
        assert resolve_template("Earnings Long Straddle").name == "Long Straddle"

    def test_unknown_returns_none(self):
        assert resolve_template("MadeUpStrategy") is None


# ── Phase 2: operational methods + new templates ────────────────────

class TestNewTemplates:
    def test_iron_butterfly_four_legs(self):
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Iron Butterfly"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=45, contracts=1,
        )
        assert len(m.legs) == 4
        sells = [l for l in m.legs if l.action == "sell"]
        buys = [l for l in m.legs if l.action == "buy"]
        assert len(sells) == 2 and len(buys) == 2
        # Short legs at ATM (both share the same strike)
        sell_strikes = sorted({l.strike for l in sells})
        assert len(sell_strikes) == 1
        # Iron butterfly is a credit structure
        assert m.net_debit < 0

    def test_covered_call_two_legs(self):
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Covered Call"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        assert len(m.legs) == 2
        # Stock leg encoded as strike=0 call
        stock = [l for l in m.legs if l.strike == 0.0]
        assert len(stock) == 1 and stock[0].action == "buy"
        # Short OTM call
        short = [l for l in m.legs if l.action == "sell"]
        assert len(short) == 1


class TestOperationalMethods:
    """Phase 2: MaterializedStrategy implements the Strategy Protocol."""

    def test_payoff_at_expiry_is_vshape_for_straddle(self):
        import numpy as np
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Long Straddle"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=60, contracts=1,
        )
        # P&L at strike (= bottom of V) must be most negative
        pnl_at_100 = float(np.atleast_1d(m.payoff_at_expiry(np.array([100.0])))[0])
        pnl_extremes = float(np.atleast_1d(m.payoff_at_expiry(np.array([60.0])))[0])
        assert pnl_extremes > pnl_at_100

    def test_payoff_at_t_decays_to_at_expiry(self):
        import numpy as np
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Long Call"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        S = np.array([110.0])
        p_today = float(np.atleast_1d(m.payoff_at_t(S, t_fraction=0.0, iv=25.0))[0])
        p_expiry = float(np.atleast_1d(m.payoff_at_t(S, t_fraction=1.0, iv=25.0))[0])
        p_intrinsic = float(np.atleast_1d(m.payoff_at_expiry(S))[0])
        # At t_fraction=1 (expiry) the time-decay payoff should equal intrinsic
        assert abs(p_expiry - p_intrinsic) < 1.0
        # And today's value > expiry value at OTM-ish strikes (extrinsic remains)
        assert p_today >= p_expiry - 1.0

    def test_greeks_dict_keys(self):
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Long Straddle"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=60, contracts=1,
        )
        g = m.greeks(100.0, iv=25.0)
        assert set(g.keys()) == {"delta", "gamma", "theta_per_day",
                                  "vega_per_1pct", "rho_per_1pct"}
        # ATM straddle: delta near 0, gamma positive, theta negative
        assert abs(g["delta"]) < 30   # small position-level delta
        assert g["gamma"] > 0
        assert g["theta_per_day"] < 0

    def test_net_premium_matches_snapshot(self):
        """When called with the same params as materialize, recomputed
        net_premium is close to the snapshot net_debit (modulo rounding
        of strikes during materialization)."""
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Long Call"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        recomputed = m.net_premium(S0=100.0, iv=25.0)
        # Strike was rounded to 100 → BSM pricing at strike=100 vs the
        # rounded leg should match the snapshot
        assert abs(recomputed - m.net_debit) < 1.0

    def test_protocol_methods_alias_snapshot_fields(self):
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Bull Call Spread"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        assert m.max_profit() == m.max_gain
        assert m.max_loss_unbounded() == m.max_loss
        assert m.name == m.template_name

    def test_iron_condor_pnl_caps(self):
        """Short IC: max profit between short strikes, max loss outside wings."""
        import numpy as np
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Short Iron Condor"].materialize(
            ticker="X", spot=100.0, iv_pct=30.0, dte=45, contracts=1,
        )
        # Inside the body should be profitable
        inside = float(np.atleast_1d(m.payoff_at_expiry(np.array([100.0])))[0])
        outside_far = float(np.atleast_1d(m.payoff_at_expiry(np.array([200.0])))[0])
        assert inside > 0
        assert outside_far < 0


class TestCoveredCallSemantics:
    """Verify the stock-leg encoding produces sane greeks + payoffs."""

    def test_covered_call_delta_is_positive(self):
        """Long 100 shares (+100Δ) − short ~30Δ call ⇒ net ~+70Δ."""
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Covered Call"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        g = m.greeks(100.0, iv=25.0)
        # Delta must be positive and roughly in [50, 90]
        assert 50 <= g["delta"] <= 95

    def test_covered_call_payoff_capped_above_short_strike(self):
        """At spot well above the short-call strike, P&L is capped."""
        import numpy as np
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Covered Call"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        # Short call sits at +5% (≈ 105). Compare two points well above
        p_near = float(np.atleast_1d(m.payoff_at_expiry(np.array([130.0])))[0])
        p_far  = float(np.atleast_1d(m.payoff_at_expiry(np.array([200.0])))[0])
        # Both should be at the cap — identical to within rounding.
        assert abs(p_far - p_near) < 1.0

    def test_covered_call_net_outlay_near_spot_times_100(self):
        """Net debit ≈ spot * 100 − short call premium."""
        from volscope.analytics.strategy_templates import TEMPLATES
        m = TEMPLATES["Covered Call"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=30, contracts=1,
        )
        # Net debit should be slightly below $10,000 (collected short prem)
        assert 9_700 < m.net_debit < 10_000
