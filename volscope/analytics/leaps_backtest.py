"""
Walk-forward backtest of the LEAPS-convergence rule.

For every historical day in the daily_vol panel, score every ticker and
simulate buying a deep-OTM call at the BSM-modelled price when the
composite score crosses ``CONVERGENCE_THRESHOLD``. Hold for fixed
horizons (3 m / 6 m / 12 m / 24 m) or until expiry, whichever comes
first. Record terminal P&L using the ticker's actually-realised spot
path.

This is the "X % of the time it worked" credibility lift the dossier
quotes. Survivorship-bias-aware: any ticker that drops out of the panel
mid-window is recorded as a force-exit at the last observed spot, so
delisted names are not silently retired into the win bucket.

Pure analytics. The CLI in ``scripts/backtest/run_leaps_backtest.py`` and the
dossier mini-chart both call ``run_backtest``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from volscope.analytics.black_scholes import bs_price
from volscope.analytics.leaps_convergence import (
    CONVERGENCE_THRESHOLD,
    compute_convergence,
    suggest_leaps,
)


# ── Public dataclasses ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Trade:
    """One simulated convergence-triggered LEAPS trade."""

    ticker:        str
    entry_date:    date
    entry_spot:    float
    strike:        float
    expiry:        date
    entry_premium: float
    score_at_entry: float
    exit_date:     date
    exit_spot:     float
    exit_premium:  float
    pnl_per_share: float
    return_pct:    float
    horizon_days:  int
    forced_exit:   bool       # True if survivorship cut closed the trade


@dataclass(frozen=True)
class BacktestResult:
    """Aggregate result of one backtest run.

    The bootstrap fields are populated by :func:`add_bootstrap_ci` so the
    main run path is fast (no resampling) and statistical inference is an
    explicit second step. ``mean_ci_lo`` / ``mean_ci_hi`` are the bounds
    of a 95 % bootstrap CI on the trade-mean return.
    """

    n_trades:       int
    win_rate:       float                # fraction of trades with return ≥ 0
    median_return:  float
    mean_return:    float
    p25_return:     float
    p75_return:     float
    max_return:     float
    min_return:     float
    horizon_days:   int
    threshold:      float
    trades:         tuple[Trade, ...]
    by_year:        dict[int, dict[str, float]] = field(default_factory=dict)
    # Statistical inference (filled by add_bootstrap_ci)
    mean_ci_lo:     Optional[float] = None
    mean_ci_hi:     Optional[float] = None
    win_rate_ci_lo: Optional[float] = None
    win_rate_ci_hi: Optional[float] = None
    p_value_vs_zero:        Optional[float] = None   # bootstrap two-sided test mean ≠ 0
    bootstrap_n_samples:    Optional[int]   = None


# ── Core simulation ──────────────────────────────────────────────────────

def run_backtest(
    panel: pd.DataFrame,
    benchmark_panel: pd.DataFrame,
    horizon_days: int = 365,
    threshold: float = CONVERGENCE_THRESHOLD,
    target_dte_days: int = 730,
    strike_uplift: float = 0.75,
    risk_free: float = 0.04,
    div_yield: float = 0.0,
    sample_every_n_days: int = 21,    # monthly resampling — ~12 entry windows / yr
    min_history_for_scoring: int = 252,
    benchmark_ticker: str = "SPY",
) -> BacktestResult:
    """Walk-forward backtest of the convergence rule.

    Parameters
    ----------
    panel
        Long-format DataFrame with at minimum columns
        ``[ticker, date, spot_price, iv_30d, hv_20d, hv_60d, iv_rank, iv_percentile]``.
        Use ``db.con.execute('SELECT * FROM daily_vol').fetchdf()`` to load.
    benchmark_panel
        Same shape but for the benchmark ticker (``SPY`` by default).
    horizon_days
        How long to hold each entry. 365 = one-year P&L snapshot.
    sample_every_n_days
        Don't score every single day — that floods the result with
        near-duplicate entries. 21 ≈ once-per-month resampling.
    """
    if panel is None or panel.empty:
        return _empty_result(horizon_days, threshold)
    if "date" not in panel.columns or "ticker" not in panel.columns:
        raise ValueError("panel must have 'date' and 'ticker' columns")
    panel = panel.sort_values(["ticker", "date"]).copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.date

    benchmark_panel = benchmark_panel.sort_values("date").copy()
    benchmark_panel["date"] = pd.to_datetime(benchmark_panel["date"]).dt.date

    # Build per-ticker history index for cheap slicing.
    panel_by_ticker: dict[str, pd.DataFrame] = {
        t: g.reset_index(drop=True) for t, g in panel.groupby("ticker")
    }

    # Sample entry dates.
    all_dates = sorted(panel["date"].unique())
    if not all_dates:
        return _empty_result(horizon_days, threshold)
    entry_dates = all_dates[::sample_every_n_days]

    trades: list[Trade] = []
    for entry_date in entry_dates:
        bench_hist = benchmark_panel[benchmark_panel["date"] <= entry_date]
        if len(bench_hist) < min_history_for_scoring // 2:
            continue
        for ticker, ticker_panel in panel_by_ticker.items():
            if ticker == benchmark_ticker:
                continue
            hist = ticker_panel[ticker_panel["date"] <= entry_date]
            if len(hist) < min_history_for_scoring:
                continue
            row = hist.iloc[-1]
            result = compute_convergence(row, hist, bench_hist)
            if result.score < threshold:
                continue

            spot = row.get("spot_price")
            iv30 = row.get("iv_30d")
            if (
                spot is None or iv30 is None
                or pd.isna(spot) or pd.isna(iv30)
                or float(spot) <= 0 or float(iv30) <= 0
            ):
                continue
            suggestion = suggest_leaps(
                ticker=ticker,
                spot=float(spot),
                iv=float(iv30) / 100.0,
                target_dte_days=target_dte_days,
                strike_uplift=strike_uplift,
                risk_free=risk_free,
                div_yield=div_yield,
                today=entry_date,
            )
            if suggestion is None:
                continue

            # Walk forward to the exit.
            exit_target = entry_date + timedelta(days=horizon_days)
            forward = ticker_panel[
                (ticker_panel["date"] > entry_date)
                & (ticker_panel["date"] <= exit_target)
            ]
            forced_exit = False
            if forward.empty:
                # No forward data at all — likely delisted right after entry.
                continue
            if forward["date"].iloc[-1] < exit_target:
                # Survivorship-bias guard: if the panel ends before the
                # horizon, force-exit at the last observed price.
                forced_exit = True

            exit_row = forward.iloc[-1]
            exit_date = exit_row["date"]
            exit_spot = float(exit_row.get("spot_price") or 0.0)
            exit_iv = exit_row.get("iv_30d")

            # Reprice the LEAPS at exit using residual time-to-expiry.
            days_held = (exit_date - entry_date).days
            days_to_exp_remaining = max(0, suggestion.days_to_exp - days_held)
            T_exit = days_to_exp_remaining / 365.0
            sigma_exit = (
                float(exit_iv) / 100.0 if exit_iv is not None and not pd.isna(exit_iv)
                else suggestion.iv
            )
            if T_exit <= 0 or sigma_exit <= 0:
                exit_premium = max(0.0, exit_spot - suggestion.strike)
            else:
                exit_premium = bs_price(
                    exit_spot, suggestion.strike, T_exit,
                    risk_free, sigma_exit, div_yield, "call",
                )

            pnl_per_share = exit_premium - suggestion.est_premium
            return_pct = (
                (pnl_per_share / suggestion.est_premium) * 100.0
                if suggestion.est_premium > 0 else 0.0
            )
            trades.append(Trade(
                ticker=ticker,
                entry_date=entry_date,
                entry_spot=round(float(spot), 2),
                strike=float(suggestion.strike),
                expiry=suggestion.expiry,
                entry_premium=round(suggestion.est_premium, 3),
                score_at_entry=round(result.score, 1),
                exit_date=exit_date,
                exit_spot=round(exit_spot, 2),
                exit_premium=round(exit_premium, 3),
                pnl_per_share=round(pnl_per_share, 3),
                return_pct=round(return_pct, 1),
                horizon_days=days_held,
                forced_exit=forced_exit,
            ))

    return _aggregate(trades, horizon_days, threshold)


# ── Aggregation ──────────────────────────────────────────────────────────

def _aggregate(trades: list[Trade], horizon_days: int, threshold: float) -> BacktestResult:
    if not trades:
        return _empty_result(horizon_days, threshold)
    returns = np.array([t.return_pct for t in trades], dtype=float)
    by_year: dict[int, dict[str, float]] = {}
    df_trades = pd.DataFrame([t.__dict__ for t in trades])
    df_trades["entry_year"] = df_trades["entry_date"].apply(lambda d: d.year)
    for year, sub in df_trades.groupby("entry_year"):
        sub_ret = sub["return_pct"].astype(float)
        by_year[int(year)] = {
            "n":           int(len(sub_ret)),
            "win_rate":    float((sub_ret >= 0).mean()),
            "median":      float(sub_ret.median()),
            "mean":        float(sub_ret.mean()),
        }
    return BacktestResult(
        n_trades=len(trades),
        win_rate=float((returns >= 0).mean()),
        median_return=float(np.median(returns)),
        mean_return=float(np.mean(returns)),
        p25_return=float(np.percentile(returns, 25)),
        p75_return=float(np.percentile(returns, 75)),
        max_return=float(np.max(returns)),
        min_return=float(np.min(returns)),
        horizon_days=horizon_days,
        threshold=threshold,
        trades=tuple(trades),
        by_year=by_year,
    )


def _empty_result(horizon_days: int, threshold: float) -> BacktestResult:
    return BacktestResult(
        n_trades=0,
        win_rate=0.0, median_return=0.0, mean_return=0.0,
        p25_return=0.0, p75_return=0.0, max_return=0.0, min_return=0.0,
        horizon_days=horizon_days, threshold=threshold,
        trades=tuple(),
    )


def summarise(result: BacktestResult) -> str:
    """Trader-facing one-paragraph summary."""
    if result.n_trades == 0:
        return f"backtest produced 0 trades at threshold ≥ {result.threshold:.0f}"
    base = (
        f"{result.n_trades} trades · {result.win_rate*100:.0f}% with non-negative "
        f"return at {result.horizon_days}d hold · median {result.median_return:+.0f}% "
        f"· p25 {result.p25_return:+.0f}% / p75 {result.p75_return:+.0f}%"
    )
    if result.mean_ci_lo is not None and result.mean_ci_hi is not None:
        base += (
            f" · mean 95%-CI [{result.mean_ci_lo:+.0f}%, {result.mean_ci_hi:+.0f}%]"
        )
    if result.p_value_vs_zero is not None:
        base += f" · p={result.p_value_vs_zero:.3f}"
    return base


# ── Statistical inference ────────────────────────────────────────────────

def add_bootstrap_ci(
    result: BacktestResult,
    n_samples: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> BacktestResult:
    """Append bootstrap-CI bounds and a p-value to a ``BacktestResult``.

    Resamples the observed trade-returns ``n_samples`` times with
    replacement. Reports:

    - 95 % CI on the *mean* return (lower/upper percentile of resampled means)
    - 95 % CI on the *win rate* (fraction of non-negative trades)
    - p-value (two-sided) for ``H0: mean_return = 0`` — the empirical
      probability that a sample mean is at least as extreme as zero on
      the null distribution centred on zero.

    Returns a new ``BacktestResult`` with the inference fields filled.
    Original is unmodified — dataclass is frozen.
    """
    if result.n_trades == 0:
        return result
    returns = np.array([t.return_pct for t in result.trades], dtype=float)
    rng = np.random.default_rng(seed=seed)
    samples = rng.choice(returns, size=(n_samples, len(returns)), replace=True)
    means = samples.mean(axis=1)
    win_rates = (samples >= 0).mean(axis=1)

    lo_pct = (1.0 - ci) / 2.0 * 100.0
    hi_pct = (1.0 + ci) / 2.0 * 100.0

    mean_lo, mean_hi = float(np.percentile(means, [lo_pct, hi_pct])[0]), float(np.percentile(means, [lo_pct, hi_pct])[1])
    wr_lo,   wr_hi   = float(np.percentile(win_rates, [lo_pct, hi_pct])[0]), float(np.percentile(win_rates, [lo_pct, hi_pct])[1])

    # Two-sided p-value: probability that |sample-mean| ≥ |observed-mean|
    # under a null distribution constructed by recentering returns at zero
    # and resampling. This is the standard non-parametric bootstrap test.
    centred = returns - returns.mean()
    null_samples = rng.choice(centred, size=(n_samples, len(returns)), replace=True)
    null_means = null_samples.mean(axis=1)
    p_value = float((np.abs(null_means) >= abs(returns.mean())).mean())

    # Rebuild the dataclass — frozen, so we can't mutate.
    return BacktestResult(
        **{**result.__dict__,
           "mean_ci_lo":     round(mean_lo, 2),
           "mean_ci_hi":     round(mean_hi, 2),
           "win_rate_ci_lo": round(wr_lo, 4),
           "win_rate_ci_hi": round(wr_hi, 4),
           "p_value_vs_zero": round(p_value, 4),
           "bootstrap_n_samples": int(n_samples)}
    )
