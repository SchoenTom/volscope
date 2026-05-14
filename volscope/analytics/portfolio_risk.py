"""
Portfolio Risk — Bloomberg-style risk aggregation across tracked positions.

Hedge-fund-grade risk view: when a trader has 4-10 positions across DAX
puts, Nasdaq puts, and HK knockouts, the question isn't "is QQQ vol cheap"
— it's "what's my net vega? Net delta? Where's my biggest concentration?
What's my Monte Carlo VaR if all my underlyings move ±2σ?"

This module aggregates Greeks across positions and produces a portfolio-
level risk decomposition.

Inputs
------
A list of ``PortfolioLeg`` objects describing the user's open structures:
ticker, quantity (signed), strike, expiry, option_type, entry_iv. The
analytics computes Greeks per leg via existing ``black_scholes`` and
sums them with sign for the portfolio totals.

Monte Carlo VaR
---------------
1000-path simulation of underlying spot returns (lognormal) + IV shocks
(normal). For each path, reprice every leg via BSM and compute the
portfolio P&L. The 5th-percentile loss is the 95% VaR; the mean of the
worst 5% is the CVaR (expected shortfall).

This module is pure analytics — no UI imports.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from volscope.analytics.black_scholes import (
    bs_delta,
    bs_gamma,
    bs_price,
    bs_theta,
    bs_vega,
)


# ── Configuration ───────────────────────────────────────────────────────

# Default risk-free rate when caller doesn't pass one.
_DEFAULT_R = 0.04

# Annual lognormal vol for the spot path in MC sims; pull from current IV
# of the leg if available, else this conservative fallback.
_DEFAULT_PATH_VOL = 0.30

# Annual IV-shock std-dev for MC; calibrated so 1σ shock ≈ ±5 IV pts.
_IV_SHOCK_STD = 0.05


# ── Input + output types ────────────────────────────────────────────────

@dataclass(frozen=True)
class PortfolioLeg:
    """One leg in the portfolio.

    Quantity is signed: positive = long, negative = short. Quantity is
    measured in *contracts* (each contract = 100 shares per US convention).
    """
    ticker:        str
    spot:          float       # current spot price of underlying
    strike:        float
    days_to_expiry: int
    iv:            float       # current IV in % (e.g. 22.0)
    option_type:   str         # "call" | "put"
    quantity:      int = 1


@dataclass(frozen=True)
class GreeksSnapshot:
    """Per-leg or aggregated Greeks.

    All Greeks are *position-scaled*: delta is total share-equivalent
    delta (multiplied by quantity × 100), vega is dollar P&L for a
    1% IV move, theta is dollar P&L per day.
    """
    delta:  float       # share-equivalent delta
    gamma:  float       # gamma per 1% spot move per share
    vega:   float       # $ P&L per 1% IV move
    theta:  float       # $ P&L per calendar day
    notional: float     # share-equivalent notional value


@dataclass(frozen=True)
class VarResult:
    """Monte Carlo VaR / CVaR for a portfolio.

    Attributes
    ----------
    var_95         : 95% Value-at-Risk — loss you would not exceed with
                     95% probability over the chosen horizon (in $).
                     Always positive; subtract from portfolio value.
    cvar_95        : Conditional VaR (expected loss in worst 5% of cases).
    expected_pnl   : Mean P&L across all simulated paths.
    worst_loss     : Most negative single-path P&L.
    n_paths        : Number of Monte Carlo paths used.
    horizon_days   : Time horizon for the simulation.
    """
    var_95:        float
    cvar_95:       float
    expected_pnl:  float
    worst_loss:    float
    n_paths:       int
    horizon_days:  int


# ── Greeks aggregation ──────────────────────────────────────────────────

def leg_greeks(leg: PortfolioLeg, r: float = _DEFAULT_R) -> GreeksSnapshot:
    """Compute position-scaled Greeks for one leg."""
    T = max(1.0, float(leg.days_to_expiry)) / 365.0
    iv_dec = max(1e-4, leg.iv / 100.0)

    delta_share = bs_delta(leg.spot, leg.strike, T, r, iv_dec, option_type=leg.option_type)
    gamma_share = bs_gamma(leg.spot, leg.strike, T, r, iv_dec)
    vega_per_share = bs_vega(leg.spot, leg.strike, T, r, iv_dec)
    theta_per_share_year = bs_theta(leg.spot, leg.strike, T, r, iv_dec, option_type=leg.option_type)

    contracts = leg.quantity
    shares = contracts * 100

    return GreeksSnapshot(
        delta=delta_share * shares,
        gamma=gamma_share * shares,
        vega=(vega_per_share / 100.0) * shares,    # bs_vega is per 1.00 σ → per 1% = /100
        theta=(theta_per_share_year / 365.0) * shares,
        notional=leg.spot * shares,
    )


def portfolio_greeks(legs: list[PortfolioLeg], r: float = _DEFAULT_R) -> GreeksSnapshot:
    """Sum Greeks across all legs."""
    if not legs:
        return GreeksSnapshot(0.0, 0.0, 0.0, 0.0, 0.0)
    aggs = [leg_greeks(leg, r=r) for leg in legs]
    return GreeksSnapshot(
        delta=sum(a.delta    for a in aggs),
        gamma=sum(a.gamma    for a in aggs),
        vega=sum(a.vega      for a in aggs),
        theta=sum(a.theta    for a in aggs),
        notional=sum(a.notional for a in aggs),
    )


# ── Concentration analysis ──────────────────────────────────────────────

def concentration_by_ticker(legs: list[PortfolioLeg]) -> pd.DataFrame:
    """Per-ticker rollup of vega + delta for diversification check."""
    if not legs:
        return pd.DataFrame(columns=["ticker", "n_legs", "delta", "vega", "notional"])
    rows = []
    by_ticker: dict[str, list[PortfolioLeg]] = {}
    for leg in legs:
        by_ticker.setdefault(leg.ticker, []).append(leg)
    for tkr, ls in by_ticker.items():
        agg = portfolio_greeks(ls)
        rows.append({
            "ticker":   tkr,
            "n_legs":   len(ls),
            "delta":    round(agg.delta, 1),
            "vega":     round(agg.vega, 0),
            "notional": round(agg.notional, 0),
        })
    return pd.DataFrame(rows).sort_values("vega", key=lambda s: s.abs(), ascending=False)


# ── Monte Carlo VaR ──────────────────────────────────────────────────────

from volscope.utils.timing import instrumented  # noqa: E402


@instrumented("analytics.mc_var")
def monte_carlo_var(
    legs:         list[PortfolioLeg],
    horizon_days: int = 5,
    n_paths:      int = 1000,
    confidence:   float = 0.95,
    seed:         Optional[int] = None,
    r:            float = _DEFAULT_R,
) -> VarResult:
    """Run Monte Carlo VaR over the given horizon.

    Parameters
    ----------
    legs         : Portfolio legs.
    horizon_days : Forward-looking horizon (calendar days).
    n_paths      : Number of MC paths (default 1000).
    confidence   : Confidence level (default 0.95 → 5th percentile).
    seed         : RNG seed for reproducibility.
    r            : Risk-free rate.
    """
    if not legs:
        return VarResult(0.0, 0.0, 0.0, 0.0, 0, horizon_days)

    rng = np.random.default_rng(seed)
    horizon_years = horizon_days / 365.0

    # Current portfolio value (sum of leg theoretical values × position)
    pv0 = 0.0
    for leg in legs:
        T = max(1.0, leg.days_to_expiry) / 365.0
        iv_dec = max(1e-4, leg.iv / 100.0)
        price = bs_price(leg.spot, leg.strike, T, r, iv_dec, option_type=leg.option_type)
        pv0 += price * leg.quantity * 100

    pnls = np.zeros(n_paths)
    for path_idx in range(n_paths):
        pv_t = 0.0
        for leg in legs:
            iv_dec  = max(1e-4, leg.iv / 100.0)
            path_vol = max(iv_dec, 0.05)  # at least 5% to avoid degenerate paths
            spot_t = leg.spot * math.exp(
                (r - 0.5 * path_vol ** 2) * horizon_years
                + path_vol * math.sqrt(horizon_years) * rng.standard_normal()
            )
            iv_t_dec = max(1e-4, iv_dec + _IV_SHOCK_STD * math.sqrt(horizon_years) * rng.standard_normal())
            T_t = max(1.0, leg.days_to_expiry - horizon_days) / 365.0
            price_t = bs_price(spot_t, leg.strike, T_t, r, iv_t_dec, option_type=leg.option_type)
            pv_t += price_t * leg.quantity * 100
        pnls[path_idx] = pv_t - pv0

    sorted_pnls = np.sort(pnls)
    cutoff = max(1, int(round((1.0 - confidence) * n_paths)))
    var_95 = -float(sorted_pnls[cutoff - 1])     # positive number = loss
    cvar_95 = -float(sorted_pnls[:cutoff].mean())
    expected_pnl = float(pnls.mean())
    worst_loss = -float(sorted_pnls[0])

    return VarResult(
        var_95=round(max(0.0, var_95), 2),
        cvar_95=round(max(0.0, cvar_95), 2),
        expected_pnl=round(expected_pnl, 2),
        worst_loss=round(max(0.0, worst_loss), 2),
        n_paths=n_paths,
        horizon_days=horizon_days,
    )
