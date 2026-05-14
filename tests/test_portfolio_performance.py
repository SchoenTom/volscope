"""Tests for portfolio_performance.compute_portfolio_performance."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.portfolio_performance import (
    PerformanceResult,
    compute_portfolio_performance,
)


def _hist(start: date, days: int, spot_start: float, iv: float = 25.0) -> pd.DataFrame:
    dates = [start + timedelta(days=i) for i in range(days)]
    spots = [spot_start * (1 + 0.005 * i) for i in range(days)]   # +0.5%/day
    return pd.DataFrame({
        "date": dates,
        "spot_price": spots,
        "iv_30d": [iv] * days,
    })


def _positions(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestEmptyPositions:
    def test_no_positions_returns_empty(self):
        result = compute_portfolio_performance(pd.DataFrame(), {})
        assert isinstance(result, PerformanceResult)
        assert result.equity_curve.empty
        assert result.contributions == []
        assert result.total_invested == 0.0
        assert result.n_positions == 0


class TestSinglePosition:
    def test_single_call_replays(self):
        entry = date.today() - timedelta(days=10)
        positions = _positions([{
            "id": 1, "ticker": "TEST", "entry_date": entry,
            "expiry": entry + timedelta(days=180),
            "strike": 100.0, "option_type": "call", "contracts": 1,
            "entry_premium": 5.0,
        }])
        history = {"TEST": _hist(entry, 11, spot_start=100.0)}
        result = compute_portfolio_performance(positions, history)
        assert not result.equity_curve.empty
        assert result.n_positions == 1
        assert result.total_invested == 500.0  # 5 × 1 × 100
        # With spot rising +0.5%/day for 10 days, a 100C should appreciate
        assert result.total_pl > 0
        assert result.contributions[0].ticker == "TEST"

    def test_missing_history_skips_position(self):
        entry = date.today() - timedelta(days=10)
        positions = _positions([{
            "id": 1, "ticker": "TEST", "entry_date": entry,
            "expiry": entry + timedelta(days=60),
            "strike": 100.0, "option_type": "call", "contracts": 1,
            "entry_premium": 5.0,
        }])
        # Empty history → position skipped, but invested still tracked
        result = compute_portfolio_performance(positions, {"TEST": pd.DataFrame()})
        assert result.equity_curve.empty
        assert result.total_invested == 500.0


class TestMultiplePositions:
    def test_aggregates_across_positions(self):
        entry = date.today() - timedelta(days=15)
        positions = _positions([
            {"id": 1, "ticker": "AAA", "entry_date": entry,
             "expiry": entry + timedelta(days=120),
             "strike": 100.0, "option_type": "call", "contracts": 1,
             "entry_premium": 5.0},
            {"id": 2, "ticker": "BBB", "entry_date": entry,
             "expiry": entry + timedelta(days=120),
             "strike": 50.0, "option_type": "call", "contracts": 2,
             "entry_premium": 3.0},
        ])
        history = {
            "AAA": _hist(entry, 16, spot_start=100.0),
            "BBB": _hist(entry, 16, spot_start=50.0),
        }
        result = compute_portfolio_performance(positions, history)
        assert result.n_positions == 2
        # 1×5×100 + 2×3×100 = 1100
        assert result.total_invested == pytest.approx(1100.0)
        assert len(result.contributions) == 2

    def test_contribution_sorted_by_pl(self):
        entry = date.today() - timedelta(days=20)
        positions = _positions([
            {"id": 1, "ticker": "AAA", "entry_date": entry,
             "expiry": entry + timedelta(days=180),
             "strike": 100.0, "option_type": "call", "contracts": 1,
             "entry_premium": 5.0},
            {"id": 2, "ticker": "BBB", "entry_date": entry,
             "expiry": entry + timedelta(days=180),
             "strike": 100.0, "option_type": "put", "contracts": 1,
             "entry_premium": 5.0},
        ])
        # AAA spot rising → call wins. BBB spot rising → put loses.
        history = {
            "AAA": _hist(entry, 21, spot_start=100.0),
            "BBB": _hist(entry, 21, spot_start=100.0),
        }
        result = compute_portfolio_performance(positions, history)
        assert result.contributions[0].pl_total >= result.contributions[1].pl_total


class TestSharpeAndDrawdown:
    def test_sharpe_computed_when_data_sufficient(self):
        entry = date.today() - timedelta(days=30)
        positions = _positions([{
            "id": 1, "ticker": "TEST", "entry_date": entry,
            "expiry": entry + timedelta(days=180),
            "strike": 100.0, "option_type": "call", "contracts": 1,
            "entry_premium": 5.0,
        }])
        history = {"TEST": _hist(entry, 31, spot_start=100.0)}
        result = compute_portfolio_performance(positions, history)
        # Smooth daily appreciation → defined Sharpe
        assert result.sharpe_252d is not None

    def test_drawdown_zero_for_monotone_curve(self):
        entry = date.today() - timedelta(days=10)
        positions = _positions([{
            "id": 1, "ticker": "TEST", "entry_date": entry,
            "expiry": entry + timedelta(days=180),
            "strike": 80.0, "option_type": "call", "contracts": 1,
            "entry_premium": 5.0,
        }])
        history = {"TEST": _hist(entry, 11, spot_start=100.0)}
        result = compute_portfolio_performance(positions, history)
        # Monotone-rising spot for an ITM call → drawdown ~0
        assert result.max_drawdown_pct is not None
        assert result.max_drawdown_pct >= -1.0  # within rounding


class TestDateCoercion:
    def test_timestamp_entry_date_handled(self):
        entry_ts = pd.Timestamp(date.today() - timedelta(days=10))
        positions = _positions([{
            "id": 1, "ticker": "TEST", "entry_date": entry_ts,
            "expiry": entry_ts + pd.Timedelta(days=180),
            "strike": 100.0, "option_type": "call", "contracts": 1,
            "entry_premium": 5.0,
        }])
        history = {"TEST": _hist(date.today() - timedelta(days=10), 11, 100.0)}
        # Must not raise the Timestamp - date TypeError
        result = compute_portfolio_performance(positions, history)
        assert result.n_positions == 1
