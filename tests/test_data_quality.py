"""Tests for the data-quality heuristic checker."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from datetime import date, timedelta

from volscope.analytics.data_quality import (
    CompletenessReport,
    CompositeQuality,
    FreshnessReport,
    QualityReport,
    check_completeness,
    check_freshness,
    check_row,
    composite_quality,
    quality_badge_html,
    summarize_quality,
)


def _row(**kwargs) -> pd.Series:
    return pd.Series(kwargs)


def _hist(spreads: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "iv_30d": [20.0 + s for s in spreads],
            "hv_20d": [20.0] * len(spreads),
        }
    )


class TestCheckRow:
    def test_clean_row_is_ok(self):
        r = check_row(_row(iv_30d=15.0, hv_20d=12.0, sector="Mega Cap Tech"))
        assert r.level == "OK"
        assert r.reasons == []

    def test_missing_iv_is_ok(self):
        r = check_row(_row(iv_30d=None, hv_20d=12.0))
        assert r.level == "OK"

    def test_nan_iv_is_ok(self):
        r = check_row(_row(iv_30d=float("nan"), hv_20d=12.0))
        assert r.level == "OK"

    def test_etf_ceiling(self):
        r = check_row(_row(iv_30d=150.0, hv_20d=15.0, sector="Index ETF"))
        assert r.level == "SUSPECT"
        assert any("ceiling" in msg for msg in r.reasons)

    def test_single_name_high_iv_ok(self):
        """500% is the single-name ceiling — below is legitimate (meme spikes)."""
        r = check_row(_row(iv_30d=400.0, hv_20d=50.0, sector="Mega Cap Tech"))
        assert r.level == "OK"

    def test_crypto_ceiling(self):
        r = check_row(_row(iv_30d=400.0, hv_20d=50.0, sector="Crypto (spot pairs)"))
        assert r.level == "SUSPECT"

    def test_near_zero_iv_is_suspect(self):
        r = check_row(_row(iv_30d=1.5, hv_20d=15.0, sector="Index ETF"))
        assert r.level == "SUSPECT"
        assert any("floor" in msg for msg in r.reasons)

    def test_spread_outlier_beyond_4_sigma_is_suspect(self):
        hist = _hist([0.0, 0.1, -0.1, 0.2, -0.2] * 10)  # tight distribution
        row = _row(iv_30d=30.0, hv_20d=20.0, sector="Index ETF")  # spread=+10
        r = check_row(row, hist)
        assert r.level == "SUSPECT"

    def test_spread_outlier_between_3_and_4_sigma_is_warn(self):
        rng = np.random.default_rng(1)
        hist_spreads = rng.normal(0, 1, 100)
        hist = _hist(list(hist_spreads))
        # ~3.2 sigma out: spread = mean + 3.2 * std ≈ 3.2
        row = _row(iv_30d=23.2, hv_20d=20.0, sector="Index ETF")
        r = check_row(row, hist)
        assert r.level in ("WARN", "SUSPECT")

    def test_short_history_skips_spread_check(self):
        hist = _hist([0.1, -0.1, 0.2])  # only 3 rows, below the 30-row threshold
        row = _row(iv_30d=50.0, hv_20d=20.0, sector="Index ETF")
        r = check_row(row, hist)
        # Should not be WARNed about spread — too little data. But the ETF
        # ceiling check still runs since it doesn't need history.
        assert r.level == "OK"  # 50% is below the 120% ETF ceiling


class TestSummarize:
    def test_empty_input(self):
        df = summarize_quality(pd.DataFrame(), {})
        assert df.empty

    def test_only_flagged_rows_returned(self):
        latest = pd.DataFrame(
            {
                "ticker": ["CLEAN", "BROKEN"],
                "iv_30d": [15.0, 200.0],
                "hv_20d": [12.0, 18.0],
                "sector": ["Index ETF", "Index ETF"],
            }
        )
        result = summarize_quality(latest, {})
        assert list(result["ticker"]) == ["BROKEN"]
        assert result.iloc[0]["level"] == "SUSPECT"

    def test_quality_report_has_level_and_reasons(self):
        r = QualityReport(level="WARN", reasons=["test reason"])
        assert r.level == "WARN"
        assert r.reasons == ["test reason"]


# ──────────────────────────────────────────────────────────────────────────
# Freshness
# ──────────────────────────────────────────────────────────────────────────

class TestFreshness:
    def test_today_is_fresh(self):
        today = date(2026, 5, 1)
        r = check_freshness(_row(date=today), today=today)
        assert r.level == "FRESH"
        assert r.age_days == 0

    def test_two_days_old_fresh(self):
        today = date(2026, 5, 1)
        r = check_freshness(_row(date=today - timedelta(days=2)), today=today)
        assert r.level == "FRESH"

    def test_five_days_old_aging(self):
        today = date(2026, 5, 1)
        r = check_freshness(_row(date=today - timedelta(days=5)), today=today)
        assert r.level == "AGING"

    def test_ten_days_old_aging(self):
        today = date(2026, 5, 1)
        r = check_freshness(_row(date=today - timedelta(days=10)), today=today)
        assert r.level == "AGING"

    def test_twenty_days_old_stale(self):
        today = date(2026, 5, 1)
        r = check_freshness(_row(date=today - timedelta(days=20)), today=today)
        assert r.level == "STALE"

    def test_missing_date_stale(self):
        r = check_freshness(_row(), today=date(2026, 5, 1))
        assert r.level == "STALE"

    def test_future_date_stale(self):
        today = date(2026, 5, 1)
        r = check_freshness(_row(date=today + timedelta(days=10)), today=today)
        assert r.level == "STALE"

    def test_string_date_parsed(self):
        r = check_freshness(_row(date="2026-04-30"), today=date(2026, 5, 1))
        assert r.age_days == 1


# ──────────────────────────────────────────────────────────────────────────
# Completeness
# ──────────────────────────────────────────────────────────────────────────

class TestCompleteness:
    def test_all_5_fields_full(self):
        r = check_completeness(_row(
            iv_30d=20, iv_60d=22, iv_90d=23, iv_180d=24, iv_skew_25d=2,
        ))
        assert r.level == "FULL"
        assert r.n_present == 5

    def test_three_of_five_partial(self):
        r = check_completeness(_row(iv_30d=20, iv_60d=22, iv_90d=23))
        assert r.level == "PARTIAL"
        assert r.n_present == 3
        assert "iv_180d" in r.missing_fields

    def test_only_iv30_minimal(self):
        r = check_completeness(_row(iv_30d=20))
        assert r.level == "MINIMAL"
        assert r.n_present == 1

    def test_nan_treated_as_missing(self):
        r = check_completeness(_row(
            iv_30d=20, iv_60d=float("nan"), iv_90d=23,
        ))
        assert "iv_60d" in r.missing_fields

    def test_empty_minimal(self):
        r = check_completeness(_row())
        assert r.level == "MINIMAL"
        assert r.n_present == 0


# ──────────────────────────────────────────────────────────────────────────
# Composite
# ──────────────────────────────────────────────────────────────────────────

class TestComposite:
    def test_clean_fresh_full_is_ok(self):
        today = date(2026, 5, 1)
        c = composite_quality(
            _row(date=today, iv_30d=20, iv_60d=22, iv_90d=23, iv_180d=24,
                 iv_skew_25d=2, hv_20d=18, sector="Mega Cap Tech"),
            today=today,
        )
        assert c.overall_level == "OK"

    def test_stale_data_marks_stale(self):
        today = date(2026, 5, 1)
        c = composite_quality(
            _row(date=today - timedelta(days=20),
                 iv_30d=20, iv_60d=22, iv_90d=23, iv_180d=24,
                 iv_skew_25d=2, hv_20d=18, sector="Mega Cap Tech"),
            today=today,
        )
        assert c.overall_level == "STALE"

    def test_minimal_completeness_marks_partial(self):
        today = date(2026, 5, 1)
        c = composite_quality(
            _row(date=today, iv_30d=20, hv_20d=18, sector="Mega Cap Tech"),
            today=today,
        )
        assert c.overall_level == "PARTIAL"

    def test_aging_yields_warn(self):
        today = date(2026, 5, 1)
        c = composite_quality(
            _row(date=today - timedelta(days=5),
                 iv_30d=20, iv_60d=22, iv_90d=23, iv_180d=24,
                 iv_skew_25d=2, hv_20d=18, sector="Mega Cap Tech"),
            today=today,
        )
        assert c.overall_level == "WARN"

    def test_one_liner_non_empty(self):
        today = date(2026, 5, 1)
        c = composite_quality(_row(date=today, iv_30d=20), today=today)
        assert isinstance(c.one_liner, str) and c.one_liner


# ──────────────────────────────────────────────────────────────────────────
# Badge HTML
# ──────────────────────────────────────────────────────────────────────────

class TestBadgeHtml:
    def test_renders_string(self):
        today = date(2026, 5, 1)
        c = composite_quality(_row(date=today, iv_30d=20), today=today)
        html = quality_badge_html(c)
        assert "<span" in html
        assert c.overall_level in html

    def test_distinct_colors_per_level(self):
        today = date(2026, 5, 1)
        ok = composite_quality(
            _row(date=today, iv_30d=20, iv_60d=22, iv_90d=23, iv_180d=24,
                 iv_skew_25d=2, hv_20d=18, sector="Mega Cap Tech"),
            today=today,
        )
        stale = composite_quality(
            _row(date=today - timedelta(days=21), iv_30d=20, iv_60d=22,
                 iv_90d=23, iv_180d=24, iv_skew_25d=2, hv_20d=18,
                 sector="Mega Cap Tech"),
            today=today,
        )
        assert quality_badge_html(ok) != quality_badge_html(stale)
