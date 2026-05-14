"""Tests for the LEAPS watchlist persistence layer."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

import pytest

from volscope.analytics.leaps_watchlist import (
    WATCHLIST_KEY,
    is_pinned,
    load_watchlist,
    pin_to_watchlist,
    unpin_from_watchlist,
)
from volscope.data.database import VolScopeDB


@pytest.fixture
def temp_db():
    """A fresh DuckDB the test owns end-to-end."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)        # let DuckDB create it cleanly
    db = VolScopeDB(db_path=path)
    yield db
    db.close()
    if os.path.exists(path):
        os.unlink(path)


# ── Empty state ─────────────────────────────────────────────────────────

def test_load_watchlist_returns_empty_when_unset(temp_db):
    assert load_watchlist(temp_db) == []


def test_is_pinned_false_when_empty(temp_db):
    assert is_pinned(temp_db, "PYPL") is False


# ── Pin / unpin ─────────────────────────────────────────────────────────

def test_pin_to_watchlist_persists_across_loads(temp_db):
    pin_to_watchlist(temp_db, "PYPL", today=date(2026, 5, 10))
    items = load_watchlist(temp_db)
    assert len(items) == 1
    assert items[0].ticker == "PYPL"
    assert items[0].pinned_at == date(2026, 5, 10)


def test_pin_dedupes_and_refreshes_pinned_at(temp_db):
    pin_to_watchlist(temp_db, "PYPL", today=date(2026, 5, 1))
    pin_to_watchlist(temp_db, "NKE",  today=date(2026, 5, 5))
    pin_to_watchlist(temp_db, "PYPL", today=date(2026, 5, 10))    # re-pin
    items = load_watchlist(temp_db)
    assert [e.ticker for e in items] == ["PYPL", "NKE"]
    assert items[0].pinned_at == date(2026, 5, 10)


def test_unpin_removes_ticker(temp_db):
    pin_to_watchlist(temp_db, "PYPL", today=date(2026, 5, 10))
    pin_to_watchlist(temp_db, "NKE",  today=date(2026, 5, 10))
    unpin_from_watchlist(temp_db, "PYPL")
    items = load_watchlist(temp_db)
    assert [e.ticker for e in items] == ["NKE"]


def test_unpin_unknown_is_noop(temp_db):
    pin_to_watchlist(temp_db, "PYPL", today=date(2026, 5, 10))
    unpin_from_watchlist(temp_db, "AAPL")
    assert [e.ticker for e in load_watchlist(temp_db)] == ["PYPL"]


def test_load_watchlist_returns_most_recent_first(temp_db):
    pin_to_watchlist(temp_db, "OLD",  today=date(2026, 1, 1))
    pin_to_watchlist(temp_db, "MID",  today=date(2026, 3, 1))
    pin_to_watchlist(temp_db, "NEW",  today=date(2026, 5, 10))
    items = load_watchlist(temp_db)
    assert [e.ticker for e in items] == ["NEW", "MID", "OLD"]


# ── Corruption resilience ──────────────────────────────────────────────

def test_load_watchlist_handles_invalid_json_gracefully(temp_db):
    temp_db.set_user_setting(WATCHLIST_KEY, "{not-json")
    assert load_watchlist(temp_db) == []


def test_load_watchlist_skips_malformed_entries(temp_db):
    temp_db.set_user_setting(
        WATCHLIST_KEY,
        '{"items":[{"ticker":"PYPL","pinned_at":"2026-05-10"},'
        '{"ticker":"BAD","pinned_at":"not-a-date"}]}',
    )
    items = load_watchlist(temp_db)
    assert [e.ticker for e in items] == ["PYPL"]
