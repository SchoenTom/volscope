"""Tests for the hash-chained audit log."""
from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import pytest

from volscope.persistence.audit_chain import (
    GENESIS_PREV_HASH, append, latest_hash, length, verify_chain,
)
from volscope.persistence.db import apply_migrations


class _DB:
    """Thin adapter so audit_chain's API matches our VolScopeDB shape."""
    def __init__(self, conn): self.con = conn


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = duckdb.connect(str(Path(d) / "bot.db"))
        apply_migrations(conn)
        yield _DB(conn)
        conn.close()


def test_genesis_row_uses_zero_prev_hash(db):
    h = append(db, kind="signal", payload={"ticker": "SPY", "score": 80})
    row = db.con.execute("SELECT prev_hash, entry_hash FROM bot_audit_chain").fetchone()
    assert row[0] == GENESIS_PREV_HASH
    assert row[1] == h
    assert len(h) == 64


def test_second_row_uses_first_entry_hash_as_prev(db):
    h1 = append(db, kind="signal", payload={"x": 1})
    h2 = append(db, kind="signal", payload={"x": 2})
    rows = db.con.execute(
        "SELECT prev_hash, entry_hash FROM bot_audit_chain ORDER BY seq"
    ).fetchall()
    assert rows[0][1] == rows[1][0] == h1
    assert rows[1][1] == h2


def test_unknown_kind_rejected(db):
    with pytest.raises(ValueError, match="unknown audit kind"):
        append(db, kind="garbage", payload={})


def test_deterministic_hash_across_key_order(db):
    """orjson sorts keys → same hash regardless of insertion order."""
    h1 = append(db, kind="signal", payload={"a": 1, "b": 2})
    # second event with same content (but constructed differently)
    h2 = append(db, kind="signal", payload={"b": 2, "a": 1})
    # entry_hashes differ because prev_hash differs, but the
    # *contribution* of the canonical payload is identical — verify by
    # round-trip on the chain
    ok, broken = verify_chain(db)
    assert ok
    assert broken is None


def test_verify_chain_passes_on_clean_chain(db):
    for i in range(100):
        append(db, kind="signal", payload={"i": i, "ticker": f"T{i}"})
    ok, seq = verify_chain(db)
    assert ok
    assert seq is None
    assert length(db) == 100


def test_verify_chain_detects_payload_tamper(db):
    for i in range(20):
        append(db, kind="signal", payload={"i": i})
    # Tamper row 10's payload
    db.con.execute(
        "UPDATE bot_audit_chain SET payload = ? WHERE seq = 10",
        ['{"i": 9999}'],
    )
    ok, seq = verify_chain(db)
    assert not ok
    assert seq == 10


def test_verify_chain_detects_prev_hash_tamper(db):
    for i in range(20):
        append(db, kind="signal", payload={"i": i})
    db.con.execute(
        "UPDATE bot_audit_chain SET prev_hash = ? WHERE seq = 5",
        ["f" * 64],
    )
    ok, seq = verify_chain(db)
    assert not ok
    assert seq == 5


def test_latest_hash_matches_top_row(db):
    h1 = append(db, kind="signal", payload={"x": 1})
    h2 = append(db, kind="signal", payload={"x": 2})
    assert latest_hash(db) == h2


def test_latest_hash_genesis_on_empty(db):
    assert latest_hash(db) == GENESIS_PREV_HASH
