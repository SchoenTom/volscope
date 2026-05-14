"""Tests for the earnings IV crush estimator."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from volscope.analytics.earnings_crush import (
    CrushEstimate,
    _find_nearest_iv,
    compute_crush_estimate,
    crush_badge_html,
)


# ---------------------------------------------------------------------------
# _find_nearest_iv
# ---------------------------------------------------------------------------

def _make_history(dates_ivs: list[tuple[datetime.date, float]]) -> pd.DataFrame:
    rows = [{"date": d, "iv_30d": iv} for d, iv in dates_ivs]
    return pd.DataFrame(rows)


class TestFindNearestIV:
    def test_exact_match(self):
        h = _make_history([(datetime.date(2026, 1, 15), 25.0)])
        result = _find_nearest_iv(h, datetime.date(2026, 1, 15))
        assert result == pytest.approx(25.0)

    def test_nearby_within_window(self):
        h = _make_history([(datetime.date(2026, 1, 13), 22.0)])
        result = _find_nearest_iv(h, datetime.date(2026, 1, 15), window=5)
        assert result == pytest.approx(22.0)

    def test_outside_window_returns_none(self):
        h = _make_history([(datetime.date(2026, 1, 1), 22.0)])
        result = _find_nearest_iv(h, datetime.date(2026, 2, 15), window=3)
        assert result is None

    def test_empty_history_returns_none(self):
        assert _find_nearest_iv(pd.DataFrame(), datetime.date(2026, 1, 15)) is None

    def test_picks_closest_of_two(self):
        h = _make_history([
            (datetime.date(2026, 1, 10), 20.0),
            (datetime.date(2026, 1, 14), 30.0),
        ])
        result = _find_nearest_iv(h, datetime.date(2026, 1, 15), window=10)
        assert result == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# compute_crush_estimate
# ---------------------------------------------------------------------------

def _make_db_mock(history_df: pd.DataFrame, earnings_dates: list[datetime.date]):
    """Return a minimal mock of VolScopeDB for crush estimation."""
    db = MagicMock()
    db.get_ticker_history.return_value = history_df

    earnings_rows = [{"ticker": "TEST", "earnings_date": d} for d in earnings_dates]
    er_df = pd.DataFrame(earnings_rows) if earnings_rows else pd.DataFrame(
        columns=["ticker", "earnings_date"]
    )
    db.con.execute.return_value.fetchdf.return_value = er_df
    return db


def _build_history_with_iv_around_dates(
    earnings_dates: list[datetime.date],
    iv_pre: float = 30.0,
    iv_post: float = 20.0,
) -> pd.DataFrame:
    """Build synthetic history with known pre/post IV around each earnings date."""
    rows = []
    for er_date in earnings_dates:
        pre_date  = er_date - datetime.timedelta(days=5)
        post_date = er_date + datetime.timedelta(days=2)
        rows.append({"date": pre_date,  "iv_30d": iv_pre})
        rows.append({"date": post_date, "iv_30d": iv_post})
    return pd.DataFrame(rows)


class TestComputeCrushEstimate:
    def test_no_earnings_returns_zero_events(self):
        db = _make_db_mock(pd.DataFrame(), earnings_dates=[])
        est = compute_crush_estimate(db, "TEST")
        assert est.n_events == 0
        assert est.avg_crush_pct is None

    def test_single_past_event_computes_crush(self):
        past_date = datetime.date.today() - datetime.timedelta(days=60)
        history = _build_history_with_iv_around_dates([past_date], iv_pre=30.0, iv_post=20.0)
        db = _make_db_mock(history, [past_date])
        est = compute_crush_estimate(db, "TEST")
        assert est.n_events == 1
        assert est.avg_crush_pct is not None
        # crush = (20 - 30) / 30 * 100 = -33.3%
        assert est.avg_crush_pct == pytest.approx(-33.3, abs=0.5)

    def test_multiple_events_averages_correctly(self):
        today = datetime.date.today()
        dates = [today - datetime.timedelta(days=d) for d in [60, 120, 180, 240]]
        history = _build_history_with_iv_around_dates(dates, iv_pre=40.0, iv_post=25.0)
        db = _make_db_mock(history, dates)
        est = compute_crush_estimate(db, "TEST")
        assert est.n_events == 4
        expected_crush = (25.0 - 40.0) / 40.0 * 100  # -37.5
        assert est.avg_crush_pct == pytest.approx(expected_crush, abs=1.0)

    def test_next_earnings_date_detected(self):
        today = datetime.date.today()
        future_date = today + datetime.timedelta(days=10)
        db = _make_db_mock(pd.DataFrame(), [future_date])
        est = compute_crush_estimate(db, "TEST")
        assert est.next_earnings_date == future_date
        assert est.days_to_earnings == 10

    def test_past_earnings_not_counted_as_upcoming(self):
        past = datetime.date.today() - datetime.timedelta(days=5)
        db = _make_db_mock(pd.DataFrame(), [past])
        est = compute_crush_estimate(db, "TEST")
        assert est.next_earnings_date is None

    def test_min_max_crush_computed(self):
        today = datetime.date.today()
        # Two events with different crush magnitudes
        dates = [today - datetime.timedelta(days=d) for d in [60, 120]]
        rows = []
        for i, er_date in enumerate(dates):
            pre_date  = er_date - datetime.timedelta(days=5)
            post_date = er_date + datetime.timedelta(days=2)
            iv_pre  = 30.0
            iv_post = 20.0 - i * 5  # 20.0 and 15.0
            rows.append({"date": pre_date, "iv_30d": iv_pre})
            rows.append({"date": post_date, "iv_30d": iv_post})
        history = pd.DataFrame(rows)
        db = _make_db_mock(history, dates)
        est = compute_crush_estimate(db, "TEST")
        assert est.min_crush_pct is not None
        assert est.max_crush_pct is not None
        assert est.min_crush_pct <= est.max_crush_pct

    def test_db_exception_returns_zero_estimate(self):
        db = MagicMock()
        db.get_ticker_history.side_effect = Exception("db error")
        est = compute_crush_estimate(db, "TEST")
        assert est.n_events == 0


# ---------------------------------------------------------------------------
# crush_badge_html
# ---------------------------------------------------------------------------

class TestCrushBadgeHtml:
    def test_no_upcoming_returns_empty(self):
        est = CrushEstimate(None, None, None, 0, None, None)
        assert crush_badge_html(est) == ""

    def test_past_earnings_returns_empty(self):
        est = CrushEstimate(-30.0, -40.0, -20.0, 2,
                            datetime.date.today() - datetime.timedelta(days=1), -1)
        assert crush_badge_html(est) == ""

    def test_upcoming_shows_er_badge(self):
        est = CrushEstimate(-30.0, -40.0, -20.0, 2,
                            datetime.date.today() + datetime.timedelta(days=5), 5)
        html = crush_badge_html(est)
        assert "ER" in html
        assert "5d" in html

    def test_today_shows_er_today(self):
        est = CrushEstimate(-28.0, -35.0, -20.0, 1,
                            datetime.date.today(), 0)
        html = crush_badge_html(est)
        assert "today" in html.lower()

    def test_crush_avg_shown_in_badge(self):
        est = CrushEstimate(-35.0, -45.0, -25.0, 3,
                            datetime.date.today() + datetime.timedelta(days=3), 3)
        html = crush_badge_html(est)
        assert "-35" in html or "−35" in html or "35" in html

    def test_badge_contains_amber_color(self):
        est = CrushEstimate(-30.0, -40.0, -20.0, 2,
                            datetime.date.today() + datetime.timedelta(days=5), 5)
        html = crush_badge_html(est)
        assert "#ff9f43" in html

    def test_no_crush_history_still_shows_er_date(self):
        est = CrushEstimate(None, None, None, 0,
                            datetime.date.today() + datetime.timedelta(days=7), 7)
        html = crush_badge_html(est)
        assert "ER" in html
        assert "7d" in html
