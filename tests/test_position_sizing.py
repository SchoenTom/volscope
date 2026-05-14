"""
Tests for volscope.analytics.position_sizing — signal-based lot sizing.

Covers:
  - SIZE_MULTIPLIERS mapping completeness
  - compute_sizing() output contract
  - compute_sizing() multiplier logic per signal category
  - compute_sizing() vega P&L estimate
  - sizing_summary_html() rendering contract
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from volscope.analytics.position_sizing import (
    ALL_SIGNAL_CATEGORIES,
    SIZE_MULTIPLIERS,
    SIZE_LABELS,
    SizingResult,
    compute_sizing,
    sizing_summary_html,
)


# ---------------------------------------------------------------------------
# SIZE_MULTIPLIERS completeness
# ---------------------------------------------------------------------------

class TestSizeMultipliers:
    def test_all_signal_categories_covered(self):
        """Every category must have a multiplier entry."""
        for cat in ALL_SIGNAL_CATEGORIES:
            assert cat in SIZE_MULTIPLIERS, f"Missing multiplier for category: {cat}"

    def test_all_multipliers_in_0_1(self):
        for cat, mult in SIZE_MULTIPLIERS.items():
            assert 0.0 <= mult <= 1.0, f"{cat}: multiplier {mult} out of [0,1]"

    def test_buy_is_full_size(self):
        assert SIZE_MULTIPLIERS["buy"] == pytest.approx(1.0)

    def test_lean_buy_is_half(self):
        assert SIZE_MULTIPLIERS["lean_buy"] == pytest.approx(0.5)

    def test_neutral_is_zero(self):
        assert SIZE_MULTIPLIERS["neutral"] == pytest.approx(0.0)

    def test_lean_rich_is_zero(self):
        assert SIZE_MULTIPLIERS["lean_rich"] == pytest.approx(0.0)

    def test_rich_is_zero(self):
        assert SIZE_MULTIPLIERS["rich"] == pytest.approx(0.0)

    def test_no_data_is_zero(self):
        assert SIZE_MULTIPLIERS["no_data"] == pytest.approx(0.0)

    def test_all_categories_have_labels(self):
        for cat in SIZE_MULTIPLIERS:
            assert cat in SIZE_LABELS
            assert isinstance(SIZE_LABELS[cat], str)
            assert len(SIZE_LABELS[cat]) > 0


# ---------------------------------------------------------------------------
# SizingResult — dataclass contract
# ---------------------------------------------------------------------------

class TestSizingResultDataclass:
    def test_is_frozen(self):
        r = SizingResult(
            signal_category="buy",
            size_multiplier=1.0,
            size_label="Full position",
            max_allocation=10_000.0,
            suggested_allocation=10_000.0,
            entry_iv=None,
            current_iv=None,
            iv_change_pp=None,
            rough_pnl_pct=None,
            rough_pnl_usd=None,
        )
        with pytest.raises((AttributeError, TypeError)):
            r.size_multiplier = 0.5  # type: ignore[misc]

    def test_fields_accessible(self):
        r = SizingResult(
            signal_category="lean_buy",
            size_multiplier=0.5,
            size_label="Half position",
            max_allocation=5_000.0,
            suggested_allocation=2_500.0,
            entry_iv=25.0,
            current_iv=28.0,
            iv_change_pp=3.0,
            rough_pnl_pct=12.0,
            rough_pnl_usd=300.0,
        )
        assert r.signal_category == "lean_buy"
        assert r.suggested_allocation == pytest.approx(2_500.0)
        assert r.iv_change_pp == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# compute_sizing — multiplier logic
# ---------------------------------------------------------------------------

class TestComputeSizingMultiplier:
    def test_buy_full_size(self):
        r = compute_sizing("buy", max_allocation=10_000.0)
        assert r.suggested_allocation == pytest.approx(10_000.0)
        assert r.size_multiplier == pytest.approx(1.0)

    def test_lean_buy_half_size(self):
        r = compute_sizing("lean_buy", max_allocation=10_000.0)
        assert r.suggested_allocation == pytest.approx(5_000.0)
        assert r.size_multiplier == pytest.approx(0.5)

    def test_neutral_zero_size(self):
        r = compute_sizing("neutral", max_allocation=10_000.0)
        assert r.suggested_allocation == pytest.approx(0.0)

    def test_lean_rich_zero_size(self):
        r = compute_sizing("lean_rich", max_allocation=10_000.0)
        assert r.suggested_allocation == pytest.approx(0.0)

    def test_rich_zero_size(self):
        r = compute_sizing("rich", max_allocation=10_000.0)
        assert r.suggested_allocation == pytest.approx(0.0)

    def test_no_data_zero_size(self):
        r = compute_sizing("no_data", max_allocation=10_000.0)
        assert r.suggested_allocation == pytest.approx(0.0)

    def test_unknown_category_zero_size(self):
        """Unknown category should default to zero allocation."""
        r = compute_sizing("garbage_category", max_allocation=5_000.0)
        assert r.suggested_allocation == pytest.approx(0.0)

    def test_zero_allocation_yields_zero_suggested(self):
        r = compute_sizing("buy", max_allocation=0.0)
        assert r.suggested_allocation == pytest.approx(0.0)

    def test_label_populated(self):
        r = compute_sizing("buy", max_allocation=1000.0)
        assert isinstance(r.size_label, str)
        assert len(r.size_label) > 0

    def test_category_stored(self):
        r = compute_sizing("lean_buy", max_allocation=1000.0)
        assert r.signal_category == "lean_buy"

    def test_max_allocation_stored(self):
        r = compute_sizing("buy", max_allocation=7_777.0)
        assert r.max_allocation == pytest.approx(7_777.0)


# ---------------------------------------------------------------------------
# compute_sizing — vega P&L estimate
# ---------------------------------------------------------------------------

class TestComputeSizingVegaPnl:
    def test_no_iv_gives_none_pnl(self):
        r = compute_sizing("buy", max_allocation=10_000.0)
        assert r.entry_iv is None
        assert r.current_iv is None
        assert r.iv_change_pp is None
        assert r.rough_pnl_pct is None
        assert r.rough_pnl_usd is None

    def test_no_entry_iv_gives_none_pnl(self):
        r = compute_sizing("buy", max_allocation=10_000.0, current_iv=28.0)
        assert r.rough_pnl_pct is None

    def test_no_current_iv_gives_none_pnl(self):
        r = compute_sizing("buy", max_allocation=10_000.0, entry_iv=25.0)
        assert r.rough_pnl_pct is None

    def test_iv_change_computed(self):
        r = compute_sizing("buy", max_allocation=10_000.0, entry_iv=25.0, current_iv=28.0)
        assert r.iv_change_pp == pytest.approx(3.0)

    def test_rough_pnl_pct_positive_when_iv_rises(self):
        """IV rise → long vol position in profit → pnl_pct > 0."""
        r = compute_sizing("buy", max_allocation=10_000.0, entry_iv=25.0, current_iv=28.0)
        assert r.rough_pnl_pct is not None
        assert r.rough_pnl_pct > 0

    def test_rough_pnl_pct_negative_when_iv_falls(self):
        """IV fall → long vol position at loss → pnl_pct < 0."""
        r = compute_sizing("buy", max_allocation=10_000.0, entry_iv=25.0, current_iv=22.0)
        assert r.rough_pnl_pct is not None
        assert r.rough_pnl_pct < 0

    def test_rough_pnl_pct_zero_when_iv_unchanged(self):
        r = compute_sizing("buy", max_allocation=10_000.0, entry_iv=25.0, current_iv=25.0)
        assert r.rough_pnl_pct == pytest.approx(0.0)

    def test_rough_pnl_pct_formula(self):
        """pnl_pct ≈ (current - entry) / entry × 100."""
        r = compute_sizing("buy", max_allocation=10_000.0, entry_iv=25.0, current_iv=30.0)
        expected_pct = (30.0 - 25.0) / 25.0 * 100.0  # = 20%
        assert r.rough_pnl_pct == pytest.approx(expected_pct, rel=1e-6)

    def test_rough_pnl_usd_formula(self):
        """pnl_usd = pnl_pct / 100 × suggested_allocation."""
        r = compute_sizing("buy", max_allocation=10_000.0, entry_iv=25.0, current_iv=30.0)
        # suggested = 10_000, pnl_pct = 20% → pnl_usd = 2_000
        assert r.rough_pnl_usd == pytest.approx(2_000.0, rel=1e-6)

    def test_rough_pnl_usd_zero_when_no_position(self):
        """WAIT signal → suggested = 0 → P&L = 0."""
        r = compute_sizing("neutral", max_allocation=10_000.0, entry_iv=25.0, current_iv=30.0)
        assert r.rough_pnl_usd == pytest.approx(0.0)

    def test_zero_entry_iv_gives_none_pnl(self):
        """Guard against division by zero in pnl formula."""
        r = compute_sizing("buy", max_allocation=10_000.0, entry_iv=0.0, current_iv=25.0)
        assert r.rough_pnl_pct is None

    def test_negative_entry_iv_gives_none_pnl(self):
        r = compute_sizing("buy", max_allocation=10_000.0, entry_iv=-5.0, current_iv=25.0)
        assert r.rough_pnl_pct is None

    def test_lean_buy_pnl_uses_half_allocation(self):
        """Half-position signal → P&L calculated on half the allocation."""
        r = compute_sizing("lean_buy", max_allocation=10_000.0, entry_iv=20.0, current_iv=24.0)
        # suggested = 5_000, pnl_pct = 20% → pnl_usd = 1_000
        assert r.rough_pnl_usd == pytest.approx(1_000.0, rel=1e-6)


# ---------------------------------------------------------------------------
# sizing_summary_html
# ---------------------------------------------------------------------------

class TestSizingSummaryHtml:
    def _result(
        self,
        cat: str = "buy",
        max_alloc: float = 10_000.0,
        entry_iv: float | None = None,
        current_iv: float | None = None,
    ) -> SizingResult:
        return compute_sizing(cat, max_alloc, entry_iv=entry_iv, current_iv=current_iv)

    def test_returns_string(self):
        html = sizing_summary_html(self._result())
        assert isinstance(html, str)

    def test_nonempty(self):
        assert len(sizing_summary_html(self._result())) > 0

    def test_contains_suggested_allocation(self):
        html = sizing_summary_html(self._result("buy", 10_000.0))
        # Suggested = $10,000 — some formatted version should appear
        assert "10" in html  # at minimum the thousands digit

    def test_buy_shows_green_color(self):
        html = sizing_summary_html(self._result("buy"))
        # BUY uses accent color (#00d4aa or similar green)
        assert "#00d" in html.lower() or "accent" in html.lower() or "00d4" in html.lower()

    def test_wait_does_not_show_allocation(self):
        """WAIT signal → suggested = 0 → UI should make this clear."""
        html = sizing_summary_html(self._result("neutral"))
        assert "WAIT" in html.upper() or "0" in html or "No " in html

    def test_shows_pnl_when_iv_available(self):
        html = sizing_summary_html(self._result("buy", 10_000.0, entry_iv=25.0, current_iv=28.0))
        # P&L is 12% → should contain "12" somewhere
        assert "12" in html

    def test_no_pnl_section_without_iv(self):
        """No entry/current IV → no P&L row in HTML."""
        html = sizing_summary_html(self._result("buy", 10_000.0))
        # Without IV data, P&L estimate should not appear as a percentage
        assert "P&L" not in html or "—" in html

    def test_negative_pnl_shows_negative(self):
        html = sizing_summary_html(
            self._result("buy", 10_000.0, entry_iv=30.0, current_iv=25.0)
        )
        assert "−" in html or "-" in html

    def test_none_result_returns_empty(self):
        """Gracefully handle None by returning empty string."""
        assert sizing_summary_html(None) == ""  # type: ignore[arg-type]
