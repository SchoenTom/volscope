"""Tests for the vola Scenario Builder."""
from __future__ import annotations

import pytest

from volscope.analytics.scenario_builder import (
    SCENARIO_HINTS,
    SCENARIO_LABELS,
    Scenario,
    build_scenario_recommendation,
    scenario_card_html,
)


class TestScenarioCatalogue:
    def test_all_scenarios_have_label(self):
        for s in Scenario:
            assert s in SCENARIO_LABELS, f"missing label for {s}"
            assert SCENARIO_LABELS[s], "label must be non-empty"

    def test_all_scenarios_have_hint(self):
        for s in Scenario:
            assert s in SCENARIO_HINTS, f"missing hint for {s}"
            assert SCENARIO_HINTS[s], "hint must be non-empty"


class TestRecommendation:
    def test_each_scenario_returns_valid_recommendation(self):
        for s in Scenario:
            rec = build_scenario_recommendation(s)
            assert rec.scenario is s
            assert rec.structure
            assert rec.direction in {"long_vol", "short_vol", "neutral_vol"}
            assert rec.target_dte > 0
            assert rec.risk_profile in {"limited", "defined", "unlimited"}
            assert rec.confidence in {"high", "medium", "low"}
            assert rec.thesis
            assert rec.why_this_dte
            assert rec.risk_one_liner

    def test_rising_vol_high_confidence_when_data_present_and_cheap(self):
        rec = build_scenario_recommendation(
            Scenario.RISING_VOL_ON_CHEAP,
            iv_percentile=12, iv_rank=15,
        )
        assert rec.confidence == "high"
        assert rec.direction == "long_vol"
        assert "vol_not_cheap_today" not in rec.flags

    def test_rising_vol_low_confidence_when_vol_not_cheap(self):
        rec = build_scenario_recommendation(
            Scenario.RISING_VOL_ON_CHEAP,
            iv_percentile=85, iv_rank=80,
        )
        assert rec.confidence == "low"
        assert "vol_not_cheap_today" in rec.flags

    def test_harvest_rich_premium_flags_when_not_rich(self):
        rec = build_scenario_recommendation(
            Scenario.HARVEST_RICH_PREMIUM,
            iv_percentile=20,
        )
        assert "vol_not_rich_today" in rec.flags

    def test_deep_otm_leaps_strike_uses_spot(self):
        rec = build_scenario_recommendation(
            Scenario.DEEP_OTM_LEAPS,
            iv_percentile=25,
            spot=45.37,
        )
        # 45.37 * 1.75 = 79.40 → round to 79
        assert "$79" in rec.strike_rule
        assert rec.target_dte >= 600  # LEAPS

    def test_deep_otm_leaps_falls_back_when_spot_missing(self):
        rec = build_scenario_recommendation(
            Scenario.DEEP_OTM_LEAPS,
            iv_percentile=25,
        )
        assert "+75 % uplift" in rec.strike_rule
        assert "missing:spot" in rec.flags

    def test_earnings_long_gamma_flags_far_er(self):
        rec = build_scenario_recommendation(
            Scenario.EARNINGS_LONG_GAMMA,
            days_to_earnings=45,
        )
        assert "er_too_far" in rec.flags
        assert rec.confidence == "low"

    def test_earnings_long_gamma_high_when_er_close(self):
        rec = build_scenario_recommendation(
            Scenario.EARNINGS_LONG_GAMMA,
            days_to_earnings=3,
        )
        assert rec.confidence == "high"
        assert "er_too_far" not in rec.flags

    def test_earnings_crush_fade_requires_past_er(self):
        rec = build_scenario_recommendation(
            Scenario.EARNINGS_CRUSH_FADE,
            days_to_earnings=10,
        )
        assert "er_not_passed_yet" in rec.flags

    def test_card_html_contains_scenario_label(self):
        rec = build_scenario_recommendation(Scenario.DEEP_OTM_LEAPS, spot=45.37)
        html = scenario_card_html(rec)
        assert SCENARIO_LABELS[Scenario.DEEP_OTM_LEAPS] in html
        assert rec.structure in html
        assert "DTE" in html

    def test_unknown_scenario_raises(self):
        # Defensive — shouldn't be reachable through enum but the code path exists.
        class _FakeScenario:
            value = "fake"
        with pytest.raises(ValueError):
            build_scenario_recommendation(_FakeScenario())  # type: ignore[arg-type]
