"""
Tests for the new Discover panels: sector vol map + market regime strip.
These are smoke tests — they verify the render functions don't crash on
realistic input shapes and emit the expected structural markers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from volscope.ui.views.discover_page import (
    _render_regime_strip,
    _render_sector_vol_map,
)


class _FakeSt:
    def __init__(self):
        self.markdown_bodies: list[str] = []
        self.captions: list[str] = []

    def markdown(self, body: str, unsafe_allow_html: bool = False) -> None:
        self.markdown_bodies.append(body)

    def caption(self, body: str) -> None:
        self.captions.append(body)


@pytest.fixture
def healthy_latest() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    tickers = [f"T{i:03d}" for i in range(24)]
    sectors = ["Tech", "Tech", "Tech", "Energy", "Energy", "Financials"] * 4
    return pd.DataFrame(
        {
            "ticker": tickers,
            "sector": sectors,
            "iv_30d": rng.uniform(10, 80, size=24),
            "iv_percentile": rng.uniform(0, 100, size=24),
            "hv_20d": rng.uniform(8, 70, size=24),
        }
    )


class TestSectorVolMap:
    def test_renders_rows_for_sectors(self, healthy_latest):
        fake = _FakeSt()
        _render_sector_vol_map(fake, healthy_latest)
        combined = " ".join(fake.markdown_bodies)
        assert "SECTOR VOL MAP" in combined
        # All rendered HTML joined — sector names appear in the rows container.
        assert "Tech" in combined
        assert "Energy" in combined
        assert "Financials" in combined

    def test_skips_singletons(self):
        """Sectors with only one ticker have no meaningful median — drop them."""
        fake = _FakeSt()
        df = pd.DataFrame(
            {
                "ticker": ["AAA", "BBB"],
                "sector": ["Tech", "Solo"],  # Solo sector only has 1
                "iv_30d": [20.0, 30.0],
                "iv_percentile": [30.0, 50.0],
                "hv_20d": [18.0, 28.0],
            }
        )
        _render_sector_vol_map(fake, df)
        html_body = " ".join(fake.markdown_bodies)
        # Neither sector has 2+ members, so the fallback caption fires.
        assert "at least two tickers" in " ".join(fake.captions)

    def test_empty_sector_column(self):
        fake = _FakeSt()
        df = pd.DataFrame({"ticker": ["A"], "iv_percentile": [50.0]})
        _render_sector_vol_map(fake, df)
        assert any("No sector data" in c for c in fake.captions)


class TestRegimeStrip:
    def test_risk_on_when_median_low(self):
        fake = _FakeSt()
        df = pd.DataFrame(
            {
                "ticker": [f"T{i}" for i in range(20)],
                "iv_percentile": [10.0] * 20,
            }
        )
        _render_regime_strip(fake, df)
        body = " ".join(fake.markdown_bodies)
        assert "RISK ON" in body

    def test_risk_off_when_median_high(self):
        fake = _FakeSt()
        df = pd.DataFrame(
            {
                "ticker": [f"T{i}" for i in range(20)],
                "iv_percentile": [90.0] * 20,
            }
        )
        _render_regime_strip(fake, df)
        body = " ".join(fake.markdown_bodies)
        assert "RISK OFF" in body

    def test_normal_middle_band(self):
        fake = _FakeSt()
        df = pd.DataFrame(
            {
                "ticker": [f"T{i}" for i in range(20)],
                "iv_percentile": [50.0] * 20,
            }
        )
        _render_regime_strip(fake, df)
        body = " ".join(fake.markdown_bodies)
        assert "NORMAL" in body

    def test_elevated_above_normal(self):
        fake = _FakeSt()
        df = pd.DataFrame(
            {
                "ticker": [f"T{i}" for i in range(20)],
                "iv_percentile": [65.0] * 20,
            }
        )
        _render_regime_strip(fake, df)
        body = " ".join(fake.markdown_bodies)
        assert "ELEVATED" in body

    def test_insufficient_data(self):
        fake = _FakeSt()
        df = pd.DataFrame(
            {"ticker": ["A", "B"], "iv_percentile": [10.0, 20.0]}
        )
        _render_regime_strip(fake, df)
        assert any("at least 5" in c for c in fake.captions)


class TestExpandedUniverse:
    def test_universe_has_at_least_200_tickers(self):
        from volscope.data.ticker_universe import all_tickers

        assert len(all_tickers()) >= 200

    def test_universe_includes_sp500_leaders(self):
        from volscope.data.ticker_universe import all_tickers

        universe = set(all_tickers())
        # A handful of names that MUST exist in any "serious" US universe.
        required = {"AAPL", "MSFT", "NVDA", "JPM", "XOM", "UNH", "V", "BRK-B"}
        missing = required - universe
        assert not missing, f"missing S&P 500 leaders: {sorted(missing)}"

    def test_universe_includes_international_examples(self):
        from volscope.data.ticker_universe import all_tickers

        universe = set(all_tickers())
        assert "BABA" in universe
        assert "ASML" in universe  # semi equipment
        assert "TSM" in universe

    def test_sector_of_returns_correct_label(self):
        from volscope.data.ticker_universe import sector_of

        assert sector_of("AAPL") == "Mega Cap Tech"
        assert sector_of("JPM") == "Financials — Banks"
        assert sector_of("UNKNOWN_TICKER") is None
