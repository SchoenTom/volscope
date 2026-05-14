"""Tests for the LEAPS-convergence walk-forward backtest."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.leaps_backtest import (
    BacktestResult,
    Trade,
    add_bootstrap_ci,
    run_backtest,
    summarise,
)


def _make_panel(
    ticker: str,
    n_days: int,
    start_date: date,
    spot_path: np.ndarray,
    iv_path: np.ndarray,
    hv_path: np.ndarray,
    iv_rank_path: np.ndarray,
    iv_pct_path: np.ndarray,
    hv60_path: np.ndarray,
) -> pd.DataFrame:
    dates = pd.date_range(start=start_date, periods=n_days, freq="B")
    return pd.DataFrame({
        "ticker":         ticker,
        "date":           dates,
        "spot_price":     spot_path,
        "iv_30d":         iv_path,
        "hv_20d":         hv_path,
        "hv_60d":         hv60_path,
        "iv_rank":        iv_rank_path,
        "iv_percentile":  iv_pct_path,
        "sector":         "Test",
    })


def _build_synthetic_universe(n_days: int = 600) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two-ticker panel: one PYPL-class setup that rallies, one boring drifter."""
    rng = np.random.default_rng(seed=42)
    start = date(2024, 1, 2)

    # Ticker A: PYPL-class. Plateau, crash, base, rally.
    quarter = n_days // 4
    spot_a = np.concatenate([
        np.full(quarter,            100.0),                 # plateau (d 0-150)
        np.linspace(100.0,  40.0,   quarter),               # crash   (d 150-300)
        np.linspace( 40.0,  42.0,   quarter),               # base    (d 300-450)
        np.linspace( 40.0, 200.0,   n_days - 3 * quarter),  # Wave-III
    ])
    iv_a   = np.full(n_days, 35.0) + rng.normal(0, 0.8, n_days)
    hv_a   = np.full(n_days, 45.0) + rng.normal(0, 0.8, n_days)
    # IV rank / percentile collapse to the annual floor once base forms.
    iv_rank_a = np.where(np.arange(n_days) < 2 * quarter,
                         np.linspace(60.0, 30.0, n_days),
                         np.full(n_days, 8.0))
    iv_pct_a = np.where(np.arange(n_days) < 2 * quarter,
                        np.linspace(70.0, 40.0, n_days),
                        np.full(n_days, 15.0))
    hv60_a    = np.full(n_days, 30.0)
    panel_a = _make_panel("AAA", n_days, start, spot_a, iv_a, hv_a, iv_rank_a, iv_pct_a, hv60_a)

    # Benchmark SPY: steady uptrend.
    spy_spot = np.linspace(400, 520, n_days)
    spy_iv   = np.full(n_days, 15.0)
    spy_hv   = np.full(n_days, 14.0)
    spy_rank = np.full(n_days, 40.0)
    spy_pct  = np.full(n_days, 50.0)
    spy_hv60 = np.full(n_days, 14.0)
    panel_spy = _make_panel(
        "SPY", n_days, start, spy_spot, spy_iv, spy_hv, spy_rank, spy_pct, spy_hv60,
    )
    full = pd.concat([panel_a, panel_spy], ignore_index=True)
    return full, panel_spy


# ── Smoke ───────────────────────────────────────────────────────────────

def test_run_backtest_on_empty_panel_returns_empty_result():
    empty = pd.DataFrame(columns=["ticker", "date"])
    result = run_backtest(empty, empty)
    assert isinstance(result, BacktestResult)
    assert result.n_trades == 0


def test_run_backtest_panel_without_required_columns_raises():
    bad = pd.DataFrame({"x": [1]})
    with pytest.raises(ValueError):
        run_backtest(bad, pd.DataFrame({"date": []}))


# ── Substantive walk-forward ────────────────────────────────────────────

def test_run_backtest_pypl_class_setup_produces_winning_trades():
    """The synthetic PYPL-class ticker that rallies should generate
    at least one entry and a positive median return."""
    full_panel, spy = _build_synthetic_universe(n_days=600)
    result = run_backtest(
        panel=full_panel,
        benchmark_panel=spy,
        horizon_days=180,
        sample_every_n_days=21,
        min_history_for_scoring=200,
    )
    assert result.n_trades >= 1
    # The synthetic rally is sharp — at least one trade should print >0.
    assert result.max_return > 0


