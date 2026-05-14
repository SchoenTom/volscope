"""Tests for signals/composite.py."""
from __future__ import annotations

import math

import pytest

from volscope.signals.composite import composite_score, size_from_score


class TestShortVolScore:
    def test_high_conviction(self):
        factors = {"ivr": 70, "ivp": 80, "iv_hv": 1.30, "term": 0.05,
                   "skew": -8, "hv_mom": 0.8}
        sc = composite_score(factors, direction="short_vol", p_calm=0.85)
        assert 70 < sc <= 100

    def test_neutral_returns_around_50(self):
        factors = {"ivr": 50, "ivp": 50, "iv_hv": 1.0, "term": 0.0,
                   "skew": 0, "hv_mom": 1.25}
        sc = composite_score(factors, direction="short_vol", p_calm=0.5)
        assert 35 <= sc <= 65   # roughly middling

    def test_low_iv_environment_low_score(self):
        factors = {"ivr": 5, "ivp": 10, "iv_hv": 0.6, "term": -0.05,
                   "skew": 5, "hv_mom": 1.5}
        sc = composite_score(factors, direction="short_vol", p_calm=0.4)
        assert sc < 30


class TestLongVolScore:
    def test_cheap_iv_high_score(self):
        factors = {"ivr": 10, "ivp": 5, "iv_hv": 0.65, "term": -0.10,
                   "skew": 8, "hv_mom": 1.8}
        sc = composite_score(factors, direction="long_vol", p_calm=float('nan'))
        assert sc > 60


class TestNanHandling:
    def test_all_nan_returns_nan(self):
        sc = composite_score({}, direction="short_vol", p_calm=float('nan'))
        assert math.isnan(sc)

    def test_partial_nan_drops_weight(self):
        # Just IVR — composite must still produce a finite score
        sc = composite_score({"ivr": 80}, direction="short_vol",
                             p_calm=float('nan'))
        assert 0 <= sc <= 100


class TestSizing:
    @pytest.mark.parametrize("score,expected", [
        (0, 0.0), (49, 0.0), (50, 0.25), (64, 0.25),
        (65, 0.5), (79, 0.5), (80, 0.75), (89, 0.75),
        (90, 1.0), (100, 1.0),
    ])
    def test_mapping(self, score, expected):
        assert size_from_score(score) == expected

    def test_nan_returns_zero(self):
        assert size_from_score(float('nan')) == 0.0
