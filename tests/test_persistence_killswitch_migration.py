"""Tests for migration 002 — bot_killswitch table."""
from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb

from volscope.persistence.db import apply_migrations


def test_002_creates_killswitch_table():
    with tempfile.TemporaryDirectory() as d:
        conn = duckdb.connect(str(Path(d) / "bot.db"))
        try:
            applied = apply_migrations(conn)
            assert "002_killswitch" in applied

            rows = conn.execute(
                "SELECT id, active FROM bot_killswitch"
            ).fetchall()
            assert rows == [(1, False)]
        finally:
            conn.close()


def test_002_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        conn = duckdb.connect(str(Path(d) / "bot.db"))
        try:
            applied1 = apply_migrations(conn)
            applied2 = apply_migrations(conn)
            assert set(applied1) >= {"001_init", "002_killswitch"}
            assert applied2 == []
        finally:
            conn.close()


def test_seed_row_only_once():
    with tempfile.TemporaryDirectory() as d:
        conn = duckdb.connect(str(Path(d) / "bot.db"))
        try:
            apply_migrations(conn)
            apply_migrations(conn)   # re-running should not duplicate seed
            count = conn.execute(
                "SELECT COUNT(*) FROM bot_killswitch"
            ).fetchone()[0]
            assert count == 1
        finally:
            conn.close()
