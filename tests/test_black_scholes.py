"""Tests for BSM model — validated against known analytical solutions."""
import numpy as np
import pytest

from volscope.analytics.black_scholes import (
    bs_delta,
    bs_gamma,
    bs_price,
    bs_rho,
    bs_theta,
    bs_vega,
    implied_volatility,
)


class TestBSMPricing:
    def test_atm_call(self):
        price = bs_price(100, 100, 1.0, 0.05, 0.20, option_type="call")
        assert abs(price - 10.4506) < 0.01

    def test_atm_put(self):
        price = bs_price(100, 100, 1.0, 0.05, 0.20, option_type="put")
        assert abs(price - 5.5735) < 0.01

    def test_put_call_parity(self):
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.30
        call = bs_price(S, K, T, r, sigma, option_type="call")
        put = bs_price(S, K, T, r, sigma, option_type="put")
        assert abs((call - put) - (S - K * np.exp(-r * T))) < 0.01

    def test_deep_itm_call(self):
        price = bs_price(150, 100, 1.0, 0.05, 0.20, option_type="call")
        assert price > 50

    def test_deep_otm_call(self):
        price = bs_price(50, 100, 1.0, 0.05, 0.20, option_type="call")
        assert price < 1

    def test_zero_time(self):
        call = bs_price(105, 100, 0.0, 0.05, 0.20, option_type="call")
        assert abs(call - 5.0) < 0.01


class TestGreeks:
    def test_vega_positive(self):
        v = bs_vega(100, 100, 1.0, 0.05, 0.20)
        assert v > 0
        assert abs(v - 37.524) < 0.01

    def test_atm_delta_call(self):
        d = bs_delta(100, 100, 1.0, 0.05, 0.20, option_type="call")
        assert 0.5 < d < 0.7

    def test_atm_delta_put(self):
        d = bs_delta(100, 100, 1.0, 0.05, 0.20, option_type="put")
        assert -0.30 > d > -0.45

    def test_gamma_positive(self):
        g = bs_gamma(100, 100, 1.0, 0.05, 0.20)
        assert g > 0

    def test_theta_negative_for_long_call(self):
        t = bs_theta(100, 100, 1.0, 0.05, 0.20, option_type="call")
        assert t < 0


class TestIVSolver:
    def test_iv_recovery_atm(self):
        true_vol = 0.25
        price = bs_price(100, 100, 0.5, 0.05, true_vol, option_type="call")
        recovered = implied_volatility(price, 100, 100, 0.5, 0.05, option_type="call")
        assert recovered is not None
        assert abs(recovered - true_vol) < 1e-6

    def test_iv_recovery_otm(self):
        true_vol = 0.40
        price = bs_price(100, 120, 0.25, 0.05, true_vol, option_type="call")
        recovered = implied_volatility(price, 100, 120, 0.25, 0.05, option_type="call")
        assert recovered is not None
        assert abs(recovered - true_vol) < 1e-4

    def test_iv_recovery_put(self):
        true_vol = 0.30
        price = bs_price(100, 100, 1.0, 0.05, true_vol, option_type="put")
        recovered = implied_volatility(price, 100, 100, 1.0, 0.05, option_type="put")
        assert recovered is not None
        assert abs(recovered - true_vol) < 1e-6

    def test_iv_near_zero_price(self):
        result = implied_volatility(0.001, 100, 200, 0.1, 0.05, option_type="call")
        assert result is None or result > 0

    def test_iv_negative_price(self):
        result = implied_volatility(-5, 100, 100, 1.0, 0.05)
        assert result is None

    def test_iv_zero_time(self):
        result = implied_volatility(5, 105, 100, 0.0, 0.05)
        assert result is None

    def test_iv_below_intrinsic(self):
        result = implied_volatility(3.0, 105, 100, 1.0, 0.05, option_type="call")
        assert result is None

    @pytest.mark.parametrize("vol", [0.05, 0.10, 0.20, 0.50, 1.00, 2.00])
    def test_iv_range_of_vols(self, vol):
        price = bs_price(100, 100, 0.5, 0.05, vol, option_type="call")
        recovered = implied_volatility(price, 100, 100, 0.5, 0.05, option_type="call")
        assert recovered is not None
        assert abs(recovered - vol) < 1e-4

    def test_iv_extreme_meme_stock(self):
        """Post-earnings meme stock can show IV above 500% — bisection bracket
        must be wide enough to catch this without returning None."""
        true_vol = 6.5
        price = bs_price(100, 100, 0.1, 0.05, true_vol, option_type="call")
        recovered = implied_volatility(price, 100, 100, 0.1, 0.05, option_type="call")
        assert recovered is not None
        assert abs(recovered - true_vol) < 0.05

    def test_bsm_dividend_yield_round_trip(self):
        """Pricing with q > 0 should lower the call; IV solver must round-trip with same q."""
        c0 = bs_price(100, 100, 1.0, 0.05, 0.20, q=0.0, option_type="call")
        c_div = bs_price(100, 100, 1.0, 0.05, 0.20, q=0.03, option_type="call")
        assert c_div < c0
        iv = implied_volatility(c_div, 100, 100, 1.0, 0.05, q=0.03, option_type="call")
        assert iv is not None
        assert abs(iv - 0.20) < 1e-6


