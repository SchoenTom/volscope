"""Tests for ui.views.onboarding_page — first-run wizard route gate."""
from __future__ import annotations

import pytest

from volscope.ui.views.onboarding_page import (
    _STARTER_PACKS,
    should_show_onboarding,
)


# ──────────────────────────────────────────────────────────────────────────
# should_show_onboarding gate
# ──────────────────────────────────────────────────────────────────────────

class _FakeDb:
    def __init__(self, completed=False, available=None, raise_on_setting=False,
                 raise_on_tickers=False):
        self.completed = completed
        self.available = list(available or [])
        self.raise_on_setting = raise_on_setting
        self.raise_on_tickers = raise_on_tickers
    def get_user_setting(self, key, default=None):
        if self.raise_on_setting:
            raise RuntimeError("boom")
        return "true" if (self.completed and key == "onboarding_complete") else default
    def get_available_tickers(self):
        if self.raise_on_tickers:
            raise RuntimeError("boom")
        return self.available


class TestShouldShowOnboarding:
    def test_fresh_db_shows_onboarding(self):
        assert should_show_onboarding(_FakeDb()) is True

    def test_completed_flag_skips(self):
        assert should_show_onboarding(_FakeDb(completed=True)) is False

    def test_existing_tickers_skip_even_without_flag(self):
        assert should_show_onboarding(_FakeDb(available=["SPY", "QQQ"])) is False

    def test_setting_failure_falls_through_to_ticker_check(self):
        # If user_settings query fails, fall back to ticker check
        db = _FakeDb(raise_on_setting=True, available=["X"])
        assert should_show_onboarding(db) is False

    def test_both_failures_default_to_show(self):
        # Conservative default — show onboarding when can't determine state
        db = _FakeDb(raise_on_setting=True, raise_on_tickers=True)
        assert should_show_onboarding(db) is True


# ──────────────────────────────────────────────────────────────────────────
# Starter packs
# ──────────────────────────────────────────────────────────────────────────

class TestStarterPacks:
    def test_quick_start_has_8_tickers(self):
        assert len(_STARTER_PACKS["Quick start (8 tickers)"]) == 8

    def test_quick_start_has_known_majors(self):
        pack = _STARTER_PACKS["Quick start (8 tickers)"]
        assert "SPY" in pack
        assert "QQQ" in pack

    def test_full_universe_label_present(self):
        # The 50 and full are populated dynamically; just check the keys
        assert "Full universe (568 tickers)" in _STARTER_PACKS
        assert "Hedge-fund book (50 tickers)" in _STARTER_PACKS
