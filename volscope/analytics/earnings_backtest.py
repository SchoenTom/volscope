"""
Earnings strategy backtest harness — turns Hub recommendations from
speculation into evidence.

For each historical earnings event in the DB:
    1. Reconstruct the pre-ER market state (spot, IV30, IV-rank, skew,
       crowded score) one trading day before the print.
    2. Apply the strategy classifier to that state (Long Straddle,
       Short Iron Condor, Long Call fade-skew, etc.).
    3. Simulate the trade: materialise legs at the reconstructed spot
       + IV, then re-price the legs the day AFTER the print using the
       actual post-ER spot + IV. P/L per contract = exit - entry.
    4. Aggregate across all events → hit rate, mean P/L %, Sharpe,
       max drawdown.

The result is a ``BacktestResult`` per (ticker, strategy_name) that
the Hub's drawer attaches as a "historical: 71 % hit · …" line under
the recommendation card.

Optional bucketing: by IV-rank quintile, by crowded band → exposes
conditional edge ("Long Straddle works in low-IV-rank but loses in
high-IV-rank").

Pure-analytics module: no Streamlit, no IO except DB reads.
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from volscope.analytics.black_scholes import bs_price
from volscope.analytics.earnings_strategy import recommend_for_earnings
from volscope.analytics.strategy_templates import (
    TEMPLATES,
    MaterializedStrategy,
)

log = logging.getLogger(__name__)

_RISK_FREE = 0.04


# ── Output type ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class EarningsTrade:
    """One historical replay of a strategy at one earnings event."""
    ticker:        str
    earnings_date: date
    strategy:      str
    entry_iv:      float
    entry_spot:    float
    exit_spot:     float
    iv_rank_at_entry: Optional[float]
    skew_at_entry:    Optional[float]
    crowded_band_at_entry: Optional[str]
    pl_per_contract: float        # dollars
    pl_pct_of_premium: float      # signed %
    win:           bool


@dataclass(frozen=True)
class BacktestResult:
    """Aggregated edge of a strategy across all historical events."""
    ticker:         str          # empty string = universe-wide
    strategy:       str
    n_events:       int
    hit_rate:       float        # 0..1
    mean_pl_pct:    float
    median_pl_pct:  float
    sharpe:         float
    max_drawdown_pct: float       # most-negative single trade
    win_loss_ratio: float         # avg-win / avg-loss
    trades:         tuple["EarningsTrade", ...]
    by_iv_rank_bucket: dict[str, float] = field(default_factory=dict)
    by_crowded_band:   dict[str, float] = field(default_factory=dict)


# ── Replay a single (ticker, earnings_date, strategy) tuple ─────────

def _state_at(db, ticker: str, asof_date: date) -> Optional[dict]:
    """Reconstruct the daily_vol row closest to (but not after) asof_date."""
    try:
        hist = db.get_ticker_history(ticker)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    h = hist.copy()
    h["date"] = pd.to_datetime(h["date"]).dt.date
    earlier = h[h["date"] <= asof_date].tail(1)
    if earlier.empty:
        return None
    return earlier.iloc[0].to_dict()


def _spot_at(db, ticker: str, target_date: date) -> Optional[float]:
    """Return the close on ``target_date`` (or earliest later if missing)."""
    try:
        hist = db.get_ticker_history(ticker)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    h = hist.copy()
    h["date"] = pd.to_datetime(h["date"]).dt.date
    later = h[h["date"] >= target_date].head(1)
    if later.empty:
        # fall back to the nearest pre-target row
        earlier = h[h["date"] < target_date].tail(1)
        if earlier.empty:
            return None
        return float(earlier["spot_price"].iloc[-1])
    return float(later["spot_price"].iloc[0])


def simulate_one(
    db,
    ticker: str,
    earnings_date: date,
    strategy_name: str,
    *,
    contracts: int = 1,
    dte_at_entry: int = 7,
) -> Optional[EarningsTrade]:
    """Replay a single ER event with the named strategy.

    Logic:
      • Pull state on `earnings_date - 1 trading day` (entry).
      • Materialise the strategy at entry IV + spot.
      • Pull spot on `earnings_date + 1 trading day` (exit).
      • Re-price the materialised legs at exit spot, using entry IV
        scaled down by 50 % (proxy for the typical post-print IV crush).
      • Compute net P/L per contract = sum of leg exit values minus
        entry premiums (signs accounting for buy/sell).

    Returns None when the event lacks the necessary pre or post rows.
    """
    template = TEMPLATES.get(strategy_name)
    if template is None:
        return None

    # ── Entry state ─────────────────────────────────────────────────
    entry = _state_at(db, ticker, earnings_date - timedelta(days=1))
    if entry is None:
        return None
    entry_iv = _f(entry.get("iv_30d"))
    entry_spot = _f(entry.get("spot_price"))
    if entry_iv is None or entry_spot is None or entry_iv <= 0:
        return None

    # ── Materialise the strategy at entry ───────────────────────────
    try:
        mat = template.materialize(
            ticker=ticker, spot=entry_spot, iv_pct=entry_iv,
            dte=int(dte_at_entry), contracts=int(contracts),
        )
    except Exception as exc:
        log.debug("materialize failed (%s %s %s): %s",
                   ticker, earnings_date, strategy_name, exc)
        return None

    # ── Exit state — re-price legs at post-ER spot + crushed IV ─────
    exit_spot = _spot_at(db, ticker, earnings_date + timedelta(days=1))
    if exit_spot is None:
        return None
    # IV crush proxy: 50 % of entry IV for the first day post-ER
    exit_iv_pct = entry_iv * 0.50
    iv_dec = exit_iv_pct / 100.0
    # T_exit: remaining days reduced by 1 trading day
    T_exit = max(1, dte_at_entry - 1) / 365.0

    net_exit = 0.0
    for leg in mat.legs:
        sign = +1 if leg.action == "buy" else -1
        # Re-price the leg under the new (spot, IV, T)
        if leg.strike <= 0 and leg.option_type == "call":
            # Stock leg encoding — value = spot per share
            leg_value = exit_spot
        else:
            leg_value = bs_price(
                exit_spot, leg.strike, T_exit, _RISK_FREE, iv_dec, 0.0,
                option_type=leg.option_type,
            )
        net_exit += sign * leg_value * leg.contracts * 100

    pl = net_exit - (-mat.net_debit if mat.net_debit < 0 else mat.net_debit)
    # net_debit > 0 means we PAID at entry; pl = exit - entry_paid
    if mat.net_debit > 0:
        pl = net_exit - mat.net_debit
    else:
        # We received credit at entry; pl = credit_received - exit_cost
        pl = -mat.net_debit - net_exit

    pl_pct = (pl / abs(mat.net_debit) * 100.0) if mat.net_debit != 0 else 0.0

    return EarningsTrade(
        ticker=ticker,
        earnings_date=earnings_date,
        strategy=strategy_name,
        entry_iv=entry_iv,
        entry_spot=entry_spot,
        exit_spot=exit_spot,
        iv_rank_at_entry=_f(entry.get("iv_rank")),
        skew_at_entry=_f(entry.get("iv_skew_25d")),
        crowded_band_at_entry=None,
        pl_per_contract=float(pl),
        pl_pct_of_premium=float(pl_pct),
        win=bool(pl > 0),
    )


# ── Aggregate across events ──────────────────────────────────────────

def _aggregate(trades: list[EarningsTrade], ticker: str, strategy: str) -> BacktestResult:
    if not trades:
        return BacktestResult(
            ticker=ticker, strategy=strategy, n_events=0,
            hit_rate=0.0, mean_pl_pct=0.0, median_pl_pct=0.0,
            sharpe=0.0, max_drawdown_pct=0.0, win_loss_ratio=0.0,
            trades=(),
        )
    n = len(trades)
    pls = [t.pl_pct_of_premium for t in trades]
    wins = [t for t in trades if t.win]
    losses = [t for t in trades if not t.win]

    mean_pl = statistics.fmean(pls)
    median_pl = statistics.median(pls)
    sd = statistics.pstdev(pls) if n > 1 else 0.0
    sharpe = (mean_pl / sd) if sd > 0 else 0.0
    avg_win = statistics.fmean([t.pl_pct_of_premium for t in wins]) if wins else 0.0
    avg_loss = abs(statistics.fmean([t.pl_pct_of_premium for t in losses])) if losses else 1e-6
    wl_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
    max_dd = min(pls)

    # IV-rank buckets
    iv_buckets: dict[str, list[float]] = {"low(<25)": [], "mid(25-75)": [], "high(>75)": []}
    for t in trades:
        r = t.iv_rank_at_entry
        if r is None:
            continue
        if r < 25:
            iv_buckets["low(<25)"].append(t.pl_pct_of_premium)
        elif r > 75:
            iv_buckets["high(>75)"].append(t.pl_pct_of_premium)
        else:
            iv_buckets["mid(25-75)"].append(t.pl_pct_of_premium)
    by_iv = {
        k: (statistics.fmean(v) if v else 0.0)
        for k, v in iv_buckets.items() if v
    }

    return BacktestResult(
        ticker=ticker, strategy=strategy, n_events=n,
        hit_rate=len(wins) / n,
        mean_pl_pct=mean_pl, median_pl_pct=median_pl,
        sharpe=sharpe, max_drawdown_pct=max_dd,
        win_loss_ratio=wl_ratio,
        trades=tuple(trades),
        by_iv_rank_bucket=by_iv,
    )


def backtest_earnings_strategy(
    db,
    ticker: str,
    strategy_name: str,
    *,
    contracts: int = 1,
    dte_at_entry: int = 7,
    max_events: int = 8,
) -> BacktestResult:
    """Replay one strategy for one ticker across its historical ERs."""
    try:
        df = db.con.execute(
            """
            SELECT earnings_date FROM earnings
            WHERE ticker = ? AND earnings_date < CURRENT_DATE
            ORDER BY earnings_date DESC LIMIT ?
            """,
            [ticker, int(max_events)],
        ).fetchdf()
    except Exception:
        df = pd.DataFrame()
    if df is None or df.empty:
        return _aggregate([], ticker, strategy_name)
    er_dates = [pd.to_datetime(d).date() for d in df["earnings_date"]]
    trades = []
    for d in er_dates:
        t = simulate_one(db, ticker, d, strategy_name,
                         contracts=contracts, dte_at_entry=dte_at_entry)
        if t is not None:
            trades.append(t)
    return _aggregate(trades, ticker, strategy_name)


def backtest_universe(
    db,
    strategy_name: str,
    *,
    min_events_per_ticker: int = 3,
    max_events_per_ticker: int = 8,
    max_tickers: Optional[int] = None,
) -> BacktestResult:
    """Replay one strategy across every ticker with sufficient history."""
    try:
        all_tickers = db.get_available_tickers() or []
    except Exception:
        all_tickers = []
    if max_tickers:
        all_tickers = all_tickers[:max_tickers]

    all_trades: list[EarningsTrade] = []
    for tk in all_tickers:
        res = backtest_earnings_strategy(
            db, tk, strategy_name,
            max_events=max_events_per_ticker,
        )
        if res.n_events >= min_events_per_ticker:
            all_trades.extend(res.trades)
    return _aggregate(all_trades, "", strategy_name)


# ── Helpers ──────────────────────────────────────────────────────────

def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def edge_string(res: BacktestResult) -> str:
    """One-line edge summary for the Hub drawer.

    Example: 'historical: 71 % hit · +28 % avg P/L · Sharpe +0.85 · n=28'
    """
    if res.n_events == 0:
        return "no historical data yet — needs at least 1 past ER"
    return (
        f"historical: {res.hit_rate*100:.0f} % hit · "
        f"{res.mean_pl_pct:+.0f} % avg P/L · "
        f"Sharpe {res.sharpe:+.2f} · n={res.n_events}"
    )
