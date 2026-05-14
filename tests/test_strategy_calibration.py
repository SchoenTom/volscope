"""Tests for analytics.strategy_calibration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from volscope.analytics.strategy_backtest import StrategyStats
from volscope.analytics import strategy_calibration as sc


def _make_stats(strategy="X", ticker=None, n=20, hr=0.6, payoff=2.0, sharpe=1.5, ep=0.05):
    return StrategyStats(
        strategy=strategy, ticker=ticker, n_trades=n,
        hit_rate=hr, avg_win_pct=0.2, avg_loss_pct=0.1,
        expected_pnl=ep, sharpe=sharpe, max_drawdown=-0.1,
        payoff_ratio=payoff, confidence=0.7,
    )


@pytest.fixture
def isolated_jsonl(tmp_path, monkeypatch):
    """Redirect the calibration JSONL to a per-test temp path."""
    jsonl = tmp_path / "stats.jsonl"
    monkeypatch.setattr(sc, "_STATS_JSONL", jsonl)
    monkeypatch.setattr(sc, "_BACKTEST_DIR", tmp_path)
    return jsonl


# ──────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_append_creates_file(self, isolated_jsonl):
        sc.append_stats([_make_stats()])
        assert isolated_jsonl.exists()
        lines = isolated_jsonl.read_text().strip().split("\n")
        assert len(lines) == 1

    def test_append_is_jsonl(self, isolated_jsonl):
        sc.append_stats([_make_stats(), _make_stats(strategy="Y")])
        lines = isolated_jsonl.read_text().strip().split("\n")
        for line in lines:
            data = json.loads(line)
            assert "strategy" in data

    def test_append_multiple_calls_accumulate(self, isolated_jsonl):
        sc.append_stats([_make_stats(strategy="A")])
        sc.append_stats([_make_stats(strategy="B")])
        lines = isolated_jsonl.read_text().strip().split("\n")
        assert len(lines) == 2


# ──────────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────────

class TestLoading:
    def test_empty_file_returns_empty_dict(self, isolated_jsonl):
        assert sc.load_latest_stats() == {}

    def test_no_file_returns_empty_dict(self, isolated_jsonl):
        # Don't create any file
        assert sc.load_latest_stats() == {}

    def test_latest_wins(self, isolated_jsonl):
        sc.append_stats([_make_stats(strategy="A", hr=0.4)])
        sc.append_stats([_make_stats(strategy="A", hr=0.7)])
        latest = sc.load_latest_stats()
        assert latest[("A", None)].hit_rate == 0.7

    def test_distinct_keys(self, isolated_jsonl):
        sc.append_stats([
            _make_stats(strategy="A", ticker=None),
            _make_stats(strategy="A", ticker="QQQ"),
            _make_stats(strategy="B", ticker=None),
        ])
        latest = sc.load_latest_stats()
        assert ("A", None) in latest
        assert ("A", "QQQ") in latest
        assert ("B", None) in latest

    def test_unreadable_line_skipped(self, isolated_jsonl):
        sc.append_stats([_make_stats()])
        with isolated_jsonl.open("a") as f:
            f.write("not json\n")
        sc.append_stats([_make_stats(strategy="Y")])
        latest = sc.load_latest_stats()
        # Both valid records loaded, garbage line ignored
        assert ("X", None) in latest
        assert ("Y", None) in latest


# ──────────────────────────────────────────────────────────────────────────
# Lookup helpers
# ──────────────────────────────────────────────────────────────────────────

class TestLookup:
    def test_get_stats_for_ticker_specific_wins(self, isolated_jsonl):
        sc.append_stats([
            _make_stats(strategy="A", ticker=None, hr=0.4),
            _make_stats(strategy="A", ticker="QQQ", hr=0.8),
        ])
        result = sc.get_stats_for("A", ticker="QQQ")
        assert result.hit_rate == 0.8

    def test_get_stats_falls_back_to_universe(self, isolated_jsonl):
        sc.append_stats([_make_stats(strategy="A", ticker=None, hr=0.5)])
        result = sc.get_stats_for("A", ticker="UNSEEN")
        assert result.hit_rate == 0.5

    def test_get_stats_returns_none_when_unknown(self, isolated_jsonl):
        sc.append_stats([_make_stats(strategy="A", ticker=None)])
        assert sc.get_stats_for("DOES_NOT_EXIST") is None

    def test_best_strategy_picks_max_expected_pnl(self, isolated_jsonl):
        sc.append_stats([
            _make_stats(strategy="A", ticker="X", ep=0.02),
            _make_stats(strategy="B", ticker="X", ep=0.10),
            _make_stats(strategy="C", ticker="X", ep=0.05),
        ])
        best = sc.best_strategy_for("X")
        assert best.strategy == "B"

    def test_best_strategy_returns_none_when_no_records(self, isolated_jsonl):
        assert sc.best_strategy_for("X") is None

    def test_universe_ranking_sorted_by_sharpe_desc(self, isolated_jsonl):
        sc.append_stats([
            _make_stats(strategy="LOW",  ticker=None, sharpe=0.5),
            _make_stats(strategy="HIGH", ticker=None, sharpe=2.5),
            _make_stats(strategy="MID",  ticker=None, sharpe=1.5),
            _make_stats(strategy="X",    ticker="QQQ", sharpe=99),  # ticker-scoped, excluded
        ])
        ranked = sc.universe_ranking()
        assert [s.strategy for s in ranked] == ["HIGH", "MID", "LOW"]
