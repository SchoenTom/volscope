"""Tests for analytics.data_validator — IV/HV self-back-check."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.data_validator import (
    Finding,
    ValidationReport,
    check_cross_proxy,
    check_iv_hv_consistency,
    check_skew_sanity,
    check_term_structure,
    check_time_series_anomaly,
    summarise_universe,
    validate_row,
    validate_universe,
)


def _row(**kwargs) -> pd.Series:
    return pd.Series(kwargs)


# ──────────────────────────────────────────────────────────────────────────
# IV/HV consistency
# ──────────────────────────────────────────────────────────────────────────

class TestIvHvConsistency:
    def test_normal_close_passes(self):
        f = check_iv_hv_consistency(_row(iv_30d=22, hv_20d=20))
        assert f.level == "OK"

    def test_moderate_divergence_flagged(self):
        # ratio = (22-8)/8 = 1.75 → FLAG (between 1.5 and 3.5)
        f = check_iv_hv_consistency(_row(iv_30d=22, hv_20d=8))
        assert f.level == "FLAG"

    def test_extreme_divergence_failed(self):
        # ratio = |80 - 5| / 5 = 15 → FAIL
        f = check_iv_hv_consistency(_row(iv_30d=80, hv_20d=5))
        assert f.level == "FAIL"

    def test_missing_data_skipped(self):
        f = check_iv_hv_consistency(_row(iv_30d=None, hv_20d=20))
        assert f.level == "OK"
        assert "insufficient" in f.detail or "skipped" in f.detail

    def test_zero_hv_skipped(self):
        f = check_iv_hv_consistency(_row(iv_30d=20, hv_20d=0))
        assert f.level == "OK"


# ──────────────────────────────────────────────────────────────────────────
# Term structure
# ──────────────────────────────────────────────────────────────────────────

class TestTermStructure:
    def test_normal_contango_passes(self):
        f = check_term_structure(_row(iv_30d=20, iv_60d=21, iv_90d=22, iv_180d=23))
        assert f.level == "OK"

    def test_small_inversion_passes(self):
        f = check_term_structure(_row(iv_30d=22, iv_60d=21, iv_90d=20, iv_180d=20))
        assert f.level == "OK"   # 2pp inversion below FLAG threshold

    def test_moderate_inversion_flagged(self):
        # front-back = 30 - 18 = 12 → FLAG (>5pp)
        f = check_term_structure(_row(iv_30d=30, iv_60d=25, iv_90d=20, iv_180d=18))
        assert f.level == "FLAG"

    def test_extreme_inversion_failed(self):
        # front-back = 50 - 20 = 30 → FAIL (>15pp)
        f = check_term_structure(_row(iv_30d=50, iv_60d=40, iv_90d=25, iv_180d=20))
        assert f.level == "FAIL"

    def test_only_one_point(self):
        f = check_term_structure(_row(iv_30d=20))
        assert f.level == "OK"


# ──────────────────────────────────────────────────────────────────────────
# Skew sanity
# ──────────────────────────────────────────────────────────────────────────

class TestSkewSanity:
    def test_normal_skew(self):
        assert check_skew_sanity(_row(iv_skew_25d=5)).level == "OK"

    def test_negative_skew_normal(self):
        assert check_skew_sanity(_row(iv_skew_25d=-2)).level == "OK"

    def test_extreme_positive_flagged(self):
        # 35 > 30 → FLAG
        assert check_skew_sanity(_row(iv_skew_25d=35)).level == "FLAG"

    def test_extreme_negative_flagged(self):
        assert check_skew_sanity(_row(iv_skew_25d=-40)).level == "FLAG"

    def test_absurd_skew_failed(self):
        # 60 > 50 → FAIL
        assert check_skew_sanity(_row(iv_skew_25d=60)).level == "FAIL"

    def test_no_skew_data(self):
        assert check_skew_sanity(_row()).level == "OK"


# ──────────────────────────────────────────────────────────────────────────
# Time-series anomaly
# ──────────────────────────────────────────────────────────────────────────

class TestTimeSeriesAnomaly:
    def test_no_history(self):
        f = check_time_series_anomaly(_row(iv_30d=22), history=None)
        assert f.level == "OK"

    def test_stable_series_no_flag(self):
        hist = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=10),
            "iv_30d": [20, 21, 19, 20, 21, 20, 19, 20, 21, 20],
        })
        f = check_time_series_anomaly(_row(iv_30d=20.5), history=hist)
        assert f.level == "OK"

    def test_extreme_jump_failed(self):
        # 7 days at 20, today at 50 → z >> 5
        hist = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=8),
            "iv_30d": [20, 20.1, 19.9, 20, 20, 20.1, 19.9, 20],
        })
        f = check_time_series_anomaly(_row(iv_30d=50), history=hist)
        assert f.level == "FAIL"

    def test_too_short_history(self):
        hist = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=2),
            "iv_30d": [20, 20.5],
        })
        f = check_time_series_anomaly(_row(iv_30d=22), history=hist)
        assert f.level == "OK"


# ──────────────────────────────────────────────────────────────────────────
# Cross proxy
# ──────────────────────────────────────────────────────────────────────────

class TestCrossProxy:
    def test_unmapped_ticker_skipped(self):
        f = check_cross_proxy("OBSCURE", _row(iv_30d=22), proxy_iv=15)
        assert f.level == "OK"
        assert "no proxy" in f.detail.lower()

    def test_spy_within_proxy_band(self):
        # SPY tolerance is 25%; IV=18 vs VIX=15 → diff=20% → OK
        f = check_cross_proxy("SPY", _row(iv_30d=18), proxy_iv=15)
        assert f.level == "OK"

    def test_spy_just_over_band_flagged(self):
        # 30% divergence > 25% → FLAG
        f = check_cross_proxy("SPY", _row(iv_30d=22), proxy_iv=15)
        assert f.level == "FLAG"

    def test_spy_extreme_divergence_failed(self):
        # >> 50% (twice band) → FAIL
        f = check_cross_proxy("SPY", _row(iv_30d=60), proxy_iv=15)
        assert f.level == "FAIL"

    def test_proxy_unavailable_skipped(self):
        f = check_cross_proxy("SPY", _row(iv_30d=22), proxy_iv=None)
        assert f.level == "OK"


# ──────────────────────────────────────────────────────────────────────────
# Aggregate
# ──────────────────────────────────────────────────────────────────────────

class TestValidateRow:
    def test_clean_row_overall_ok(self):
        r = validate_row(
            "AAPL",
            _row(iv_30d=22, hv_20d=20, iv_60d=23, iv_90d=24, iv_180d=25,
                 iv_skew_25d=3),
        )
        assert r.overall_level == "OK"

    def test_one_fail_pulls_overall_to_fail(self):
        r = validate_row(
            "X",
            _row(iv_30d=22, hv_20d=20, iv_skew_25d=70),  # skew=70 → FAIL
        )
        assert r.overall_level == "FAIL"

    def test_only_flags_yields_flag_overall(self):
        r = validate_row(
            "X",
            _row(iv_30d=22, hv_20d=8, iv_skew_25d=35),  # IV/HV FLAG + skew FLAG
        )
        assert r.overall_level == "FLAG"

    def test_n_passes_n_flags_n_fails_sum(self):
        r = validate_row(
            "X",
            _row(iv_30d=22, hv_20d=20, iv_60d=21, iv_skew_25d=3),
        )
        assert r.n_passes + r.n_flags + r.n_fails == 5

    def test_findings_tuple_size(self):
        r = validate_row("X", _row(iv_30d=22, hv_20d=20))
        assert len(r.findings) == 5


# ──────────────────────────────────────────────────────────────────────────
# Universe
# ──────────────────────────────────────────────────────────────────────────

class TestValidateUniverse:
    def test_empty_universe(self):
        assert validate_universe(pd.DataFrame(), {}) == []

    def test_runs_for_each_row(self):
        df = pd.DataFrame({
            "ticker": ["AAPL", "QQQ", "SPY"],
            "iv_30d": [22.0, 18.0, 15.0],
            "hv_20d": [20.0, 18.0, 14.0],
        })
        reports = validate_universe(df, histories={})
        assert len(reports) == 3

    def test_proxy_levels_passed_through(self):
        df = pd.DataFrame({
            "ticker": ["SPY"],
            "iv_30d": [50.0],   # vs VIX=15 → 233% divergence → FAIL
            "hv_20d": [20.0],
        })
        reports = validate_universe(df, histories={}, proxy_levels={"^VIX": 15.0})
        assert len(reports) == 1
        proxy_findings = [f for f in reports[0].findings if f.check == "proxy"]
        assert proxy_findings[0].level == "FAIL"


# ──────────────────────────────────────────────────────────────────────────
# Summarise
# ──────────────────────────────────────────────────────────────────────────

class TestSummarise:
    def test_empty(self):
        s = summarise_universe([])
        assert s["n_total"] == 0
        assert s["n_ok"] == 0

    def test_counts(self):
        df = pd.DataFrame({
            "ticker": ["A", "B", "C"],
            "iv_30d": [22, 22, 100],   # C: large IV vs HV → FAIL
            "hv_20d": [20, 20,   1],
        })
        reports = validate_universe(df, histories={})
        s = summarise_universe(reports)
        assert s["n_total"] == 3
        assert s["n_fail"] >= 1


# ──────────────────────────────────────────────────────────────────────────
# Frozen guards
# ──────────────────────────────────────────────────────────────────────────

class TestFrozen:
    def test_finding_frozen(self):
        f = Finding(check="x", level="OK", detail="ok")
        with pytest.raises(Exception):
            f.level = "FAIL"  # type: ignore[misc]

    def test_report_frozen(self):
        r = validate_row("X", _row(iv_30d=22, hv_20d=20))
        with pytest.raises(Exception):
            r.overall_level = "FAIL"  # type: ignore[misc]