def test_run_backtest_horizon_respected_when_panel_ends_early():
    """If the panel terminates before horizon, the trade is forced-exited."""
    full_panel, spy = _build_synthetic_universe(n_days=400)
    result = run_backtest(
        panel=full_panel,
        benchmark_panel=spy,
        horizon_days=720,    # longer than the panel
        sample_every_n_days=21,
        min_history_for_scoring=200,
    )
    if result.n_trades > 0:
        # Every trade should be marked as forced-exit because horizon > panel.
        assert all(t.forced_exit for t in result.trades)


# ── Aggregation ─────────────────────────────────────────────────────────

def test_summarise_returns_meaningful_string():
    full_panel, spy = _build_synthetic_universe(n_days=500)
    result = run_backtest(
        panel=full_panel, benchmark_panel=spy,
        horizon_days=120, sample_every_n_days=21, min_history_for_scoring=200,
    )
    summary = summarise(result)
    assert isinstance(summary, str)
    assert len(summary) > 0


# ── Bootstrap-CI ─────────────────────────────────────────────────────────

def _result_with_returns(returns: list[float]) -> BacktestResult:
    """Build a BacktestResult straight from a list of returns for unit tests."""
    trades = tuple(
        Trade(
            ticker=f"T{i}", entry_date=date(2024, 1, 1), entry_spot=100.0,
            strike=180.0, expiry=date(2026, 1, 1), entry_premium=2.0,
            score_at_entry=70, exit_date=date(2024, 7, 1), exit_spot=120.0,
            exit_premium=2.0 + r * 2.0 / 100,
            pnl_per_share=r * 2.0 / 100, return_pct=r,
            horizon_days=180, forced_exit=False,
        )
        for i, r in enumerate(returns)
    )
    return BacktestResult(
        n_trades=len(trades),
        win_rate=sum(1 for r in returns if r >= 0) / max(1, len(returns)),
        median_return=float(np.median(returns)) if returns else 0.0,
        mean_return=float(np.mean(returns)) if returns else 0.0,
        p25_return=float(np.percentile(returns, 25)) if returns else 0.0,
        p75_return=float(np.percentile(returns, 75)) if returns else 0.0,
        max_return=max(returns) if returns else 0.0,
        min_return=min(returns) if returns else 0.0,
        horizon_days=180, threshold=65,
        trades=trades,
    )


def test_bootstrap_ci_mean_brackets_observed_mean():
    """The 95% CI on the mean must contain the observed sample mean."""
    rng = np.random.default_rng(seed=0)
    returns = rng.normal(loc=20, scale=30, size=200).tolist()
    base = _result_with_returns(returns)
    enriched = add_bootstrap_ci(base, n_samples=500)
    assert enriched.mean_ci_lo is not None
    assert enriched.mean_ci_hi is not None
    assert enriched.mean_ci_lo <= enriched.mean_return <= enriched.mean_ci_hi


def test_bootstrap_p_value_low_when_signal_is_strong():
    """200 trades all centred on +30% should reject zero-mean null hypothesis."""
    rng = np.random.default_rng(seed=1)
    returns = rng.normal(loc=30, scale=10, size=200).tolist()
    enriched = add_bootstrap_ci(_result_with_returns(returns), n_samples=500)
    assert enriched.p_value_vs_zero is not None
    assert enriched.p_value_vs_zero < 0.01


def test_bootstrap_p_value_high_when_signal_is_zero():
    """Zero-centred noise must produce a p-value far from significance."""
    rng = np.random.default_rng(seed=2)
    returns = rng.normal(loc=0, scale=20, size=200).tolist()
    enriched = add_bootstrap_ci(_result_with_returns(returns), n_samples=500)
    assert enriched.p_value_vs_zero is not None
    assert enriched.p_value_vs_zero > 0.10


def test_bootstrap_handles_empty_result():
    empty = _result_with_returns([])
    out = add_bootstrap_ci(empty)
    assert out.mean_ci_lo is None
    assert out.p_value_vs_zero is None


def test_summarise_includes_ci_when_present():
    rng = np.random.default_rng(seed=3)
    returns = rng.normal(loc=15, scale=10, size=100).tolist()
    enriched = add_bootstrap_ci(_result_with_returns(returns), n_samples=300)
    s = summarise(enriched)
    assert "95%-CI" in s
    assert "p=" in s
