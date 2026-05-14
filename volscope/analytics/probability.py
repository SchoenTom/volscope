"""
Probability of Profit (PoP) under the risk-neutral measure.

Two entry points:

    pop_closed_form(strategy, S0, iv, r, q, T) -> float
        For vanilla structures with at-most-two breakevens; uses the
        log-normal CDF directly. Fast, exact, no randomness.

    pop_monte_carlo(strategy, S0, iv, r, q, T, n_paths=10000, seed=42)
        For multi-region payoffs (Iron Butterfly, Iron Condor's profit
        zone-between-shorts, Calendar Spread). Vectorised numpy
        simulation under risk-neutral drift; seed makes it reproducible.

    pop(strategy, S0, iv, r, q, T, prefer_mc=False) -> float
        High-level convenience — picks closed-form when the strategy
        has ≤ 2 breakevens and a monotone-profit interpretation,
        otherwise falls back to Monte Carlo. Always returns a value in
        [0, 1].

The risk-neutral assumption (drift = r − q − 0.5 σ²) is the standard
academic convention. A ``use_real_world_drift`` toggle is provided for
research workflows but is *not* the default — the goal of PoP is to
answer "if vol behaves as the market is currently pricing it, how
often is this trade profitable", which is risk-neutral by definition.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from scipy.stats import norm


# ── Public surface ──────────────────────────────────────────────────

def pop_closed_form(
    strategy,
    S0: float,
    iv: float,
    r: float = 0.04,
    q: float = 0.0,
    T: Optional[float] = None,
) -> Optional[float]:
    """Closed-form PoP for strategies with a monotone profit region.

    Handles the four simple shapes:
      - Long Call / Long Put: P(S_T crosses single breakeven)
      - Bull/Bear Spread:     P(S_T crosses single breakeven, capped both sides)
      - Long Straddle/Strangle: P(S_T < lower BE or S_T > upper BE)

    Returns None for anything more complex (caller should fall back to
    Monte Carlo). The Strategy must expose ``.legs`` and either
    ``.breakevens`` (snapshot tuple) or ``.breakevens_at()``.
    """
    breakevens = _resolve_breakevens(strategy)
    if not breakevens:
        return None
    T_eff = _resolve_T(strategy, T)
    if T_eff is None or T_eff <= 0:
        return None
    sigma = max(0.001, iv / 100.0)
    # Risk-neutral drift for log(S_T/S_0)
    mu = (r - q - 0.5 * sigma * sigma) * T_eff
    sd = sigma * math.sqrt(T_eff)

    # Determine if the strategy's profit region is "outside" both BEs
    # (long-vol shape) or "between" both BEs (short-vol shape) or
    # one-sided (single-BE shape).
    direction = getattr(strategy, "direction", "long_vol")

    if len(breakevens) == 1:
        be = float(breakevens[0])
        z = (math.log(be / S0) - mu) / sd
        # Long call → profit iff S_T > be → P = 1 − N(z)
        # Long put  → profit iff S_T < be → P = N(z)
        leg0 = strategy.legs[0]
        if leg0.option_type == "call" and leg0.action == "buy":
            return 1.0 - norm.cdf(z)
        if leg0.option_type == "put" and leg0.action == "buy":
            return norm.cdf(z)
        # Single-leg short: profit when S_T stays the other side
        if leg0.option_type == "call" and leg0.action == "sell":
            return norm.cdf(z)
        if leg0.option_type == "put" and leg0.action == "sell":
            return 1.0 - norm.cdf(z)
        return None

    if len(breakevens) == 2:
        lo, hi = sorted(float(b) for b in breakevens)
        z_lo = (math.log(lo / S0) - mu) / sd
        z_hi = (math.log(hi / S0) - mu) / sd
        # Long-vol structures (straddle/strangle): profit OUTSIDE
        # Short-vol structures (iron condor between BEs): profit INSIDE
        if direction == "long_vol":
            return norm.cdf(z_lo) + (1.0 - norm.cdf(z_hi))
        if direction == "short_vol":
            return norm.cdf(z_hi) - norm.cdf(z_lo)

    return None


def pop_monte_carlo(
    strategy,
    S0: float,
    iv: float,
    r: float = 0.04,
    q: float = 0.0,
    T: Optional[float] = None,
    n_paths: int = 10_000,
    seed: int = 42,
    use_real_world_drift: bool = False,
    real_world_drift: float = 0.08,
) -> float:
    """Monte Carlo PoP for any payoff shape.

    Simulates ``n_paths`` log-normal terminal prices under risk-neutral
    drift (or user-supplied real-world drift), evaluates the strategy's
    ``payoff_at_expiry`` on the sample, returns the empirical fraction
    of paths that finish profitable.

    The PRNG is seeded so the result is deterministic for the same
    inputs (Streamlit reruns produce identical PoP).
    """
    T_eff = _resolve_T(strategy, T)
    if T_eff is None or T_eff <= 0:
        return 0.0
    sigma = max(0.001, iv / 100.0)
    drift = real_world_drift if use_real_world_drift else (r - q)
    mu = (drift - 0.5 * sigma * sigma) * T_eff
    sd = sigma * math.sqrt(T_eff)

    rng = np.random.default_rng(seed)
    z = rng.standard_normal(int(max(100, n_paths)))
    S_T = S0 * np.exp(mu + sd * z)
    pnl = np.asarray(strategy.payoff_at_expiry(S_T), dtype=float)
    return float((pnl > 0).mean())


def pop(
    strategy,
    S0: float,
    iv: float,
    r: float = 0.04,
    q: float = 0.0,
    T: Optional[float] = None,
    prefer_mc: bool = False,
    **mc_kwargs,
) -> float:
    """High-level PoP — picks closed-form when applicable.

    Set ``prefer_mc=True`` to force Monte Carlo (useful for sanity
    checks against the closed form on supported shapes).
    """
    if not prefer_mc:
        cf = pop_closed_form(strategy, S0, iv, r, q, T)
        if cf is not None and 0.0 <= cf <= 1.0:
            return cf
    return pop_monte_carlo(strategy, S0, iv, r, q, T, **mc_kwargs)


def profit_density(
    strategy,
    S0: float,
    iv: float,
    r: float = 0.04,
    q: float = 0.0,
    T: Optional[float] = None,
    n_paths: int = 10_000,
    seed: int = 42,
    n_bins: int = 60,
):
    """Histogram of P&L outcomes — used by the UI to render a small
    sparkline next to the PoP number.

    Returns ``(bin_centres, density)`` as 1-D numpy arrays.
    """
    T_eff = _resolve_T(strategy, T)
    if T_eff is None or T_eff <= 0:
        return np.array([0.0]), np.array([0.0])
    sigma = max(0.001, iv / 100.0)
    mu = (r - q - 0.5 * sigma * sigma) * T_eff
    sd = sigma * math.sqrt(T_eff)
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(int(max(100, n_paths)))
    S_T = S0 * np.exp(mu + sd * z)
    pnl = np.asarray(strategy.payoff_at_expiry(S_T), dtype=float)
    hist, edges = np.histogram(pnl, bins=int(n_bins), density=True)
    centres = 0.5 * (edges[:-1] + edges[1:])
    return centres, hist


# ── Internals ───────────────────────────────────────────────────────

def _resolve_breakevens(strategy):
    """Pull breakevens from a strategy in either the snapshot or
    Protocol-method form. Returns a (possibly empty) tuple."""
    bes = getattr(strategy, "breakevens", None)
    if callable(bes):
        try:
            bes = bes()
        except TypeError:
            bes = ()
    if bes is None:
        return ()
    return tuple(float(b) for b in bes if b is not None)


def _resolve_T(strategy, T_hint: Optional[float]) -> Optional[float]:
    """Pick the time-to-expiry to use for PoP.

    Priority:
      1. Explicit ``T`` argument (years)
      2. Strategy's earliest-expiring leg, derived from ``leg.expiry``
         relative to today
    """
    if T_hint is not None and T_hint > 0:
        return float(T_hint)
    legs = getattr(strategy, "legs", ())
    if not legs:
        return None
    from datetime import date as _date
    today = _date.today()
    days = [
        max(1, (leg.expiry - today).days)
        for leg in legs
        if getattr(leg, "expiry", None) is not None
    ]
    if not days:
        return None
    return min(days) / 365.0
