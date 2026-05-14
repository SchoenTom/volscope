"""Tests for ui.components.navigation — cross-page nav primitive."""
from __future__ import annotations

import pytest

from volscope.ui.components.navigation import (
    NavIntent,
    _prefill_key,
    consume_prefill,
    is_active,
    nav_to,
)


@pytest.fixture
def fake_streamlit(monkeypatch):
    """Mock streamlit's session_state with a plain dict + minimal interface."""
    class _FakeState(dict):
        # Streamlit's session_state supports dict + attribute access
        def __getattr__(self, k):
            try:
                return self[k]
            except KeyError as e:
                raise AttributeError(k) from e
        def __setattr__(self, k, v):
            self[k] = v

    state = _FakeState()

    class _FakeSt:
        session_state = state

    import volscope.ui.components.navigation as nav_mod
    monkeypatch.setattr(
        "streamlit.session_state",
        state,
        raising=False,
    )
    # Also stub out streamlit module entry for direct import
    monkeypatch.setitem(__import__("sys").modules, "streamlit", _FakeSt)
    return state


# ──────────────────────────────────────────────────────────────────────────
# NavIntent dataclass
# ──────────────────────────────────────────────────────────────────────────

class TestNavIntent:
    def test_minimal(self):
        i = NavIntent(page="Scope")
        assert i.page == "Scope"
        assert i.ticker is None
        assert i.payload is None

    def test_full(self):
        i = NavIntent(page="Pre-Trade", ticker="QQQ", source="Discover",
                       payload={"strike": 400})
        assert i.payload["strike"] == 400

    def test_frozen(self):
        i = NavIntent(page="X")
        with pytest.raises(Exception):
            i.page = "Y"  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────
# Prefill key naming
# ──────────────────────────────────────────────────────────────────────────

class TestPrefillKey:
    def test_lowercase(self):
        assert _prefill_key("Scope") == "prefill_scope"

    def test_dash_to_underscore(self):
        assert _prefill_key("Pre-Trade") == "prefill_pre_trade"

    def test_space_to_underscore(self):
        assert _prefill_key("Mega Scan") == "prefill_mega_scan"


# ──────────────────────────────────────────────────────────────────────────
# nav_to behaviour
# ──────────────────────────────────────────────────────────────────────────

class TestNavTo:
    def test_sets_active_page(self, fake_streamlit):
        nav_to(NavIntent(page="Scope"))
        assert fake_streamlit["active_page"] == "Scope"

    def test_sets_ticker_when_provided(self, fake_streamlit):
        nav_to(NavIntent(page="Scope", ticker="QQQ"))
        assert fake_streamlit["selected_ticker"] == "QQQ"

    def test_skips_ticker_when_none(self, fake_streamlit):
        fake_streamlit["selected_ticker"] = "PRE_EXISTING"
        nav_to(NavIntent(page="Scope", ticker=None))
        # Should NOT touch existing selected_ticker when intent has none
        assert fake_streamlit["selected_ticker"] == "PRE_EXISTING"

    def test_writes_payload_to_namespaced_key(self, fake_streamlit):
        nav_to(NavIntent(page="Pre-Trade", payload={"strike": 400}))
        assert fake_streamlit["prefill_pre_trade"] == {"strike": 400}

    def test_clears_stale_nav_source(self, fake_streamlit):
        fake_streamlit["nav_source"] = "OldSource"
        nav_to(NavIntent(page="Scope"))   # no source provided
        assert "nav_source" not in fake_streamlit

    def test_sets_nav_source_when_provided(self, fake_streamlit):
        nav_to(NavIntent(page="Scope", source="Discover"))
        assert fake_streamlit["nav_source"] == "Discover"

    def test_does_not_call_rerun(self, fake_streamlit, monkeypatch):
        # Verify nav_to does not invoke st.rerun() — the rerun is implicit
        # via the streamlit button handler. We assert by adding a tracked
        # attribute and checking it stays untouched.
        rerun_called = []
        import sys
        st_module = sys.modules.get("streamlit")
        st_module.rerun = lambda: rerun_called.append(True)  # type: ignore[attr-defined]
        nav_to(NavIntent(page="Scope"))
        assert rerun_called == []


# ──────────────────────────────────────────────────────────────────────────
# consume_prefill
# ──────────────────────────────────────────────────────────────────────────

class TestConsumePrefill:
    def test_returns_none_when_nothing(self, fake_streamlit):
        assert consume_prefill("Scope") is None

    def test_returns_payload_and_clears(self, fake_streamlit):
        fake_streamlit["prefill_scope"] = {"foo": 1}
        assert consume_prefill("Scope") == {"foo": 1}
        # Second call returns None — payload gone
        assert consume_prefill("Scope") is None

    def test_handles_page_with_dash(self, fake_streamlit):
        fake_streamlit["prefill_pre_trade"] = {"strike": 100}
        assert consume_prefill("Pre-Trade") == {"strike": 100}

    def test_other_pages_unaffected(self, fake_streamlit):
        fake_streamlit["prefill_scope"] = {"a": 1}
        fake_streamlit["prefill_portfolio"] = {"b": 2}
        consume_prefill("Scope")
        assert "prefill_portfolio" in fake_streamlit


# ──────────────────────────────────────────────────────────────────────────
# is_active
# ──────────────────────────────────────────────────────────────────────────

class TestIsActive:
    def test_true_when_match(self, fake_streamlit):
        fake_streamlit["active_page"] = "Pre-Trade"
        assert is_active("Pre-Trade") is True

    def test_false_when_different(self, fake_streamlit):
        fake_streamlit["active_page"] = "Scope"
        assert is_active("Pre-Trade") is False

    def test_false_when_unset(self, fake_streamlit):
        assert is_active("Anything") is False
