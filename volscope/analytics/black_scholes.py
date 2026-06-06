"""
Black-Scholes-Merton Option Pricing & IV Solver.

All functions use continuous dividend yield q.
If no dividend, pass q=0.

Functions:
    bs_price(S, K, T, r, sigma, q=0, option_type='call') -> float
    bs_vega(S, K, T, r, sigma, q=0) -> float
    bs_delta(S, K, T, r, sigma, q=0, option_type='call') -> float
    bs_gamma(S, K, T, r, sigma, q=0) -> float
    bs_theta(S, K, T, r, sigma, q=0, option_type='call') -> float
    implied_volatility(market_price, S, K, T, r, q=0, option_type='call') -> float | None
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy.stats import norm


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return d1, d2


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    q: float = 0.0,
    option_type: str = "call",
) -> Optional[float]:
    """Black-Scholes-Merton price with continuous dividend yield q."""
    if S <= 0 or K <= 0:
        return 0.0
    if T <= 0:
        if option_type == "call":
            return float(max(S - K, 0.0))
        return float(max(K - S, 0.0))
    if sigma <= 0:
        if option_type == "call":
            return max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
        return max(K * math.exp(-r * T) - S * math.exp(-q * T), 0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)
    if option_type == "call":
        return S * disc_q * norm.cdf(d1) - K * disc_r * norm.cdf(d2)
    if option_type == "put":
        return K * disc_r * norm.cdf(-d2) - S * disc_q * norm.cdf(-d1)
    return None  # analytics rule: bad input returns None, never raises


def bs_vega(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """Vega — sensitivity to 1.00 change in sigma. Per 1% change, divide by 100.

    Mathematically vega → 0 only as S → 0; for σ → 0+ at ATM, vega does NOT
    collapse — n(d1) blows up to compensate for the √T factor and the
    product remains positive. Returning 0 here would break Newton-Raphson
    IV solvers that use vega as the Jacobian. Floor σ at a tiny positive
    value so d1 is well-defined.
    """
    if S <= 0 or K <= 0 or T <= 0:
        return 0.0
    sigma = max(sigma, 1e-4)
    d1, _ = _d1_d2(S, K, T, r, sigma, q)
    return S * math.exp(-q * T) * norm.pdf(d1) * math.sqrt(T)


def bs_delta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    q: float = 0.0,
    option_type: str = "call",
) -> Optional[float]:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, r, sigma, q)
    disc_q = math.exp(-q * T)
    if option_type == "call":
        return disc_q * norm.cdf(d1)
    if option_type == "put":
        return disc_q * (norm.cdf(d1) - 1.0)
    return None  # analytics rule: bad input returns None, never raises


def bs_gamma(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, r, sigma, q)
    return math.exp(-q * T) * norm.pdf(d1) / (S * sigma * math.sqrt(T))


def bs_theta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    q: float = 0.0,
    option_type: str = "call",
) -> Optional[float]:
    """Theta per year (divide by 365 for per-day)."""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)
    first = -(S * disc_q * norm.pdf(d1) * sigma) / (2.0 * math.sqrt(T))
    if option_type == "call":
        return first - r * K * disc_r * norm.cdf(d2) + q * S * disc_q * norm.cdf(d1)
    if option_type == "put":
        return first + r * K * disc_r * norm.cdf(-d2) - q * S * disc_q * norm.cdf(-d1)
    return None  # analytics rule: bad input returns None, never raises


def bs_rho(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    q: float = 0.0,
    option_type: str = "call",
) -> Optional[float]:
    """
    Rho — sensitivity of option price to 1.00 change in risk-free rate.

    For per-1 %-rate semantics, divide the return value by 100 in the
    caller (Options Lab Greeks display does exactly this).

    Closed form (q-adjusted BSM):
        rho_call = +K T exp(-rT) N(d2)
        rho_put  = -K T exp(-rT) N(-d2)

    The q-yield does not appear explicitly because rho is the
    derivative w.r.t. r only — q enters indirectly through d2 via the
    drift term ``(r - q + 0.5 σ²)``.
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    _, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_r = math.exp(-r * T)
    if option_type == "call":
        return K * T * disc_r * norm.cdf(d2)
    if option_type == "put":
        return -K * T * disc_r * norm.cdf(-d2)
    return None  # analytics rule: bad input returns None, never raises


def _intrinsic(S: float, K: float, r: float, q: float, T: float, option_type: str) -> float:
    """No-arbitrage lower bound for a European option."""
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)
    if option_type == "call":
        return max(S * disc_q - K * disc_r, 0.0)
    return max(K * disc_r - S * disc_q, 0.0)


def _manaster_koehler_seed(S: float, K: float, T: float, r: float, q: float) -> float:
    """
    Manaster-Koehler (1982) initial guess for Newton-Raphson IV solver.
    Guarantees Newton starts on the convex side of the BSM price curve.
    """
    try:
        seed = math.sqrt(abs(2.0 * (math.log(S / K) + (r - q) * T) / T))
    except (ValueError, ZeroDivisionError):
        return 0.3
    if seed < 0.05 or seed > 5.0 or not math.isfinite(seed):
        return 0.3
    return seed


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float = 0.0,
    option_type: str = "call",
    tol: float = 1e-8,
    max_iter: int = 100,
) -> Optional[float]:
    """
    Solve for implied volatility from a market option price.

    Strategy: Newton-Raphson from sigma_0 = 0.3, fallback to bisection on
    [0.001, 5.0] when vega vanishes or Newton strays.

    Returns None if inputs are unphysical or the solver fails to converge.
    """
    if market_price is None or not np.isfinite(market_price) or market_price <= 0:
        return None
    if S <= 0 or K <= 0 or T <= 0:
        return None
    if option_type not in ("call", "put"):
        return None

    lower_bound = _intrinsic(S, K, r, q, T, option_type)
    if market_price < lower_bound - 1e-8:
        return None

    sigma = _manaster_koehler_seed(S, K, T, r, q)
    for _ in range(max_iter):
        price = bs_price(S, K, T, r, sigma, q, option_type)
        diff = price - market_price
        if abs(diff) < tol:
            return sigma
        vega = bs_vega(S, K, T, r, sigma, q)
        if vega < 1e-12:
            break
        sigma_new = sigma - diff / vega
        if sigma_new <= 0 or sigma_new > 10 or not np.isfinite(sigma_new):
            break
        sigma = sigma_new
    else:
        # exhausted Newton iterations without convergence
        pass

    # Bisection fallback on [1e-4, 10.0] — wide enough to bracket meme-stock IV
    # bursts (>500%) and intraday post-earnings spikes the Newton step misses.
    low, high = 1e-4, 10.0
    p_low = bs_price(S, K, T, r, low, q, option_type) - market_price
    p_high = bs_price(S, K, T, r, high, q, option_type) - market_price
    if p_low * p_high > 0:
        return None
    for _ in range(200):
        mid = 0.5 * (low + high)
        p_mid = bs_price(S, K, T, r, mid, q, option_type) - market_price
        if abs(p_mid) < tol or (high - low) < tol:
            return mid
        if p_low * p_mid < 0:
            high = mid
            p_high = p_mid
        else:
            low = mid
            p_low = p_mid
    return 0.5 * (low + high)
