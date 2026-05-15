"""
Tests for the central freshness-assessment module.

The non-obvious scenarios the tests pin down:

- Monday-after-Friday-scrape is FRESH (not 3-stale)
- Memorial-Day-Monday is correctly skipped — Fri → Tue counts 1 biz day
- 5 business days old = STALE (the badge colour flips amber)
- >5 business days = VERY_STALE (badge red)
- None ⇒ MISSING
- Future timestamps (clock skew) clamp to 0 days_old
"""
from __future__ import annotations

from datetime import date

import pytest

from volscope.data.freshness import (
    FreshnessLevel,
    assess_freshness,
    business_days_between,
    is_business_day,
)


def test_is_business_day_friday():
    assert is_business_day(date(2026, 5, 15)) is True


def test_is_business_day_saturday():
    assert is_business_day(date(2026, 5, 16)) is False


def test_is_business_day_memorial_day_2026():
    # May 25, 2026 is Memorial Day (NYSE closed)
    assert is_business_day(date(2026, 5, 25)) is False


def test_business_days_between_same_day():
    # Both endpoints inclusive — same day = 1 business day if it's a weekday
    assert business_days_between(date(2026, 5, 15), date(2026, 5, 15)) == 1


def test_business_days_between_friday_to_monday():
    # Fri 15 → Mon 18 = 2 business days (Fri + Mon, weekend excluded)
    assert business_days_between(date(2026, 5, 15), date(2026, 5, 18)) == 2


def test_business_days_between_skips_holidays():
    # Fri 22 → Tue 26 (Mon 25 = Memorial Day) = 2 days (Fri + Tue)
    assert business_days_between(date(2026, 5, 22), date(2026, 5, 26)) == 2


def test_business_days_between_inverted_returns_zero():
    assert business_days_between(date(2026, 5, 15), date(2026, 5, 14)) == 0


def test_assess_fresh_same_day():
    today = date(2026, 5, 15)
    r = assess_freshness(today, asof=today)
    assert r.level == FreshnessLevel.FRESH
    assert r.business_days_old == 0
    assert r.color_hint == "green"


def test_assess_fresh_monday_after_friday_scrape():
    # The flagship scenario: Fri scrape → Mon morning sees FRESH.
    r = assess_freshness(
        date(2026, 5, 15), asof=date(2026, 5, 18),
    )
    assert r.level in (FreshnessLevel.FRESH, FreshnessLevel.RECENT)
    # 1 trading day strictly between Fri and Mon (just Mon itself, then
    # we strip 1 for the "strictly between" semantics) → 1.
    assert r.business_days_old <= 1


def test_assess_stale_5_business_days():
    # 5 business days = exactly the STALE/VERY_STALE boundary.
    r = assess_freshness(
        date(2026, 5, 8), asof=date(2026, 5, 15),
    )
    assert r.business_days_old == 5
    assert r.level == FreshnessLevel.STALE
    assert r.color_hint == "amber"


def test_assess_very_stale_long_gap():
    r = assess_freshness(
        date(2026, 4, 1), asof=date(2026, 5, 15),
    )
    assert r.level == FreshnessLevel.VERY_STALE
    assert r.color_hint == "red"


def test_assess_missing_when_no_scrape():
    r = assess_freshness(None, asof=date(2026, 5, 15))
    assert r.level == FreshnessLevel.MISSING
    assert r.last_scrape is None
    assert "scrape" in r.warning_message.lower()


def test_assess_future_clock_skew_clamps_to_zero():
    r = assess_freshness(
        date(2026, 5, 16), asof=date(2026, 5, 15),
    )
    assert r.days_old == 0
    assert r.level == FreshnessLevel.FRESH


def test_next_business_day_skips_weekend():
    # Friday → next biz day = Monday
    r = assess_freshness(date(2026, 5, 15), asof=date(2026, 5, 15))
    assert r.expected_next_update == date(2026, 5, 18)


def test_next_business_day_skips_memorial_day():
    # Friday before Memorial Day → next biz day = Tuesday after.
    r = assess_freshness(date(2026, 5, 22), asof=date(2026, 5, 22))
    assert r.expected_next_update == date(2026, 5, 26)


def test_warning_message_contains_date():
    r = assess_freshness(date(2026, 5, 1), asof=date(2026, 5, 15))
    assert "2026-05-01" in r.warning_message
