"""Tests for volscope/analytics/garch.py — GARCH(1,1)-t wrapper."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("arch")

from volscope.analytics.garch import GarchForecaster   # noqa: E402


def _synthetic_log_returns(n: int = 500, sigma: float = 0.20,
                            seed: int = 42) -> pd.Series:
    """Daily log returns from a constant-sigma GBM. Annualised σ = ``sigma``."""
    rng = np.random.default_rng(seed)
    daily_sigma = sigma / np.sqrt(252.0)
    return pd.Series(rng.normal(0.0, daily_sigma, n))


class TestGarchFit:
    def test_fits_synthetic_returns(self):
        gf = GarchForecaster().fit(_synthetic_log_returns(500, sigma=0.20))
        assert gf.is_fit
        assert "alpha[1]" in gf.params
        assert "beta[1]" in gf.params

    def test_raises_on_short_series(self):
        gf = GarchForecaster()
        with pytest.raises(ValueError, match="at least 60"):
            gf.fit(pd.Series([0.001] * 30))

    def test_persistence_below_one(self):
        gf = GarchForecaster().fit(_synthetic_log_returns(800, sigma=0.20))
        alpha = gf.params["alpha[1]"]
        beta = gf.params["beta[1]"]
        assert alpha + beta < 1.0, f"non-stationary: α+β = {alpha+beta:.4f}"


class TestGarchForecast:
    def test_forecast_recovers_sigma_roughly(self):
        # 500 daily obs from a known σ=0.20 process. 30-day forecast
        # should land in a wide but sane band around 0.20.
        gf = GarchForecaster().fit(_synthetic_log_returns(500, sigma=0.20))
        sigma_hat = gf.forecast_vol(horizon=30)
        assert 0.10 < sigma_hat < 0.35, f"σ̂ = {sigma_hat:.3f}"

    def test_forecast_raises_when_not_fit(self):
        gf = GarchForecaster()
        with pytest.raises(RuntimeError, match="fit"):
            gf.forecast_vol()


class TestConditionalVol:
    def test_conditional_vol_length_matches(self):
        ret = _synthetic_log_returns(500, sigma=0.25)
        gf = GarchForecaster().fit(ret)
        cv = gf.conditional_vol()
        assert len(cv) == len(ret)
        assert (cv > 0).all()
