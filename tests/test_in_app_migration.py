"""
Tests for the in-app legacy-spread migration.

The user shouldn't have to stop Streamlit and run a separate Python script.
`VolScopeDB.migrate_legacy_flat_spread()` runs the same UPDATE on the live
DB handle so a button in the Scope page banner can fix the data inline.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date

import pytest

from volscope.data.database import VolScopeDB


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "migrate.db")
    d = VolScopeDB(path)
    yield d
    d.close()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _seed_legacy(db: VolScopeDB, ticker: str, n: int = 5) -> None:
    """Insert rows with iv_30d == hv_20d exactly (the legacy bug)."""
    for i in range(n):
        db.upsert_daily(
            ticker,
            date(2026, 4, 1 + i),
            spot_price=100.0,
            iv_30d=20.0,
            hv_20d=20.0,
            hv_yz_20d=19.0,
            iv_hv_spread=0.0,
        )


class TestInAppMigration:
    def test_migrates_all_rows_when_no_ticker_arg(self, db):
        _seed_legacy(db, "AAA", n=5)
        _seed_legacy(db, "BBB", n=3)
        n = db.migrate_legacy_flat_spread()
        assert n == 8

        hist_a = db.get_ticker_history("AAA")
        assert (hist_a["iv_30d"] - hist_a["hv_20d"]).abs().sum() > 0

    def test_migrates_only_target_ticker(self, db):
        _seed_legacy(db, "AAA", n=5)
        _seed_legacy(db, "BBB", n=3)
        n = db.migrate_legacy_flat_spread(ticker="AAA")
        assert n == 5

        hist_a = db.get_ticker_history("AAA")
        hist_b = db.get_ticker_history("BBB")
        # AAA is fixed...
        assert (hist_a["iv_30d"] - hist_a["hv_20d"]).abs().sum() > 0
        # BBB is untouched.
        assert (hist_b["iv_30d"] - hist_b["hv_20d"]).abs().sum() == 0

    def test_migration_is_idempotent(self, db):
        _seed_legacy(db, "AAA", n=5)
        first = db.migrate_legacy_flat_spread()
        second = db.migrate_legacy_flat_spread()
        assert first == 5
        assert second == 0  # nothing left to fix

    def test_empty_db_returns_zero(self, db):
        assert db.migrate_legacy_flat_spread() == 0

    def test_non_legacy_rows_are_untouched(self, db):
        # Real (non-flat) row — iv != hv.
        db.upsert_daily(
            "REAL",
            date(2026, 4, 14),
            iv_30d=22.5,
            hv_20d=18.0,
            hv_yz_20d=19.0,
            iv_hv_spread=4.5,
        )
        n = db.migrate_legacy_flat_spread()
        assert n == 0
        hist = db.get_ticker_history("REAL")
        assert float(hist.iloc[0]["iv_30d"]) == 22.5  # unchanged

    def test_recomputed_values_match_vrp_formula(self, db):
        _seed_legacy(db, "AAA", n=1)
        db.migrate_legacy_flat_spread(vrp_mult=1.20)
        hist = db.get_ticker_history("AAA")
        row = hist.iloc[0]
        # Original hv_yz_20d was 19.0, vrp_mult was 1.20.
        assert abs(float(row["iv_30d"]) - 19.0 * 1.20) < 1e-6
        # Spread = (19*1.2) - 20 = 22.8 - 20 = 2.8
        assert abs(float(row["iv_hv_spread"]) - 2.8) < 1e-6
