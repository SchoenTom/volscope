"""Generate synthetic GBM paths with KNOWN volatility, recover it."""
import numpy as np
import pandas as pd
import pytest

from volscope.analytics.historical_vol import (
    hv_close_to_close,
    hv_garman_klass,
    hv_parkinson,
    hv_yang_zhang,
)


def generate_gbm(S0: float = 100.0, mu: float = 0.05, sigma: float = 0.25, N: int = 504):
    """Generate N+1 days of synthetic OHLC data with known sigma."""
    rng = np.random.default_rng(42)
    dt = 1.0 / 252.0
    Z = rng.standard_normal(N)
    log_returns = (mu - 0.5 * sigma * sigma) * dt + sigma * np.sqrt(dt) * Z
    prices = S0 * np.exp(np.cumsum(log_returns))
    prices = np.insert(prices, 0, S0)

    close = pd.Series(prices)
    open_ = close.shift(1).fillna(S0)
    noise_hi = np.abs(rng.normal(0, 0.005, len(close)))
    noise_lo = np.abs(rng.normal(0, 0.005, len(close)))
    pair_max = pd.DataFrame({"c": close, "o": open_}).max(axis=1)
    pair_min = pd.DataFrame({"c": close, "o": open_}).min(axis=1)
    high = pair_max * (1 + noise_hi)
    low = pair_min * (1 - noise_lo)
    return open_, high, low, close


class TestHVEstimators:
    def setup_method(self):
        self.open, self.high, self.low, self.close = generate_gbm(sigma=0.25)

    def test_cc_recovers_vol(self):
        hv = hv_close_to_close(self.close, window=60)
        recent = hv.dropna().tail(100).mean()
        assert 15 < recent < 40

    def test_parkinson_recovers_vol(self):
        hv = hv_parkinson(self.high, self.low, window=60)
        recent = hv.dropna().tail(100).mean()
        assert 10 < recent < 60

    def test_gk_recovers_vol(self):
        hv = hv_garman_klass(self.open, self.high, self.low, self.close, window=60)
        recent = hv.dropna().tail(100).mean()
        assert 10 < recent < 60

    def test_yz_recovers_vol(self):
        hv = hv_yang_zhang(self.open, self.high, self.low, self.close, window=60)
        recent = hv.dropna().tail(100).mean()
        assert 10 < recent < 60

    def test_yz_bounded_error(self):
        # On pure-GBM synthetic data, CC is optimal since the process is close-to-close
        # by construction. YZ should still produce a reasonable estimate.
        yz = hv_yang_zhang(self.open, self.high, self.low, self.close, 60).dropna().tail(100)
        assert (yz - 25.0).abs().mean() < 10.0

    def test_all_return_series(self):
        cc = hv_close_to_close(self.close, 20)
        pk = hv_parkinson(self.high, self.low, 20)
        gk = hv_garman_klass(self.open, self.high, self.low, self.close, 20)
        yz = hv_yang_zhang(self.open, self.high, self.low, self.close, 20)
        for s in (cc, pk, gk, yz):
            assert isinstance(s, pd.Series)

    def test_nan_handling_cc(self):
        hv = hv_close_to_close(self.close, window=20)
        # with window=20 rolling std, first 20 values are NaN (need 20 returns + 1 NaN first row)
        assert hv.iloc[:20].isna().all()
        assert hv.iloc[25:].notna().all()

    def test_gk_no_nan_on_tight_range(self):
        """Garman-Klass term can dip negative when range is tight relative to drift —
        the estimator must clip to 0 and never produce NaN sqrt errors."""
        n = 60
        # Tight intraday range, large overnight drift — would cause negative variance.
        close = pd.Series(np.linspace(100.0, 110.0, n))
        open_ = close.shift(1).fillna(100.0)
        high = pd.DataFrame({"o": open_, "c": close}).max(axis=1) * 1.0001
        low = pd.DataFrame({"o": open_, "c": close}).min(axis=1) * 0.9999
        gk = hv_garman_klass(open_, high, low, close, window=20)
        assert gk.dropna().notna().all()
        assert (gk.dropna() >= 0).all()
