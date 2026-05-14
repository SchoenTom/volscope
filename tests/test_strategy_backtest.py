"""Tests for analytics.strategy_backtest — simulation engine."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.strategy_backtest import (
    StrategyStats,
    TradeOutcome,
    aggregate_per_ticker,
    aggregate_stats,
    aggregate_universe,
    by_strategy,
    by_strategy_ticker,
    calibration_for_kelly,
    simulate_ticker,
    simulate_universe,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _hist_with_signal(
    n: int = 250,
    start_iv: float = 30.0,
    end_iv: float = 18.0,
    start_perc: float = 90.0,
    end_perc: float = 15.0,
) -> pd.DataFrame:
    """Build synthetic vol history with a clean trend so signals fire."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    iv30 = np.linspace(start_iv, end_iv, n)
    iv60 = iv30 + 1.0
    perc = np.linspace(start_perc, end_perc, n)
    skew = np.full(n, 0.0)
    return pd.DataFrame({
        "date": dates,
        "iv_30d": iv30,
        "iv_60d": iv60,
        "iv_percentile": perc,
        "iv_skew_25d": skew,
    })


# ──────────────────────────────────────────────────────────────────────────
# simulate_ticker — basic contract
# ──────────────────────────────────────────────────────────────────────────

class TestSimulateTicker:
    def test_returns_list(self):
        hist = _hist_with_signal()
        trades = simulate_ticker("X", hist)
        assert isinstance(trades, list)

    def test_each_is_trade_outcome(self):
        hist = _hist_with_signal()
        trades = simulate_ticker("X", hist)
        if trades:
            assert all(isinstance(t, TradeOutcome) for t in trades)

    def test_empty_history(self):
        assert simulate_ticker("X", pd.DataFrame()) == []
        assert simulate_ticker("X", None) == []

    def test_history_missing_iv_returns_empty(self):
        df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")]})
        assert simulate_ticker("X", df) == []

    def test_hold_days_param_changes_exit_horizon(self):
        # Build an oscillating IV that's always at perc=10 to force buy signals
        n = 200
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "iv_30d":        20.0 + np.sin(np.arange(n) / 6) * 5,
            "iv_60d":        21.0 + np.sin(np.arange(n) / 6) * 5,
            "iv_percentile": np.full(n, 10.0),
            "iv_skew_25d":   np.full(n, 0.0),
        })
        trades_short = simulate_ticker("X", df, hold_days=10)
        trades_long  = simulate_ticker("X", df, hold_days=60)
        assert trades_short and trades_long
        # Short hold should produce different exit dates than long hold
        first_short = trades_short[0]
        first_long  = trades_long[0]
        delta_short = (pd.Timestamp(first_short.exit_date) - pd.Timestamp(first_short.entry_date)).days
        delta_long  = (pd.Timestamp(first_long.exit_date) - pd.Timestamp(first_long.entry_date)).days
        assert delta_long > delta_short

    def test_default_hold_days_uses_direction_table(self):
        # When hold_days=None, each direction gets its own default
        # (long_vol=45, short_vol=30, neutral_vol=30)
        n = 200
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "iv_30d":        np.full(n, 20.0),
            "iv_60d":        np.full(n, 21.0),
            "iv_percentile": np.full(n, 10.0),  # cheap → long_vol signals
            "iv_skew_25d":   np.full(n, 0.0),
        })
        trades = simulate_ticker("X", df)
        # Default for long_vol is 45 trading days
        for t in trades[:5]:
            delta = (pd.Timestamp(t.exit_date) - pd.Timestamp(t.entry_date)).days
            # Calendar days for 45 trading days ≈ 63
            assert 50 <= delta <= 80

    def test_signals_fire_when_percentile_low(self):
        # Force percentile = 10 throughout — should generate cheap-vol signals
        n = 200
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "iv_30d": np.full(n, 18.0),
            "iv_60d": np.full(n, 19.0),
            "iv_percentile": np.full(n, 10.0),
            "iv_skew_25d": np.full(n, 0.0),
        })
        trades = simulate_ticker("X", df)
        assert len(trades) > 0

    def test_long_vol_pnl_signs_correct_with_rising_iv(self):
        # IV rises monotonically 15 → 30 → long vol should profit
        n = 150
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "iv_30d": np.linspace(15.0, 30.0, n),
            "iv_60d": np.linspace(16.0, 31.0, n),
            "iv_percentile": np.linspace(10.0, 50.0, n),
            "iv_skew_25d": np.full(n, 0.0),
        })
        trades = simulate_ticker("X", df)
        long_vol_trades = [t for t in trades if t.direction == "long_vol"]
        if long_vol_trades:
            wins = [t for t in long_vol_trades if t.is_win]
            # majority should win when IV is rising into low-perc signals
            assert len(wins) >= len(long_vol_trades) // 2


