"""Methodology tests for the options scraper internals."""
from __future__ import annotations

import math

import pandas as pd

from volscope.analytics.black_scholes import _manaster_koehler_seed, bs_price
from volscope.data.options_scraper import (
    _atm_iv_interpolated,
    _filter_for_aggregate,
    _filter_for_iv,
    _interpolate_iv,
)


class TestManasterKoehler:
    def test_atm_seed_reasonable(self):
        seed = _manaster_koehler_seed(100, 100, 1.0, 0.05, 0.0)
        assert 0.05 <= seed <= 5.0

    def test_deep_itm_seed_reasonable(self):
        seed = _manaster_koehler_seed(150, 100, 1.0, 0.05, 0.0)
        assert 0.05 <= seed <= 5.0

    def test_invalid_falls_back_to_default(self):
        # K=0 should not blow up
        seed = _manaster_koehler_seed(100, 0.0001, 1.0, 0.05, 0.0)
        assert isinstance(seed, float)
        assert seed > 0


class TestVarianceInterpolation:
    def test_total_variance_interpolation_single_point(self):
        assert _interpolate_iv([(30, 25.0)], 30) == 25.0

    def test_total_variance_interpolation_flat(self):
        """With identical IV across maturities, interpolation must reproduce it."""
        result = _interpolate_iv([(14, 30.0), (45, 30.0)], target_days=30)
        assert abs(result - 30.0) < 1e-9

    def test_total_variance_interpolation_concave(self):
        """When IV term structure is upward sloping, interpolated IV at intermediate
        maturity falls between the two endpoints."""
        result = _interpolate_iv([(14, 20.0), (45, 30.0)], target_days=30)
        assert 20.0 < result < 30.0

    def test_extrapolation_uses_nearest(self):
        result = _interpolate_iv([(60, 25.0), (90, 28.0)], target_days=30)
        assert result == 25.0  # nearest endpoint


class TestATMInterpolation:
    def _build_chain(self, spot: float, vol: float, T: float, strikes: list[float]) -> pd.DataFrame:
        rows = []
        for k in strikes:
            c = bs_price(spot, k, T, 0.045, vol, option_type="call")
            rows.append(
                {
                    "strike": k,
                    "bid": max(c - 0.02, 0.01),
                    "ask": c + 0.02,
                    "volume": 500,
                    "openInterest": 1000,
                }
            )
        return pd.DataFrame(rows)

    def test_atm_interpolation_recovers_true_vol(self):
        spot, vol, T = 100.0, 0.25, 0.25
        chain = self._build_chain(spot, vol, T, [95, 100, 105])
        iv, weight = _atm_iv_interpolated(chain, spot, T, r=0.045, q=0.0, option_type="call")
        assert iv is not None
        assert abs(iv - vol) < 1e-3
        assert weight > 0

    def test_atm_interpolation_uses_brackets_not_average(self):
        """If spot is between two strikes, must interpolate, not average all 3."""
        spot, vol, T = 102.5, 0.30, 0.25
        chain = self._build_chain(spot, vol, T, [100, 105, 110])
        iv, _ = _atm_iv_interpolated(chain, spot, T, r=0.045, q=0.0, option_type="call")
        assert iv is not None
        assert abs(iv - vol) < 1e-3

    def test_atm_falls_back_to_nearest_when_no_bracket(self):
        spot, vol, T = 100.0, 0.30, 0.25
        # All strikes above spot — no bracket
        chain = self._build_chain(spot, vol, T, [110, 115, 120])
        iv, _ = _atm_iv_interpolated(chain, spot, T, r=0.045, q=0.0, option_type="call")
        assert iv is not None  # should still produce something via fallback

    def test_atm_returns_none_for_empty(self):
        iv, w = _atm_iv_interpolated(
            pd.DataFrame(), 100.0, 0.25, r=0.045, q=0.0, option_type="call"
        )
        assert iv is None
        assert w == 0.0

    def test_atm_rejects_huge_spreads(self):
        """A 80%-of-mid spread should cause the row to be excluded."""
        spot, T = 100.0, 0.25
        chain = pd.DataFrame(
            [
                {"strike": 95, "bid": 1.0, "ask": 9.0, "volume": 100, "openInterest": 100},
                {"strike": 105, "bid": 1.0, "ask": 9.0, "volume": 100, "openInterest": 100},
            ]
        )
        iv, _ = _atm_iv_interpolated(chain, spot, T, r=0.045, q=0.0, option_type="call")
        assert iv is None


class TestFilters:
    def test_filter_for_iv_strict(self):
        df = pd.DataFrame(
            [
                {"strike": 100, "bid": 1.0, "ask": 1.1, "volume": 0, "openInterest": 5},   # OI too low
                {"strike": 105, "bid": 0.0, "ask": 0.5, "volume": 100, "openInterest": 50}, # bid=0 → drop
                {"strike": 110, "bid": 2.0, "ask": 2.1, "volume": 100, "openInterest": 50}, # keep
                {"strike": 115, "bid": 3.0, "ask": 2.9, "volume": 100, "openInterest": 50}, # crossed → drop
            ]
        )
        out = _filter_for_iv(df)
        assert list(out["strike"]) == [110]

    def test_filter_for_aggregate_keeps_tail_strikes(self):
        df = pd.DataFrame(
            [
                {"strike": 100, "bid": 0.0, "ask": 0.5, "volume": 0, "openInterest": 0},
                {"strike": 105, "bid": 1.0, "ask": 1.1, "volume": 100, "openInterest": 50},
            ]
        )
        out = _filter_for_aggregate(df)
        assert len(out) == 2
