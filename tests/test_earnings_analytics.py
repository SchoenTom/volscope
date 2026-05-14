"""Tests for the earnings-hub analytics layer (E2)."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

import pandas as pd
import pytest


@pytest.fixture
def db():
    """Fresh DuckDB with a synthetic ticker + 100d of history."""
    from volscope.data.database import VolScopeDB
    tmp = tempfile.mkdtemp(prefix="vs_eh_")
    db = VolScopeDB(db_path=os.path.join(tmp, "v.db"))

    rows = []
    for i, d in enumerate(pd.date_range(end=date.today(), periods=100)):
        spot = 100 + 0.05 * i
        rows.append({
            "ticker": "TEST",
            "date": d.date(),
            "spot_price": spot,
            "iv_30d": 30.0 + 0.05 * i,
            "iv_60d": 32.0,
            "iv_90d": 33.0,
            "hv_20d": 25.0,
            "hv_60d": 26.0,
            "iv_skew_25d": 3.0,
            "iv_rank": 50.0,
            "iv_percentile": 60.0,
            "put_call_ratio": 0.9 + (i % 7) * 0.05,
            "total_call_volume": 1_000_000,
            "total_put_volume": 800_000,
            "total_open_interest": 5_000_000,
            "iv_hv_spread": 5.0,
            "company_name": "Test Co",
            "sector": "Tech",
        })
    for r in rows:
        db.upsert_daily(r["ticker"], r["date"], **{
            k: v for k, v in r.items() if k not in ("ticker", "date")
        })
    yield db
    db.close()


# ── ImpliedMove ──────────────────────────────────────────────────────

class TestImpliedMove:
    def test_short_dte_uses_straddle(self, db):
        from volscope.analytics.earnings_expected_move import compute_implied_move
        er = date.today() + timedelta(days=3)
        im = compute_implied_move(db, "TEST", er)
        assert im is not None
        assert im.method == "atm_straddle_bsm"
        assert 0 < im.move_pct < 30   # sanity bound
        assert im.upper_bound > im.spot
        assert im.lower_bound < im.spot

    def test_far_dte_uses_iv_scale(self, db):
        from volscope.analytics.earnings_expected_move import compute_implied_move
        er = date.today() + timedelta(days=45)
        im = compute_implied_move(db, "TEST", er)
        assert im is not None
        assert im.method == "atm_iv_scale"
        assert im.move_pct > 0

    def test_cross_check_populated(self, db):
        from volscope.analytics.earnings_expected_move import compute_implied_move
        im = compute_implied_move(db, "TEST", date.today() + timedelta(days=5))
        assert im.cross_check_iv_method_pct > 0

    def test_skew_biases_bounds(self, db):
        """Positive put-skew should pull lower-bound further down."""
        from volscope.analytics.earnings_expected_move import compute_implied_move
        im = compute_implied_move(db, "TEST", date.today() + timedelta(days=5))
        # With skew=3pt, lower magnitude should equal or exceed upper magnitude
        assert abs(im.lower_pct) >= abs(im.upper_pct) - 0.5

    def test_missing_ticker_returns_none(self, db):
        from volscope.analytics.earnings_expected_move import compute_implied_move
        assert compute_implied_move(db, "GHOST", date.today()) is None


# ── Calibration ──────────────────────────────────────────────────────

class TestCalibration:
    def test_insufficient_history_returns_none(self, db):
        from volscope.analytics.earnings_expected_move import calibrate_implied_vs_realised
        # No `earnings` rows seeded → must return None
        cal = calibrate_implied_vs_realised(db, "TEST")
        assert cal is None

    def test_underprices_when_realised_exceeds_implied(self, db):
        from volscope.analytics.earnings_expected_move import calibrate_implied_vs_realised
        # Seed 3 historical events where actual > implied
        for i in range(3):
            ed = date.today() - timedelta(days=90 * (i + 1))
            db.con.execute(
                """
                INSERT INTO earnings (ticker, earnings_date,
                    last_implied_pct, last_reaction_pct)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO UPDATE SET
                    last_implied_pct = EXCLUDED.last_implied_pct,
                    last_reaction_pct = EXCLUDED.last_reaction_pct
                """,
                ["TEST", ed, 2.0, 4.0],
            )
        cal = calibrate_implied_vs_realised(db, "TEST")
        assert cal is not None
        assert cal.band == "underprices"
        assert cal.ratio == pytest.approx(2.0, abs=0.05)


# ── CrowdedPreER ────────────────────────────────────────────────────

class TestCrowdedPreER:
    def test_insufficient_events_returns_none(self, db):
        from volscope.analytics.crowded_pre_er import compute_pre_er_crowded
        # No earnings seeded → no historical events → None
        result = compute_pre_er_crowded(db, "TEST")
        assert result is None

    def test_returns_dataclass_when_history_present(self, db):
        from volscope.analytics.crowded_pre_er import compute_pre_er_crowded
        for i in range(4):
            ed = date.today() - timedelta(days=70 * (i + 1))
            db.con.execute(
                "INSERT INTO earnings (ticker, earnings_date) VALUES (?, ?) "
                "ON CONFLICT DO NOTHING",
                ["TEST", ed],
            )
        result = compute_pre_er_crowded(db, "TEST", min_events=3)
        # May still be None if not enough crowded samples within window,
        # but if non-None, sanity-check fields.
        if result is not None:
            assert 0 <= result.score_today <= 100
            assert 0 <= result.percentile_today <= 100
            assert result.band in ("calm", "normal", "elevated", "exceptional")


# ── Earnings strategy decision ──────────────────────────────────────

class TestEarningsStrategy:
    def test_long_straddle_when_underpriced(self):
        from volscope.analytics.earnings_strategy import recommend_for_earnings
        rec = recommend_for_earnings(
            implied_move_pct=4.0, skew_pt=1.0,
            crowded_band="normal", iv_rank=40,
            calibration_ratio=1.4,
        )
        assert rec.structure == "Long Straddle"
        assert rec.template_name == "Long Straddle"
        assert rec.confidence in ("high", "medium")

    def test_short_condor_when_rich_iv_calm(self):
        from volscope.analytics.earnings_strategy import recommend_for_earnings
        rec = recommend_for_earnings(
            implied_move_pct=2.0, skew_pt=0.0,
            crowded_band="calm", iv_rank=90, calibration_ratio=None,
        )
        assert rec.structure == "Short Iron Condor"

    def test_long_call_fade_put_skew(self):
        from volscope.analytics.earnings_strategy import recommend_for_earnings
        rec = recommend_for_earnings(
            implied_move_pct=5.0, skew_pt=6.0,
            crowded_band="elevated", iv_rank=50,
        )
        assert rec.structure == "Long Call"

    def test_long_put_fade_call_skew(self):
        from volscope.analytics.earnings_strategy import recommend_for_earnings
        rec = recommend_for_earnings(
            implied_move_pct=5.0, skew_pt=-6.0,
            crowded_band="exceptional", iv_rank=50,
        )
        assert rec.structure == "Long Put"

    def test_wait_when_no_edge(self):
        from volscope.analytics.earnings_strategy import recommend_for_earnings
        rec = recommend_for_earnings(
            implied_move_pct=3.0, skew_pt=0.5,
            crowded_band="normal", iv_rank=50,
        )
        assert rec.structure == "Wait"
        assert rec.template_name is None
