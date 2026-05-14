"""Tests for analytics.daily_delta."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.daily_delta import (
    DailyDelta,
    compute_daily_delta,
    rank_daily_deltas,
)


def _hist(*ivs, percs=None) -> pd.DataFrame:
    n = len(ivs)
    base_date = date(2026, 5, 1)
    return pd.DataFrame({
        "date": [base_date + timedelta(days=i) for i in range(n)],
        "iv_30d": list(ivs),
        "iv_percentile": list(percs) if percs else [50.0] * n,
    })


# ──────────────────────────────────────────────────────────────────────────
# compute_daily_delta
# ──────────────────────────────────────────────────────────────────────────

class TestComputeDailyDelta:
    def test_basic(self):
        d = compute_daily_delta("X", _hist(20.0, 22.0))
        assert d is not None
        assert d.iv_today == 22.0
        assert d.iv_yesterday == 20.0
        assert d.iv_change == 2.0

    def test_negative_change(self):
        d = compute_daily_delta("X", _hist(25.0, 20.0))
        assert d.iv_change == -5.0

    def test_too_short_returns_none(self):
        assert compute_daily_delta("X", _hist(20.0)) is None

    def test_empty_returns_none(self):
        assert compute_daily_delta("X", pd.DataFrame()) is None

    def test_none_returns_none(self):
        assert compute_daily_delta("X", None) is None

    def test_nan_iv_handled(self):
        d = compute_daily_delta("X", _hist(20.0, float("nan")))
        # If today is NaN, iv_change unreachable → None
        assert d is not None
        assert d.iv_change is None

    def test_uses_last_two_rows(self):
        # Only the latest 2 rows matter
        d = compute_daily_delta("X", _hist(10.0, 11.0, 12.0, 22.0, 25.0))
        assert d.iv_change == 3.0  # 25 - 22


# ──────────────────────────────────────────────────────────────────────────
# Color + headline
# ──────────────────────────────────────────────────────────────────────────

class TestColorAndHeadline:
    def test_big_up_move_red(self):
        d = compute_daily_delta("X", _hist(20.0, 26.0))
        # +6pt is big move up → red
        assert d.color == "#ff4466"
        assert "spike" in d.headline.lower()

    def test_big_down_move_green(self):
        d = compute_daily_delta("X", _hist(30.0, 24.0))
        # -6pt big move down → green
        assert d.color == "#00d4aa"
        assert "crush" in d.headline.lower()

    def test_notable_up_move_amber(self):
        d = compute_daily_delta("X", _hist(20.0, 23.0))
        # +3pt notable but not big → amber
        assert d.color == "#ff9f43"

    def test_quiet_move_muted(self):
        d = compute_daily_delta("X", _hist(20.0, 20.5))
        assert d.color == "#8a8f9e"


# ──────────────────────────────────────────────────────────────────────────
# Rank
# ──────────────────────────────────────────────────────────────────────────

class TestRankDailyDeltas:
    def test_returns_top_n_by_abs_change(self):
        h = {
            "A": _hist(20, 22),   # +2
            "B": _hist(20, 30),   # +10
            "C": _hist(20, 19),   # -1
            "D": _hist(20, 14),   # -6
        }
        ranked = rank_daily_deltas(h, n=2)
        assert len(ranked) == 2
        # B (10) and D (6) must be top
        tickers = {d.ticker for d in ranked}
        assert tickers == {"B", "D"}

    def test_skips_short_history(self):
        h = {"A": _hist(20), "B": _hist(20, 25)}  # A has 1 row
        ranked = rank_daily_deltas(h)
        assert len(ranked) == 1
        assert ranked[0].ticker == "B"

    def test_empty_returns_empty(self):
        assert rank_daily_deltas({}) == []


# ──────────────────────────────────────────────────────────────────────────
# Frozen
# ──────────────────────────────────────────────────────────────────────────

class TestFrozen:
    def test_frozen(self):
        d = compute_daily_delta("X", _hist(20, 22))
        with pytest.raises(Exception):
            d.iv_change = 0  # type: ignore[misc]
