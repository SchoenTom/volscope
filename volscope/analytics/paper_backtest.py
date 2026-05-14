"""
Paper backtest — v0.3.0.

Replay historical daily_vol + bot_chain_snapshots:

1. For each historical date in range, regenerate signals (factors →
   composite → gates → ranking) using only data available as of that date.
2. Execute each new signal via paper_engine against the chain snapshot
   as of that date.
3. Daily MTM all open positions; close on 50% PT / 2× stop / 21-DTE.
4. At the end, produce a `BacktestReport` with realized Sharpe / win
   rate / max-DD / profit factor / expectancy.

This is the single most important number the operator will read before
risking real money. It replaces vague "looks profitable" gut-feel with
a hard backtested edge measurement.

Phase 3 of the masterplan will swap this in-house engine for the
three-tier validation (vectorbt + optopsy + this engine for ground
truth). For now, this is the source of truth.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestReport:
    """Output of a backtest replay. Renderable by Bot Dashboard."""
    n_trades: int
    n_wins: int
    n_losses: int
    win_rate: float                  # 0 to 1
    avg_win: float                   # $
    avg_loss: float                  # $ (negative)
    profit_factor: float             # sum(wins) / abs(sum(losses))
    expectancy: float                # avg P&L per trade
    total_pnl: float
    sharpe: float                    # annualised, daily-PnL based
    max_drawdown: float              # $ peak-to-trough
    max_drawdown_pct: float          # vs peak NLV
    daily_returns: list[float] = field(default_factory=list)


@dataclass
class _OpenPosition:
    """In-memory representation during replay (not persisted)."""
    trade_id: str
    entered_at: date
    direction: str
    credit_or_debit: float
    legs: list[dict]                 # same structure as bot_legs


def backtest_window(
    db, *,
    start: date,
    end: date,
    underlying_set: list[str],
    nlv_start: float = 100_000.0,
) -> BacktestReport:
    """
    Replay (start, end] day-by-day.

    Stub implementation in v0.3.0: walks the date range, queries
    bot_chain_snapshots for each date, but the inner loop (regenerate
    signal → execute) is left as a callback contract since the
    factor-history layer needs more data than current daily_vol
    provides.

    Returns an *honest* report — zero trades if no chain history
    available, rather than fabricating P&L.
    """
    if start >= end:
        return _empty_report()

    # Inspect what chain history we actually have
    have = db.con.execute("""
        SELECT MIN(DATE(snapshot_ts)), MAX(DATE(snapshot_ts)),
               COUNT(DISTINCT DATE(snapshot_ts))
        FROM bot_chain_snapshots
        WHERE ticker = ANY(?)
    """, [list(underlying_set)]).fetchone()
    if have is None or have[0] is None:
        log.info("no chain history — returning empty report")
        return _empty_report()

    # Phase 1 implementation: stub that returns the empty report,
    # not fabricated data. Phase 3 wires this to a full event-driven
    # simulator.
    log.info("chain history: %s → %s (%d distinct days)",
              have[0], have[1], have[2])
    return _empty_report()


def report_from_closed_trades(db) -> BacktestReport:
    """
    Build a `BacktestReport` from whatever closed trades are in
    `bot_trades`. Useful for paper-engine LIVE performance review,
    not just historical replay.
    """
    rows = db.con.execute("""
        SELECT realized_pnl, opened_at, closed_at
        FROM bot_trades
        WHERE status = 'CLOSED' AND realized_pnl IS NOT NULL
        ORDER BY closed_at
    """).fetchall()
    if not rows:
        return _empty_report()

    pnls = np.array([float(r[0]) for r in rows])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    n_wins = int(len(wins))
    n_losses = int(len(losses))
    win_rate = n_wins / len(pnls)
    avg_win = float(wins.mean()) if n_wins else 0.0
    avg_loss = float(losses.mean()) if n_losses else 0.0
    sum_wins = float(wins.sum())
    sum_losses = float(abs(losses.sum()))
    profit_factor = sum_wins / sum_losses if sum_losses > 0 else float("inf")
    expectancy = float(pnls.mean())
    total = float(pnls.sum())

    # Sharpe from daily P&L
    closed_dates = [r[2].date() for r in rows]
    daily_pnl_dict: dict[date, float] = {}
    for d, p in zip(closed_dates, pnls):
        daily_pnl_dict[d] = daily_pnl_dict.get(d, 0.0) + float(p)
    daily_pnls = list(daily_pnl_dict.values())
    if len(daily_pnls) > 1:
        arr = np.array(daily_pnls)
        sigma = float(arr.std(ddof=1))
        mean = float(arr.mean())
        sharpe = mean / sigma * math.sqrt(252.0) if sigma > 0 else 0.0
    else:
        sharpe = 0.0

    # Drawdown from cumulative P&L
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    drawdown = cum - peak
    max_dd = float(drawdown.min())
    max_dd_pct = float(abs(max_dd) / peak.max()) if peak.max() > 0 else 0.0

    return BacktestReport(
        n_trades=len(pnls), n_wins=n_wins, n_losses=n_losses,
        win_rate=win_rate, avg_win=avg_win, avg_loss=avg_loss,
        profit_factor=profit_factor, expectancy=expectancy,
        total_pnl=total, sharpe=sharpe,
        max_drawdown=max_dd, max_drawdown_pct=max_dd_pct,
        daily_returns=daily_pnls,
    )


def _empty_report() -> BacktestReport:
    return BacktestReport(
        n_trades=0, n_wins=0, n_losses=0, win_rate=0.0,
        avg_win=0.0, avg_loss=0.0, profit_factor=0.0,
        expectancy=0.0, total_pnl=0.0, sharpe=0.0,
        max_drawdown=0.0, max_drawdown_pct=0.0,
    )
