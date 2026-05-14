"""Tests for analytics.earnings_watch — forward earnings alerts."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.earnings_crush import CrushEstimate
from volscope.analytics.earnings_watch import (
    EarningsAlert,
    alert_card_html,
    build_earnings_alert,
)


# ──────────────────────────────────────────────────────────────────────────
# Severity escalation
# ──────────────────────────────────────────────────────────────────────────

class TestSeverity:
    def test_alert_today(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 3),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert a is not None
        assert a.severity == "alert"

    def test_alert_one_day(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 4),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert a is not None
        assert a.severity == "alert"

    def test_warn_three_days(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 6),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert a.severity == "warn"

    def test_watch_seven_days(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert a.severity == "watch"

    def test_info_far_out(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 25),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert a.severity == "info"

    def test_returns_none_far_horizon(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 8, 1),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert a is None

    def test_returns_none_long_past(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 4, 1),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert a is None

    def test_iv_richness_bumps_severity(self):
        # 7d to ER + IV pctl 90 → bumped from watch to warn
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=30, iv_percentile=90,
            today=date(2026, 5, 3),
        )
        assert a.severity == "warn"

    def test_low_iv_no_bump(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=20, iv_percentile=20,
            today=date(2026, 5, 3),
        )
        assert a.severity == "watch"   # not bumped


# ──────────────────────────────────────────────────────────────────────────
# Headline + body
# ──────────────────────────────────────────────────────────────────────────

class TestText:
    def test_headline_today(self):
        a = build_earnings_alert(
            "MSTR", earnings_date=date(2026, 5, 3),
            spot=300, iv_pct=80, today=date(2026, 5, 3),
        )
        assert "TODAY" in a.headline
        assert "MSTR" in a.headline

    def test_headline_includes_dte(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert "7 day" in a.headline

    def test_body_includes_em_when_iv_present(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert "Expected move" in a.body

    def test_body_includes_iv_pctl(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=20, iv_percentile=82,
            today=date(2026, 5, 3),
        )
        assert "pctl 82" in a.body

    def test_body_includes_crush_when_available(self):
        crush = CrushEstimate(
            avg_crush_pct=-22.5, min_crush_pct=-45.0, max_crush_pct=-8.0,
            n_events=4, next_earnings_date=date(2026, 5, 10), days_to_earnings=7,
        )
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=20, crush_estimate=crush,
            today=date(2026, 5, 3),
        )
        assert "crush avg" in a.body
        assert "-22.5pt" in a.body


# ──────────────────────────────────────────────────────────────────────────
# Expected move integration
# ──────────────────────────────────────────────────────────────────────────

class TestExpectedMoveIntegration:
    def test_em_uses_iv_when_no_chain(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=24, today=date(2026, 5, 3),
        )
        assert a.expected_move is not None
        assert a.expected_move.iv_based is not None
        assert a.expected_move.straddle is None

    def test_em_uses_chain_when_provided(self):
        df = pd.DataFrame([
            {"strike": 100, "option_type": "call", "bid": 2.4, "ask": 2.6, "open_interest": 100},
            {"strike": 100, "option_type": "put", "bid": 2.4, "ask": 2.6, "open_interest": 100},
        ])
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=20, options_df=df,
            today=date(2026, 5, 3),
        )
        assert a.expected_move is not None
        assert a.expected_move.straddle is not None


# ──────────────────────────────────────────────────────────────────────────
# Frozen + HTML
# ──────────────────────────────────────────────────────────────────────────

class TestFrozenAndHtml:
    def test_alert_frozen(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        with pytest.raises(Exception):
            a.severity = "alert"  # type: ignore[misc]

    def test_html_renders(self):
        a = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        html = alert_card_html(a)
        assert "<div" in html
        assert a.severity.upper() in html

    def test_html_distinct_per_severity(self):
        a1 = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 4),  # alert
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        a2 = build_earnings_alert(
            "X", earnings_date=date(2026, 5, 10),  # watch
            spot=100, iv_pct=20, today=date(2026, 5, 3),
        )
        assert alert_card_html(a1) != alert_card_html(a2)
