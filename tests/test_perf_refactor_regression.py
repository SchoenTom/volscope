"""Regression locks for the recent performance refactors.

These tests pin behaviour that earlier rewrites optimised for speed, so a
future "clean-up" can't silently reintroduce the slow / wrong path:

1. ``VolScopeDB.get_all_latest`` — the QUALIFY ROW_NUMBER() single-scan
   rewrite must still return exactly one (latest) row per ticker.
2. ``alerts_scanner._bulk_days_to_earnings`` — the one-query bulk lookup
   that replaced 800+ per-ticker ``get_upcoming_earnings`` calls.
3. ``alerts_scanner.scan_alerts`` — end-to-end on a tiny seeded DB,
   incl. the ``allow_tickers`` watchlist filter.
4. ``risk_free`` — the "tried-today" fallback must NOT re-hit the network
   after a failed fetch day.
5. ``VolScopeDB`` — the composite ``idx_daily_vol_ticker_date`` index
   that every per-ticker query relies on must be created on open.

All DBs are temp files; no network; the operator's real DB is untouched.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

import volscope.data.risk_free as rf
from volscope.analytics.alerts_scanner import Alert, _bulk_days_to_earnings, scan_alerts
from volscope.config import RISK_FREE_RATE
from volscope.data.database import VolScopeDB


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    """A fresh, isolated temp DuckDB — never the operator's real DB."""
    conn = VolScopeDB(db_path=str(tmp_path / "regress.db"))
    try:
        yield conn
    finally:
        conn.close()


# ── 1. get_all_latest — QUALIFY ROW_NUMBER rewrite ────────────────────

def test_get_all_latest_one_latest_row_per_ticker(db):
    """2 tickers × 3 dates → exactly one row each = the latest date."""
    d0 = date(2026, 1, 1)
    for i in range(3):
        d = d0 + timedelta(days=i)
        # iv_30d encodes the day so we can assert the latest won.
        db.upsert_daily("AAA", d, iv_30d=10.0 + i, hv_20d=20.0)
        db.upsert_daily("BBB", d, iv_30d=30.0 + i, hv_20d=20.0)

    latest = db.get_all_latest()

    assert len(latest) == 2
    by_ticker = {r["ticker"]: r for _, r in latest.iterrows()}
    assert set(by_ticker) == {"AAA", "BBB"}
    # Latest date = d0 + 2 days for both, with the day-2 iv values.
    # (DuckDB hands the DATE back as a pandas Timestamp.)
    latest_day = d0 + timedelta(days=2)
    assert pd.Timestamp(by_ticker["AAA"]["date"]).date() == latest_day
    assert pd.Timestamp(by_ticker["BBB"]["date"]).date() == latest_day
    assert by_ticker["AAA"]["iv_30d"] == pytest.approx(12.0)
    assert by_ticker["BBB"]["iv_30d"] == pytest.approx(32.0)


# ── 2. _bulk_days_to_earnings — bulk single-query rewrite ─────────────

def test_bulk_days_to_earnings_future_past_and_negative(db):
    today = date.today()
    # AAA: a future print 5d out (and an older past one → future wins).
    db.upsert_earnings("AAA", today - timedelta(days=40))
    db.upsert_earnings("AAA", today + timedelta(days=5))
    # BBB: only a past print 3d ago → negative days, most-recent past.
    db.upsert_earnings("BBB", today - timedelta(days=30))
    db.upsert_earnings("BBB", today - timedelta(days=3))
    # CCC: not queried → must be absent from the result.
    db.upsert_earnings("CCC", today + timedelta(days=2))

    out = _bulk_days_to_earnings(db, ["AAA", "BBB"])

    assert out["AAA"] == 5            # future preferred
    assert out["BBB"] == -3           # most-recent past, negative
    assert "CCC" not in out           # not in the requested ticker list


def test_bulk_days_to_earnings_empty_tickers(db):
    assert _bulk_days_to_earnings(db, []) == {}


# ── 3. scan_alerts — end-to-end + allow_tickers filter ────────────────

def _seed_alertable(db):
    """Seed two tickers that each fire at least one rule today."""
    today = date.today()
    # AAA: IV percentile at a historic low (< 5) → ANOMALY.
    db.upsert_daily("AAA", today, iv_30d=25.0, hv_20d=22.0, iv_percentile=2.0)
    # BBB: IV/HV richly priced (ratio > 1.5) → ANOMALY.
    db.upsert_daily("BBB", today, iv_30d=40.0, hv_20d=20.0, iv_percentile=50.0)


def test_scan_alerts_runs_and_returns_alert_list(db):
    _seed_alertable(db)
    alerts = scan_alerts(db)
    assert isinstance(alerts, list)
    assert alerts and all(isinstance(a, Alert) for a in alerts)
    tickers = {a.ticker for a in alerts}
    assert "AAA" in tickers and "BBB" in tickers


def test_scan_alerts_allow_tickers_filter(db):
    _seed_alertable(db)
    only_aaa = scan_alerts(db, allow_tickers={"AAA"})
    assert only_aaa  # AAA still fires
    assert {a.ticker for a in only_aaa} == {"AAA"}


def test_scan_alerts_empty_db(db):
    assert scan_alerts(db) == []


# ── 4. risk_free — tried-today fallback skips the network ─────────────

def test_risk_free_tried_today_does_not_refetch(monkeypatch):
    rf.reset_cache()
    calls = {"n": 0}

    def _counting_fetch(series: str):
        calls["n"] += 1
        return None  # simulate a failed fetch day

    monkeypatch.setattr(rf, "_fetch_one", _counting_fetch)

    # First call: refresh attempts all 4 series, all fail → static rate.
    assert rf.get_rate(30) == RISK_FREE_RATE
    first = calls["n"]
    assert first > 0  # it did try the network once

    # Second call: tried==today short-circuit → no further network hits.
    assert rf.get_rate(30) == RISK_FREE_RATE
    assert calls["n"] == first

    rf.reset_cache()


# ── 5. database — composite index created on open ─────────────────────

def test_ticker_date_composite_index_created(db):
    names = {
        r[0]
        for r in db.con.execute(
            "SELECT index_name FROM duckdb_indexes()"
        ).fetchall()
    }
    assert "idx_daily_vol_ticker_date" in names
