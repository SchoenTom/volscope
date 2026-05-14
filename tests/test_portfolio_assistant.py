"""Tests for analytics.portfolio_assistant — intelligent commentary engine."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.optionsschein_lookup import OptionsscheinSpec
from volscope.analytics.portfolio_assistant import (
    EntryQuality,
    GreekTrajectory,
    PortfolioInsight,
    PositionInsight,
    WarningFlag,
    aggregate_portfolio,
    assess_entry_quality,
    build_position_insight,
    compute_greek_trajectory,
    generate_warnings,
    suggest_actions,
)


def _spec(**overrides):
    base = dict(
        underlying="QQQ",
        option_type="put",
        strike=380.0,
        expiry=date.today() + timedelta(days=60),
        instrument_type="vanilla",
    )
    base.update(overrides)
    return OptionsscheinSpec(**base)


# ──────────────────────────────────────────────────────────────────────────
# Greek trajectory
# ──────────────────────────────────────────────────────────────────────────

class TestGreekTrajectory:
    def test_returns_trajectory(self):
        traj = compute_greek_trajectory(_spec(), current_spot=400.0, current_iv=22.0)
        assert isinstance(traj, GreekTrajectory)

    def test_long_put_negative_delta(self):
        traj = compute_greek_trajectory(_spec(), current_spot=400.0, current_iv=22.0)
        assert traj.delta_now < 0

    def test_long_call_positive_delta(self):
        spec = _spec(option_type="call", strike=420.0)
        traj = compute_greek_trajectory(spec, current_spot=400.0, current_iv=22.0)
        assert traj.delta_now > 0

    def test_delta_grows_with_spot_for_call(self):
        spec = _spec(option_type="call", strike=400.0)
        traj = compute_greek_trajectory(spec, current_spot=400.0, current_iv=22.0)
        assert traj.delta_at_plus_10pct > traj.delta_at_minus_10pct

    def test_vega_positive_for_long_position(self):
        traj = compute_greek_trajectory(_spec(), current_spot=400.0, current_iv=22.0)
        assert traj.vega_now > 0

    def test_theta_negative_for_long_position(self):
        traj = compute_greek_trajectory(_spec(), current_spot=400.0, current_iv=22.0)
        assert traj.theta_now < 0


# ──────────────────────────────────────────────────────────────────────────
# Entry quality
# ──────────────────────────────────────────────────────────────────────────

class TestEntryQuality:
    def test_excellent_when_low_pct(self):
        eq = assess_entry_quality(
            spec=_spec(), current_iv=22.0, entry_iv=18.0,
            entry_iv_pctl=10.0, current_spot=400.0,
        )
        assert eq.quality_label == "EXCELLENT"

    def test_bad_when_high_pct(self):
        eq = assess_entry_quality(
            spec=_spec(), current_iv=22.0, entry_iv=35.0,
            entry_iv_pctl=92.0, current_spot=400.0,
        )
        assert eq.quality_label == "BAD"

    def test_iv_change_signed(self):
        eq = assess_entry_quality(
            spec=_spec(), current_iv=25.0, entry_iv=20.0,
            entry_iv_pctl=50.0, current_spot=400.0,
        )
        assert eq.iv_change_since_entry_pp == 5.0

    def test_no_entry_iv_yields_none_change(self):
        eq = assess_entry_quality(
            spec=_spec(), current_iv=22.0, entry_iv=None,
            entry_iv_pctl=None, current_spot=400.0,
        )
        assert eq.iv_change_since_entry_pp is None


# ──────────────────────────────────────────────────────────────────────────
# Warnings
# ──────────────────────────────────────────────────────────────────────────

class TestWarnings:
    def test_alert_for_dead_knockout(self):
        spec = _spec(option_type="call", instrument_type="knockout",
                     strike=400, barrier=380)
        traj = compute_greek_trajectory(spec, current_spot=400.0, current_iv=22.0)
        ws = generate_warnings(
            spec=spec, current_spot=370.0, current_iv=22.0,
            iv_pct_now=50.0, earnings_in=None, greeks=traj,
            is_dead=True, moneyness_pct=-7.5,
        )
        assert any(w.code == "KO_DEAD" and w.severity == "alert" for w in ws)

    def test_alert_when_near_ko_barrier(self):
        spec = _spec(option_type="call", instrument_type="knockout",
                     strike=400, barrier=380)
        traj = compute_greek_trajectory(spec, current_spot=383.0, current_iv=22.0)
        ws = generate_warnings(
            spec=spec, current_spot=383.0, current_iv=22.0,
            iv_pct_now=50.0, earnings_in=None, greeks=traj,
            is_dead=False, moneyness_pct=-4.25,
        )
        assert any(w.code == "KO_NEAR" and w.severity == "alert" for w in ws)

    def test_dte_low_alert(self):
        spec = _spec(expiry=date.today() + timedelta(days=3))
        traj = compute_greek_trajectory(spec, current_spot=400.0, current_iv=22.0)
        ws = generate_warnings(
            spec=spec, current_spot=400.0, current_iv=22.0,
            iv_pct_now=50.0, earnings_in=None, greeks=traj,
            is_dead=False, moneyness_pct=0.0,
        )
        assert any(w.code == "DTE_LOW" for w in ws)

    def test_earnings_warning(self):
        traj = compute_greek_trajectory(_spec(), current_spot=400.0, current_iv=22.0)
        ws = generate_warnings(
            spec=_spec(), current_spot=400.0, current_iv=22.0,
            iv_pct_now=50.0, earnings_in=3, greeks=traj,
            is_dead=False, moneyness_pct=0.0,
        )
        assert any(w.code == "EARNINGS_NEAR" for w in ws)

    def test_iv_rich_warning(self):
        traj = compute_greek_trajectory(_spec(), current_spot=400.0, current_iv=22.0)
        ws = generate_warnings(
            spec=_spec(), current_spot=400.0, current_iv=22.0,
            iv_pct_now=88.0, earnings_in=None, greeks=traj,
            is_dead=False, moneyness_pct=0.0,
        )
        assert any(w.code == "IV_RICH" for w in ws)


# ──────────────────────────────────────────────────────────────────────────
# Suggested actions
# ──────────────────────────────────────────────────────────────────────────

class TestSuggestActions:
    def test_dead_position_action_close(self):
        traj = compute_greek_trajectory(_spec(), current_spot=400.0, current_iv=22.0)
        eq = EntryQuality(50.0, 0.0, 0.0, 0.0, "FAIR")
        actions = suggest_actions(
            spec=_spec(), greeks=traj, iv_pct_now=50.0,
            entry_quality=eq, is_dead=True, earnings_in=None,
            moneyness_pct=0.0,
        )
        assert any("KO triggered" in a or "closed" in a.lower() for a in actions)

    def test_iv_rich_suggests_take_profits(self):
        traj = compute_greek_trajectory(_spec(), current_spot=400.0, current_iv=22.0)
        actions = suggest_actions(
            spec=_spec(), greeks=traj, iv_pct_now=85.0,
            entry_quality=None, is_dead=False, earnings_in=None,
            moneyness_pct=0.0,
        )
        assert any("profit" in a.lower() for a in actions)


# ──────────────────────────────────────────────────────────────────────────
# Build position insight (integration)
# ──────────────────────────────────────────────────────────────────────────

class TestBuildInsight:
    def test_returns_insight(self):
        ins = build_position_insight(
            spec=_spec(), current_spot=400.0, current_iv=22.0,
        )
        assert isinstance(ins, PositionInsight)

    def test_summary_contains_underlying(self):
        ins = build_position_insight(
            spec=_spec(), current_spot=400.0, current_iv=22.0,
        )
        assert "QQQ" in ins.summary

    def test_dead_position_has_dead_summary(self):
        spec = _spec(option_type="call", instrument_type="knockout",
                     strike=400, barrier=380)
        ins = build_position_insight(
            spec=spec, current_spot=370.0, current_iv=22.0,
        )
        assert ins.is_dead is True
        assert "KO" in ins.summary

    def test_moneyness_signs(self):
        # ITM call: spot > strike → positive moneyness
        ins = build_position_insight(
            spec=_spec(option_type="call", strike=380.0),
            current_spot=420.0, current_iv=22.0,
        )
        assert ins.moneyness_pct > 0

    def test_no_iv_returns_zero_greeks(self):
        ins = build_position_insight(
            spec=_spec(), current_spot=400.0, current_iv=None,
        )
        assert ins.greeks.delta_now == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Portfolio aggregation
# ──────────────────────────────────────────────────────────────────────────

class TestAggregatePortfolio:
    def test_empty(self):
        agg = aggregate_portfolio([])
        assert agg.n_positions == 0
        assert "No positions" in agg.headline

    def test_concentration_warning(self):
        # 3 positions all in QQQ → concentration warning
        ins_list = []
        for _ in range(3):
            ins_list.append(build_position_insight(
                spec=_spec(underlying="QQQ"),
                current_spot=400.0, current_iv=22.0,
            ))
        agg = aggregate_portfolio(ins_list)
        assert any("concentrated" in w.lower() for w in agg.diversification_warnings)

    def test_diversification_warning_few_underlyings(self):
        # 4 positions but only 2 underlyings → low diversification
        ins_list = []
        for tk in ["QQQ", "QQQ", "MSTR", "MSTR"]:
            ins_list.append(build_position_insight(
                spec=_spec(underlying=tk),
                current_spot=400.0, current_iv=22.0,
            ))
        agg = aggregate_portfolio(ins_list)
        # Either concentration or low-div warning fires
        assert agg.diversification_warnings

    def test_alert_count(self):
        spec_dead = _spec(option_type="call", instrument_type="knockout",
                           strike=400, barrier=380)
        ins_dead = build_position_insight(
            spec=spec_dead, current_spot=370.0, current_iv=22.0,
        )
        ins_ok = build_position_insight(
            spec=_spec(), current_spot=400.0, current_iv=22.0,
        )
        agg = aggregate_portfolio([ins_dead, ins_ok])
        assert agg.n_dead == 1
        assert agg.n_warnings_alert >= 1


# ──────────────────────────────────────────────────────────────────────────
# Frozen guards
# ──────────────────────────────────────────────────────────────────────────

class TestFrozen:
    def test_position_insight_frozen(self):
        ins = build_position_insight(
            spec=_spec(), current_spot=400.0, current_iv=22.0,
        )
        with pytest.raises(Exception):
            ins.summary = "X"  # type: ignore[misc]

    def test_warning_flag_frozen(self):
        w = WarningFlag(severity="alert", code="X", message="y")
        with pytest.raises(Exception):
            w.severity = "watch"  # type: ignore[misc]
