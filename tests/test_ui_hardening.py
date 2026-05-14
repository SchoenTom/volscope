"""Tests for UI hardening — error boundaries and data-status helpers."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta

import pytest

from volscope.data.database import VolScopeDB
from volscope.ui.components.error_boundary import error_boundary


class _FakeSt:
    """Minimal streamlit stand-in for unit-testing UI components."""

    def __init__(self):
        self.errors: list[str] = []
        self.markdown_calls: list[str] = []
        self.code_calls: list[str] = []

    def markdown(self, body: str, unsafe_allow_html: bool = False):
        self.markdown_calls.append(body)

    def code(self, body: str):
        self.code_calls.append(body)


class TestErrorBoundary:
    def test_catches_exception_and_renders(self):
        fake = _FakeSt()
        with error_boundary(fake, "IV chart"):
            raise ValueError("bad shape")
        assert any("IV chart failed" in m for m in fake.markdown_calls)
        assert any("ValueError" in m for m in fake.markdown_calls)
        assert any("bad shape" in m for m in fake.markdown_calls)

    def test_passes_through_on_success(self):
        fake = _FakeSt()
        value = 0
        with error_boundary(fake, "IV chart"):
            value = 42
        assert value == 42
        assert fake.markdown_calls == []

    def test_isolates_failures(self):
        fake = _FakeSt()
        # First block fails, second block still executes.
        with error_boundary(fake, "block A"):
            raise RuntimeError("boom")
        executed = False
        with error_boundary(fake, "block B"):
            executed = True
        assert executed
        assert any("block A failed" in m for m in fake.markdown_calls)
        assert not any("block B failed" in m for m in fake.markdown_calls)

    def test_show_traceback_option(self):
        fake = _FakeSt()
        with error_boundary(fake, "chart", show_traceback=True):
            raise KeyError("missing")
        assert fake.code_calls, "traceback should render when show_traceback=True"

    def test_none_exception_type(self):
        # Errors with empty message shouldn't crash the boundary itself.
        fake = _FakeSt()
        with error_boundary(fake, "x"):
            raise ValueError()
        assert any("x failed" in m for m in fake.markdown_calls)


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "status-test.db")
    d = VolScopeDB(path)
    yield d
    d.close()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


class TestLastScrapeDate:
    def test_empty_db(self, db):
        assert db.get_last_scrape_date() is None

    def test_returns_most_recent(self, db):
        db.upsert_daily("AAA", date(2026, 1, 1), iv_30d=20.0)
        db.upsert_daily("AAA", date(2026, 4, 14), iv_30d=22.0)
        db.upsert_daily("BBB", date(2026, 3, 15), iv_30d=30.0)
        assert db.get_last_scrape_date() == date(2026, 4, 14)

    def test_freshness_categories(self):
        from volscope.ui.components.sidebar import _freshness

        today = date.today()
        label_fresh, color_fresh = _freshness(today)
        label_ok, color_ok = _freshness(today - timedelta(days=3))
        label_stale, color_stale = _freshness(today - timedelta(days=30))
        label_none, color_none = _freshness(None)

        assert "fresh" in label_fresh.lower()
        assert color_fresh == "#00d4aa"
        assert "ok" in label_ok.lower()
        assert color_ok == "#ff9f43"
        assert "stale" in label_stale.lower()
        assert color_stale == "#ff4466"
        assert color_none == "#ff4466"


class TestCompanyNameLookup:
    def test_empty_returns_none(self, db):
        assert db.get_company_name("UNKNOWN") is None

    def test_stored_name_is_returned(self, db):
        db.upsert_daily(
            "TEST", date(2026, 1, 1), iv_30d=20.0, company_name="Test Corp"
        )
        assert db.get_company_name("TEST") == "Test Corp"

    def test_returns_most_recent_non_null(self, db):
        db.upsert_daily("TEST", date(2026, 1, 1), company_name="Old Name")
        db.upsert_daily("TEST", date(2026, 2, 1), company_name="New Name")
        assert db.get_company_name("TEST") == "New Name"
