"""Tests for the new signals/factors.py atomic factor library."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from volscope.signals.factors import (
    factor_vector, hv_momentum, iv_hv_ratio, ivp, ivr,
    skew_25d_rr, term_slope,
)


class TestIVR:
    def test_at_max(self):
        s = pd.Series([10, 20, 30])
        assert ivr(pd.Series(list(s) + list(np.linspace(10, 30, 20)) + [30])) == pytest.approx(100, abs=0.1)

    def test_at_min(self):
        s = pd.Series(list(np.linspace(20, 40, 30)) + [20])
        assert ivr(s) == pytest.approx(0, abs=0.1)

    def test_zero_range_returns_nan(self):
        assert math.isnan(ivr(pd.Series([20] * 100)))

    def test_too_few_obs_returns_nan(self):
        assert math.isnan(ivr(pd.Series([10, 20])))


class TestIVP:
    def test_all_below(self):
        s = pd.Series(list(np.arange(0, 50)) + [50])
        assert ivp(s) > 95          # 50 is above all 0-49

    def test_all_above(self):
        s = pd.Series(list(np.arange(50, 100)) + [50])
        # current = 50 is at minimum of [50..99] — 0 days below
        assert ivp(s) == 0.0


class TestIVHV:
    def test_neutral(self):
        assert iv_hv_ratio(20, 20) == 1.0

    def test_rich(self):
        assert iv_hv_ratio(30, 20) == 1.5

    def test_cheap(self):
        assert iv_hv_ratio(15, 30) == 0.5

    def test_zero_hv_nan(self):
        assert math.isnan(iv_hv_ratio(20, 0))


class TestTermSlope:
    def test_contango(self):
        assert term_slope(30, 25) > 0

    def test_backwardation(self):
        assert term_slope(25, 30) < 0


class TestSkewRR:
    def test_normal_skew_negative(self):
        # equities: puts richer than calls → RR < 0
        assert skew_25d_rr(iv_25d_call=20, iv_25d_put=25) == -5.0

    def test_unusual_skew_positive(self):
        assert skew_25d_rr(iv_25d_call=30, iv_25d_put=25) == 5.0


class TestHvMomentum:
    def test_accelerating(self):
        assert hv_momentum(30, 20) == 1.5

    def test_decelerating(self):
        assert hv_momentum(10, 20) == 0.5


class TestFactorVector:
    def test_returns_all_keys(self):
        hist = pd.Series(np.linspace(15, 35, 252))
        fv = factor_vector(iv_30d=25, iv_90d=23, hv_5d=18, hv_20d=20,
                           hv_30d=22, iv_history_252d=hist,
                           iv_25d_call=22, iv_25d_put=27)
        assert set(fv.keys()) == {"ivr", "ivp", "iv_hv", "term", "skew", "hv_mom"}
        assert all(isinstance(v, float) for v in fv.values())
