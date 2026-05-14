"""Tests for the bot_chain_snapshots migration (003) + chain_quote module."""
from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pytest

from volscope.data.chain_quote import (
    Quote, SlippageModel, apply_slippage, get_quote,
)
from volscope.persistence.db import apply_migrations


@pytest.fixture
def chain_db():
    """A DuckDB with migrations applied + a synthetic chain snapshot."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "bot.db"
        conn = duckdb.connect(str(path))
        apply_migrations(conn)
        snap_ts = datetime(2026, 5, 14, 16, 0, tzinfo=timezone.utc)
        expiry = date(2026, 6, 19)
        # Insert 5 strikes for SPY calls + puts
        rows = []
        for strike in [400, 405, 410, 415, 420]:
            for right in ["C", "P"]:
                mid = 5.0 if right == "C" else 3.0
                rows.append((
                    "SPY", snap_ts, expiry, strike, right,
                    mid - 0.10, mid + 0.10, mid, mid, 0.20,
                    None, None, None, None, 1000, 5000, 410.0,
                ))
        # Make a tiny shim object that paper_engine can call .con.execute on
        for r in rows:
            conn.execute("""
                INSERT INTO bot_chain_snapshots
                (ticker, snapshot_ts, expiry, strike, option_right,
                 bid, ask, mid, last_price, iv,
                 delta, gamma, theta, vega, volume, open_interest, underlying_px)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, r)

        class _DB:
            def __init__(self, c): self.con = c
        try:
            yield _DB(conn)
        finally:
            conn.close()


def test_migration_creates_chain_table(chain_db):
    rows = chain_db.con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='bot_chain_snapshots'"
    ).fetchone()
    assert rows[0] == 1


def test_view_bot_chain_latest_works(chain_db):
    rows = chain_db.con.execute(
        "SELECT COUNT(*) FROM bot_chain_latest WHERE ticker='SPY'"
    ).fetchone()
    assert rows[0] == 10                  # 5 strikes × 2 rights


def test_get_quote_exact_strike(chain_db):
    q = get_quote(chain_db, ticker="SPY", strike=410, expiry=date(2026, 6, 19),
                   right="C")
    assert q is not None
    assert q.strike == 410
    assert q.right == "C"
    assert q.mid == 5.0


def test_get_quote_falls_back_to_closest_strike(chain_db):
    """Target 411 should match the 410 strike (within 5% tolerance)."""
    q = get_quote(chain_db, ticker="SPY", strike=411, expiry=date(2026, 6, 19),
                   right="C")
    assert q is not None
    assert q.strike == 410        # closest in-band


def test_get_quote_rejects_out_of_tolerance(chain_db):
    """Target 500 → far outside 5% band of available 400-420 → None."""
    q = get_quote(chain_db, ticker="SPY", strike=500, expiry=date(2026, 6, 19),
                   right="C")
    assert q is None


def test_apply_slippage_buy_pays_more(chain_db):
    q = get_quote(chain_db, ticker="SPY", strike=410, expiry=date(2026, 6, 19),
                   right="C")
    model = SlippageModel()
    buy_px = apply_slippage(q, side="buy", model=model, dte=30, is_index=True)
    sell_px = apply_slippage(q, side="sell", model=model, dte=30, is_index=True)
    assert buy_px > q.mid > sell_px


def test_apply_slippage_short_dte_heavier(chain_db):
    q = get_quote(chain_db, ticker="SPY", strike=410, expiry=date(2026, 6, 19),
                   right="C")
    model = SlippageModel()
    long_buy = apply_slippage(q, side="buy", model=model, dte=30, is_index=True)
    short_buy = apply_slippage(q, side="buy", model=model, dte=0, is_index=True)
    assert short_buy >= long_buy
