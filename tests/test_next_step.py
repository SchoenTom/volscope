"""Tests for volscope.ui.components.next_step.

Per master-plan §13.3: every NEXT_STEPS target MUST resolve to a real
page in app._PAGE_REGISTRY (no 404 on click), and the helper must
render safely on unknown pages.
"""
from __future__ import annotations

import pytest

from volscope.ui.components.next_step import NEXT_STEPS


def test_every_target_is_a_real_registered_page():
    """Every (target, label, needs_ticker) tuple's target must
    appear in app._PAGE_REGISTRY. Otherwise clicking → 404."""
    from volscope.ui.app import _PAGE_REGISTRY
    bad: list[tuple[str, str]] = []
    for source, entries in NEXT_STEPS.items():
        for target, _label, _nt in entries:
            if target not in _PAGE_REGISTRY:
                bad.append((source, target))
    assert not bad, (
        f"NEXT_STEPS contains targets not in app._PAGE_REGISTRY: {bad}. "
        f"Either add the page to the registry or fix the typo."
    )


def test_no_self_referential_entries():
    """A page never links to itself in its own next-step list."""
    self_loops = []
    for source, entries in NEXT_STEPS.items():
        for target, _label, _nt in entries:
            if target == source:
                self_loops.append(source)
    assert not self_loops, (
        f"Self-referential NEXT_STEPS entries: {self_loops}"
    )


def test_label_templates_substitute_ticker_correctly():
    """Any label_template containing {ticker} should substitute
    cleanly when a ticker is provided."""
    for source, entries in NEXT_STEPS.items():
        for _target, label, _nt in entries:
            substituted = label.format(ticker="PYPL")
            assert "{" not in substituted, (
                f"Unmatched placeholder in NEXT_STEPS[{source!r}] label "
                f"{label!r}: {substituted}"
            )


def test_ticker_required_marker_consistent():
    """If a label contains {ticker}, needs_ticker MUST be True
    (otherwise we'd render an un-substituted '{ticker}' on screen)."""
    for source, entries in NEXT_STEPS.items():
        for target, label, needs_t in entries:
            if "{ticker}" in label:
                assert needs_t, (
                    f"NEXT_STEPS[{source!r}] entry for {target!r} uses "
                    f"{{ticker}} in label but needs_ticker is False — "
                    f"will render literal placeholder."
                )


def test_every_app_page_has_a_next_step_entry_or_is_explicitly_terminal():
    """Pages without exit links can ONLY be terminal pages (Help,
    Onboarding). Every other page must have at least one next step.
    This is the master-plan §4 contract."""
    from volscope.ui.app import _PAGE_REGISTRY
    terminal_pages = {"Help", "Onboarding"}
    for page in _PAGE_REGISTRY:
        if page in terminal_pages:
            continue
        assert page in NEXT_STEPS and NEXT_STEPS[page], (
            f"Page {page!r} has no NEXT_STEPS entries — every "
            f"non-terminal page MUST have at least one cross-link."
        )
