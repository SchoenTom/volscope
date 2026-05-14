"""
Tests for volscope.analytics.ml_signal — logistic regression on vol features.

Covers:
  - _build_features()   feature engineering (vrp, iv_change_7d)
  - _build_targets()    target label construction
  - _fit_logistic()     L-BFGS-B logistic regression kernel
  - predict_buy_prob()  end-to-end prediction (None guards, output contract)
  - ml_badge_html()     HTML rendering contract
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.ml_signal import (
    MLPrediction,
    _build_features,
    _build_targets,
    _fit_logistic,
    ml_badge_html,
    predict_buy_prob,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hist(
    n: int,
    iv_start: float = 25.0,
    hv: float = 20.0,
    perc_start: float = 50.0,
    trend: float = 0.0,
) -> pd.DataFrame:
    """Synthetic daily_vol history with n rows."""
    today = date.today()
    dates = [today - timedelta(days=n - 1 - i) for i in range(n)]
    iv   = [iv_start + trend * i for i in range(n)]
    perc = [max(0.0, min(100.0, perc_start + trend * i)) for i in range(n)]
    return pd.DataFrame({
        "date":           dates,
        "iv_30d":         iv,
        "hv_20d":         [hv] * n,
        "iv_percentile":  perc,
        "iv_rank":        perc,
        "put_call_ratio": [0.8] * n,
    })


# ---------------------------------------------------------------------------
# _build_features
# ---------------------------------------------------------------------------

class TestBuildFeatures:
    def test_adds_vrp_column(self):
        df = _hist(30, iv_start=25.0, hv=20.0)
        feat = _build_features(df)
        assert "vrp" in feat.columns

    def test_vrp_correct_ratio(self):
        df = _hist(30, iv_start=25.0, hv=20.0)
        feat = _build_features(df)
        np.testing.assert_allclose(feat["vrp"].dropna(), 25.0 / 20.0, rtol=1e-6)

    def test_vrp_nan_when_hv_zero(self):
        df = _hist(10, hv=0.0)
        feat = _build_features(df)
        assert feat["vrp"].isna().all()

    def test_adds_iv_change_7d(self):
        df = _hist(20, perc_start=50.0, trend=1.0)
        feat = _build_features(df)
        assert "iv_change_7d" in feat.columns
        # diff(7) of a linear series with slope 1 → always 7
        valid = feat["iv_change_7d"].dropna()
        assert len(valid) > 0
        np.testing.assert_allclose(valid, 7.0, rtol=0.01)

    def test_date_column_preserved(self):
        df = _hist(20)
        feat = _build_features(df)
        assert "date" in feat.columns
        assert len(feat) == 20

    def test_sorted_by_date(self):
        df = _hist(20).sample(frac=1, random_state=0)  # shuffle
        feat = _build_features(df)
        dates = pd.to_datetime(feat["date"])
        assert (dates.diff().dropna() >= pd.Timedelta(0)).all()


# ---------------------------------------------------------------------------
# _build_targets
# ---------------------------------------------------------------------------

class TestBuildTargets:
    def _targets(self, iv_series: list[float], hold: int = 10) -> list:
        n = len(iv_series)
        df = pd.DataFrame({
            "date":   [date.today() - timedelta(days=n-1-i) for i in range(n)],
            "iv_30d": iv_series,
        })
        return _build_targets(df, hold).tolist()

    def test_one_when_iv_falls(self):
        # iv[0]=25, iv[5]=20 → falls → y=1
        iv = [25.0] * 5 + [20.0] * 15
        assert self._targets(iv, hold=5)[0] == pytest.approx(1.0)

    def test_zero_when_iv_rises(self):
        iv = [20.0] * 5 + [25.0] * 15
        assert self._targets(iv, hold=5)[0] == pytest.approx(0.0)

    def test_zero_when_iv_flat(self):
        iv = [25.0] * 20
        assert self._targets(iv, hold=5)[0] == pytest.approx(0.0)

    def test_last_hold_rows_are_nan(self):
        iv = list(range(1, 21))  # 20 rows
        targets = self._targets(iv, hold=10)
        assert all(math.isnan(t) for t in targets[-10:])

    def test_non_nan_count(self):
        iv = [20.0] * 20
        targets = self._targets(iv, hold=10)
        non_nan = sum(1 for t in targets if not math.isnan(t))
        assert non_nan == 10

    def test_returns_empty_without_iv_column(self):
        df = pd.DataFrame({"date": [date.today()], "hv_20d": [20.0]})
        result = _build_targets(df)
        assert result.empty or result.isna().all()


# ---------------------------------------------------------------------------
# _fit_logistic
# ---------------------------------------------------------------------------

class TestFitLogistic:
    def test_converges_on_perfectly_separable_data(self):
        n = 100
        X = np.column_stack([
            np.ones(n),
            np.concatenate([np.full(n//2, 2.0), np.full(n//2, -2.0)]),
        ])
        y = np.concatenate([np.ones(n//2), np.zeros(n//2)]).astype(float)
        theta = _fit_logistic(X, y)
        assert theta is not None
        assert len(theta) == 2
        # Positive coefficient: larger x → more likely class 1
        assert theta[1] > 0

    def test_returns_none_single_row(self):
        X = np.array([[1.0, 0.5]])
        y = np.array([1.0])
        assert _fit_logistic(X, y) is None

    def test_returns_ndarray(self):
        rng = np.random.default_rng(42)
        n = 60
        X = np.column_stack([np.ones(n), rng.standard_normal(n)])
        y = (rng.standard_normal(n) > 0).astype(float)
        theta = _fit_logistic(X, y)
        assert theta is not None
        assert isinstance(theta, np.ndarray)

    def test_shape_matches_features(self):
        rng = np.random.default_rng(0)
        n, d = 80, 4
        X = np.column_stack([np.ones(n), rng.standard_normal((n, d-1))])
        y = (rng.standard_normal(n) > 0).astype(float)
        theta = _fit_logistic(X, y)
        assert theta is not None
        assert theta.shape == (d,)


# ---------------------------------------------------------------------------
# predict_buy_prob — None guards
# ---------------------------------------------------------------------------

class TestPredictBuyProbNoneGuards:
    def test_none_on_empty_history(self):
        assert predict_buy_prob("QQQ", pd.DataFrame()) is None

    def test_none_on_insufficient_rows(self):
        """Fewer than _MIN_TRAIN_ROWS valid training rows → None."""
        assert predict_buy_prob("QQQ", _hist(30)) is None

    def test_none_without_iv_column(self):
        df = pd.DataFrame({
            "date":          [date.today() - timedelta(days=i) for i in range(200)],
            "hv_20d":        [20.0] * 200,
            "iv_percentile": [50.0] * 200,
        })
        assert predict_buy_prob("QQQ", df) is None

    def test_none_with_constant_iv_and_small_n(self):
        assert predict_buy_prob("T", _hist(40)) is None


# ---------------------------------------------------------------------------
# predict_buy_prob — output contract
# ---------------------------------------------------------------------------

class TestPredictBuyProbOutput:
    def test_returns_mlprediction(self):
        result = predict_buy_prob("QQQ", _hist(200, trend=-0.05))
        assert result is not None
        assert isinstance(result, MLPrediction)

    def test_buy_prob_in_unit_interval(self):
        result = predict_buy_prob("QQQ", _hist(200))
        if result is not None:
            assert 0.0 <= result.buy_prob <= 1.0

    def test_ticker_field_correct(self):
        result = predict_buy_prob("MSTR", _hist(200))
        if result is not None:
            assert result.ticker == "MSTR"

    def test_n_train_positive(self):
        result = predict_buy_prob("SNOW", _hist(200))
        if result is not None:
            assert result.n_train > 0

    def test_features_used_is_tuple(self):
        result = predict_buy_prob("QQQ", _hist(200))
        if result is not None:
            assert isinstance(result.features_used, tuple)

    def test_deterministic(self):
        hist = _hist(200, iv_start=30.0, trend=-0.05)
        r1 = predict_buy_prob("QQQ", hist)
        r2 = predict_buy_prob("QQQ", hist)
        if r1 is not None and r2 is not None:
            assert r1.buy_prob == pytest.approx(r2.buy_prob)

    def test_buy_prob_is_float(self):
        result = predict_buy_prob("QQQ", _hist(200))
        if result is not None:
            assert isinstance(result.buy_prob, float)

    def test_returns_something_with_300_rows(self):
        """More data → definitely enough for training."""
        result = predict_buy_prob("QQQ", _hist(300))
        assert result is not None


# ---------------------------------------------------------------------------
# MLPrediction — frozen dataclass contract
# ---------------------------------------------------------------------------

class TestMLPredictionDataclass:
    def test_is_frozen(self):
        pred = MLPrediction(
            ticker="QQQ", date=date.today(),
            buy_prob=0.7, n_train=100, features_used=("iv_percentile",)
        )
        with pytest.raises((AttributeError, TypeError)):
            pred.buy_prob = 0.5  # type: ignore[misc]

    def test_buy_prob_stored(self):
        pred = MLPrediction(
            ticker="X", date=date.today(),
            buy_prob=0.42, n_train=80, features_used=()
        )
        assert pred.buy_prob == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# ml_badge_html
# ---------------------------------------------------------------------------

def _pred(prob: float, n: int = 100) -> MLPrediction:
    return MLPrediction(
        ticker="QQQ", date=date.today(),
        buy_prob=prob, n_train=n,
        features_used=("iv_percentile", "vrp"),
    )


class TestMlBadgeHtml:
    def test_empty_when_none(self):
        assert ml_badge_html(None) == ""

    def test_nonempty_for_prediction(self):
        assert len(ml_badge_html(_pred(0.7))) > 0

    def test_high_prob_shows_buy_label(self):
        html = ml_badge_html(_pred(0.80))
        assert "BUY" in html

    def test_mid_prob_shows_lean_label(self):
        html = ml_badge_html(_pred(0.55))
        assert "LEAN" in html or "lean" in html.lower()

    def test_neutral_prob_shows_neutral_label(self):
        html = ml_badge_html(_pred(0.42))
        assert "NEUTRAL" in html or "neutral" in html.lower()

    def test_low_prob_shows_wait_label(self):
        html = ml_badge_html(_pred(0.20))
        assert "WAIT" in html

    def test_contains_percentage(self):
        html = ml_badge_html(_pred(0.73))
        assert "73" in html

    def test_n_train_shown(self):
        html = ml_badge_html(_pred(0.65, n=123))
        assert "123" in html

    def test_boundary_high(self):
        """p=0.65 is exactly the BUY threshold."""
        html = ml_badge_html(_pred(0.65))
        assert "BUY" in html

    def test_boundary_low(self):
        """p=0.35 is the NEUTRAL lower bound (>= 0.35 → NEUTRAL, < 0.35 → WAIT)."""
        html = ml_badge_html(_pred(0.35))
        assert "NEUTRAL" in html

    def test_below_boundary_shows_wait(self):
        """p=0.34 is below the NEUTRAL threshold → WAIT."""
        html = ml_badge_html(_pred(0.34))
        assert "WAIT" in html
