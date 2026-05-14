"""Tests for analytics.kelly_sizing — Kelly-Criterion bet fractions."""
from __future__ import annotations

import math

import pytest

from volscope.analytics.kelly_sizing import (
    KellyResult,
    compute_kelly_sizing,
    kelly_fraction,
    kelly_summary_html,
)


# ──────────────────────────────────────────────────────────────────────────
# kelly_fraction — pure formula
# ──────────────────────────────────────────────────────────────────────────

class TestKellyFraction:
    def test_textbook_example(self):
        # p=0.6, b=1.0  →  f = (1*0.6 - 0.4)/1 = 0.2
        assert math.isclose(kelly_fraction(0.6, 1.0), 0.2, abs_tol=1e-6)

    def test_break_even_zero(self):
        # p=0.5, b=1.0  →  f = 0
        assert math.isclose(kelly_fraction(0.5, 1.0), 0.0, abs_tol=1e-6)

    def test_negative_edge(self):
        # p=0.4, b=1.0  →  f < 0 (no bet)
        assert kelly_fraction(0.4, 1.0) < 0

    def test_high_payoff_compensates_low_p(self):
        # p=0.3, b=4.0  →  f = (4*0.3 - 0.7)/4 = 0.5/4 = 0.125
        assert math.isclose(kelly_fraction(0.3, 4.0), 0.125, abs_tol=1e-6)

    def test_zero_payoff_returns_zero(self):
        assert kelly_fraction(0.7, 0.0) == 0.0

    def test_negative_payoff_returns_zero(self):
        assert kelly_fraction(0.7, -1.0) == 0.0

    def test_p_above_one_clamped_to_zero(self):
        assert kelly_fraction(1.5, 1.0) == 0.0

    def test_p_below_zero_clamped_to_zero(self):
        assert kelly_fraction(-0.1, 1.0) == 0.0


# ──────────────────────────────────────────────────────────────────────────
# compute_kelly_sizing — backtest path
# ──────────────────────────────────────────────────────────────────────────

class TestBacktestPath:
    def test_returns_kelly_result(self):
        # 60 wins of 5%, 40 losses of -3%
        hits = [True] * 60 + [False] * 40
        pnls = [5.0] * 60 + [-3.0] * 40
        r = compute_kelly_sizing(backtest_hits=hits, backtest_pnls=pnls)
        assert isinstance(r, KellyResult)

    def test_p_win_correct(self):
        hits = [True] * 60 + [False] * 40
        pnls = [5.0] * 60 + [-3.0] * 40
        r = compute_kelly_sizing(backtest_hits=hits, backtest_pnls=pnls)
        assert r.p_win == pytest.approx(0.6, abs=0.001)

    def test_payoff_ratio_correct(self):
        hits = [True] * 60 + [False] * 40
        pnls = [5.0] * 60 + [-3.0] * 40
        r = compute_kelly_sizing(backtest_hits=hits, backtest_pnls=pnls)
        # avg_win=5, avg_loss=3 → 5/3 ≈ 1.667
        assert r.payoff_ratio == pytest.approx(1.667, abs=0.01)

    def test_full_kelly_correct(self):
        hits = [True] * 60 + [False] * 40
        pnls = [5.0] * 60 + [-3.0] * 40
        r = compute_kelly_sizing(backtest_hits=hits, backtest_pnls=pnls)
        # f = (1.667*0.6 - 0.4) / 1.667 = 0.6/1.667 = 0.36
        assert r.full_kelly == pytest.approx(0.36, abs=0.01)

    def test_fractional_kelly_uses_quarter(self):
        hits = [True] * 60 + [False] * 40
        pnls = [5.0] * 60 + [-3.0] * 40
        r = compute_kelly_sizing(backtest_hits=hits, backtest_pnls=pnls)
        # 0.36 * 0.25 = 0.09
        assert r.fractional_kelly == pytest.approx(0.09, abs=0.01)

    def test_fractional_kelly_capped_at_50pct(self):
        # 95 wins of 100%, 5 losses of 1% → enormous Kelly, must cap
        hits = [True] * 95 + [False] * 5
        pnls = [100.0] * 95 + [-1.0] * 5
        r = compute_kelly_sizing(backtest_hits=hits, backtest_pnls=pnls)
        assert r.fractional_kelly <= 0.5

    def test_no_edge_zeroes_fractional(self):
        hits = [True] * 30 + [False] * 70
        pnls = [3.0] * 30 + [-3.0] * 70
        r = compute_kelly_sizing(backtest_hits=hits, backtest_pnls=pnls)
        assert r.fractional_kelly == 0.0

    def test_below_min_n_zeroes(self):
        hits = [True] * 10 + [False] * 5
        pnls = [5.0] * 10 + [-3.0] * 5
        r = compute_kelly_sizing(backtest_hits=hits, backtest_pnls=pnls)
        assert r.fractional_kelly == 0.0
        assert "obs" in r.notes

    def test_no_losers_returns_zero_payoff(self):
        hits = [True] * 50
        pnls = [5.0] * 50
        r = compute_kelly_sizing(backtest_hits=hits, backtest_pnls=pnls)
        assert r.payoff_ratio == 0.0

    def test_confidence_grows_with_n(self):
        small = compute_kelly_sizing(
            backtest_hits=[True] * 30 + [False] * 20,
            backtest_pnls=[5.0] * 30 + [-3.0] * 20,
        )
        large = compute_kelly_sizing(
            backtest_hits=[True] * 120 + [False] * 80,
            backtest_pnls=[5.0] * 120 + [-3.0] * 80,
        )
        assert small.confidence < large.confidence


