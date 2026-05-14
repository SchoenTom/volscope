"""Tests for analytics.earnings_calendar."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.earnings_calendar import (
    EarningsEvent,
    severity_for_dte,
    upcoming_earnings,
)


class _FakeDb:
    """Minimal stub that mimics ``get_upcoming_earnings``."""
    def __init__(self, mapping: dict):
        self.mapping = mapping
    def get_upcoming_earnings(self, ticker: str, from_date: date) -> pd.DataFrame:
        date_for = self.mapping.get(ticker)
        if date_for is None or date_for < from_date:
            return pd.DataFrame()
        return pd.DataFrame({"earnings_date": [date_for]})


# ──────────────────────────────────────────────────────────────────────────
# upcoming_earnings
# ──────────────────────────────────────────────────────────────────────────

class TestUpcomingEarnings:
    def test_empty_returns_empty(self):
        db = _FakeDb({})
        assert upcoming_earnings(db, ["A", "B"]) == []

    def test_single_event(self):
        today = date(2026, 5, 3)
        db = _FakeDb({"X": today + timedelta(days=3)})
        result = upcoming_earnings(db, ["X"], today=today)
        assert len(result) == 1
        assert result[0].days_to_earnings == 3

    def test_sorted_by_dte_ascending(self):
        today = date(2026, 5, 3)
        db = _FakeDb({
            "FAR":   today + timedelta(days=10),
            "NEAR":  today + timedelta(days=2),
            "MID":   today + timedelta(days=5),
        })
        result = upcoming_earnings(db, ["FAR", "NEAR", "MID"], today=today)
        assert [r.ticker for r in result] == ["NEAR", "MID", "FAR"]

    def test_filters_by_horizon(self):
        today = date(2026, 5, 3)
        db = _FakeDb({"WAY_OUT": today + timedelta(days=60)})
        result = upcoming_earnings(db, ["WAY_OUT"], horizon_days=14, today=today)
        assert result == []

    def test_excludes_past_earnings(self):
        today = date(2026, 5, 3)
        # Past dates aren't returned by get_upcoming_earnings (the SQL filters them)
        db = _FakeDb({"OLD": today - timedelta(days=5)})
        result = upcoming_earnings(db, ["OLD"], today=today)
        assert result == []


# ──────────────────────────────────────────────────────────────────────────
# severity_for_dte
# ──────────────────────────────────────────────────────────────────────────

class TestSeverity:
    def test_today_is_alert(self):
        assert severity_for_dte(0) == "alert"

    def test_two_days_is_warn(self):
        assert severity_for_dte(2) == "warn"

    def test_week_is_watch(self):
        assert severity_for_dte(7) == "watch"

    def test_far_is_info(self):
        assert severity_for_dte(14) == "info"


# ──────────────────────────────────────────────────────────────────────────
# Frozen
# ──────────────────────────────────────────────────────────────────────────

class TestFrozen:
    def test_event_frozen(self):
        e = EarningsEvent("X", date(2026, 5, 5), 2)
        with pytest.raises(Exception):
            e.ticker = "Y"  # type: ignore[misc]