# ──────────────────────────────────────────────────────────────────────────
# Aggregation
# ──────────────────────────────────────────────────────────────────────────

class TestAggregation:
    def test_empty_returns_zero_stats(self):
        s = aggregate_stats([], strategy="X")
        assert s.n_trades == 0
        assert s.hit_rate == 0.0

    def test_single_winner(self):
        t = TradeOutcome("A", "S", "long_vol", "2024-01-01", "2024-02-01",
                         entry_iv=20, exit_iv=25, iv_change=5, pnl_pct=0.25, is_win=True)
        s = aggregate_stats([t], strategy="S")
        assert s.hit_rate == 1.0
        assert s.avg_win_pct == 0.25
        assert s.avg_loss_pct == 0.0

    def test_mixed_outcomes(self):
        wins = [TradeOutcome("A", "S", "long_vol", "x", "y", 20, 25, 5, 0.20, True) for _ in range(6)]
        losses = [TradeOutcome("A", "S", "long_vol", "x", "y", 20, 18, -2, -0.10, False) for _ in range(4)]
        s = aggregate_stats(wins + losses, strategy="S")
        assert s.n_trades == 10
        assert s.hit_rate == 0.6
        assert s.avg_win_pct == pytest.approx(0.20, abs=0.001)
        assert s.avg_loss_pct == pytest.approx(0.10, abs=0.001)
        assert s.payoff_ratio == pytest.approx(2.0, abs=0.001)

    def test_sharpe_positive_with_positive_expected(self):
        wins = [TradeOutcome("A", "S", "long_vol", "x", "y", 20, 25, 5, 0.20, True) for _ in range(6)]
        losses = [TradeOutcome("A", "S", "long_vol", "x", "y", 20, 18, -2, -0.10, False) for _ in range(4)]
        s = aggregate_stats(wins + losses, strategy="S")
        assert s.sharpe > 0

    def test_max_drawdown_negative_or_zero(self):
        outcomes = [
            TradeOutcome("A", "S", "long_vol", "x", "y", 20, 18, -2, -0.10, False),
            TradeOutcome("A", "S", "long_vol", "x", "y", 20, 17, -3, -0.15, False),
            TradeOutcome("A", "S", "long_vol", "x", "y", 20, 22, 2, 0.10, True),
        ]
        s = aggregate_stats(outcomes, strategy="S")
        assert s.max_drawdown <= 0

    def test_confidence_grows_with_n(self):
        small = aggregate_stats(
            [TradeOutcome("A", "S", "long_vol", "x", "y", 20, 25, 5, 0.20, True)] * 10,
            "S",
        )
        large = aggregate_stats(
            [TradeOutcome("A", "S", "long_vol", "x", "y", 20, 25, 5, 0.20, True)] * 30,
            "S",
        )
        assert small.confidence < large.confidence

    def test_confidence_zero_when_below_min_signals(self):
        s = aggregate_stats(
            [TradeOutcome("A", "S", "long_vol", "x", "y", 20, 25, 5, 0.20, True)] * 5,
            "S",
        )
        assert s.confidence == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Grouping
