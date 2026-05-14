"""Tests for volscope/risk/kill_switch.py."""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import pytest

from volscope.risk.kill_switch import (
    KillSwitch, KillSwitchState, check_daily_loss, check_disconnect,
    check_drawdown, check_term_inversion, check_vix,
)


@pytest.fixture
def sticky_path():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "KILL"


# ── Manual trip paths ────────────────────────────────────────────────


def test_initial_state_clear(sticky_path):
    ks = KillSwitch(sticky_path=sticky_path)
    tripped, _ = ks.is_tripped()
    assert not tripped


def test_file_trip(sticky_path):
    ks = KillSwitch(sticky_path=sticky_path)
    ks.trip("test reason")
    tripped, reason = ks.is_tripped()
    assert tripped
    assert "test reason" in reason


def test_env_trip(sticky_path, monkeypatch):
    monkeypatch.setenv("BOT_KILL_TEST", "1")
    ks = KillSwitch(sticky_path=sticky_path, env_var="BOT_KILL_TEST")
    tripped, reason = ks.is_tripped()
    assert tripped
    assert "BOT_KILL_TEST" in reason


def test_db_trip_via_callback(sticky_path):
    state = KillSwitchState(active=True, reason="db trip", tripped_at="now")
    ks = KillSwitch(sticky_path=sticky_path, db_check=lambda: state)
    tripped, reason = ks.is_tripped()
    assert tripped
    assert "db" in reason or "trip" in reason


# ── Reset ────────────────────────────────────────────────────────────


def test_reset_requires_literal_token(sticky_path):
    ks = KillSwitch(sticky_path=sticky_path)
    ks.trip("test")
    with pytest.raises(ValueError, match="literal"):
        ks.reset(human_confirmation="please")


def test_reset_with_correct_token_clears(sticky_path, monkeypatch):
    monkeypatch.setenv("BOT_KILL", "1")
    ks = KillSwitch(sticky_path=sticky_path)
    ks.trip("test")
    assert ks.is_tripped()[0]
    token = f"I-RESET-VOLSCOPE-{date.today():%Y%m%d}"
    ks.reset(human_confirmation=token)
    assert not sticky_path.exists()
    assert "BOT_KILL" not in os.environ


# ── Auto-check functions ────────────────────────────────────────────


def test_drawdown_below_threshold():
    trip, _ = check_drawdown(nlv_today=95_000, nlv_30d_peak=100_000)
    assert not trip


def test_drawdown_above_threshold():
    trip, reason = check_drawdown(nlv_today=75_000, nlv_30d_peak=100_000)
    assert trip
    assert "25" in reason or "20" in reason


def test_vix_check():
    assert not check_vix(20)[0]
    trip, reason = check_vix(45)
    assert trip
    assert "45" in reason


def test_daily_loss():
    assert not check_daily_loss(-0.01)[0]
    trip, _ = check_daily_loss(-0.05)
    assert trip


def test_disconnect():
    assert not check_disconnect(30)[0]
    assert check_disconnect(120)[0]


def test_term_inversion():
    assert not check_term_inversion(vix9d=18, vix=20)[0]   # contango
    trip, _ = check_term_inversion(vix9d=25, vix=20)        # backwardation
    assert trip


def test_term_inversion_handles_zero_vix():
    trip, _ = check_term_inversion(vix9d=20, vix=0)
    assert not trip   # gracefully ignored
