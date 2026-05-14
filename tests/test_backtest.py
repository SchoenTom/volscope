"""
Tests for volscope.analytics.backtest — signal-conditional IV backtest engine.

Covers:
  - run_backtest()           edge cases, output contract, metric computation
  - BacktestResult           dataclass fields
  - rolling_hit_rate()       windowed BUY hit-rate time series
  - build_calibration_table() human-readable summary DataFrame
  - create_backtest_hit_rate_chart()     chart builder smoke tests
  - create_backtest_distribution_chart() chart builder smoke tests
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from volscope.analytics.backtest import (
    ALL_CATEGORIES,
    BacktestResult,
    _safe,
    build_calibration_table,
    rolling_hit_rate,
    run_backtest,
)
from volscope.ui.components.chart_builders import (
    create_backtest_distribution_chart,
    create_backtest_hit_rate_chart,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hist(
    n: int,
    iv_start: float = 25.0,
    iv_trend: float = 0.0,
    hv: float = 20.0,
    perc_start: float = 50.0,
) -> pd.DataFrame:
    """Synthetic daily_vol DataFrame with n rows."""
    today = date(2024, 1, 1)
    dates = [today + timedelta(days=i) for i in range(n)]
    iv = [max(1.0, iv_start + iv_trend * i) for i in range(n)]
    perc = [max(0.0, min(100.0, perc_start)) for _ in range(n)]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "iv_30d": iv,
            "hv_20d": [hv] * n,
            "iv_percentile": perc,
            "iv_rank": perc,
        }
    )


def _cheap_hist(n: int = 60) -> pd.DataFrame:
    """History where IV is historically cheap (perc=10) and cheaper than HV."""
    return _hist(n, iv_start=15.0, iv_trend=-0.05, hv=20.0, perc_start=10.0)


def _rich_hist(n: int = 60) -> pd.DataFrame:
    """History where IV is historically expensive (perc=85) and above HV."""
    return _hist(n, iv_start=30.0, iv_trend=0.05, hv=20.0, perc_start=85.0)


# ---------------------------------------------------------------------------
# _safe helper
# ---------------------------------------------------------------------------

class TestSafeHelper:
    def test_none_returns_none(self):
        assert _safe(None) is None

    def test_nan_returns_none(self):
        assert _safe(float("nan")) is None

    def test_inf_returns_none(self):
        assert _safe(float("inf")) is None

    def test_valid_float(self):
        assert _safe(3.14) == pytest.approx(3.14)

    def test_string_float(self):
        assert _safe("25.0") == pytest.approx(25.0)

    def test_zero(self):
        assert _safe(0.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# run_backtest — edge cases
# ---------------------------------------------------------------------------

class TestRunBacktestEdgeCases:
    def test_none_input_returns_none(self):
        assert run_backtest(None) is None  # type: ignore[arg-type]

    def test_empty_df_returns_none(self):
        assert run_backtest(pd.DataFrame()) is None

    def test_too_few_rows_returns_none(self):
        df = _hist(15)  # hold_days=10 + _MIN_ROWS=20 = 30 needed
        assert run_backtest(df, hold_days=10) is None

    def test_sufficient_rows_returns_result(self):
        df = _hist(60)
        result = run_backtest(df, hold_days=10)
        assert result is not None

    def test_all_nan_iv_returns_none(self):
        df = _hist(60)
        df["iv_30d"] = float("nan")
        result = run_backtest(df, hold_days=10)
        assert result is None

    def test_zero_iv_excluded(self):
        """Rows with iv_30d <= 0 should be skipped; all-zero IV → no valid signals."""
        df = _hist(60)
        df["iv_30d"] = 0.0  # zero IV → excluded (division by zero guard)
        result = run_backtest(df, hold_days=10)
        assert result is None


# ---------------------------------------------------------------------------
# run_backtest — output contract
# ---------------------------------------------------------------------------

class TestRunBacktestOutputContract:
    def setup_method(self):
        self.result = run_backtest(_hist(80), ticker="TEST", hold_days=10)

    def test_returns_backtest_result(self):
        assert isinstance(self.result, BacktestResult)

    def test_ticker_field(self):
        assert self.result.ticker == "TEST"

    def test_hold_days_field(self):
        assert self.result.hold_days == 10

    def test_n_total_positive(self):
        assert self.result.n_total > 0

    def test_signals_df_is_dataframe(self):
        assert isinstance(self.result.signals_df, pd.DataFrame)

    def test_signals_df_required_columns(self):
        cols = self.result.signals_df.columns.tolist()
        for c in ("date", "signal_cat", "signal_label", "iv_entry", "iv_exit",
                  "iv_change_pct", "hit"):
            assert c in cols, f"Missing column: {c}"

    def test_hit_rates_all_categories(self):
        for cat in ALL_CATEGORIES:
            assert cat in self.result.hit_rates

    def test_avg_iv_changes_all_categories(self):
        for cat in ALL_CATEGORIES:
            assert cat in self.result.avg_iv_changes

    def test_n_signals_all_categories(self):
        for cat in ALL_CATEGORIES:
            assert cat in self.result.n_signals

    def test_n_total_matches_signals_df(self):
        assert self.result.n_total == len(self.result.signals_df)

    def test_hit_rates_in_0_1(self):
        for cat, hr in self.result.hit_rates.items():
            if not math.isnan(hr):
                assert 0.0 <= hr <= 1.0, f"{cat}: {hr}"


# ---------------------------------------------------------------------------
# run_backtest — metric correctness on controlled data
# ---------------------------------------------------------------------------

class TestHitRateComputation:
    def test_buy_signal_hit_when_iv_falls(self):
        """When IV steadily falls from a cheap starting point, BUY signals should hit."""
        # IV starts at 15 (cheap vs HV=20, perc=10) and falls → every signal hits
        df = _hist(80, iv_start=15.0, iv_trend=-0.1, hv=20.0, perc_start=10.0)
        result = run_backtest(df, hold_days=10)
        assert result is not None
        # Some buy or lean_buy signals should be present
        buy_n = result.n_signals.get("buy", 0) + result.n_signals.get("lean_buy", 0)
        assert buy_n > 0
        # All buy signals should hit (IV fell)
        buy_hr = result.hit_rates.get("buy", float("nan"))
        lean_hr = result.hit_rates.get("lean_buy", float("nan"))
        for hr in (buy_hr, lean_hr):
            if not math.isnan(hr):
                assert hr == pytest.approx(1.0), f"Expected 1.0 hit rate, got {hr}"

    def test_rich_signal_hit_when_iv_rises(self):
        """When IV steadily rises from a rich starting point, RICH signals should hit."""
        df = _hist(80, iv_start=30.0, iv_trend=0.1, hv=20.0, perc_start=85.0)
        result = run_backtest(df, hold_days=10)
        assert result is not None
        rich_n = result.n_signals.get("rich", 0) + result.n_signals.get("lean_rich", 0)
        assert rich_n > 0
        rich_hr = result.hit_rates.get("rich", float("nan"))
        lean_hr = result.hit_rates.get("lean_rich", float("nan"))
        for hr in (rich_hr, lean_hr):
            if not math.isnan(hr):
                assert hr == pytest.approx(1.0), f"Expected 1.0 hit rate, got {hr}"

    def test_avg_iv_change_negative_when_falling(self):
        """Falling IV history → avg iv_change_pct should be negative for buy signals."""
        df = _hist(80, iv_start=15.0, iv_trend=-0.2, hv=20.0, perc_start=10.0)
        result = run_backtest(df, hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        for cat in ("buy", "lean_buy"):
            chg = result.avg_iv_changes.get(cat, float("nan"))
            if not math.isnan(chg) and result.n_signals[cat] > 0:
                assert chg < 0, f"{cat}: expected negative avg change, got {chg}"

    def test_avg_iv_change_positive_when_rising(self):
        """Rising IV history → avg iv_change_pct should be positive for rich signals."""
        df = _hist(80, iv_start=30.0, iv_trend=0.2, hv=20.0, perc_start=85.0)
        result = run_backtest(df, hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        for cat in ("rich", "lean_rich"):
            chg = result.avg_iv_changes.get(cat, float("nan"))
            if not math.isnan(chg) and result.n_signals[cat] > 0:
                assert chg > 0, f"{cat}: expected positive avg change, got {chg}"


class TestMaxDrawdown:
    def test_max_drawdown_present_for_buy_signals(self):
        df = _cheap_hist(80)
        result = run_backtest(df, hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        buy_n = result.n_signals.get("buy", 0) + result.n_signals.get("lean_buy", 0)
        if buy_n == 0:
            pytest.skip("no buy signals generated")
        for cat in ("buy", "lean_buy"):
            if result.n_signals[cat] > 0:
                assert cat in result.max_drawdowns

    def test_max_drawdown_nan_for_non_buy(self):
        df = _hist(80)
        result = run_backtest(df, hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        for cat in ("neutral", "lean_rich", "rich"):
            md = result.max_drawdowns.get(cat, 0.0)
            assert math.isnan(md), f"Expected NaN for {cat} max_drawdown, got {md}"

    def test_max_drawdown_nonnegative_when_iv_spikes(self):
        """When IV rises after entry, max drawdown should be > 0."""
        df = _hist(80, iv_start=15.0, iv_trend=0.3, hv=20.0, perc_start=10.0)
        result = run_backtest(df, hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        buy_n = result.n_signals.get("buy", 0) + result.n_signals.get("lean_buy", 0)
        if buy_n == 0:
            pytest.skip("no buy signals generated")
        for cat in ("buy", "lean_buy"):
            md = result.max_drawdowns.get(cat, float("nan"))
            if not math.isnan(md) and result.n_signals[cat] > 0:
                assert md > 0, f"{cat}: expected positive max drawdown, got {md}"


# ---------------------------------------------------------------------------
# rolling_hit_rate
# ---------------------------------------------------------------------------

class TestRollingHitRate:
    def test_returns_dataframe(self):
        result = run_backtest(_cheap_hist(120), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        rhr = rolling_hit_rate(result.signals_df)
        assert isinstance(rhr, pd.DataFrame)

    def test_output_columns(self):
        result = run_backtest(_cheap_hist(120), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        rhr = rolling_hit_rate(result.signals_df)
        assert "date" in rhr.columns
        assert "hit_rate" in rhr.columns

    def test_empty_when_no_buy_signals(self):
        """If history has no cheap signals, rolling_hit_rate returns empty."""
        df = _hist(80, iv_start=30.0, hv=20.0, perc_start=85.0)
        result = run_backtest(df, hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        buy_n = result.n_signals.get("buy", 0) + result.n_signals.get("lean_buy", 0)
        if buy_n > 0:
            pytest.skip("buy signals present — cannot test empty path")
        rhr = rolling_hit_rate(result.signals_df)
        assert rhr.empty

    def test_hit_rate_in_0_1(self):
        result = run_backtest(_cheap_hist(150), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        rhr = rolling_hit_rate(result.signals_df)
        if rhr.empty:
            pytest.skip("no rolling data")
        assert (rhr["hit_rate"] >= 0).all()
        assert (rhr["hit_rate"] <= 1).all()

    def test_custom_window(self):
        result = run_backtest(_cheap_hist(120), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        rhr = rolling_hit_rate(result.signals_df, window=20)
        assert isinstance(rhr, pd.DataFrame)


# ---------------------------------------------------------------------------
# build_calibration_table
# ---------------------------------------------------------------------------

class TestBuildCalibrationTable:
    def test_returns_dataframe(self):
        result = run_backtest(_hist(80), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        cal = build_calibration_table(result)
        assert isinstance(cal, pd.DataFrame)

    def test_required_columns(self):
        result = run_backtest(_hist(80), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        cal = build_calibration_table(result)
        for col in ("Signal", "N", "Hit Rate", "Avg IV Δ%"):
            assert col in cal.columns, f"Missing column: {col}"

    def test_only_present_categories(self):
        """Categories with zero instances should not appear in the table."""
        result = run_backtest(_hist(80), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        cal = build_calibration_table(result)
        for _, row in cal.iterrows():
            n = row["N"]
            assert n > 0

    def test_empty_result_gives_empty_table(self):
        """A BacktestResult with all-zero n_signals yields an empty table."""
        dummy = BacktestResult(
            ticker="X",
            hold_days=10,
            n_total=0,
            signals_df=pd.DataFrame(),
            hit_rates={c: float("nan") for c in ALL_CATEGORIES},
            avg_iv_changes={c: float("nan") for c in ALL_CATEGORIES},
            max_drawdowns={c: float("nan") for c in ALL_CATEGORIES},
            n_signals={c: 0 for c in ALL_CATEGORIES},
        )
        cal = build_calibration_table(dummy)
        assert cal.empty


# ---------------------------------------------------------------------------
# Chart builders — smoke tests
# ---------------------------------------------------------------------------

class TestBacktestChartBuilders:
    def test_hit_rate_chart_empty_df(self):
        fig = create_backtest_hit_rate_chart(pd.DataFrame(columns=["date", "hit_rate"]))
        assert fig is not None

    def test_hit_rate_chart_with_data(self):
        result = run_backtest(_cheap_hist(150), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        rhr = rolling_hit_rate(result.signals_df)
        fig = create_backtest_hit_rate_chart(rhr)
        assert fig is not None

    def test_distribution_chart_empty_df(self):
        fig = create_backtest_distribution_chart(pd.DataFrame(columns=["signal_cat", "iv_change_pct"]))
        assert fig is not None

    def test_distribution_chart_with_data(self):
        result = run_backtest(_hist(80), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        fig = create_backtest_distribution_chart(result.signals_df)
        assert fig is not None

    def test_hit_rate_chart_has_traces_when_data(self):
        result = run_backtest(_cheap_hist(150), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        rhr = rolling_hit_rate(result.signals_df)
        if rhr.empty:
            pytest.skip("no rolling data")
        fig = create_backtest_hit_rate_chart(rhr)
        assert len(fig.data) > 0

    def test_distribution_chart_traces_per_category(self):
        result = run_backtest(_hist(80), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        fig = create_backtest_distribution_chart(result.signals_df)
        # Should have at least one histogram trace
        assert len(fig.data) >= 1


class TestBootstrapCIAndBaseline:
    """Phase R4 — bootstrap CI + naive baseline plumbing for the Scope UI."""

    def test_bootstrap_ci_produces_valid_interval(self):
        from volscope.analytics.backtest import bootstrap_ci
        point, lo, hi = bootstrap_ci([-5.0, -3.0, -2.0, -1.0, 0.0, 1.0])
        assert lo <= point <= hi
        assert -50 < lo < 50
        assert -50 < hi < 50

    def test_bootstrap_ci_handles_empty_input(self):
        import math
        from volscope.analytics.backtest import bootstrap_ci
        point, lo, hi = bootstrap_ci([])
        assert math.isnan(point) and math.isnan(lo) and math.isnan(hi)

    def test_bootstrap_ci_skips_nan(self):
        import math
        from volscope.analytics.backtest import bootstrap_ci
        point, lo, hi = bootstrap_ci([1.0, float("nan"), 2.0, 3.0])
        assert not math.isnan(point)
        assert lo <= point <= hi

    def test_bootstrap_ci_deterministic_with_seed(self):
        from volscope.analytics.backtest import bootstrap_ci
        a = bootstrap_ci([1.0, 2.0, 3.0, 4.0], seed=7)
        b = bootstrap_ci([1.0, 2.0, 3.0, 4.0], seed=7)
        assert a == b

    def test_naive_baseline_returns_fraction(self):
        from volscope.analytics.backtest import naive_baseline_hit_rate
        result = run_backtest(_hist(80), hold_days=10)
        if result is None:
            pytest.skip("not enough data")
        nb = naive_baseline_hit_rate(result.signals_df)
        assert 0.0 <= nb <= 1.0

    def test_naive_baseline_empty_returns_nan(self):
        import math
        import pandas as pd
        from volscope.analytics.backtest import naive_baseline_hit_rate
        nb = naive_baseline_hit_rate(pd.DataFrame())
        assert math.isnan(nb)
