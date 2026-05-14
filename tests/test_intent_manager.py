"""Tests for the order-intent idempotency layer."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import duckdb
import pytest

from volscope.execution.intent_manager import (
    count_by_status, create_intent, get_intent, mark_acked,
    mark_rejected, mark_submitted, unacked_intents,
)
from volscope.persistence.db import apply_migrations


class _DB:
    def __init__(self, c): self.con = c


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = duckdb.connect(str(Path(d) / "bot.db"))
        apply_migrations(conn)
        yield _DB(conn)
        conn.close()


def _legs():
    return [
        {"side": "sell", "right": "C", "strike": 420, "expiry": "2026-06-19", "contracts": 1},
        {"side": "buy",  "right": "C", "strike": 425, "expiry": "2026-06-19", "contracts": 1},
    ]


def test_create_intent_returns_uuid(db):
    iid = create_intent(db, strategy="ic_45dte_v1", underlying="SPY",
                         direction="short_vol", intended_legs=_legs())
    assert len(iid) == 36                # uuid4 hex length


def test_create_intent_idempotent_on_same_uuid(db):
    iid = "test-uuid-123"
    iid1 = create_intent(db, intent_uuid=iid, strategy="x", underlying="SPY",
                          direction="short_vol", intended_legs=_legs())
    iid2 = create_intent(db, intent_uuid=iid, strategy="x", underlying="SPY",
                          direction="short_vol", intended_legs=_legs())
    assert iid1 == iid2 == iid
    rec = get_intent(db, iid)
    assert rec is not None


def test_mark_submitted_then_acked(db):
    iid = create_intent(db, strategy="ic", underlying="SPY",
                         direction="short_vol", intended_legs=_legs())
    mark_submitted(db, iid, order_ref="ic_0001", permid=12345)
    mark_acked(db, iid, permid=12345)
    rec = get_intent(db, iid)
    assert rec.status == "ACKED"
    assert rec.permid == 12345
    assert rec.order_ref == "ic_0001"
    assert rec.acked_at is not None


def test_mark_rejected(db):
    iid = create_intent(db, strategy="ic", underlying="SPY",
                         direction="short_vol", intended_legs=_legs())
    mark_rejected(db, iid, reason="risk check failed")
    rec = get_intent(db, iid)
    assert rec.status == "REJECTED"
    assert rec.reject_reason == "risk check failed"


def test_acked_terminal_not_overwritten(db):
    """A second mark_submitted on an ACKED intent must NOT regress status."""
    iid = create_intent(db, strategy="ic", underlying="SPY",
                         direction="short_vol", intended_legs=_legs())
    mark_submitted(db, iid, order_ref="ref1")
    mark_acked(db, iid)
    mark_submitted(db, iid, order_ref="ref2")     # should be no-op
    rec = get_intent(db, iid)
    assert rec.status == "ACKED"
    assert rec.order_ref == "ref1"                # original survives


def test_unacked_intents_filtered_by_age(db):
    """Old PENDING/SUBMITTED rows show up; new ones don't."""
    iid_old = create_intent(db, strategy="ic", underlying="SPY",
                             direction="short_vol", intended_legs=_legs())
    # Simulate an old intent by direct UPDATE — created_at in the past
    db.con.execute("""
        UPDATE bot_order_intents
        SET created_at = CURRENT_TIMESTAMP - INTERVAL 60 SECOND
        WHERE intent_uuid = ?
    """, [iid_old])
    iid_new = create_intent(db, strategy="ic", underlying="QQQ",
                             direction="short_vol", intended_legs=_legs())
    out = unacked_intents(db, older_than_seconds=30)
    assert iid_old in [r.intent_uuid for r in out]
    assert iid_new not in [r.intent_uuid for r in out]


def test_unacked_excludes_terminal_states(db):
    """ACKED + REJECTED rows are never in the unacked list."""
    iid_acked = create_intent(db, strategy="ic", underlying="SPY",
                                direction="short_vol", intended_legs=_legs())
    mark_acked(db, iid_acked)
    iid_rejected = create_intent(db, strategy="ic", underlying="QQQ",
                                   direction="short_vol", intended_legs=_legs())
    mark_rejected(db, iid_rejected, reason="test")
    # Age them so the filter would otherwise include them
    db.con.execute(
        "UPDATE bot_order_intents SET created_at = CURRENT_TIMESTAMP - INTERVAL 60 SECOND"
    )
    out = unacked_intents(db, older_than_seconds=30)
    seen = {r.intent_uuid for r in out}
    assert iid_acked not in seen
    assert iid_rejected not in seen


def test_count_by_status(db):
    for _ in range(3):
        create_intent(db, strategy="ic", underlying="SPY",
                       direction="short_vol", intended_legs=_legs())
    counts = count_by_status(db)
    assert counts.get("PENDING") == 3


def test_get_intent_missing_returns_none(db):
    assert get_intent(db, "no-such-uuid") is None
