"""Tests for analytics.expected_move."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.expected_move import (
    ConsensusMove,
    IvEstimate,
    MaxPainEstimate,
    StraddleEstimate,
    compute_expected_move,
    estimate_from_iv,
    estimate_from_straddle,
    estimate_max_pain,
    reconcile_estimates,
)


def _chain(strikes, call_bids, call_asks, put_bids, put_asks, ois=None):
    """Helper to build an options DataFrame with given strikes + quotes."""
    rows = []
    for i, k in enumerate(strikes):
        rows.append({
            "strike": k, "option_type": "call",
            "bid": call_bids[i], "ask": call_asks[i],
            "open_interest": (ois[0][i] if ois else 100),
        })
        rows.append({
            "strike": k, "option_type": "put",
            "bid": put_bids[i], "ask": put_asks[i],
            "open_interest": (ois[1][i] if ois else 100),
        })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────
# Straddle method
# ──────────────────────────────────────────────────────────────────────────

class TestStraddle:
    def test_simple_atm(self):
        # Spot=100, ATM strike=100 with call mid=2.50, put mid=2.50 → EM=$5 = 5%
        df = _chain([95, 100, 105],
                    call_bids=[6.0, 2.4, 0.8], call_asks=[6.2, 2.6, 1.0],
                    put_bids=[0.8, 2.4, 6.0],  put_asks=[1.0, 2.6, 6.2])
        e = estimate_from_straddle(df, spot=100.0, days_to_event=2)
        assert e is not None
        assert e.em_dollar == pytest.approx(5.0, abs=0.1)
        assert e.em_pct == pytest.approx(5.0, abs=0.1)
        assert e.atm_strike == 100.0

    def test_off_grid_spot_picks_closest(self):
        df = _chain([95, 100, 105],
                    call_bids=[6.0, 2.4, 0.8], call_asks=[6.2, 2.6, 1.0],
                    put_bids=[0.8, 2.4, 6.0],  put_asks=[1.0, 2.6, 6.2])
        e = estimate_from_straddle(df, spot=101.5, days_to_event=2)
        assert e is not None
        assert e.atm_strike == 100.0   # nearest to 101.5

    def test_empty_chain_returns_none(self):
        assert estimate_from_straddle(pd.DataFrame(), 100, 2) is None
        assert estimate_from_straddle(None, 100, 2) is None

    def test_zero_spot_returns_none(self):
        df = _chain([100], [2], [2.5], [2], [2.5])
        assert estimate_from_straddle(df, spot=0, days_to_event=2) is None

    def test_no_call_or_no_put_returns_none(self):
        # Only call rows
        df = pd.DataFrame([
            {"strike": 100, "option_type": "call", "bid": 2, "ask": 2.5, "open_interest": 100},
        ])
        assert estimate_from_straddle(df, spot=100, days_to_event=2) is None

    def test_widens_with_n_strikes(self):
        # With multi-strike averaging, a different ATM range can be picked
        df = _chain([95, 100, 105, 110],
                    call_bids=[6.0, 2.4, 0.8, 0.2], call_asks=[6.2, 2.6, 1.0, 0.4],
                    put_bids=[0.2, 2.4, 6.0, 11.0], put_asks=[0.4, 2.6, 6.2, 11.2])
        e1 = estimate_from_straddle(df, spot=100, days_to_event=2, n_strikes=1)
        e2 = estimate_from_straddle(df, spot=100, days_to_event=2, n_strikes=3)
        assert e1.n_strikes_used == 1
        assert e2.n_strikes_used == 3

    def test_invalid_quotes_filtered(self):
        # bid > ask = invalid
        df = pd.DataFrame([
            {"strike": 100, "option_type": "call", "bid": 5, "ask": 2, "open_interest": 100},
            {"strike": 100, "option_type": "put", "bid": 5, "ask": 2, "open_interest": 100},
        ])
        assert estimate_from_straddle(df, spot=100, days_to_event=2) is None


# ──────────────────────────────────────────────────────────────────────────
# IV method
# ──────────────────────────────────────────────────────────────────────────

class TestIvMethod:
    def test_basic(self):
        # spot=100, IV=20%, 30 days → EM ≈ 100 * 0.20 * sqrt(30/365) ≈ 5.73
        e = estimate_from_iv(spot=100.0, iv_pct=20.0, days=30)
        assert e is not None
        assert e.em_pct == pytest.approx(5.73, abs=0.1)
        assert e.em_dollar == pytest.approx(5.73, abs=0.1)

    def test_zero_iv_returns_none(self):
        assert estimate_from_iv(100, 0, 30) is None

    def test_zero_days_returns_none(self):
        assert estimate_from_iv(100, 20, 0) is None

    def test_zero_spot_returns_none(self):
        assert estimate_from_iv(0, 20, 30) is None

    def test_em_grows_with_sqrt_time(self):
        e1 = estimate_from_iv(100, 20, 7)
        e4 = estimate_from_iv(100, 20, 28)
        # 4× time → 2× move
        assert e4.em_pct == pytest.approx(e1.em_pct * 2, rel=0.01)


# ──────────────────────────────────────────────────────────────────────────
# Max-Pain method
# ──────────────────────────────────────────────────────────────────────────

class TestMaxPain:
    def test_returns_strike_with_min_pain(self):
        # If put OI is heavy at low strikes and call OI heavy at high strikes,
        # max pain = the middle strike.
        rows = [
            {"strike": 90,  "option_type": "put",  "open_interest": 1000},
            {"strike": 100, "option_type": "put",  "open_interest": 100},
            {"strike": 110, "option_type": "put",  "open_interest": 10},
            {"strike": 90,  "option_type": "call", "open_interest": 10},
            {"strike": 100, "option_type": "call", "open_interest": 100},
            {"strike": 110, "option_type": "call", "open_interest": 1000},
        ]
        df = pd.DataFrame(rows)
        e = estimate_max_pain(df, spot=100.0)
        assert e is not None
        # Max pain should be at the strike that minimises payout — typically near 100
        assert e.max_pain_strike == 100.0

    def test_zero_oi_returns_none(self):
        df = pd.DataFrame([
            {"strike": 100, "option_type": "call", "open_interest": 0},
            {"strike": 100, "option_type": "put", "open_interest": 0},
        ])
        assert estimate_max_pain(df, 100) is None

    def test_empty_returns_none(self):
        assert estimate_max_pain(pd.DataFrame(), 100) is None

    def test_em_is_distance_from_spot(self):
        rows = [
            {"strike": 90,  "option_type": "put",  "open_interest": 100},
            {"strike": 100, "option_type": "put",  "open_interest": 100},
            {"strike": 110, "option_type": "call", "open_interest": 100},
        ]
        e = estimate_max_pain(pd.DataFrame(rows), spot=105.0)
        if e is not None:
            assert e.em_dollar == abs(e.spot - e.max_pain_strike)


# ──────────────────────────────────────────────────────────────────────────
# Reconciler
# ──────────────────────────────────────────────────────────────────────────

class TestReconcile:
    def test_no_methods_zero_confidence(self):
        c = reconcile_estimates("X", 5, None, None, None)
        assert c.confidence == 0.0
        assert c.consensus_em_pct is None

    def test_only_iv_low_confidence(self):
        iv = IvEstimate(spot=100, iv_pct=20, days=30, em_dollar=5.7, em_pct=5.7)
        c = reconcile_estimates("X", 30, None, iv, None)
        assert c.confidence == 0.1
        assert c.consensus_em_pct == 5.7

    def test_methods_agree_high_confidence(self):
        s = StraddleEstimate(spot=100, atm_strike=100, call_mid=2.5, put_mid=2.5,
                             em_dollar=5.0, em_pct=5.0, n_strikes_used=1, days_to_event=2)
        iv = IvEstimate(spot=100, iv_pct=20, days=30, em_dollar=5.7, em_pct=5.5)
        c = reconcile_estimates("X", 30, s, iv, None)
        assert c.confidence == 1.0   # within 15%

    def test_methods_disagree_low_confidence(self):
        s = StraddleEstimate(spot=100, atm_strike=100, call_mid=2, put_mid=2,
                             em_dollar=4.0, em_pct=4.0, n_strikes_used=1, days_to_event=2)
        iv = IvEstimate(spot=100, iv_pct=80, days=30, em_dollar=22, em_pct=22)
        c = reconcile_estimates("X", 30, s, iv, None)
        assert c.confidence < 0.5

    def test_consensus_is_average(self):
        s = StraddleEstimate(spot=100, atm_strike=100, call_mid=2, put_mid=2,
                             em_dollar=4.0, em_pct=4.0, n_strikes_used=1, days_to_event=2)
        iv = IvEstimate(spot=100, iv_pct=24, days=30, em_dollar=6, em_pct=6.0)
        c = reconcile_estimates("X", 30, s, iv, None)
        assert c.consensus_em_pct == pytest.approx(5.0, abs=0.01)


# ──────────────────────────────────────────────────────────────────────────
# Compose
# ──────────────────────────────────────────────────────────────────────────

class TestCompose:
    def test_returns_consensus(self):
        df = _chain([95, 100, 105],
                    call_bids=[6.0, 2.4, 0.8], call_asks=[6.2, 2.6, 1.0],
                    put_bids=[0.8, 2.4, 6.0],  put_asks=[1.0, 2.6, 6.2])
        c = compute_expected_move("X", 100.0, iv_pct=20, days_to_event=30, options_df=df)
        assert isinstance(c, ConsensusMove)
        assert c.straddle is not None
        assert c.iv_based is not None

    def test_no_options_falls_back_to_iv_only(self):
        c = compute_expected_move("X", 100.0, iv_pct=20, days_to_event=30, options_df=None)
        assert c.straddle is None
        assert c.iv_based is not None
        assert c.confidence == 0.1

    def test_no_iv_no_options_zero_confidence(self):
        c = compute_expected_move("X", 100.0, iv_pct=None, days_to_event=30, options_df=None)
        assert c.confidence == 0.0


# ──────────────────────────────────────────────────────────────────────────
# Frozen guards
# ──────────────────────────────────────────────────────────────────────────

class TestFrozen:
    def test_consensus_frozen(self):
        c = compute_expected_move("X", 100, 20, 30, None)
        with pytest.raises(Exception):
            c.confidence = 0.0  # type: ignore[misc]
