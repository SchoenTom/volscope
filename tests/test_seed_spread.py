"""
Regression test for the flat IV-HV spread bug.

The old seed set `iv_30d = hv_20d = hv_close_to_close(close)`, which made
every Scope page spread chart a dead flat line at zero. The new seed uses
two different estimators scaled by a variance risk premium multiplier, so
the spread is always non-zero AND variable.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

import volscope.data.price_fetcher as pf
from volscope.data.database import VolScopeDB
from volscope.data.ticker_resolver import resolve_and_ingest


def _synthetic_ohlcv(n: int = 250, sigma: float = 0.25) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    dt = 1 / 252
    z = rng.standard_normal(n)
    r = (0.05 - 0.5 * sigma * sigma) * dt + sigma * np.sqrt(dt) * z
    close = 100.0 * np.exp(np.cumsum(r))
    open_ = np.roll(close, 1)
    open_[0] = 100.0
    # Intraday range noise — drives YZ vs CC divergence.
    intraday_noise = rng.uniform(0.002, 0.015, size=n)
    high = np.maximum(open_, close) * (1 + intraday_noise)
    low = np.minimum(open_, close) * (1 - intraday_noise)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": 1_000_000},
        index=idx,
    )


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "seed.db")
    d = VolScopeDB(path)
    yield d
    d.close()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


class TestSeedSpread:
    def test_spread_is_non_zero_after_seed(self, db, monkeypatch):
        monkeypatch.setattr(pf, "fetch_ohlcv", lambda t, period="2y": _synthetic_ohlcv(250))
        result = resolve_and_ingest(db, "TEST")
        assert result.ok, result.message

        history = db.get_ticker_history("TEST")
        spreads = (history["iv_30d"] - history["hv_20d"]).dropna()
        assert len(spreads) > 100

        # None of the fresh seed rows should produce an exact zero spread.
        zeros = (spreads.abs() < 1e-9).sum()
        assert zeros < len(spreads) * 0.05, (
            f"{zeros}/{len(spreads)} rows have zero spread — seed proxy is broken"
        )

    def test_spread_mean_is_positive_vrp(self, db, monkeypatch):
        """Average VRP should be positive — IV trades above RV on average."""
        monkeypatch.setattr(pf, "fetch_ohlcv", lambda t, period="2y": _synthetic_ohlcv(250))
        resolve_and_ingest(db, "TEST")
        history = db.get_ticker_history("TEST")
        mean_spread = (history["iv_30d"] - history["hv_20d"]).dropna().mean()
        assert mean_spread > 0, f"Mean spread was {mean_spread}, expected > 0"

    def test_spread_has_variance(self, db, monkeypatch):
        """The spread must VARY over time — a constant offset would still
        leave the user with a boring flat chart."""
        monkeypatch.setattr(pf, "fetch_ohlcv", lambda t, period="2y": _synthetic_ohlcv(250))
        resolve_and_ingest(db, "TEST")
        history = db.get_ticker_history("TEST")
        spreads = (history["iv_30d"] - history["hv_20d"]).dropna()
        assert spreads.std() > 0.1, f"Spread std was {spreads.std():.4f}, expected > 0.1"

    def test_iv_is_not_equal_to_hv(self, db, monkeypatch):
        """The direct bug: iv_30d must NOT be identical to hv_20d."""
        monkeypatch.setattr(pf, "fetch_ohlcv", lambda t, period="2y": _synthetic_ohlcv(250))
        resolve_and_ingest(db, "TEST")
        history = db.get_ticker_history("TEST")
        # Count rows where iv_30d == hv_20d exactly.
        identical = ((history["iv_30d"] - history["hv_20d"]).abs() < 1e-9).sum()
        assert identical == 0, f"{identical} rows have iv_30d == hv_20d"

    def test_spread_column_is_populated(self, db, monkeypatch):
        """The `iv_hv_spread` DB column must also be populated, not just the
        derived spread. It was hardcoded to 0.0 in the old seed."""
        monkeypatch.setattr(pf, "fetch_ohlcv", lambda t, period="2y": _synthetic_ohlcv(250))
        resolve_and_ingest(db, "TEST")
        history = db.get_ticker_history("TEST")
        spread_col = history["iv_hv_spread"].dropna()
        assert len(spread_col) > 100
        non_zero = (spread_col.abs() > 0.01).sum()
        assert non_zero > 100, "iv_hv_spread column is all zeros"
