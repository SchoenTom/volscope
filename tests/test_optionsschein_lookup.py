"""Tests for analytics.optionsschein_lookup."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.optionsschein_lookup import (
    ChainMatch,
    INSTRUMENT_TYPES,
    OptionsscheinSpec,
    bsm_iv_proxy_from_history,
    compute_entry_iv_percentile,
    days_to_expiry,
    distance_to_barrier_pct,
    find_chain_match,
    historical_iv_at,
    is_knockout_dead,
)


def _spec(**overrides):
    base = dict(
        underlying="QQQ",
        option_type="put",
        strike=380.0,
        expiry=date.today() + timedelta(days=60),
        instrument_type="vanilla",
    )
    base.update(overrides)
    return OptionsscheinSpec(**base)


# ──────────────────────────────────────────────────────────────────────────
# OptionsscheinSpec
# ──────────────────────────────────────────────────────────────────────────

class TestSpec:
    def test_frozen(self):
        s = _spec()
        with pytest.raises(Exception):
            s.strike = 0  # type: ignore[misc]

    def test_default_instrument_type_vanilla(self):
        s = _spec()
        assert s.instrument_type == "vanilla"

    def test_instrument_types_constant(self):
        assert "vanilla" in INSTRUMENT_TYPES
        assert "knockout" in INSTRUMENT_TYPES


# ──────────────────────────────────────────────────────────────────────────
# Chain match
# ──────────────────────────────────────────────────────────────────────────

def _chain_df(spot=400):
    expiries = [date.today() + timedelta(days=d) for d in [30, 60, 90]]
    rows = []
    for exp in expiries:
        for strike in [350, 360, 370, 380, 390, 400, 410, 420]:
            for ot in ["call", "put"]:
                rows.append({
                    "strike": strike,
                    "iv": 25.0 + abs(strike - spot) * 0.05,
                    "expiry": exp,
                    "option_type": ot,
                })
    return pd.DataFrame(rows)


class TestFindChainMatch:
    def test_exact_match(self):
        df = _chain_df()
        spec = _spec(strike=380.0, expiry=date.today() + timedelta(days=60))
        m = find_chain_match(spec, df, spot=400.0)
        assert m is not None
        assert m.matched_strike == 380.0

    def test_returns_none_when_outside_tolerance(self):
        df = _chain_df()
        spec = _spec(strike=200.0)   # way off-grid
        assert find_chain_match(spec, df, spot=400.0) is None

    def test_filters_by_option_type(self):
        df = _chain_df()
        spec = _spec(option_type="call", strike=400.0)
        m = find_chain_match(spec, df, spot=400.0)
        assert m is not None

    def test_picks_closest_expiry(self):
        df = _chain_df()
        spec = _spec(expiry=date.today() + timedelta(days=58), strike=400.0)
        m = find_chain_match(spec, df, spot=400.0)
        assert m is not None
        # Should pick the 60d expiry
        assert m.expiry_diff_days <= 7

    def test_none_when_empty_df(self):
        spec = _spec()
        assert find_chain_match(spec, pd.DataFrame(), spot=400.0) is None

    def test_none_when_missing_columns(self):
        df = pd.DataFrame({"strike": [380.0]})
        spec = _spec()
        assert find_chain_match(spec, df, spot=400.0) is None


# ──────────────────────────────────────────────────────────────────────────
# IV proxy from history
# ──────────────────────────────────────────────────────────────────────────

class TestIvProxyFromHistory:
    def test_picks_closest_term_bucket(self):
        df = pd.DataFrame({
            "date": [date(2026, 5, 1)],
            "iv_30d": [22.0],
            "iv_60d": [24.0],
            "iv_90d": [26.0],
        })
        v = bsm_iv_proxy_from_history(df, target_dte=60)
        assert v == 24.0

    def test_skips_nan(self):
        df = pd.DataFrame({
            "date": [date(2026, 5, 1)],
            "iv_30d": [float("nan")],
            "iv_60d": [24.0],
        })
        v = bsm_iv_proxy_from_history(df, target_dte=30)
        assert v == 24.0

    def test_empty_returns_none(self):
        assert bsm_iv_proxy_from_history(pd.DataFrame(), target_dte=30) is None

    def test_none_input(self):
        assert bsm_iv_proxy_from_history(None, target_dte=30) is None


# ──────────────────────────────────────────────────────────────────────────
# Historical IV at date
# ──────────────────────────────────────────────────────────────────────────

class TestHistoricalIvAt:
    def test_picks_latest_before_target(self):
        df = pd.DataFrame({
            "date": [date(2026, 1, 1), date(2026, 4, 1), date(2026, 6, 1)],
            "iv_30d": [10.0, 20.0, 30.0],
        })
        # User entered on 2026-05-15 → should pick 2026-04-01
        v = historical_iv_at(df, target_dt=date(2026, 5, 15), target_dte=30)
        assert v == 20.0

    def test_returns_none_if_target_before_history(self):
        df = pd.DataFrame({
            "date": [date(2026, 6, 1)],
            "iv_30d": [30.0],
        })
        v = historical_iv_at(df, target_dt=date(2026, 1, 1), target_dte=30)
        assert v is None


# ──────────────────────────────────────────────────────────────────────────
# Entry IV percentile
# ──────────────────────────────────────────────────────────────────────────

class TestEntryIvPercentile:
    def test_high_iv_yields_high_percentile(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "date": [date(2026, 1, 1) + timedelta(days=i) for i in range(100)],
            "iv_30d": rng.uniform(15, 25, 100),
        })
        # Entry at 30 (above all observed) → percentile near 100
        p = compute_entry_iv_percentile(df, entry_iv=30.0, entry_date=date(2026, 4, 15))
        assert p is not None and p > 90

    def test_low_iv_yields_low_percentile(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "date": [date(2026, 1, 1) + timedelta(days=i) for i in range(100)],
            "iv_30d": rng.uniform(15, 25, 100),
        })
        p = compute_entry_iv_percentile(df, entry_iv=10.0, entry_date=date(2026, 4, 15))
        assert p is not None and p < 10


# ──────────────────────────────────────────────────────────────────────────
# Knockout helpers
# ──────────────────────────────────────────────────────────────────────────

class TestKnockoutHelpers:
    def test_long_call_ko_dead_when_spot_below_barrier(self):
        spec = _spec(option_type="call", instrument_type="knockout",
                     strike=400, barrier=380)
        assert is_knockout_dead(spec, current_spot=375.0)

    def test_long_call_ko_alive_when_spot_above_barrier(self):
        spec = _spec(option_type="call", instrument_type="knockout",
                     strike=400, barrier=380)
        assert not is_knockout_dead(spec, current_spot=395.0)

    def test_long_put_ko_dead_when_spot_above_barrier(self):
        spec = _spec(option_type="put", instrument_type="knockout",
                     strike=380, barrier=420)
        assert is_knockout_dead(spec, current_spot=425.0)

    def test_vanilla_never_dead(self):
        spec = _spec(instrument_type="vanilla")
        assert not is_knockout_dead(spec, current_spot=999.0)

    def test_distance_to_barrier_call_positive(self):
        spec = _spec(option_type="call", instrument_type="knockout",
                     strike=400, barrier=380)
        d = distance_to_barrier_pct(spec, current_spot=400.0)
        assert d > 0

    def test_distance_no_barrier_returns_none(self):
        spec = _spec()
        assert distance_to_barrier_pct(spec, current_spot=400.0) is None


# ──────────────────────────────────────────────────────────────────────────
# Days to expiry
# ──────────────────────────────────────────────────────────────────────────

class TestDaysToExpiry:
    def test_future_expiry(self):
        spec = _spec(expiry=date.today() + timedelta(days=45))
        assert days_to_expiry(spec) == 45

    def test_past_expiry_returns_zero(self):
        spec = _spec(expiry=date.today() - timedelta(days=10))
        assert days_to_expiry(spec) == 0
