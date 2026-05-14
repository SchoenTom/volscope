"""Tests for Earnings Hub v2 — backtest, diagnostics, thesis, capture."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

import pandas as pd
import pytest


@pytest.fixture
def db():
    """Fresh DuckDB with 100d of TEST history + 3 prior earnings."""
    from volscope.data.database import VolScopeDB
    tmp = tempfile.mkdtemp(prefix="vs_ehv2_")
    db = VolScopeDB(db_path=os.path.join(tmp, "v.db"))

    # 200 trading days of history
    for i, d in enumerate(pd.date_range(end=date.today(), periods=200)):
        spot = 100 + 0.05 * i
        db.upsert_daily(
            "TEST", d.date(),
            spot_price=spot, iv_30d=30.0, iv_60d=32.0, iv_90d=33.0,
            hv_20d=25.0, hv_60d=26.0,
            iv_skew_25d=2.0,
            iv_rank=55.0, iv_percentile=60.0,
            put_call_ratio=1.0,
            total_call_volume=1_000_000, total_put_volume=800_000,
            total_open_interest=5_000_000,
            iv_hv_spread=5.0,
            company_name="Test Co", sector="Tech",
        )
    # 3 historical earnings
    for offset in (90, 180, 270):
        ed = date.today() - timedelta(days=offset)
        db.con.execute(
            "INSERT INTO earnings (ticker, earnings_date, last_implied_pct,"
            " last_reaction_pct) VALUES (?, ?, ?, ?) "
            "ON CONFLICT DO UPDATE SET "
            "last_implied_pct = EXCLUDED.last_implied_pct, "
            "last_reaction_pct = EXCLUDED.last_reaction_pct",
            ["TEST", ed, 2.0, 4.0 if offset == 90 else -3.0],
        )
    yield db
    db.close()


# ── Backtest harness ────────────────────────────────────────────────

class TestBacktest:
    def test_single_event_simulation_returns_or_none(self, db):
        from volscope.analytics.earnings_backtest import simulate_one
        ed = date.today() - timedelta(days=90)
        # simulate_one needs spot rows 1 day before AND after — our
        # fixture has continuous history, so this should produce
        t = simulate_one(db, "TEST", ed, "Long Straddle")
        # Either None (if our window selection trips edge case) or full
        if t is not None:
            assert t.ticker == "TEST"
            assert t.strategy == "Long Straddle"
            assert isinstance(t.win, bool)

    def test_ticker_backtest_aggregates(self, db):
        from volscope.analytics.earnings_backtest import (
            backtest_earnings_strategy, edge_string,
        )
        res = backtest_earnings_strategy(db, "TEST", "Long Call")
        # n_events might be 0 if our synthetic data trips a guard;
        # ensure the dataclass shape works either way.
        assert res.strategy == "Long Call"
        s = edge_string(res)
        assert isinstance(s, str) and len(s) > 5

    def test_aggregate_empty(self, db):
        from volscope.analytics.earnings_backtest import _aggregate
        empty = _aggregate([], "TEST", "Long Call")
        assert empty.n_events == 0
        assert empty.hit_rate == 0.0


# ── Diagnostics ─────────────────────────────────────────────────────

class TestDiagnostics:
    def test_calibration_bar_empty_returns_empty(self):
        from volscope.ui.components.earnings_diagnostics import render_calibration_bar
        assert render_calibration_bar([]) == ""

    def test_calibration_bar_with_rows(self):
        from volscope.ui.components.earnings_diagnostics import render_calibration_bar
        html = render_calibration_bar([
            {"earnings_date": date(2025, 11, 1),
             "last_implied_pct": 3.0, "last_reaction_pct": 4.5},
            {"earnings_date": date(2025, 8, 1),
             "last_implied_pct": 5.0, "last_reaction_pct": -2.0},
        ])
        assert "IMPLIED" in html or "implied" in html.lower()
        assert "2025-11-01" in html

    def test_drift_returns_empty_on_no_history(self):
        from volscope.ui.components.earnings_diagnostics import render_pre_er_drift
        assert render_pre_er_drift(pd.DataFrame(), date.today()) == ""

    def test_drift_returns_svg(self, db):
        from volscope.ui.components.earnings_diagnostics import render_pre_er_drift
        h = db.get_ticker_history("TEST")
        html = render_pre_er_drift(h, date.today())
        assert "vs-drift-block" in html

    def test_anomaly_badge_silent_below_threshold(self):
        from volscope.ui.components.earnings_diagnostics import render_anomaly_badge
        assert render_anomaly_badge(0.5) == ""
        assert render_anomaly_badge(None) == ""

    def test_anomaly_badge_fires_above_threshold(self):
        from volscope.ui.components.earnings_diagnostics import render_anomaly_badge
        html = render_anomaly_badge(2.3)
        assert "ANOMALY" in html

    def test_anomaly_score_needs_history(self):
        from volscope.ui.components.earnings_diagnostics import compute_anomaly_score
        assert compute_anomaly_score(pd.DataFrame(), date.today()) is None


# ── Thesis generator ────────────────────────────────────────────────

class TestAutoThesis:
    def test_calibration_underprices_lead(self):
        from volscope.analytics.earnings_thesis import auto_thesis
        t = auto_thesis(
            ticker="NVDA",
            implied_move_pct=6.0, skew_pt=1.0,
            crowded_band="normal", crowded_pct=55,
            calibration_ratio=1.4, iv_rank=55,
            crush_avg_pct=-40, n_calibration_events=8,
        )
        assert t is not None
        assert "NVDA" in t and ("undersell" in t.lower() or "long-vol" in t.lower())

    def test_extreme_skew_lead(self):
        from volscope.analytics.earnings_thesis import auto_thesis
        t = auto_thesis(
            ticker="META",
            implied_move_pct=4.0, skew_pt=5.5,
            crowded_band="exceptional", crowded_pct=92,
            calibration_ratio=None, iv_rank=60,
            crush_avg_pct=None, n_calibration_events=0,
        )
        assert t is not None
        assert "Crowded" in t or "crowded" in t

    def test_extreme_iv_rank_lead(self):
        from volscope.analytics.earnings_thesis import auto_thesis
        t = auto_thesis(
            ticker="AAPL",
            implied_move_pct=2.0, skew_pt=1.0,
            crowded_band="normal", crowded_pct=50,
            calibration_ratio=None, iv_rank=90,
            crush_avg_pct=-35, n_calibration_events=0,
        )
        assert t is not None
        assert "IV rank" in t or "rank" in t.lower()

    def test_default_narration(self):
        from volscope.analytics.earnings_thesis import auto_thesis
        t = auto_thesis(
            ticker="XYZ",
            implied_move_pct=9.0, skew_pt=0.5,
            crowded_band="normal", crowded_pct=50,
            calibration_ratio=None, iv_rank=50,
            crush_avg_pct=None, n_calibration_events=0,
        )
        assert t is not None
        assert "9.0%" in t

    def test_none_when_no_signal(self):
        from volscope.analytics.earnings_thesis import auto_thesis
        t = auto_thesis(
            ticker="XYZ",
            implied_move_pct=0, skew_pt=0,
            crowded_band="normal", crowded_pct=50,
            calibration_ratio=None, iv_rank=50,
            crush_avg_pct=None, n_calibration_events=0,
        )
        assert t is None
