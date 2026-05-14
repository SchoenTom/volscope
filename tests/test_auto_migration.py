"""
The auto-migration invariant.

VolScopeDB.__init__ silently runs the legacy-flat-spread migration on open.
This test pins that contract: legacy rows MUST be fixed before any user
code reads them, without an explicit fix_now call.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date

import pytest

from volscope.data.database import VolScopeDB


@pytest.fixture
def db_path():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "auto-migrate.db")
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _seed_legacy_rows(db: VolScopeDB, ticker: str, n: int = 5) -> None:
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


class TestAutoMigration:
    def test_legacy_rows_fixed_on_reopen(self, db_path):
        """Seed legacy rows, close, reopen — reopen auto-migrates them."""
        db1 = VolScopeDB(db_path, auto_migrate=False)  # disable on init to seed legacy
        _seed_legacy_rows(db1, "AAA", n=5)
        db1.close()

        # Reopen WITH auto_migrate=True (default). The init hook must fix them.
        db2 = VolScopeDB(db_path)
        hist = db2.get_ticker_history("AAA")
        spreads = (hist["iv_30d"] - hist["hv_20d"]).abs()
        assert (spreads > 1e-6).all(), "legacy rows not auto-migrated on reopen"
        db2.close()

    def test_auto_migrate_flag_can_be_disabled(self, db_path):
        """Explicit opt-out still works for tests that need to seed bad data."""
        db1 = VolScopeDB(db_path, auto_migrate=False)
        _seed_legacy_rows(db1, "BBB", n=3)
        db1.close()

        db2 = VolScopeDB(db_path, auto_migrate=False)
        hist = db2.get_ticker_history("BBB")
        spreads = (hist["iv_30d"] - hist["hv_20d"]).abs()
        assert (spreads < 1e-6).all(), (
            "auto_migrate=False should have left legacy rows untouched"
        )
        db2.close()

    def test_fresh_db_auto_migrate_is_noop(self, db_path):
        """Auto-migration on a fresh empty DB must be a no-op, not a crash."""
        db = VolScopeDB(db_path)  # auto_migrate=True
        assert db.get_ticker_history("NONEXISTENT").empty
        db.close()

    def test_mixed_db_only_legacy_rows_migrated(self, db_path):
        db1 = VolScopeDB(db_path, auto_migrate=False)
        _seed_legacy_rows(db1, "LEGACY", n=3)
        # Also insert a clean non-legacy row.
        db1.upsert_daily(
            "CLEAN",
            date(2026, 4, 14),
            iv_30d=22.5,
            hv_20d=18.0,
            hv_yz_20d=19.0,
            iv_hv_spread=4.5,
        )
        db1.close()

        db2 = VolScopeDB(db_path)
        clean = db2.get_ticker_history("CLEAN").iloc[0]
        assert float(clean["iv_30d"]) == 22.5  # unchanged
        legacy = db2.get_ticker_history("LEGACY")
        spreads = (legacy["iv_30d"] - legacy["hv_20d"]).abs()
        assert (spreads > 1e-6).all()
        db2.close()
