"""
Scenario Analyzer — deterministic stress tests on the user's portfolio.

While ``portfolio_risk.monte_carlo_var`` answers "what's my probabilistic
worst-case loss?", the scenario analyzer answers a different, more
concrete question: *"What happens to my portfolio if VIX jumps to 30?"*
or *"What if MSTR drops 20%?"*.

The trader specifies a named scenario as a set of shocks
(per-ticker spot-shock %, per-ticker IV-shock pp), the engine reprices
every leg via BSM, and returns a structured result with:

  - Per-leg P&L
  - Total portfolio P&L
  - Greek drift (current → post-stress)
  - Triggered knockouts
  - Largest contributors

Pre-baked scenarios cover canonical hedge-fund stress tests:
  - "Aug 2024 carry unwind"     (-8% spot, +8pp IV across all)
  - "March 2020 COVID crash"    (-30% spot, +20pp IV)
  - "Vol spike: VIX 14 → 30"    (no spot shock, +16pp IV)
  - "Mean reversion week"       (no spot shock, -5pp IV)

This module is pure analytics — no DB writes, no UI imports.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from volscope.analytics.black_scholes import bs_delta, bs_gamma, bs_price, bs_vega
from volscope.analytics.portfolio_risk import (
    GreeksSnapshot,
    PortfolioLeg,
    leg_greeks,
    portfolio_greeks,
)


# ── Configuration ───────────────────────────────────────────────────────

_R = 0.04


# ── Input + output types ────────────────────────────────────────────────

@dataclass(frozen=True)
class Shock:
    """Per-ticker shock specification.

    Either one or both fields may be set:
      - spot_shock_pct : -0.20 = spot drops 20%
      - iv_shock_pp    : +5.0 = IV rises 5 percentage points
    """
    spot_shock_pct: float = 0.0
    iv_shock_pp:    float = 0.0


@dataclass(frozen=True)
class Scenario:
    """A named scenario.

    ``shocks`` is a dict ticker → Shock. Tickers not in the dict are
    unaffected. A wildcard ticker "*" applies its shock to *all* tickers
    that don't have an explicit override.
    """
    name:        str
    description: str
    shocks:      dict[str, Shock]


@dataclass(frozen=True)
class LegImpact:
    """One leg's stress-test result."""
    ticker:        str
    strike:        float
    option_type:   str
    quantity:      int
    pre_price:     float
    post_price:    float
    pnl_dollar:    float        # = (post - pre) × quantity × 100
    pre_delta:     float
    post_delta:    float
    knocked_out:   bool         # placeholder — no barrier on PortfolioLeg


@dataclass(frozen=True)
class ScenarioResult:
    """Aggregated outcome of a scenario across the whole portfolio."""
    scenario_name:   str
    total_pnl:       float
    total_pre_value: float
    total_post_value: float
    leg_impacts:     tuple[LegImpact, ...]
    pre_greeks:      GreeksSnapshot
    post_greeks:     GreeksSnapshot
    worst_leg:       Optional[LegImpact]
    best_leg:        Optional[LegImpact]


# ── Pre-baked scenarios ─────────────────────────────────────────────────

PREBAKED_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="Vol spike: VIX 14 → 30",
        description="No spot shock; IV rises 16pp across all tickers (pure vol expansion).",
        shocks={"*": Shock(spot_shock_pct=0.0, iv_shock_pp=+16.0)},
    ),
    Scenario(
        name="Mean reversion week",
        description="No spot shock; IV falls 5pp (typical post-event normalisation).",
        shocks={"*": Shock(spot_shock_pct=0.0, iv_shock_pp=-5.0)},
    ),
    Scenario(
        name="-10% / +8pp (correction)",
        description="Broad equity correction with vol expansion.",
        shocks={"*": Shock(spot_shock_pct=-0.10, iv_shock_pp=+8.0)},
    ),
    Scenario(
        name="-20% / +15pp (severe stress)",
        description="Equity bear move with sharp vol expansion (Aug 2015, Q4 2018).",
        shocks={"*": Shock(spot_shock_pct=-0.20, iv_shock_pp=+15.0)},
    ),
    Scenario(
        name="COVID March 2020 (-30% / +20pp)",
        description="Worst recent precedent for combined spot crash + vol spike.",
        shocks={"*": Shock(spot_shock_pct=-0.30, iv_shock_pp=+20.0)},
    ),
    Scenario(
        name="+10% / -5pp (rally + complacency)",
        description="Equity rally with vol contraction — short-vol favourable.",
        shocks={"*": Shock(spot_shock_pct=+0.10, iv_shock_pp=-5.0)},
    ),
)


# ── Core engine ─────────────────────────────────────────────────────────

