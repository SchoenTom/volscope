"""
Backtest Engine — "Was the Signal Right?"

For each historical row in a ticker's daily_vol history:
  1. Compute the VolSignal (BUY/LEAN_BUY/WAIT/LEAN_RICH/RICH) from the
     IV percentile and VRP that existed *on that date*.
  2. Look ahead `hold_days` rows and record what iv_30d actually did.
  3. A BUY signal is a "hit" when IV fell; a RICH signal hits when IV rose.

Metrics returned in BacktestResult:
  - hit_rate per category (fraction of signals where IV moved the "right" way)
  - avg_iv_change_pct per category (mean % change in iv_30d over the hold period)
  - max_drawdown_pct per buy category (worst peak IV spike during the hold window,
    expressed as % rise from entry — negative = IV never spiked above entry)
  - n_signals per category
  - signals_df — full row-level annotated DataFrame for chart rendering

Dependencies: numpy, pandas, volscope.analytics.signal.
No scipy, no internet, no DB access — pass history_df in directly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from volscope.analytics.signal import compute_signal


# ── Tuning ────────────────────────────────────────────────────────────────────
_MIN_ROWS = 20      # require at least this many rows after the hold window
_ROLLING_WIN = 63   # ~3 calendar months of trading days for rolling hit rate


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """
    Full backtest output for a single ticker.

    Attributes
    ----------
    ticker        : Ticker symbol (empty string if not provided).
    hold_days     : Forecast horizon — how many trading rows ahead we measured.
    n_total       : Total signal instances evaluated (all categories).
    signals_df    : Row-level DataFrame. Columns:
                    date, signal_cat, signal_label,
                    iv_entry, iv_exit, iv_change_pct, hit,
                    max_iv_drawdown_pct
    hit_rates     : {category: float} fraction of signals where IV moved in the
                    predicted direction. NaN when category has no instances.
    avg_iv_changes: {category: float} mean iv_30d % change over hold period.
    max_drawdowns : {category: float} for BUY categories only — worst peak IV
                    rise during the hold window as % of iv_entry. NaN otherwise.
    n_signals     : {category: int} count of instances per category.
    """

    ticker: str
    hold_days: int
    n_total: int
    signals_df: pd.DataFrame
    hit_rates: dict
    avg_iv_changes: dict
    max_drawdowns: dict
    n_signals: dict


# ── Category ordering ─────────────────────────────────────────────────────────
ALL_CATEGORIES = ("buy", "lean_buy", "neutral", "lean_rich", "rich")


# ── Core computation ──────────────────────────────────────────────────────────

def run_backtest(
    history_df: pd.DataFrame,
    ticker: str = "",
    hold_days: int = 10,
) -> Optional[BacktestResult]:
    """
    Run a signal-conditional IV backtest on a daily_vol history DataFrame.

    Parameters
    ----------
    history_df : daily_vol rows — must contain date, iv_30d, hv_20d,
                 iv_percentile. Extra columns are ignored.
    ticker     : Ticker symbol for the result label.
    hold_days  : Trading rows to look ahead for the IV outcome.

    Returns
    -------
    BacktestResult, or None when there is not enough data (< hold_days + _MIN_ROWS).
    """
    if history_df is None or history_df.empty:
        return None
    if len(history_df) < hold_days + _MIN_ROWS:
        return None

    h = history_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(h["date"]):
        h["date"] = pd.to_datetime(h["date"])
    h = h.sort_values("date").reset_index(drop=True)

    rows = []
    for i in range(len(h) - hold_days):
        row = h.iloc[i]
        future = h.iloc[i + hold_days]

        iv_entry = _safe(row.get("iv_30d"))
        iv_exit  = _safe(future.get("iv_30d"))
        iv_perc  = row.get("iv_percentile")
        hv_20d   = row.get("hv_20d")

        if iv_entry is None or iv_exit is None or iv_entry <= 0:
            continue

        signal = compute_signal(iv_perc, iv_entry, hv_20d)
        iv_change_pct = (iv_exit - iv_entry) / iv_entry * 100.0

        cat = signal.category
        # Hit definition: directionally correct signal
        if cat in ("buy", "lean_buy"):
            hit: Optional[bool] = iv_change_pct < 0
        elif cat in ("rich", "lean_rich"):
            hit = iv_change_pct > 0
        else:
            hit = None  # WAIT / NO DATA — no directional claim

        # Max IV run-up during hold window (% above entry), BUY signals only
        max_iv_drawdown_pct: Optional[float] = None
        if cat in ("buy", "lean_buy"):
            window_ivs = h.iloc[i : i + hold_days + 1]["iv_30d"].dropna()
            if not window_ivs.empty:
                peak = float(window_ivs.max())
                max_iv_drawdown_pct = (peak - iv_entry) / iv_entry * 100.0

        rows.append(
            {
                "date": row["date"],
                "signal_cat": cat,
                "signal_label": signal.label,
                "iv_entry": iv_entry,
                "iv_exit": iv_exit,
                "iv_change_pct": iv_change_pct,
                "hit": hit,
                "max_iv_drawdown_pct": max_iv_drawdown_pct,
            }
        )

    if not rows:
        return None

    signals_df = pd.DataFrame(rows)

    hit_rates: dict = {}
    avg_iv_changes: dict = {}
    max_drawdowns: dict = {}
    n_signals: dict = {}

    for cat in ALL_CATEGORIES:
        sub = signals_df[signals_df["signal_cat"] == cat]
        n_signals[cat] = len(sub)
        if sub.empty:
            hit_rates[cat] = float("nan")
            avg_iv_changes[cat] = float("nan")
            max_drawdowns[cat] = float("nan")
            continue
        avg_iv_changes[cat] = float(sub["iv_change_pct"].mean())
        hits = sub["hit"].dropna()
        hit_rates[cat] = float(hits.mean()) if len(hits) > 0 else float("nan")
        if cat in ("buy", "lean_buy"):
            md = sub["max_iv_drawdown_pct"].dropna()
            max_drawdowns[cat] = float(md.max()) if len(md) > 0 else float("nan")
        else:
            max_drawdowns[cat] = float("nan")

    return BacktestResult(
        ticker=ticker,
        hold_days=hold_days,
        n_total=len(signals_df),
        signals_df=signals_df,
        hit_rates=hit_rates,
        avg_iv_changes=avg_iv_changes,
        max_drawdowns=max_drawdowns,
        n_signals=n_signals,
    )


def rolling_hit_rate(signals_df: pd.DataFrame, window: int = _ROLLING_WIN) -> pd.DataFrame:
    """
    Compute rolling hit rate for BUY signals (buy + lean_buy) over a trading-row window.

    Parameters
    ----------
    signals_df : BacktestResult.signals_df (must have date, signal_cat, hit columns).
    window     : Rolling window in trading rows.

    Returns
    -------
    DataFrame with columns date and hit_rate (NaN when window has < 5 hits).
    """
    buy_mask = signals_df["signal_cat"].isin(("buy", "lean_buy"))
    buy_df = signals_df[buy_mask].copy()
    if buy_df.empty:
        return pd.DataFrame(columns=["date", "hit_rate"])
    buy_df = buy_df.sort_values("date").reset_index(drop=True)
    buy_df["hit_float"] = buy_df["hit"].astype(float)
    buy_df["hit_rate"] = (
        buy_df["hit_float"]
        .rolling(window, min_periods=max(5, window // 4))
        .mean()
    )
    return buy_df[["date", "hit_rate"]].dropna(subset=["hit_rate"])


def bootstrap_ci(
    values: list[float] | "pd.Series",
    n_resamples: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float]:
    """
    Bootstrap confidence interval for the mean of `values`.

    Returns ``(point, lo, hi)`` — the sample mean plus the lower/upper
    bound of the percentile-bootstrap interval. Empty input → all NaN.
    Used by the Scope-Backtest UI to show whether a signal's average
    return is statistically distinguishable from zero.
    """
    import numpy as np

    arr = np.asarray(list(values), dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        nan = float("nan")
        return (nan, nan, nan)
    rng = np.random.default_rng(seed)
    samples = rng.choice(arr, size=(n_resamples, arr.size), replace=True)
    means = samples.mean(axis=1)
    lo, hi = np.percentile(means, [(1 - ci) / 2 * 100, (1 + ci) / 2 * 100])
    return (float(arr.mean()), float(lo), float(hi))


def naive_baseline_hit_rate(signals_df: pd.DataFrame) -> float:
    """
    Naive long-vol baseline — what hit-rate would a strategy get that
    bought vol on EVERY day, regardless of signal? Equal to the
    fraction of days where iv_30d fell over the hold window. Used as a
    null hypothesis: a real signal must beat this.
    """
    if signals_df is None or signals_df.empty or "iv_change_pct" not in signals_df.columns:
        return float("nan")
    s = signals_df["iv_change_pct"].dropna()
    if s.empty:
        return float("nan")
    return float((s < 0).mean())


def build_calibration_table(result: BacktestResult) -> pd.DataFrame:
    """
    Build a human-readable calibration summary DataFrame for the Backtest tab.

    Columns: Signal, N, Hit Rate, Avg IV Δ%, Max Spike%
    """
    labels = {
        "buy":       "BUY VOL",
        "lean_buy":  "LEAN BUY",
        "neutral":   "WAIT",
        "lean_rich": "LEAN RICH",
        "rich":      "RICH",
    }
    rows = []
    for cat in ALL_CATEGORIES:
        n = result.n_signals.get(cat, 0)
        if n == 0:
            continue
        hr = result.hit_rates.get(cat, float("nan"))
        avg_chg = result.avg_iv_changes.get(cat, float("nan"))
        max_dd  = result.max_drawdowns.get(cat, float("nan"))
        rows.append(
            {
                "Signal":     labels[cat],
                "N":          n,
                "Hit Rate":   f"{hr * 100:.0f}%" if not math.isnan(hr) else "—",
                "Avg IV Δ%":  f"{avg_chg:+.1f}%" if not math.isnan(avg_chg) else "—",
                "Max Spike%": f"{max_dd:+.1f}%" if not math.isnan(max_dd) else "—",
            }
        )
    return pd.DataFrame(rows)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(v: object) -> Optional[float]:
    """Return float if finite, else None."""
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None
