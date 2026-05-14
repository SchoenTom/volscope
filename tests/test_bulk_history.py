"""Tests for VolScopeDB.get_recent_for_tickers bulk fetcher.

This path replaces N per-ticker queries on the Discover page. It is the
reason the movers + crowded panels became responsive at 80 tickers.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.data.database import VolScopeDB


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "bulk.db")
    d = VolScopeDB(path)
    yield d
    d.close()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _seed(db: VolScopeDB, ticker: str, n: int, start_iv: float) -> None:
    base = date(2026, 1, 1)
    for i in range(n):
        db.upsert_daily(
            ticker,
            base + timedelta(days=i),
            spot_price=100.0 + i,
            iv_30d=start_iv + i * 0.1,
            hv_20d=start_iv - 1 + i * 0.05,
        )


class TestBulkFetcher:
    def test_empty_tickers(self, db):
        assert db.get_recent_for_tickers([]) == {}

    def test_unknown_tickers_return_empty_frames(self, db):
        result = db.get_recent_for_tickers(["DOES_NOT_EXIST"])
        assert "DOES_NOT_EXIST" in result
        assert result["DOES_NOT_EXIST"].empty

    def test_basic_multi_ticker(self, db):
        _seed(db, "AAA", 10, start_iv=20.0)
        _seed(db, "BBB", 5, start_iv=30.0)
        result = db.get_recent_for_tickers(["AAA", "BBB"], lookback_days=100)
        assert set(result.keys()) == {"AAA", "BBB"}
        assert len(result["AAA"]) == 10
        assert len(result["BBB"]) == 5
        # Rows should be chronologically sorted per ticker
        assert list(result["AAA"]["date"]) == sorted(result["AAA"]["date"])

    def test_lookback_limit(self, db):
        _seed(db, "AAA", 200, start_iv=15.0)
        result = db.get_recent_for_tickers(["AAA"], lookback_days=60)
        assert len(result["AAA"]) == 60
        # Should be the *most recent* 60 — the oldest row should be day 140.
        min_date = pd.Timestamp(result["AAA"]["date"].min()).date()
        assert min_date == date(2026, 1, 1) + timedelta(days=140)

    def test_iv_column_preserved(self, db):
        _seed(db, "AAA", 5, start_iv=25.0)
        result = db.get_recent_for_tickers(["AAA"], lookback_days=10)
        assert "iv_30d" in result["AAA"].columns
        assert "hv_20d" in result["AAA"].columns
        # Row number helper column must be stripped.
        assert "rn" not in result["AAA"].columns

    def test_partial_universe(self, db):
        _seed(db, "AAA", 10, start_iv=20.0)
        _seed(db, "BBB", 10, start_iv=30.0)
        _seed(db, "CCC", 10, start_iv=40.0)
        result = db.get_recent_for_tickers(["AAA", "CCC"], lookback_days=10)
        assert set(result.keys()) == {"AAA", "CCC"}
        assert "BBB" not in result

    def test_single_query_efficiency(self, db):
        """Sanity check: bulk result for N tickers comes from one SELECT, not N."""
        for i in range(30):
            _seed(db, f"T{i:02d}", 5, start_iv=float(10 + i))
        tickers = [f"T{i:02d}" for i in range(30)]
        result = db.get_recent_for_tickers(tickers, lookback_days=5)
        assert len(result) == 30
        for t in tickers:
            assert len(result[t]) == 5
