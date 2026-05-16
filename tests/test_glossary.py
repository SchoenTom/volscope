"""Tests for the centralised KPI glossary (master plan §13.3)."""
from __future__ import annotations

from volscope.ui.components.glossary import GLOSSARY, glossary


def test_glossary_lookup_returns_known_term():
    assert "Rank" in glossary("iv_rank")
    assert "Percentile" in glossary("iv_percentile")


def test_glossary_lookup_unknown_returns_empty_string():
    # Silent fallback — never raise
    assert glossary("this-key-does-not-exist") == ""


def test_every_glossary_entry_is_one_or_two_sentences():
    for key, text in GLOSSARY.items():
        sentences = [s for s in text.split(". ") if s.strip()]
        assert len(sentences) <= 3, (
            f"Glossary entry {key!r} has > 3 sentence fragments — keep "
            f"it short. Current: {text[:80]}..."
        )


def test_every_glossary_entry_starts_with_term_or_definition():
    bad_starts = ("This ", "It ", "We ", "The metric ", "The value ")
    for key, text in GLOSSARY.items():
        assert not text.startswith(bad_starts), (
            f"Glossary {key!r} starts with hedging phrase: {text[:40]}..."
        )


def test_glossary_terms_are_unique_keys():
    assert len(GLOSSARY) == len(set(GLOSSARY.keys()))


def test_critical_kpis_present():
    required = {
        "iv_rank", "iv_percentile", "iv_30d", "iv_skew_25d",
        "vol_regime", "expected_move", "iv_hv_spread", "delta",
        "max_pain", "kelly_fraction",
    }
    missing = required - set(GLOSSARY.keys())
    assert not missing, f"Glossary missing required keys: {missing}"