# ──────────────────────────────────────────────────────────────────────────
# compute_kelly_sizing — fallback path
# ──────────────────────────────────────────────────────────────────────────

class TestFallbackPath:
    def test_summary_stats_path(self):
        r = compute_kelly_sizing(fallback_p_win=0.6, fallback_payoff=2.0)
        # full kelly = (2*0.6 - 0.4)/2 = 0.4
        assert r.full_kelly == pytest.approx(0.4, abs=0.001)
        # fractional = 0.4 * 0.25 = 0.1
        assert r.fractional_kelly == pytest.approx(0.1, abs=0.001)

    def test_fallback_confidence_small(self):
        r = compute_kelly_sizing(fallback_p_win=0.7, fallback_payoff=1.5)
        assert r.confidence == 0.3

    def test_fallback_negative_payoff_clamped(self):
        r = compute_kelly_sizing(fallback_p_win=0.6, fallback_payoff=-2.0)
        assert r.full_kelly == 0.0

    def test_fallback_p_above_one_clamped(self):
        r = compute_kelly_sizing(fallback_p_win=1.5, fallback_payoff=2.0)
        assert r.p_win == 1.0


# ──────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_no_inputs(self):
        r = compute_kelly_sizing()
        assert r.fractional_kelly == 0.0
        assert "insufficient" in r.notes

    def test_mismatched_lengths(self):
        r = compute_kelly_sizing(
            backtest_hits=[True, False],
            backtest_pnls=[5.0],
        )
        assert r.fractional_kelly == 0.0

    def test_frozen_dataclass(self):
        r = compute_kelly_sizing(fallback_p_win=0.6, fallback_payoff=2.0)
        with pytest.raises(Exception):
            r.full_kelly = 0.0  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────
# HTML rendering
# ──────────────────────────────────────────────────────────────────────────

class TestHtml:
    def test_renders_string(self):
        r = compute_kelly_sizing(fallback_p_win=0.6, fallback_payoff=2.0)
        html = kelly_summary_html(r, max_alloc_usd=10_000)
        assert "<div" in html
        assert "Kelly" in html

    def test_includes_suggested_usd(self):
        r = compute_kelly_sizing(fallback_p_win=0.6, fallback_payoff=2.0)
        html = kelly_summary_html(r, max_alloc_usd=10_000)
        # 0.1 × $10,000 = $1,000
        assert "1,000" in html or "$1,000" in html

    def test_zero_kelly_renders(self):
        r = compute_kelly_sizing()
        html = kelly_summary_html(r, max_alloc_usd=10_000)
        assert "<div" in html

    def test_notes_in_html_when_present(self):
        r = compute_kelly_sizing()
        html = kelly_summary_html(r, max_alloc_usd=10_000)
        if r.notes:
            assert r.notes in html
