"""Tests for the validation_log DB table + helpers."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.data.database import VolScopeDB


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Per-test isolated DB."""
    monkeypatch.setenv("VOLSCOPE_DATA_DIR", str(tmp_path))
    db_obj = VolScopeDB(db_path=str(tmp_path / "test.duckdb"))
    yield db_obj
    db_obj.close()


# ──────────────────────────────────────────────────────────────────────────
# Schema + upsert
# ──────────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_table_exists(self, db):
        # Should not raise
        df = db.get_validation_log(target_date=date(2026, 5, 3))
        assert df.empty

    def test_upsert_creates_row(self, db):
        db.upsert_validation_report(
            ticker="X", target_date=date(2026, 5, 3),
            overall_level="OK", n_passes=5, n_flags=0, n_fails=0,
            details_json="[]",
        )
        df = db.get_validation_log(target_date=date(2026, 5, 3))
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "X"
        assert df.iloc[0]["overall_level"] == "OK"

    def test_upsert_idempotent(self, db):
        for _ in range(3):
            db.upsert_validation_report(
                ticker="X", target_date=date(2026, 5, 3),
                overall_level="OK", n_passes=5, n_flags=0, n_fails=0,
            )
        df = db.get_validation_log(target_date=date(2026, 5, 3))
        # Same (ticker, date) → only one row
        assert len(df) == 1

    def test_upsert_different_dates_keep_history(self, db):
        for d in [date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3)]:
            db.upsert_validation_report(
                ticker="X", target_date=d,
                overall_level="OK", n_passes=5, n_flags=0, n_fails=0,
            )
        for d in [date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3)]:
            df = db.get_validation_log(target_date=d)
            assert len(df) == 1


# ──────────────────────────────────────────────────────────────────────────
# Summary aggregation
# ──────────────────────────────────────────────────────────────────────────

class TestSummary:
    def test_empty_summary(self, db):
        df = db.get_validation_summary(target_date=date(2026, 5, 3))
        assert df.empty

    def test_summary_groups_by_level(self, db):
        d = date(2026, 5, 3)
        for ticker, level in [("A", "OK"), ("B", "OK"), ("C", "FLAG"), ("D", "FAIL")]:
            db.upsert_validation_report(
                ticker=ticker, target_date=d, overall_level=level,
                n_passes=0, n_flags=0, n_fails=0,
            )
        df = db.get_validation_summary(target_date=d)
        rows = df.set_index("overall_level")["n"].to_dict()
        assert rows["OK"] == 2
        assert rows["FLAG"] == 1
        assert rows["FAIL"] == 1


# ──────────────────────────────────────────────────────────────────────────
# Log ordering
# ──────────────────────────────────────────────────────────────────────────

class TestLogOrdering:
    def test_fail_first_then_flag_then_ok(self, db):
        d = date(2026, 5, 3)
        for ticker, level in [
            ("OK_ONE", "OK"),
            ("FAIL_ONE", "FAIL"),
            ("FLAG_ONE", "FLAG"),
            ("OK_TWO", "OK"),
        ]:
            db.upsert_validation_report(
                ticker=ticker, target_date=d, overall_level=level,
                n_passes=0, n_flags=0, n_fails=0,
            )
        df = db.get_validation_log(target_date=d)
        levels = df["overall_level"].tolist()
        # FAIL first, FLAG next, OK last
        assert levels[0] == "FAIL"
        assert levels[1] == "FLAG"
        assert "OK" in levels[2:]

    def test_limit_caps_rows(self, db):
        d = date(2026, 5, 3)
        for i in range(10):
            db.upsert_validation_report(
                ticker=f"T{i}", target_date=d, overall_level="OK",
                n_passes=0, n_flags=0, n_fails=0,
            )
        df = db.get_validation_log(target_date=d, limit=3)
        assert len(df) == 3
