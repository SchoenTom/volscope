"""Tests for components/auto_refresh.py — opt-in per-page rerun."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from volscope.ui.components import auto_refresh


class TestStateKeys:
    def test_keys_are_namespaced_per_page(self):
        a_int, a_last = auto_refresh._state_keys("discover")
        b_int, b_last = auto_refresh._state_keys("scope")
        assert a_int != b_int
        assert a_last != b_last

    def test_keys_normalize_whitespace_and_dashes(self):
        a_int, _ = auto_refresh._state_keys("Pre-Trade")
        b_int, _ = auto_refresh._state_keys("pre trade")
        c_int, _ = auto_refresh._state_keys("pre_trade")
        assert a_int == b_int == c_int


class TestIntervalOptions:
    def test_off_is_zero_seconds(self):
        opts = dict(auto_refresh.INTERVAL_OPTIONS)
        assert opts["Off"] == 0

    def test_intervals_are_monotonically_increasing(self):
        seconds = [secs for _, secs in auto_refresh.INTERVAL_OPTIONS]
        assert seconds == sorted(seconds)

    def test_no_interval_below_30s(self):
        """Yahoo rate-limits and cache TTL is 60s — anything <30s is wasteful."""
        for label, secs in auto_refresh.INTERVAL_OPTIONS:
            if secs > 0:
                assert secs >= 30, f"{label} too aggressive"


class TestToggleNoop:
    """Smoke test the renderer doesn't crash with a mocked Streamlit."""

    def test_toggle_off_does_not_rerun(self):
        """When Off is selected, st.rerun must NOT be called."""
        with patch.object(auto_refresh, "st") as st:
            st.session_state = {}
            cols = [MagicMock(), MagicMock()]
            for c in cols:
                c.__enter__ = lambda self: self
                c.__exit__ = lambda *a: None
            st.columns.return_value = cols
            st.selectbox.return_value = "Off"

            auto_refresh.auto_refresh_toggle("discover")

            st.rerun.assert_not_called()

    def test_toggle_initializes_state_when_changed(self):
        """Switching to 30s writes to session_state."""
        with patch.object(auto_refresh, "st") as st:
            state: dict = {}
            st.session_state = state
            cols = [MagicMock(), MagicMock()]
            for c in cols:
                c.__enter__ = lambda self: self
                c.__exit__ = lambda *a: None
            st.columns.return_value = cols
            st.selectbox.return_value = "30s"

            auto_refresh.auto_refresh_toggle("scope")

            interval_key, _ = auto_refresh._state_keys("scope")
            assert state[interval_key] == 30
