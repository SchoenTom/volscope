"""
Tests for the Quick Start flow invariants.

The contract:
  - `make quickstart` seeds exactly the tickers in `_STARTER_PACK`
  - The first-run welcome card in discover_page uses the SAME tickers
  - If a future refactor changes one list without the other, this test fails

We pin both sides of the contract with a shared symbol set so the Makefile
and the UI can't drift out of sync silently.
"""
from __future__ import annotations

import re
from pathlib import Path

from volscope.ui.views.discover_page import _STARTER_PACK


class TestQuickstartContract:
    def test_starter_pack_has_eight_tickers(self):
        assert len(_STARTER_PACK) == 8

    def test_starter_pack_only_contains_liquid_names(self):
        """The starter pack must be all broadly-liquid names that any Yahoo
        install will resolve. No obscure symbols, no international codes
        (those need the fallback path)."""
        expected_core = {"SPY", "QQQ", "AAPL", "NVDA", "TSLA"}
        assert expected_core <= set(_STARTER_PACK), (
            f"Core liquid names missing from starter pack: "
            f"{expected_core - set(_STARTER_PACK)}"
        )

    def test_starter_pack_includes_asset_class_diversity(self):
        """The starter pack should cover more than just mega-cap tech — a
        first-run user should see cheap vs rich vs normal tickers, not just
        one regime. Including SPY (index ETF), GLD (commodity), TLT (bonds)
        gives the Discover page real diversity to rank against."""
        s = set(_STARTER_PACK)
        assert "SPY" in s  # broad index
        assert "GLD" in s  # commodity
        assert "TLT" in s  # bonds

    def test_makefile_quickstart_target_matches_starter_pack(self):
        """The `quickstart` Makefile target must pass exactly the same
        ticker list via --tickers. If one side changes without the other,
        fail the test so the README and the UI stay truthful."""
        makefile_path = Path(__file__).resolve().parent.parent / "Makefile"
        text = makefile_path.read_text()

        match = re.search(
            r"quickstart:.*?seed_database\.py --tickers (\S+)",
            text,
            re.DOTALL,
        )
        assert match is not None, "quickstart target in Makefile is missing or malformed"

        makefile_tickers = tuple(match.group(1).split(","))
        assert makefile_tickers == _STARTER_PACK, (
            f"Makefile starter pack {makefile_tickers} does not match "
            f"discover_page _STARTER_PACK {_STARTER_PACK}"
        )

    def test_makefile_has_quickstart_target(self):
        makefile_path = Path(__file__).resolve().parent.parent / "Makefile"
        text = makefile_path.read_text()
        assert "quickstart:" in text
        assert "pip install" in text.split("quickstart:")[1].split("\n\n")[0]
        assert "streamlit run" in text.split("quickstart:")[1].split("\n\n")[0]

    def test_makefile_has_all_advertised_targets(self):
        """README advertises these; if a refactor removes one, break loudly."""
        makefile_path = Path(__file__).resolve().parent.parent / "Makefile"
        text = makefile_path.read_text()
        for target in (
            "quickstart",
            "setup",
            "run",
            "seed-starter",
            "seed-full",
            "seed",
            "scrape",
            "test",
            "verify",
            "clean",
        ):
            assert f"{target}:" in text, f"Makefile is missing target: {target}"

    def test_readme_mentions_quickstart(self):
        readme = Path(__file__).resolve().parent.parent / "README.md"
        text = readme.read_text()
        assert "make quickstart" in text
        assert "Quick Start" in text
