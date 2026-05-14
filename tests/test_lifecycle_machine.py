"""Tests for volscope/lifecycle/machine.py."""
from __future__ import annotations

import pytest

pytest.importorskip("transitions")

from volscope.lifecycle.machine import TradeLifecycle   # noqa: E402


def test_initial_state_is_signaled():
    audit_log: list[dict] = []
    life = TradeLifecycle("t1", audit_callback=audit_log.append)
    assert life.state == "SIGNALED"


def test_size_requires_risk_check_passed():
    audit_log: list[dict] = []
    life = TradeLifecycle("t1", audit_callback=audit_log.append)
    # without risk_check_passed → transition refused
    life.size(reason="no payload")
    assert life.state == "SIGNALED"          # still here
    # with the right flag → transitions
    life.size(reason="passed", payload={"risk_check_passed": True})
    assert life.state == "SIZED"
    assert audit_log[-1]["to_state"] == "SIZED"
    assert audit_log[-1]["from_state"] == "SIGNALED"


def test_submit_requires_order_ref():
    audit_log: list[dict] = []
    life = TradeLifecycle("t1", audit_callback=audit_log.append)
    life.size(reason="risk ok", payload={"risk_check_passed": True})
    life.submit(reason="no ref")
    assert life.state == "SIZED"             # blocked
    life.submit(reason="ref ok", payload={"order_ref": "ic_0001"})
    assert life.state == "SUBMITTED"


def test_full_happy_path():
    audit_log: list[dict] = []
    life = TradeLifecycle("t1", audit_callback=audit_log.append)
    life.size(reason="ok", payload={"risk_check_passed": True})
    life.submit(reason="ok", payload={"order_ref": "x"})
    life.fill(reason="filled")
    life.manage(reason="now managed")
    life.begin_close(reason="50% PT")
    life.complete(reason="closed")
    assert life.state == "CLOSED"
    assert life.is_terminal
    # 6 transitions = 6 audit rows (initial state is NOT an event)
    assert len(audit_log) == 6


def test_abandon_from_any_state():
    audit_log: list[dict] = []
    life = TradeLifecycle("t1", audit_callback=audit_log.append)
    life.size(reason="ok", payload={"risk_check_passed": True})
    life.abandon(reason="manual_override")
    assert life.state == "ABANDONED"
    assert life.is_terminal


def test_audit_callback_receives_required_fields():
    audit_log: list[dict] = []
    life = TradeLifecycle("t1", audit_callback=audit_log.append)
    life.size(reason="r", payload={"risk_check_passed": True})
    row = audit_log[-1]
    for key in ("trade_id", "from_state", "to_state", "ts", "reason", "payload"):
        assert key in row
    assert row["trade_id"] == "t1"