class TestRho:
    """Rho — sensitivity to 1.00 rate change. Q-aware via d2."""

    def test_call_rho_positive(self):
        """Long call value rises with rates (forward-price effect)."""
        assert bs_rho(100, 100, 1.0, 0.04, 0.25, option_type="call") > 0

    def test_put_rho_negative(self):
        """Long put value falls with rates."""
        assert bs_rho(100, 100, 1.0, 0.04, 0.25, option_type="put") < 0

    def test_put_call_parity_for_rho(self):
        """rho_call - rho_put = K T exp(-rT).

        Direct derivative of put-call parity w.r.t. r.
        """
        S, K, T, r, sigma = 100, 110, 0.75, 0.04, 0.22
        for q in (0.0, 0.03):
            rc = bs_rho(S, K, T, r, sigma, q=q, option_type="call")
            rp = bs_rho(S, K, T, r, sigma, q=q, option_type="put")
            expected = K * T * np.exp(-r * T)
            assert abs((rc - rp) - expected) < 1e-6

    def test_finite_difference_matches_analytic_call(self):
        """Bump-and-revalue Δprice/Δr vs closed-form rho. Tol 1e-3 rel."""
        S, K, T, sigma = 100, 100, 1.0, 0.25
        for q in (0.0, 0.02, 0.05):
            for r in (0.02, 0.04, 0.08):
                h = 1e-5
                p_up = bs_price(S, K, T, r + h, sigma, q=q, option_type="call")
                p_dn = bs_price(S, K, T, r - h, sigma, q=q, option_type="call")
                fd = (p_up - p_dn) / (2 * h)
                ana = bs_rho(S, K, T, r, sigma, q=q, option_type="call")
                assert abs(fd - ana) / max(1e-9, abs(ana)) < 1e-3

    def test_finite_difference_matches_analytic_put(self):
        S, K, T, sigma = 100, 100, 1.0, 0.25
        for q in (0.0, 0.02, 0.05):
            for r in (0.02, 0.04, 0.08):
                h = 1e-5
                p_up = bs_price(S, K, T, r + h, sigma, q=q, option_type="put")
                p_dn = bs_price(S, K, T, r - h, sigma, q=q, option_type="put")
                fd = (p_up - p_dn) / (2 * h)
                ana = bs_rho(S, K, T, r, sigma, q=q, option_type="put")
                assert abs(fd - ana) / max(1e-9, abs(ana)) < 1e-3

    def test_zero_time_returns_zero(self):
        assert bs_rho(100, 100, 0.0, 0.04, 0.25, option_type="call") == 0.0

    def test_zero_sigma_returns_zero(self):
        assert bs_rho(100, 100, 1.0, 0.04, 0.0, option_type="call") == 0.0

    def test_invalid_option_type_raises(self):
        with pytest.raises(ValueError):
            bs_rho(100, 100, 1.0, 0.04, 0.25, option_type="banana")