# ──────────────────────────────────────────────────────────────────────────

class TestGrouping:
    def test_by_strategy(self):
        ts = [
            TradeOutcome("A", "S1", "long_vol", "x", "y", 20, 25, 5, 0.20, True),
            TradeOutcome("A", "S2", "short_vol", "x", "y", 20, 18, -2, 0.10, True),
        ]
        grp = by_strategy(ts)
        assert set(grp.keys()) == {"S1", "S2"}

    def test_by_strategy_ticker(self):
        ts = [
            TradeOutcome("A", "S1", "long_vol", "x", "y", 20, 25, 5, 0.20, True),
            TradeOutcome("B", "S1", "long_vol", "x", "y", 20, 25, 5, 0.20, True),
        ]
        grp = by_strategy_ticker(ts)
        assert set(grp.keys()) == {("S1", "A"), ("S1", "B")}


# ──────────────────────────────────────────────────────────────────────────
# Universe simulation
# ──────────────────────────────────────────────────────────────────────────

class TestUniverse:
    def test_simulates_multiple_tickers(self):
        histories = {"X": _hist_with_signal(), "Y": _hist_with_signal(end_iv=22.0)}
        trades = simulate_universe(histories)
        assert isinstance(trades, list)

    def test_aggregate_universe(self):
        histories = {"X": _hist_with_signal(), "Y": _hist_with_signal(end_iv=22.0)}
        trades = simulate_universe(histories)
        agg = aggregate_universe(trades)
        for strat, stats in agg.items():
            assert isinstance(stats, StrategyStats)

    def test_aggregate_per_ticker(self):
        histories = {"X": _hist_with_signal(), "Y": _hist_with_signal(end_iv=22.0)}
        trades = simulate_universe(histories)
        agg = aggregate_per_ticker(trades)
        for (s, t), stats in agg.items():
            assert stats.ticker == t


# ──────────────────────────────────────────────────────────────────────────
# Kelly calibration helper
# ──────────────────────────────────────────────────────────────────────────

class TestKellyCalibration:
    def test_below_min_returns_none_none(self):
        s = StrategyStats("S", "X", n_trades=5, hit_rate=0.6, avg_win_pct=0.2,
                          avg_loss_pct=0.1, expected_pnl=0.05, sharpe=1.0,
                          max_drawdown=-0.1, payoff_ratio=2.0, confidence=0.0)
        p, payoff, n = calibration_for_kelly(s)
        assert p is None and payoff is None
        assert n == 5

    def test_above_min_returns_p_and_payoff(self):
        s = StrategyStats("S", "X", n_trades=20, hit_rate=0.6, avg_win_pct=0.2,
                          avg_loss_pct=0.1, expected_pnl=0.05, sharpe=1.0,
                          max_drawdown=-0.1, payoff_ratio=2.0, confidence=0.5)
        p, payoff, n = calibration_for_kelly(s)
        assert p == 0.6
        assert payoff == 2.0

    def test_zero_payoff_returns_none(self):
        s = StrategyStats("S", "X", n_trades=20, hit_rate=1.0, avg_win_pct=0.2,
                          avg_loss_pct=0.0, expected_pnl=0.2, sharpe=99.0,
                          max_drawdown=0.0, payoff_ratio=0.0, confidence=0.5)
        p, payoff, n = calibration_for_kelly(s)
        assert p is None
        assert payoff is None


# ──────────────────────────────────────────────────────────────────────────
# Frozen guards
# ──────────────────────────────────────────────────────────────────────────

class TestFrozen:
    def test_trade_outcome_frozen(self):
        t = TradeOutcome("A", "S", "long_vol", "x", "y", 20, 25, 5, 0.20, True)
        with pytest.raises(Exception):
            t.pnl_pct = 0.0  # type: ignore[misc]

    def test_strategy_stats_frozen(self):
        s = StrategyStats("S", None, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        with pytest.raises(Exception):
            s.n_trades = 1  # type: ignore[misc]
