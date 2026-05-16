"""Tests for volscope.ui.components.phase_header.

Per master-plan §13.3: the strip MUST render valid HTML for every
page in app._PAGE_REGISTRY AND fall back silently on unknown pages.
"""
from __future__ import annotations

import pytest

from volscope.ui.components.phase_header import (
    PAGE_TO_PHASE, PHASES, rgba_inline,
)


class _FakeSt:
    """Minimal Streamlit shim — captures every markdown call."""
    def __init__(self):
        self.html: list[str] = []

    def markdown(self, body, *, unsafe_allow_html=False):
        self.html.append(body)


def test_phases_have_four_entries():
    assert len(PHASES) == 4
    for p in PHASES:
        assert "num" in p and "key" in p and "title" in p and "default_page" in p


def test_every_app_registry_page_is_either_mapped_or_explicitly_blank():
    """Every page in app._PAGE_REGISTRY must appear in PAGE_TO_PHASE
    (degraded "" is acceptable for meta-pages like Onboarding/Help).
    """
    from volscope.ui.app import _PAGE_REGISTRY
    for page in _PAGE_REGISTRY:
        assert page in PAGE_TO_PHASE, (
            f"Page '{page}' is in app._PAGE_REGISTRY but missing from "
            f"phase_header.PAGE_TO_PHASE. Add it (use '' for meta-pages)."
        )


def test_every_phase_default_page_is_a_real_page():
    """Each phase's default_page must exist in app._PAGE_REGISTRY,
    otherwise clicking the strip navigates to a 404.
    """
    from volscope.ui.app import _PAGE_REGISTRY
    for p in PHASES:
        assert p["default_page"] in _PAGE_REGISTRY, (
            f"Phase {p['key']} default_page '{p['default_page']}' is not "
            f"a registered page."
        )


def test_render_phase_header_known_page_emits_html():
    from volscope.ui.components.phase_header import render_phase_header
    st = _FakeSt()
    render_phase_header(st, page_name="Scope", ticker="PYPL")
    assert len(st.html) == 1
    body = st.html[0]
    # Includes a phase indicator
    assert "Scan" in body
    assert "Investigate" in body
    # Ticker badge
    assert "PYPL" in body
    # Active highlight on Investigate (Scope's phase)
    assert "rgba(" in body  # the active pill uses rgba background


def test_render_phase_header_unknown_page_renders_no_highlight_but_still_works():
    from volscope.ui.components.phase_header import render_phase_header
    st = _FakeSt()
    render_phase_header(st, page_name="this-page-does-not-exist")
    # MUST still render (the strip is informational, not gating)
    assert len(st.html) == 1
    body = st.html[0]
    assert "Scan" in body and "Investigate" in body


def test_render_phase_header_without_ticker_skips_badge():
    from volscope.ui.components.phase_header import render_phase_header
    st = _FakeSt()
    render_phase_header(st, page_name="Discover")
    body = st.html[0]
    # No ticker badge
    assert "● " not in body  # we use ● as the badge marker


def test_rgba_inline_converts_6char_hex():
    assert rgba_inline("#00d4aa", 0.5) == "rgba(0,212,170,0.5)"


def test_rgba_inline_passes_through_non_hex():
    assert rgba_inline("red", 0.5) == "red"
    assert rgba_inline("rgba(1,2,3,1)", 0.5) == "rgba(1,2,3,1)"


def test_rgba_inline_handles_empty_safely():
    # Should not raise on empty / None-equivalent input
    assert rgba_inline("", 0.5) == ""
