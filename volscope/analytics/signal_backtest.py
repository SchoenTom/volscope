"""
Historical backtest of a Signal Engine recommendation.

For any (ticker, signal_type) we replay history: at each date where
the **same trigger conditions** would have fired (e.g. IV percentile <
20 + IV/HV < 0.75), we simulate the recommended structure with a 30-d
hold window and compute P/L using BSM re-pricing.

Output is a ``SignalBacktest`` — hit_rate, mean_pl_pct, n_events,
Sharpe — which the Signals dashboard surfaces as
``"historical: 71 % hit · Sharpe +0.85 · n=14"`` under each card.

Separate from ``earnings_backtest.py`` because:
  - earnings_backtest replays around known earnings dates
  - signal_backtest replays around *any* day the trigger condition fired

Pure analytics, no Streamlit, cached per (ticker, signal_type).
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from volscope.analytics.black_scholes import bs_price
from volscope.analytics.strategy_templates import TEMPLATES

log = logging.getLogger(__name__)

_RISK_FREE = 0.04
_HOLD_DAYS = 30          # default hold window per simulated trade


@dataclass(frozen=True)
class SignalBacktest:
    ticker:      str
    signal_type: str
    strategy:    str
    n_events:    int
    hit_rate:    float          # 0..1
    mean_pl_pct: float           # signed % of premium
    median_pl_pct: float
    sharpe:      float
    win_loss_ratio: float


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


def _trigger_fired(row: pd.Series, signal_type: str) -> bool:
    """Did the named trigger fire on this historical row?

    Mirrors the thresholds in ``signals.py`` exactly.
    """
    iv = _f(row.get("iv_30d"))
    hv = _f(row.get("hv_yz_20d")) or _f(row.get("hv_20d"))
    rank = _f(row.get("iv_rank"))
    perc = _f(row.get("iv_percentile"))
    if any(x is None for x in (iv, hv, rank, perc)) or hv <= 0:
        return False
    ratio = iv / hv

    if signal_type == "TRIPLE_CHEAP":
        return perc < 20 and ratio < 0.75
    if signal_type == "LOW_RANK":
        return perc < 30 and rank < 15
    if signal_type == "TRIPLE_RICH":
        return perc > 80 and ratio > 1.20
    if signal_type == "HIGH_RANK":
        return perc > 70 and rank > 50
    return False


def simulate_signal_trade(
    db,
    ticker: str,
    fire_date: date,
    strategy_name: str,
    *,
    hold_days: int = _HOLD_DAYS,
) -> Optional[float]:
    """Replay one historical signal-fire and return P/L as % of premium.

    Materialise the structure on ``fire_date`` using that day's IV +
    spot, re-price at ``fire_date + hold_days`` using that day's spot
    and a half-decayed IV. ``None`` when data is insufficient.
    """
    tpl = TEMPLATES.get(strategy_name)
    if tpl is None:
        return None
    try:
        hist = db.get_ticker_history(ticker)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    h = hist.copy()
    h["date"] = pd.to_datetime(h["date"]).dt.date

    entry_rows = h[h["date"] == fire_date].head(1)
    if entry_rows.empty:
        return None
    entry = entry_rows.iloc[0]
    spot = _f(entry.get("spot_price"))
    iv = _f(entry.get("iv_30d"))
    if spot is None or iv is None or spot <= 0 or iv <= 0:
        return None

    exit_rows = h[h["date"] >= (fire_date + timedelta(days=hold_days))].head(1)
    if exit_rows.empty:
        return None
    exit_row = exit_rows.iloc[0]
    exit_spot = _f(exit_row.get("spot_price"))
    if exit_spot is None or exit_spot <= 0:
        return None

    try:
        mat = tpl.materialize(
            ticker=ticker, spot=spot, iv_pct=iv, dte=hold_days * 2,
            contracts=1,
        )
    except Exception:
        return None

    # Re-price legs at exit with half-decayed IV
    exit_iv_dec = max(0.001, (iv * 0.7) / 100.0)
    T_exit = max(1, hold_days) / 365.0
    net_exit = 0.0
    for leg in mat.legs:
        sign = +1 if leg.action == "buy" else -1
        if leg.strike <= 0 and leg.option_type == "call":
            leg_val = exit_spot   # stock leg
        else:
            leg_val = bs_price(
                exit_spot, leg.strike, T_exit, _RISK_FREE, exit_iv_dec, 0.0,
                option_type=leg.option_type,
            )
        net_exit += sign * leg_val * leg.contracts * 100

    if mat.net_debit > 0:
        pl = net_exit - mat.net_debit
    else:
        pl = -mat.net_debit - net_exit
    pl_pct = (pl / abs(mat.net_debit) * 100.0) if mat.net_debit != 0 else 0.0
    return float(pl_pct)


def backtest_signal(
    db,
    ticker: str,
    signal_type: str,
    strategy_name: str,
    *,
    max_events: int = 20,
    cooldown_days: int = 21,
) -> SignalBacktest:
    """Scan a ticker's history for every trigger-fire and simulate it."""
    try:
        hist = db.get_ticker_history(ticker)
    except Exception:
        return _empty(ticker, signal_type, strategy_name)
    if hist is None or hist.empty:
        return _empty(ticker, signal_type, strategy_name)
    h = hist.copy()
    h["date"] = pd.to_datetime(h["date"]).dt.date

    pls: list[float] = []
    last_fire: Optional[date] = None
    for _, row in h.iterrows():
        d: date = row["date"]
        if last_fire is not None and (d - last_fire).days < cooldown_days:
            continue
        if not _trigger_fired(row, signal_type):
            continue
        pl = simulate_signal_trade(db, ticker, d, strategy_name)
        if pl is None:
            continue
        pls.append(pl)
        last_fire = d
        if len(pls) >= max_events:
            break

    return _aggregate(pls, ticker, signal_type, strategy_name)


def _aggregate(pls: list[float], ticker: str,
               signal_type: str, strategy: str) -> SignalBacktest:
    n = len(pls)
    if n == 0:
        return _empty(ticker, signal_type, strategy)
    wins = [p for p in pls if p > 0]
    losses = [p for p in pls if p <= 0]
    mean = statistics.fmean(pls)
    med = statistics.median(pls)
    sd = statistics.pstdev(pls) if n > 1 else 0.0
    sharpe = (mean / sd) if sd > 0 else 0.0
    avg_win = statistics.fmean(wins) if wins else 0.0
    avg_loss = abs(statistics.fmean(losses)) if losses else 1e-6
    wl_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")
    return SignalBacktest(
        ticker=ticker, signal_type=signal_type, strategy=strategy,
        n_events=n, hit_rate=len(wins) / n,
        mean_pl_pct=mean, median_pl_pct=med,
        sharpe=sharpe, win_loss_ratio=wl_ratio,
    )


def _empty(ticker, signal_type, strategy) -> SignalBacktest:
    return SignalBacktest(
        ticker=ticker, signal_type=signal_type, strategy=strategy,
        n_events=0, hit_rate=0.0, mean_pl_pct=0.0, median_pl_pct=0.0,
        sharpe=0.0, win_loss_ratio=0.0,
    )


def edge_string(bt: SignalBacktest) -> str:
    """One-line edge summary for the signal card."""
    if bt.n_events == 0:
        return "no historical fires in DB yet"
    return (
        f"historical: {bt.hit_rate*100:.0f} % hit · "
        f"{bt.mean_pl_pct:+.0f} % avg · Sharpe {bt.sharpe:+.2f} · "
        f"n={bt.n_events}"
    )
