"""Tests for the bot's DuckDB schema migrations."""
from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import pytest

from volscope.persistence.db import _split_statements, apply_migrations


def test_split_statements_basic():
    sql = "CREATE TABLE a (x INT); INSERT INTO a VALUES (1);"
    parts = _split_statements(sql)
    assert len(parts) == 2
    assert "CREATE TABLE a" in parts[0]
    assert "INSERT" in parts[1]


def test_split_statements_ignores_semicolons_in_strings():
    sql = "SELECT 'a;b;c' AS x; SELECT 1;"
    parts = _split_statements(sql)
    assert len(parts) == 2


def test_apply_migrations_creates_all_bot_tables(tmp_path: Path):
    conn = duckdb.connect(str(tmp_path / "bot.db"))
    try:
        applied = apply_migrations(conn)
        assert "001_init" in applied

        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name LIKE 'bot_%' ORDER BY table_name"
        ).fetchall()
        names = {r[0] for r in rows}
        expected = {"bot_trades", "bot_legs", "bot_pnl_daily",
                    "bot_signals_log", "bot_orders_log", "bot_migrations"}
        assert expected.issubset(names), f"missing: {expected - names}"
    finally:
        conn.close()


def test_apply_migrations_is_idempotent(tmp_path: Path):
    conn = duckdb.connect(str(tmp_path / "bot.db"))
    try:
        first = apply_migrations(conn)
        second = apply_migrations(conn)
        assert "001_init" in first
        assert second == []          # no migrations re-applied on second run
    finally:
        conn.close()


def test_signal_log_insert_roundtrip(tmp_path: Path):
    """Smoke: can we INSERT and read back a signals_log row?"""
    conn = duckdb.connect(str(tmp_path / "bot.db"))
    try:
        apply_migrations(conn)
        conn.execute("""
            INSERT INTO bot_signals_log
            (signal_id, snapshot_date, underlying, direction,
             composite_score, factors_json, gates_json, decision)
            VALUES ('s1', '2026-05-14', 'SPY', 'short_vol',
                    82.5, '{"ivr":70}', '[]', 'EXECUTE')
        """)
        row = conn.execute(
            "SELECT signal_id, underlying, decision FROM bot_signals_log"
        ).fetchone()
        assert row == ("s1", "SPY", "EXECUTE")
    finally:
        conn.close()
