"""
Strategy Calibration — bridge between backtest results and Kelly sizing.

Loads persisted backtest stats from disk (JSONL) and exposes lookup
helpers so live recommendation paths can ask: *"What's the historical
hit-rate of the Long Put Spread strategy on QQQ?"* and feed that into
``kelly_sizing.compute_kelly_sizing`` for data-driven bet fractions.

Persistence layout
------------------
``data/backtest/strategy_stats.jsonl`` — append-only, one StrategyStats
JSON per line. Latest entry per (strategy, ticker) wins.

This module does NOT run simulations — it only reads. Use
``scripts/backtest/run_strategy_simulation.py`` to populate the JSONL.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from volscope.analytics.strategy_backtest import StrategyStats


_DATA_DIR     = Path(__file__).resolve().parents[2] / "data"
_BACKTEST_DIR = _DATA_DIR / "backtest"
_STATS_JSONL  = _BACKTEST_DIR / "strategy_stats.jsonl"


# ── Persistence ──────────────────────────────────────────────────────────

def append_stats(stats_list: list[StrategyStats]) -> None:
    """Append a batch of StrategyStats records to the JSONL file."""
    _BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    _STATS_JSONL.touch(exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    with _STATS_JSONL.open("a") as f:
        for s in stats_list:
            payload = {"_ts": ts, **asdict(s)}
            f.write(json.dumps(payload) + "\n")


def load_latest_stats() -> dict[tuple[str, Optional[str]], StrategyStats]:
    """Read the JSONL and return the latest StrategyStats per (strategy, ticker).

    The 'latest' rule walks the file once, keeping the most-recent record
    per key.  Returns an empty dict if no file or no records.
    """
    if not _STATS_JSONL.exists():
        return {}
    out: dict[tuple, StrategyStats] = {}
    for line in _STATS_JSONL.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        # Strip the _ts annotation we added in append_stats
        data.pop("_ts", None)
        try:
            stats = StrategyStats(**data)
        except TypeError:
            continue
        key = (stats.strategy, stats.ticker)
        out[key] = stats   # later wins (file is append-only chronological)
    return out


# ── Lookup helpers ───────────────────────────────────────────────────────

def get_stats_for(
    strategy: str,
    ticker:   Optional[str] = None,
) -> Optional[StrategyStats]:
    """Best-match lookup.  If a ticker-specific record exists, return it;
    otherwise fall back to the universe-wide record (ticker=None).
    """
    stats = load_latest_stats()
    if ticker is not None:
        spec = stats.get((strategy, ticker))
        if spec is not None:
            return spec
    return stats.get((strategy, None))


def best_strategy_for(ticker: str) -> Optional[StrategyStats]:
    """Return the StrategyStats with highest expected_pnl for this ticker."""
    stats = load_latest_stats()
    candidates = [s for (strat, t), s in stats.items() if t == ticker]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.expected_pnl)


def universe_ranking() -> list[StrategyStats]:
    """Return universe-level StrategyStats sorted by Sharpe descending."""
    stats = load_latest_stats()
    universe = [s for (strat, t), s in stats.items() if t is None]
    return sorted(universe, key=lambda s: s.sharpe, reverse=True)
