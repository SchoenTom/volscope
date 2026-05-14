"""
Portfolio performance — replay each open position from entry to today
to produce a daily mark-to-market equity curve.

Pure analytics. No Streamlit, no IO. Uses BSM as the pricing model
because we don't have a daily option-chain snapshot.

The replay is deterministic: given the same positions + price history
+ IV history, the equity curve is reproducible. That makes it suitable
for tests and for backtests (e.g. measuring how a recommended-trade
pipeline would have performed).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

import math
import pandas as pd

from volscope.analytics.black_scholes import bs_price


# ── Outputs ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PositionContribution:
    """Per-position contribution to total portfolio P&L (today)."""
    position_id:    int
    ticker:         str
    label:          str           # e.g. "PYPL $80 C 2028-05-09"
    contracts:      int
    entry_premium:  float
    current_value:  float
    pl_per_contract: float
    pl_total:       float
    pl_pct:         float


@dataclass(frozen=True)
class PerformanceResult:
    """Aggregate portfolio performance over time."""
    equity_curve:   pd.DataFrame    # date, total_value, pl_total, pl_pct
    contributions:  list[PositionContribution]
    total_invested: float
    total_value:    float
    total_pl:       float
    total_pl_pct:   float
    n_positions:    int
    inception:      Optional[date]
    last_date:      Optional[date]
    sharpe_252d:    Optional[float] = None
    max_drawdown_pct: Optional[float] = None


# ── Helpers ───────────────────────────────────────────────────────────

def _coerce_date(v) -> Optional[date]:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, date) and not isinstance(v, pd.Timestamp):
        return v
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _theoretical_premium(
    spot: float,
    strike: float,
    iv_pct: float,
    days_to_expiry: int,
    option_type: str,
    risk_free: float = 0.04,
) -> float:
    if spot <= 0 or strike <= 0 or iv_pct <= 0 or days_to_expiry <= 0:
        return 0.0
    T = days_to_expiry / 365.0
    iv_dec = iv_pct / 100.0
    return bs_price(spot, strike, T, risk_free, iv_dec, option_type=option_type)


def _max_drawdown_pct(values: pd.Series) -> Optional[float]:
    if values.empty:
        return None
    running_max = values.cummax()
    drawdown = (values - running_max) / running_max
    mn = float(drawdown.min())
    return mn * 100.0


def _sharpe(daily_returns: pd.Series, periods_per_year: int = 252) -> Optional[float]:
    if daily_returns.empty or len(daily_returns) < 5:
        return None
    mu = daily_returns.mean()
    sigma = daily_returns.std()
    if sigma == 0 or pd.isna(sigma):
        return None
    return float((mu / sigma) * (periods_per_year ** 0.5))


# ── Main computation ─────────────────────────────────────────────────

def compute_portfolio_performance(
    positions_df: pd.DataFrame,
    history_by_ticker: dict[str, pd.DataFrame],
    asof: Optional[date] = None,
) -> PerformanceResult:
    """
    Daily MTM equity curve + per-position contributions.

    Parameters
    ----------
    positions_df : DataFrame from db.get_positions(active_only=True).
                   Required columns: id, ticker, entry_date, expiry,
                   strike, option_type, contracts, entry_premium.
    history_by_ticker : ticker → daily_vol DataFrame slice. Must have
                        date, spot_price, iv_30d.
    asof : end-date for the replay (default today).

    Returns
    -------
    PerformanceResult with equity_curve, contributions, aggregate stats.
    Empty / mostly-empty positions yield a sensible empty result.
    """
    asof = asof or date.today()
    if positions_df is None or positions_df.empty:
        return PerformanceResult(
            equity_curve=pd.DataFrame(columns=["date", "total_value", "pl_total", "pl_pct"]),
            contributions=[], total_invested=0.0, total_value=0.0,
            total_pl=0.0, total_pl_pct=0.0, n_positions=0,
            inception=None, last_date=None,
        )

    # ── Replay each position ────────────────────────────────────────
    per_position_curves: list[pd.DataFrame] = []
    contributions: list[PositionContribution] = []
    total_invested = 0.0

    for _, row in positions_df.iterrows():
        pid           = int(row.get("id") or 0)
        ticker        = str(row.get("ticker") or "")
        entry_date    = _coerce_date(row.get("entry_date"))
        expiry        = _coerce_date(row.get("expiry"))
        strike        = _safe_float(row.get("strike"))
        contracts     = int(row.get("contracts") or 1)
        entry_premium = _safe_float(row.get("entry_premium")) or 0.0
        option_type   = str(row.get("option_type") or "call").lower()

        if not ticker or strike is None or expiry is None or entry_date is None:
            continue

        invested = entry_premium * contracts * 100
        total_invested += invested

        hist = history_by_ticker.get(ticker)
        if hist is None or hist.empty:
            continue
        h = hist.copy()
        h["date"] = pd.to_datetime(h["date"]).dt.date
        h = h.sort_values("date")
        h = h[(h["date"] >= entry_date) & (h["date"] <= asof)]
        if h.empty:
            continue

        # Daily MTM values for this position
        rows = []
        for _, hrow in h.iterrows():
            d = hrow["date"]
            spot = _safe_float(hrow.get("spot_price"))
            iv = _safe_float(hrow.get("iv_30d"))
            if spot is None or iv is None:
                continue
            dte = max(1, (expiry - d).days)
            premium = _theoretical_premium(spot, strike, iv, dte, option_type)
            rows.append({
                "date": d,
                "value": premium * contracts * 100,
                "pl":    (premium - entry_premium) * contracts * 100,
            })
        if not rows:
            continue
        pdf = pd.DataFrame(rows)
        pdf["position_id"] = pid
        per_position_curves.append(pdf)

        # Today's contribution snapshot
        last_row = pdf.iloc[-1]
        current_value = float(last_row["value"])
        pl_per_contract = (current_value / max(1, contracts) / 100) - entry_premium
        pl_total = float(last_row["pl"])
        pl_pct = (pl_total / invested * 100) if invested > 0 else 0.0
        label = f"{ticker} ${strike:.0f} {option_type[0].upper()} {expiry.isoformat()}"
        contributions.append(PositionContribution(
            position_id=pid, ticker=ticker, label=label, contracts=contracts,
            entry_premium=entry_premium, current_value=current_value,
            pl_per_contract=pl_per_contract, pl_total=pl_total, pl_pct=pl_pct,
        ))

    if not per_position_curves:
        return PerformanceResult(
            equity_curve=pd.DataFrame(columns=["date", "total_value", "pl_total", "pl_pct"]),
            contributions=[], total_invested=total_invested, total_value=0.0,
            total_pl=0.0, total_pl_pct=0.0, n_positions=int(len(positions_df)),
            inception=None, last_date=None,
        )

    # ── Aggregate to portfolio-level curve ──────────────────────────
    all_curves = pd.concat(per_position_curves, ignore_index=True)
    agg = (
        all_curves.groupby("date")
        .agg(total_value=("value", "sum"), pl_total=("pl", "sum"))
        .reset_index()
        .sort_values("date")
    )
    agg["pl_pct"] = (agg["pl_total"] / total_invested * 100) if total_invested > 0 else 0.0

    last = agg.iloc[-1]
    daily_returns = agg["total_value"].pct_change().dropna()
    perf = PerformanceResult(
        equity_curve=agg,
        contributions=sorted(contributions, key=lambda c: c.pl_total, reverse=True),
        total_invested=total_invested,
        total_value=float(last["total_value"]),
        total_pl=float(last["pl_total"]),
        total_pl_pct=float(last["pl_pct"]),
        n_positions=int(len(per_position_curves)),
        inception=agg["date"].iloc[0],
        last_date=last["date"],
        sharpe_252d=_sharpe(daily_returns),
        max_drawdown_pct=_max_drawdown_pct(agg["total_value"]),
    )
    return perf
