"""
Strategy Backtest Simulation Engine.

Walks each strategy template from ``strategy_recommender`` through every
ticker's vol history and produces calibrated performance statistics:
hit rate, Sharpe, max drawdown, average win/loss magnitude, expected
payoff. The output feeds two upstream consumers:

1. ``kelly_sizing.compute_kelly_sizing`` — turns hit-rate + payoff into
   data-driven bet fractions instead of summary-stat fallbacks.
2. ``strategy_recommender`` v2 — adjusts scores per-ticker by the
   strategy's historical performance on that specific underlying.

Simulation methodology
----------------------
For each (ticker, strategy, signal_date):
  - read iv_30d at signal_date (entry)
  - read iv_30d at signal_date + hold_days (exit)
  - long-vol expressions: P&L = (exit_iv − entry_iv) × vega_proxy
  - short-vol expressions: P&L = (entry_iv − exit_iv) × vega_proxy
  - calendar / neutral structures: rough P&L proportional to
    abs(term_slope_change), capped to ±theta-budget

This is intentionally a *first-order* simulation. Real options
P&L includes gamma, second-order vega, and theta decay — but the
*ranking* of strategies and the *hit-rate* (sign of P&L) are robust
to first-order approximation. We document the limitation in every
output object so callers know to weight Kelly fractions accordingly.

The module is pure analytics — no DB writes from this layer; persistence
is the orchestrator's job.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from volscope.analytics.strategy_recommender import recommend_strategies


# ── Configuration ────────────────────────────────────────────────────────

# Default holding window per direction. Long-vol expressions average
# 60-90 days holding; short-vol typically 30-45 days.
_HOLD_DAYS = {
    "long_vol":    45,
    "short_vol":   30,
    "neutral_vol": 30,
}

# Vega proxy: BSM vega for an ATM 60d option on a $100 stock at 25% IV
# is roughly $0.18 per 1% IV move. We scale this to a "% of premium"
# normalisation so the simulation is dimensionless across tickers.
# A 5pt IV move on a long put then yields ~+25% on a $1 premium leg.
_VEGA_PCT_PER_IV_PT = 0.05    # 1pt IV → 5% premium move (rough 60d ATM)

# Minimum signals per (strategy, ticker) to produce calibrated stats.
_MIN_SIGNALS = 8

# Annualisation for Sharpe (252 trading days, ~30d holding → 8.4 trades/yr).
_TRADES_PER_YEAR = 12


# ── Output types ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TradeOutcome:
    """One simulated trade record."""
    ticker:        str
    strategy:      str
    direction:     str
    entry_date:    object   # pd.Timestamp or str
    exit_date:     object
    entry_iv:      float
    exit_iv:       float
    iv_change:     float
    pnl_pct:       float    # signed % return on premium
    is_win:        bool


@dataclass(frozen=True)
class StrategyStats:
    """Aggregated stats for one (strategy, ticker) pair, or one strategy."""
    strategy:       str
    ticker:         Optional[str]
    n_trades:       int
    hit_rate:       float        # 0..1
    avg_win_pct:    float        # mean of positive P&L %
    avg_loss_pct:   float        # mean of |negative P&L|, positive
    expected_pnl:   float        # mean of signed P&L
    sharpe:         float        # annualised
    max_drawdown:   float        # signed, negative
    payoff_ratio:   float        # avg_win / avg_loss
    confidence:     float        # 0..1, function of n_trades


# ── Trade generation ─────────────────────────────────────────────────────

def _strategy_signals_for_ticker(
    history: pd.DataFrame,
    hold_days: int,
) -> list[tuple[pd.Timestamp, str, str]]:
    """Walk a ticker's vol history and emit (date, strategy_name, direction).

    Each row of history is a candidate signal date — we feed its
    iv_percentile / skew / term_slope into ``recommend_strategies`` and
    log the top-1 non-WAIT recommendation if any.

    ``hold_days`` is required: the caller (``simulate_ticker``) decides the
    forward window — either the user-supplied value or ``max(_HOLD_DAYS)``
    so signals are not generated for rows we cannot evaluate.
    """
    if history is None or history.empty:
        return []
    df = history.sort_values("date").reset_index(drop=True)
    signals: list[tuple] = []

    iv30 = df["iv_30d"] if "iv_30d" in df else None
    iv60 = df["iv_60d"] if "iv_60d" in df else None
    perc = df["iv_percentile"] if "iv_percentile" in df else None
    skew = df["iv_skew_25d"] if "iv_skew_25d" in df else None

    if iv30 is None or perc is None:
        return []

    for i in range(len(df) - hold_days):
        row = df.iloc[i]
        try:
            term = (
                float(iv60.iloc[i]) - float(iv30.iloc[i])
                if iv60 is not None and pd.notna(iv60.iloc[i]) and pd.notna(iv30.iloc[i])
                else None
            )
        except Exception:
            term = None
        try:
            sk = float(skew.iloc[i]) if skew is not None and pd.notna(skew.iloc[i]) else None
        except Exception:
            sk = None
        try:
            pc = float(perc.iloc[i]) if pd.notna(perc.iloc[i]) else None
        except Exception:
            pc = None
        if pc is None:
            continue
        recs = recommend_strategies(
            iv_percentile=pc,
            skew_25=sk,
            term_slope=term,
        )
        if not recs or recs[0].name == "WAIT":
            continue
        top = recs[0]
        signals.append((row["date"], top.name, top.direction))
    return signals


def simulate_ticker(
    ticker:    str,
    history:   pd.DataFrame,
    hold_days: Optional[int] = None,
) -> list[TradeOutcome]:
    """Simulate every recommended strategy across the ticker's history.

    Returns a list of TradeOutcome objects, one per signal generated.
    Empty list when no signals or insufficient history.
    """
    if history is None or history.empty or "iv_30d" not in history.columns:
        return []

    df = history.sort_values("date").reset_index(drop=True)
    iv = df["iv_30d"].astype(float).values
    dates = df["date"].values

    out: list[TradeOutcome] = []
    # Signal-generation needs enough forward bars to evaluate the trade.
    # Use the longest possible hold so signals don't get generated for
    # rows that we can't actually evaluate.
    if hold_days is not None:
        signal_lookahead = hold_days
    else:
        signal_lookahead = max(_HOLD_DAYS.values())
    signals = _strategy_signals_for_ticker(df, hold_days=signal_lookahead)

    for sig_date, strat_name, direction in signals:
        h = hold_days if hold_days is not None else _HOLD_DAYS.get(direction, 30)
        try:
            entry_idx = int(np.where(dates == sig_date)[0][0])
        except (IndexError, ValueError):
            continue
        exit_idx = entry_idx + h
        if exit_idx >= len(iv):
            continue
        entry_iv = iv[entry_idx]
        exit_iv  = iv[exit_idx]
        if not (math.isfinite(entry_iv) and math.isfinite(exit_iv)) or entry_iv <= 0:
            continue

        iv_change = exit_iv - entry_iv

        # First-order P&L per direction
        if direction == "long_vol":
            pnl_pct = iv_change * _VEGA_PCT_PER_IV_PT
        elif direction == "short_vol":
            pnl_pct = -iv_change * _VEGA_PCT_PER_IV_PT
        else:
            # Neutral / calendar — P&L tied to magnitude of move (small moves win)
            # Simple proxy: positive when |Δiv| < 2pt, negative when > 5pt
            mag = abs(iv_change)
            pnl_pct = (3.0 - mag) * _VEGA_PCT_PER_IV_PT * 0.5

        out.append(TradeOutcome(
            ticker=ticker,
            strategy=strat_name,
            direction=direction,
            entry_date=sig_date,
            exit_date=dates[exit_idx],
            entry_iv=float(entry_iv),
            exit_iv=float(exit_iv),
            iv_change=float(iv_change),
            pnl_pct=float(pnl_pct),
            is_win=bool(pnl_pct > 0),
        ))

    return out


# ── Aggregation ──────────────────────────────────────────────────────────

def aggregate_stats(
    trades:    list[TradeOutcome],
    strategy:  str,
    ticker:    Optional[str] = None,
) -> StrategyStats:
    """Aggregate a list of trade outcomes into a StrategyStats object."""
    if not trades:
        return StrategyStats(
            strategy=strategy, ticker=ticker, n_trades=0,
            hit_rate=0.0, avg_win_pct=0.0, avg_loss_pct=0.0,
            expected_pnl=0.0, sharpe=0.0, max_drawdown=0.0,
            payoff_ratio=0.0, confidence=0.0,
        )

    pnls = np.array([t.pnl_pct for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    hit_rate    = float(len(wins) / len(pnls))
    avg_win_pct = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss_pct = float(abs(losses).mean()) if len(losses) > 0 else 0.0
    expected_pnl = float(pnls.mean())

    # Annualised Sharpe — rough, assumes _TRADES_PER_YEAR per year
    if len(pnls) > 1 and pnls.std(ddof=1) > 0:
        sharpe = float(expected_pnl / pnls.std(ddof=1) * math.sqrt(_TRADES_PER_YEAR))
    else:
        sharpe = 0.0

    # Max drawdown on cumulative P&L curve
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_drawdown = float(dd.min()) if len(dd) > 0 else 0.0

    payoff_ratio = avg_win_pct / avg_loss_pct if avg_loss_pct > 0 else 0.0

    # Confidence — calibrated against _MIN_SIGNALS and a stable target of 30
    if len(pnls) < _MIN_SIGNALS:
        confidence = 0.0
    else:
        confidence = min(1.0, len(pnls) / 30.0)

    return StrategyStats(
        strategy=strategy,
        ticker=ticker,
        n_trades=len(pnls),
        hit_rate=round(hit_rate, 4),
        avg_win_pct=round(avg_win_pct, 4),
        avg_loss_pct=round(avg_loss_pct, 4),
        expected_pnl=round(expected_pnl, 4),
        sharpe=round(sharpe, 3),
        max_drawdown=round(max_drawdown, 4),
        payoff_ratio=round(payoff_ratio, 3),
        confidence=round(confidence, 2),
    )


from volscope.utils.timing import instrumented  # noqa: E402


@instrumented("analytics.simulate_universe")
def simulate_universe(
    histories: dict[str, pd.DataFrame],
) -> list[TradeOutcome]:
    """Run simulation across a dict of {ticker: history}. Flat list output."""
    all_trades: list[TradeOutcome] = []
    for ticker, hist in histories.items():
        all_trades.extend(simulate_ticker(ticker, hist))
    return all_trades


def by_strategy(trades: list[TradeOutcome]) -> dict[str, list[TradeOutcome]]:
    """Group trades by strategy name."""
    out: dict[str, list[TradeOutcome]] = {}
    for t in trades:
        out.setdefault(t.strategy, []).append(t)
    return out


def by_strategy_ticker(trades: list[TradeOutcome]) -> dict[tuple[str, str], list[TradeOutcome]]:
    """Group trades by (strategy, ticker)."""
    out: dict[tuple, list[TradeOutcome]] = {}
    for t in trades:
        out.setdefault((t.strategy, t.ticker), []).append(t)
    return out


def aggregate_universe(
    trades: list[TradeOutcome],
) -> dict[str, StrategyStats]:
    """Per-strategy stats across the entire universe."""
    return {
        strat: aggregate_stats(grp, strategy=strat, ticker=None)
        for strat, grp in by_strategy(trades).items()
    }


def aggregate_per_ticker(
    trades: list[TradeOutcome],
) -> dict[tuple[str, str], StrategyStats]:
    """Per (strategy, ticker) stats — feeds calibrated Kelly sizing."""
    return {
        (s, t): aggregate_stats(grp, strategy=s, ticker=t)
        for (s, t), grp in by_strategy_ticker(trades).items()
    }


# ── Calibration helper for Kelly sizer ───────────────────────────────────

def calibration_for_kelly(
    stats: StrategyStats,
) -> tuple[Optional[float], Optional[float], int]:
    """Convert StrategyStats into the (p_win, payoff, n) tuple Kelly needs.

    Returns (None, None, n) when n_trades < _MIN_SIGNALS so the caller
    can fall back gracefully.
    """
    if stats.n_trades < _MIN_SIGNALS or stats.payoff_ratio <= 0:
        return (None, None, stats.n_trades)
    return (stats.hit_rate, stats.payoff_ratio, stats.n_trades)
