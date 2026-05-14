"""KPI / metric helper tests."""
from __future__ import annotations

from datetime import date, timedelta

from volscope.ui.components.metric_components import freshness_badge


def test_fresh_today():
    label, color = freshness_badge(date.today())
    assert "FRESH" in label
    assert color.startswith("#")


def test_ok_within_a_week():
    label, _ = freshness_badge(date.today() - timedelta(days=3))
    assert "OK" in label


def test_stale_after_a_week():
    label, _ = freshness_badge(date.today() - timedelta(days=14))
    assert "STALE" in label


def test_no_data():
    label, _ = freshness_badge(None)
    assert "NO DATA" in label


def test_iso_string_input():
    label, _ = freshness_badge("2026-04-13")
    assert label.endswith("d") or "FRESH" in label or "OK" in label
