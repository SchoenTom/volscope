"""Tests for the centralized glossary."""
from __future__ import annotations

import pytest

from volscope.ui.glossary import GLOSSARY, tooltip


def test_every_term_has_non_empty_definition():
    """No empty values — every entry must carry real explanatory text."""
    for term, definition in GLOSSARY.items():
        assert definition, f"term {term!r} has empty definition"
        assert len(definition) > 10, f"term {term!r} has trivial definition: {definition!r}"


def test_tooltip_returns_canonical_string():
    assert tooltip("IVR") == GLOSSARY["IVR"]


def test_tooltip_unknown_term_returns_empty_string():
    """Missing terms must not crash — silent empty fallback."""
    assert tooltip("not-a-real-term") == ""
    assert tooltip("") == ""


def test_core_terms_present():
    """Sanity check that the load-bearing terms are defined."""
    core = ["IV", "IVR", "IVP", "VRP", "Delta", "Gamma", "Vega",
            "Theta", "Rho", "DTE", "Regime", "p_calm", "POP",
            "Kelly", "Quality Score", "Contamination",
            "Structural Break"]
    for term in core:
        assert term in GLOSSARY, f"core term {term!r} missing"


def test_no_duplicate_definitions():
    """Catches copy-paste errors where two terms got the same definition."""
    definitions: dict[str, str] = {}
    for term, definition in GLOSSARY.items():
        if definition in definitions:
            pytest.fail(
                f"duplicate definition: {term!r} and "
                f"{definitions[definition]!r} share {definition!r}"
            )
        definitions[definition] = term


def test_definitions_have_no_raw_html_tags():
    """Definitions shouldn't carry HTML tags — they're rendered as plain
    text inside Streamlit tooltips. Inequality glyphs like '< 20' or
    '> 0.75' are fine; only tag-shaped sequences (``<word``, ``</word``)
    would actually break a renderer.
    """
    import re
    tag_re = re.compile(r"</?[A-Za-z][A-Za-z0-9]*")
    for term, definition in GLOSSARY.items():
        assert not tag_re.search(definition), (
            f"term {term!r} contains HTML-tag-like sequence: {definition!r}"
        )