def _resolve_shock(scenario: Scenario, ticker: str) -> Shock:
    """Pick the per-ticker shock; fall back to wildcard '*' if any."""
    if ticker in scenario.shocks:
        return scenario.shocks[ticker]
    if "*" in scenario.shocks:
        return scenario.shocks["*"]
    return Shock()   # zero shock


def stress_leg(leg: PortfolioLeg, shock: Shock, r: float = _R) -> LegImpact:
    """Reprice a single leg under the given shock."""
    T = max(1.0, leg.days_to_expiry) / 365.0
    iv_pre = max(1e-4, leg.iv / 100.0)
    pre_price = bs_price(leg.spot, leg.strike, T, r, iv_pre, option_type=leg.option_type)
    pre_delta = bs_delta(leg.spot, leg.strike, T, r, iv_pre, option_type=leg.option_type)

    new_spot = leg.spot * (1.0 + shock.spot_shock_pct)
    new_iv_pct = max(1.0, leg.iv + shock.iv_shock_pp)
    iv_post = new_iv_pct / 100.0

    post_price = bs_price(new_spot, leg.strike, T, r, iv_post, option_type=leg.option_type)
    post_delta = bs_delta(new_spot, leg.strike, T, r, iv_post, option_type=leg.option_type)

    pnl = (post_price - pre_price) * leg.quantity * 100

    return LegImpact(
        ticker=leg.ticker,
        strike=leg.strike,
        option_type=leg.option_type,
        quantity=leg.quantity,
        pre_price=round(pre_price, 4),
        post_price=round(post_price, 4),
        pnl_dollar=round(pnl, 2),
        pre_delta=round(pre_delta, 4),
        post_delta=round(post_delta, 4),
        knocked_out=False,
    )


def run_scenario(legs: list[PortfolioLeg], scenario: Scenario, r: float = _R) -> ScenarioResult:
    """Evaluate the scenario across all legs."""
    if not legs:
        zero = GreeksSnapshot(0.0, 0.0, 0.0, 0.0, 0.0)
        return ScenarioResult(
            scenario_name=scenario.name,
            total_pnl=0.0, total_pre_value=0.0, total_post_value=0.0,
            leg_impacts=(),
            pre_greeks=zero, post_greeks=zero,
            worst_leg=None, best_leg=None,
        )

    impacts: list[LegImpact] = []
    pre_value = 0.0
    post_value = 0.0
    for leg in legs:
        shock = _resolve_shock(scenario, leg.ticker)
        impact = stress_leg(leg, shock, r=r)
        impacts.append(impact)
        pre_value += impact.pre_price * leg.quantity * 100
        post_value += impact.post_price * leg.quantity * 100

    pre_g = portfolio_greeks(legs, r=r)

    # Build post-shock legs for Greek recompute
    post_legs: list[PortfolioLeg] = []
    for leg in legs:
        shock = _resolve_shock(scenario, leg.ticker)
        post_legs.append(PortfolioLeg(
            ticker=leg.ticker,
            spot=leg.spot * (1.0 + shock.spot_shock_pct),
            strike=leg.strike,
            days_to_expiry=leg.days_to_expiry,
            iv=max(1.0, leg.iv + shock.iv_shock_pp),
            option_type=leg.option_type,
            quantity=leg.quantity,
        ))
    post_g = portfolio_greeks(post_legs, r=r)

    worst = min(impacts, key=lambda i: i.pnl_dollar)
    best  = max(impacts, key=lambda i: i.pnl_dollar)

    return ScenarioResult(
        scenario_name=scenario.name,
        total_pnl=round(post_value - pre_value, 2),
        total_pre_value=round(pre_value, 2),
        total_post_value=round(post_value, 2),
        leg_impacts=tuple(impacts),
        pre_greeks=pre_g,
        post_greeks=post_g,
        worst_leg=worst,
        best_leg=best,
    )


def run_all_prebaked(legs: list[PortfolioLeg], r: float = _R) -> list[ScenarioResult]:
    """Run all PREBAKED_SCENARIOS and return the list of results."""
    return [run_scenario(legs, s, r=r) for s in PREBAKED_SCENARIOS]


# ── Custom scenario builder ─────────────────────────────────────────────

def build_custom_scenario(
    name:           str,
    spot_shock_pct: dict[str, float],
    iv_shock_pp:    dict[str, float],
    description:    str = "",
) -> Scenario:
    """Compose a Scenario from per-ticker shock dicts.

    Both dicts may include the wildcard key "*" for a default shock.
    Tickers in either dict but missing in the other get the missing
    component as 0.
    """
    keys = set(spot_shock_pct) | set(iv_shock_pp)
    shocks = {
        k: Shock(
            spot_shock_pct=float(spot_shock_pct.get(k, 0.0)),
            iv_shock_pp=float(iv_shock_pp.get(k, 0.0)),
        )
        for k in keys
    }
    return Scenario(name=name, description=description, shocks=shocks)
