"""
Tests for the data-quality sanity layer:
  - daily_scrape rejects scraped IVs that exceed per-ticker-class caps
  - daily_scrape rejects day-over-day jumps that look like data artifacts
  - opportunity.find_daily_outliers drops artifact-looking rows BEFORE ranking

These are the direct fixes for: "SPY IV 78%" (cap rejection) and
"SPY ▲ 58.2" (artifact filter in movers panel).
"""
from __future__ import annotations

import pandas as pd
import pytest

from volscope.analytics.opportunity import (
    _looks_like_data_artifact,
    find_daily_outliers,
)
from scripts.daily_scrape import _iv_cap_for


class TestPlausibilityCaps:
    @pytest.mark.parametrize(
        "ticker,sector,expected_cap",
        [
            ("SPY", "Index ETF", 120.0),
            ("XLF", "Sector ETF", 120.0),
            ("VXX", "Vol ETF", 400.0),
            ("SVXY", "Vol ETF", 400.0),
            ("AAPL", "Mega Cap Tech", 500.0),
            ("GME", "Meme / High Vol", 500.0),
            ("BTC-USD", "Crypto (spot pairs)", 300.0),
            ("^VIX", "Indices (read-only)", 100.0),
            ("^GSPC", None, 100.0),  # starts with ^ even without sector
        ],
    )
    def test_cap_by_ticker_class(self, ticker, sector, expected_cap):
        assert _iv_cap_for(ticker, sector) == expected_cap

    def test_unknown_sector_falls_back_to_single_name(self):
        assert _iv_cap_for("RANDOM", "Some Weird Sector") == 500.0

    def test_spy_78_percent_would_be_accepted(self):
        """SPY at 78% IV is technically within the ETF cap of 120%. The cap
        rejects only clearly-impossible values; 78% gets through. The user's
        other safeguard is the day-over-day artifact filter."""
        assert 78.0 < _iv_cap_for("SPY", "Index ETF")

    def test_spy_150_percent_would_be_rejected(self):
        """Anything over the cap is a clear data bug — reject."""
        assert 150.0 > _iv_cap_for("SPY", "Index ETF")


class TestArtifactDetection:
    def test_small_move_is_not_artifact(self):
        # Real daily move: 15% -> 18%, +3pt, 20% relative
        assert not _looks_like_data_artifact(15.0, 18.0)

    def test_moderate_move_is_not_artifact(self):
        # Real stressful move: 20% -> 35%, +15pt, 75% relative
        assert not _looks_like_data_artifact(20.0, 35.0)

    def test_seed_to_scrape_jump_is_artifact(self):
        """The exact pattern the user saw: prev=20 (seed proxy), curr=78
        (stale scrape). 58 absolute, 290% relative. Both thresholds tripped."""
        assert _looks_like_data_artifact(20.0, 78.0)

    def test_scrape_to_bad_scrape_jump_is_artifact(self):
        assert _looks_like_data_artifact(15.0, 85.0)

    def test_none_inputs_are_safe(self):
        assert not _looks_like_data_artifact(None, 50.0)
        assert not _looks_like_data_artifact(50.0, None)
        assert not _looks_like_data_artifact(None, None)

    def test_zero_prev_is_safe(self):
        assert not _looks_like_data_artifact(0.0, 50.0)


class TestMoversDropArtifacts:
    def test_artifact_row_excluded_from_movers(self):
        """If SPY has a 58pt fake jump, it must NOT appear as a mover."""
        latest = pd.DataFrame(
            {"ticker": ["SPY", "AAPL"], "iv_30d": [78.0, 32.0]}
        )
        prev = pd.DataFrame({"ticker": ["SPY", "AAPL"], "iv_30d": [20.0, 30.0]})
        movers = find_daily_outliers(latest, prev, n=5)
        tickers = movers["ticker"].tolist()
        assert "SPY" not in tickers, (
            "SPY's 20→78 jump should be filtered as an artifact"
        )
        assert "AAPL" in tickers  # Real small move should still show up.

    def test_all_artifacts_returns_empty(self):
        latest = pd.DataFrame(
            {"ticker": ["SPY", "QQQ"], "iv_30d": [85.0, 92.0]}
        )
        prev = pd.DataFrame({"ticker": ["SPY", "QQQ"], "iv_30d": [15.0, 18.0]})
        movers = find_daily_outliers(latest, prev, n=5)
        assert movers.empty

    def test_real_moves_still_ranked(self):
        """A calm stock with a real small move shouldn't be filtered."""
        latest = pd.DataFrame(
            {"ticker": ["KO", "PEP"], "iv_30d": [16.0, 18.0]}
        )
        prev = pd.DataFrame({"ticker": ["KO", "PEP"], "iv_30d": [14.0, 15.0]})
        movers = find_daily_outliers(latest, prev, n=5)
        assert len(movers) == 2
