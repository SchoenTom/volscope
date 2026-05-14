"""Tests for analytics.strategy_recommender."""
from __future__ import annotations

import pytest

from volscope.analytics.strategy_recommender import (
    StrategyRec,
    recommend_strategies,
    strategy_card_html,
)


# ──────────────────────────────────────────────────────────────────────────
# Output contract
# ──────────────────────────────────────────────────────────────────────────

class TestOutputContract:
    def test_returns_non_empty_list(self):
        recs = recommend_strategies()
        assert len(recs) >= 1

    def test_rec_is_strategy_rec(self):
        recs = recommend_strategies(iv_percentile=10.0)
        assert all(isinstance(r, StrategyRec) for r in recs)

    def test_score_in_range(self):
        recs = recommend_strategies(iv_percentile=10.0, edge_score=80.0)
        for r in recs:
            assert 0.0 <= r.score <= 100.0

    def test_sorted_descending_by_score(self):
        recs = recommend_strategies(iv_percentile=10.0, edge_score=80.0,
                                    skew_25=-0.5, term_slope=3.0)
        scores = [r.score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_frozen_dataclass(self):
        rec = recommend_strategies(iv_percentile=10.0)[0]
        with pytest.raises(Exception):
            rec.score = 0.0  # type: ignore[misc]

    def test_default_returns_wait(self):
        # No inputs at all → WAIT placeholder
        recs = recommend_strategies()
        assert recs[0].name == "WAIT"


# ──────────────────────────────────────────────────────────────────────────
# Cheap-vol regime
# ──────────────────────────────────────────────────────────────────────────

class TestCheapRegime:
    def test_very_cheap_returns_long_put_spread(self):
        recs = recommend_strategies(iv_percentile=10.0, edge_score=80.0)
        names = [r.name for r in recs]
        assert "Long Put Spread" in names

    def test_very_cheap_returns_calendar(self):
        recs = recommend_strategies(iv_percentile=10.0)
        names = [r.name for r in recs]
        assert "Long Calendar Spread" in names

    def test_cheap_with_negative_skew_adds_risk_reversal(self):
        recs = recommend_strategies(iv_percentile=10.0, skew_25=-1.0)
        names = [r.name for r in recs]
        assert "Long Risk Reversal" in names

    def test_lean_cheap_with_backwardation_adds_calendar(self):
        recs = recommend_strategies(iv_percentile=30.0, term_slope=-3.0)
        names = [r.name for r in recs]
        assert "Calendar — Backwardation Reversion" in names


# ──────────────────────────────────────────────────────────────────────────
# Rich-vol regime
# ──────────────────────────────────────────────────────────────────────────

class TestRichRegime:
    def test_very_rich_returns_iron_condor(self):
        recs = recommend_strategies(iv_percentile=85.0)
        names = [r.name for r in recs]
        assert "Short Iron Condor" in names

    def test_very_rich_returns_strangle(self):
        recs = recommend_strategies(iv_percentile=85.0)
        names = [r.name for r in recs]
        assert "Short Strangle" in names

    def test_rich_with_no_earnings_adds_lean_condor(self):
        recs = recommend_strategies(iv_percentile=70.0)
        names = [r.name for r in recs]
        assert "Short Iron Condor" in names

    def test_rich_with_earnings_near_skips_lean_condor(self):
        recs = recommend_strategies(iv_percentile=70.0, days_to_earnings=3)
        # Lean condor not added; earnings_iron_condor IS added
        ec_recs = [r for r in recs if r.name == "Earnings Iron Condor"]
        assert ec_recs


# ──────────────────────────────────────────────────────────────────────────
# Skew + term-structure trades
# ──────────────────────────────────────────────────────────────────────────

class TestSkewTrades:
    def test_extreme_put_skew_adds_short_rr(self):
        recs = recommend_strategies(iv_percentile=50.0, skew_25=6.0)
        names = [r.name for r in recs]
        assert "Short Risk Reversal" in names

    def test_normal_skew_no_short_rr(self):
        recs = recommend_strategies(iv_percentile=50.0, skew_25=0.0)
        names = [r.name for r in recs]
        assert "Short Risk Reversal" not in names


class TestTermStructureTrades:
    def test_steep_contango_adds_carry_calendar(self):
        recs = recommend_strategies(iv_percentile=50.0, term_slope=3.0)
        names = [r.name for r in recs]
        assert "Calendar — Contango Carry" in names

    def test_flat_term_no_carry(self):
        recs = recommend_strategies(iv_percentile=50.0, term_slope=0.5)
        names = [r.name for r in recs]
        assert "Calendar — Contango Carry" not in names


# ──────────────────────────────────────────────────────────────────────────
# Earnings-driven recs
# ──────────────────────────────────────────────────────────────────────────

class TestEarningsTrades:
    def test_cheap_iv_with_er_near_recommends_long_straddle(self):
        recs = recommend_strategies(iv_percentile=15.0, days_to_earnings=5)
        names = [r.name for r in recs]
        assert "Earnings Long Straddle" in names

    def test_rich_iv_with_er_near_recommends_iron_condor(self):
        recs = recommend_strategies(iv_percentile=80.0, days_to_earnings=5)
        names = [r.name for r in recs]
        assert "Earnings Iron Condor" in names

    def test_earnings_near_flag_set(self):
        recs = recommend_strategies(iv_percentile=15.0, days_to_earnings=3)
        # All recs should carry the earnings_near flag
        for r in recs:
            if r.name != "WAIT":
                assert "earnings_near" in r.flags


# ──────────────────────────────────────────────────────────────────────────
# History gate
# ──────────────────────────────────────────────────────────────────────────

class TestHistoryGate:
    def test_short_history_downgrades_score(self):
        with_hist = recommend_strategies(iv_percentile=15.0, has_long_history=True)
        without   = recommend_strategies(iv_percentile=15.0, has_long_history=False)
        # Same set of recs, but each scored ~10pts lower
        with_top_score    = with_hist[0].score
        without_top_score = without[0].score
        assert without_top_score < with_top_score
        assert "limited backtest history" in without[0].flags


# ──────────────────────────────────────────────────────────────────────────
# Edge handling
# ──────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_nan_percentile_returns_wait(self):
        recs = recommend_strategies(iv_percentile=float("nan"))
        assert recs[0].name == "WAIT"

    def test_string_inputs_return_wait(self):
        # Bad type (string) — _safe_float returns None → no recs → WAIT
        recs = recommend_strategies(iv_percentile="garbage")  # type: ignore[arg-type]
        assert recs[0].name == "WAIT"

    def test_inf_skew_skipped(self):
        recs = recommend_strategies(iv_percentile=10.0, skew_25=float("inf"))
        names = [r.name for r in recs]
        # inf skew → not used → no Risk Reversal added
        assert "Long Risk Reversal" not in names


# ──────────────────────────────────────────────────────────────────────────
# Direction labels
# ──────────────────────────────────────────────────────────────────────────

class TestDirectionLabels:
    def test_long_put_spread_is_long_vol(self):
        recs = recommend_strategies(iv_percentile=10.0)
        rec = next(r for r in recs if r.name == "Long Put Spread")
        assert rec.direction == "long_vol"

    def test_iron_condor_is_short_vol(self):
        recs = recommend_strategies(iv_percentile=85.0)
        rec = next(r for r in recs if r.name == "Short Iron Condor")
        assert rec.direction == "short_vol"


# ──────────────────────────────────────────────────────────────────────────
# Risk profile labels
# ──────────────────────────────────────────────────────────────────────────

class TestRiskProfile:
    def test_strangle_unlimited(self):
        recs = recommend_strategies(iv_percentile=85.0)
        rec = next(r for r in recs if r.name == "Short Strangle")
        assert rec.risk_profile == "unlimited"

    def test_iron_condor_defined(self):
        recs = recommend_strategies(iv_percentile=85.0)
        rec = next(r for r in recs if r.name == "Short Iron Condor")
        assert rec.risk_profile == "defined"


# ──────────────────────────────────────────────────────────────────────────
# HTML rendering
# ──────────────────────────────────────────────────────────────────────────

class TestHtml:
    def test_card_renders(self):
        rec = recommend_strategies(iv_percentile=10.0)[0]
        html = strategy_card_html(rec)
        assert "<div" in html
        assert rec.name in html

    def test_long_vol_color_distinct(self):
        long_rec = next(r for r in recommend_strategies(iv_percentile=10.0)
                        if r.direction == "long_vol")
        short_rec = next(r for r in recommend_strategies(iv_percentile=85.0)
                         if r.direction == "short_vol")
        h_l = strategy_card_html(long_rec)
        h_s = strategy_card_html(short_rec)
        assert h_l != h_s

    def test_wait_renders_no_legs_message(self):
        rec = recommend_strategies()[0]
        html = strategy_card_html(rec)
        assert "WAIT" in html
