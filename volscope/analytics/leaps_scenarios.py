"""
Scenario engine for LEAPS positions.

Three orthogonal scenario lenses:

1. **Spot-path × time** — at a future date, with the spot at level S, what
   is the LEAPS premium worth (mark-to-market) under the current σ? This
   is the matrix that answers "what if NKE prints $80 in 12 months?".
2. **IV-reversion vega gain** — if the implied vol re-prices to a target
   level *today*, with spot unchanged, what is the vega-driven $ change
   per contract? This is the "free money" the deck claims is hidden in
   IV-Rank-12 names.
3. **Theta runway** — how much time-value the position bleeds per month
   from now to expiry, surfacing the cliff in the last 3-6 months.

Pure analytics. The Streamlit dossier wires these into expanders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from volscope.analytics.black_scholes import bs_price, bs_theta
from volscope.analytics.leaps_convergence import LeapsSuggestion


# ── Spot × time matrix ───────────────────────────────────────────────────

@dataclass(frozen=True)
class ScenarioCell:
    """One cell in the spot × time matrix."""

    spot:        float
    months:      int                        # months from valuation date
    premium:     float                      # per-share premium under BSM
    pnl_per_share:    float                 # premium − entry premium
    pnl_per_contract: float                 # × 100


@dataclass(frozen=True)
class ScenarioMatrix:
    """Spot × time grid of mark-to-market premium projections."""

    ticker:        str
    iv_assumed:    float                    # decimal
    months_grid:   tuple[int, ...]          # e.g. (1, 6, 12, 24)
    spot_grid:     tuple[float, ...]
    cells:         tuple[tuple[ScenarioCell, ...], ...]
    # cells[i][j] = ScenarioCell at spot_grid[i], months_grid[j]


# Default grids — multiplicative on spot (×0.7 .. ×2.5) and standard months
_DEFAULT_SPOT_MULTIPLIERS = (0.70, 1.00, 1.30, 1.70, 2.00, 2.50, 3.30)
_DEFAULT_MONTH_HORIZONS = (1, 6, 12, 24)


def build_scenario_matrix(
    suggestion: LeapsSuggestion,
    iv_assumed: Optional[float] = None,
    spot_multipliers: tuple[float, ...] = _DEFAULT_SPOT_MULTIPLIERS,
    month_horizons: tuple[int, ...] = _DEFAULT_MONTH_HORIZONS,
    risk_free: float = 0.04,
    div_yield: float = 0.0,
) -> ScenarioMatrix:
    """Build the spot × time mark-to-market matrix.

    By default uses the suggestion's own IV (i.e. assumes σ stays constant).
    Override ``iv_assumed`` to model an IV-reverted regime — then every
    cell shifts up by the vega gain plus the spot/time component.
    """
    iv = float(iv_assumed if iv_assumed is not None else suggestion.iv)
    cols: list[tuple[ScenarioCell, ...]] = []
    for mult in spot_multipliers:
        spot_level = round(float(suggestion.spot) * mult, 2)
        row: list[ScenarioCell] = []
        for months in month_horizons:
            t_remaining = max(0.0, (suggestion.days_to_exp - months * 30) / 365.0)
            if t_remaining <= 0:
                premium = max(0.0, spot_level - suggestion.strike)
            else:
                premium = bs_price(
                    spot_level, suggestion.strike, t_remaining,
                    risk_free, iv, div_yield, "call",
                )
            pnl_per_share = premium - suggestion.est_premium
            row.append(ScenarioCell(
                spot=spot_level,
                months=months,
                premium=round(premium, 3),
                pnl_per_share=round(pnl_per_share, 3),
                pnl_per_contract=round(pnl_per_share * 100, 2),
            ))
        cols.append(tuple(row))
    return ScenarioMatrix(
        ticker=suggestion.ticker,
        iv_assumed=iv,
        months_grid=tuple(month_horizons),
        spot_grid=tuple(round(float(suggestion.spot) * m, 2) for m in spot_multipliers),
        cells=tuple(cols),
    )


# ── IV-reversion vega gain ───────────────────────────────────────────────

@dataclass(frozen=True)
class VegaGainTable:
    """Premium change if IV reverts to each target level today, spot unchanged."""

    ticker:        str
    spot:          float
    current_iv:    float
    targets:       tuple[float, ...]                   # decimals
    rows:          tuple["VegaGainRow", ...]


@dataclass(frozen=True)
class VegaGainRow:
    target_iv:           float
    new_premium:         float
    pnl_per_share:       float
    pnl_per_contract:    float
    pnl_pct_of_premium:  float


_DEFAULT_VEGA_TARGETS = (0.20, 0.30, 0.40, 0.50, 0.60, 0.80)


def build_vega_gain_table(
    suggestion: LeapsSuggestion,
    targets: tuple[float, ...] = _DEFAULT_VEGA_TARGETS,
    risk_free: float = 0.04,
    div_yield: float = 0.0,
) -> VegaGainTable:
    """Show the vega-only contribution if IV reverts today, spot unchanged.

    The deck claims a 67 % premium gain from IV expanding 30 % → 50 %
    *without any spot move*. This table makes that claim auditable for
    every ticker.
    """
    T = suggestion.days_to_exp / 365.0
    rows: list[VegaGainRow] = []
    for target in targets:
        new_premium = bs_price(
            suggestion.spot, suggestion.strike, T, risk_free,
            float(target), div_yield, "call",
        )
        pnl_share = new_premium - suggestion.est_premium
        pnl_contract = pnl_share * 100
        pnl_pct = (
            (pnl_share / suggestion.est_premium * 100.0)
            if suggestion.est_premium > 0 else 0.0
        )
        rows.append(VegaGainRow(
            target_iv=float(target),
            new_premium=round(new_premium, 3),
            pnl_per_share=round(pnl_share, 3),
            pnl_per_contract=round(pnl_contract, 2),
            pnl_pct_of_premium=round(pnl_pct, 1),
        ))
    return VegaGainTable(
        ticker=suggestion.ticker,
        spot=float(suggestion.spot),
        current_iv=float(suggestion.iv),
        targets=tuple(targets),
        rows=tuple(rows),
    )


# ── Theta runway ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ThetaRunwayPoint:
    """One sample on the theta-decay curve."""

    months_held:        int
    days_to_exp:        int
    theta_per_day:      float            # decay rate at this point
    theta_per_month:    float            # avg over the next 30d
    cumulative_decay:   float            # premium lost from entry to here


@dataclass(frozen=True)
class ThetaRunway:
    """Theta-decay curve from entry through expiry."""

    ticker:    str
    points:    tuple[ThetaRunwayPoint, ...]
    cliff_starts_at_month: Optional[int]   # first month where |theta| doubles


def build_theta_runway(
    suggestion: LeapsSuggestion,
    risk_free: float = 0.04,
    div_yield: float = 0.0,
) -> ThetaRunway:
    """Sample the theta-decay curve monthly until expiry.

    Detects the "cliff" — the month where daily theta first doubles vs.
    its entry rate. Below the cliff the position bleeds slowly; above
    it the position is uneconomical to hold.
    """
    entry_T = suggestion.days_to_exp / 365.0
    entry_theta = bs_theta(
        suggestion.spot, suggestion.strike, entry_T, risk_free,
        suggestion.iv, div_yield, "call",
    ) / 365.0   # per-day
    points: list[ThetaRunwayPoint] = []
    cliff_month: Optional[int] = None
    cumulative = 0.0
    last_theta_per_day = entry_theta
    total_months = max(1, suggestion.days_to_exp // 30)
    for months in range(0, total_months + 1):
        days_remaining = suggestion.days_to_exp - months * 30
        if days_remaining <= 0:
            break
        T_now = days_remaining / 365.0
        theta_per_day_now = bs_theta(
            suggestion.spot, suggestion.strike, T_now, risk_free,
            suggestion.iv, div_yield, "call",
        ) / 365.0
        # Average theta over the next 30d ~= (now + 30d-from-now) / 2.
        T_next = max(0.0, (days_remaining - 30) / 365.0)
        theta_next = bs_theta(
            suggestion.spot, suggestion.strike, T_next, risk_free,
            suggestion.iv, div_yield, "call",
        ) / 365.0 if T_next > 0 else 0.0
        theta_per_month = (theta_per_day_now + theta_next) / 2.0 * 30.0
        if months > 0:
            cumulative += abs(theta_per_month)
        if (
            cliff_month is None
            and entry_theta != 0.0
            and abs(theta_per_day_now) >= 2.0 * abs(entry_theta)
        ):
            cliff_month = months
        points.append(ThetaRunwayPoint(
            months_held=months,
            days_to_exp=days_remaining,
            theta_per_day=round(theta_per_day_now, 5),
            theta_per_month=round(theta_per_month, 4),
            cumulative_decay=round(cumulative, 3),
        ))
        last_theta_per_day = theta_per_day_now
    return ThetaRunway(
        ticker=suggestion.ticker,
        points=tuple(points),
        cliff_starts_at_month=cliff_month,
    )


# ── Invalidation / risk levels ───────────────────────────────────────────

@dataclass(frozen=True)
class RiskTable:
    """Defined-risks table mirroring the PYPL deck's risk section."""

    ticker:               str
    max_loss_dollars:     float            # = capital deployed
    invalidation_spot:    float            # auto-derived
    scaling_in_levels:    tuple["ScalingRung", ...]


@dataclass(frozen=True)
class ScalingRung:
    spot_trigger:    float
    add_fraction:    float       # of original position size
    rationale:       str


def build_risk_table(
    suggestion: LeapsSuggestion,
    capital_deployed: float,
    invalidation_pct_below_spot: float = 0.20,
) -> RiskTable:
    """Build the defined-risk + scaling-in plan for one position.

    Invalidation level: ``spot × (1 − invalidation_pct_below_spot)``.
    Default 20 % below entry spot, matching the deck's $42.81 → $33 fib
    extension level for PYPL.

    Scaling-in rungs at -15 %, -25 %, -35 % from entry — each rung adds
    progressively larger increments, mirroring the deck's 25 %/50 %/aggressive
    pattern.
    """
    entry_spot = float(suggestion.spot)
    invalidation_spot = round(entry_spot * (1.0 - invalidation_pct_below_spot), 2)

    rungs = (
        ScalingRung(
            spot_trigger=round(entry_spot * 0.85, 2),
            add_fraction=0.25,
            rationale="initial support test — small add to lower avg cost",
        ),
        ScalingRung(
            spot_trigger=round(entry_spot * 0.75, 2),
            add_fraction=0.50,
            rationale="major fib extension reached — larger add",
        ),
        ScalingRung(
            spot_trigger=round(entry_spot * 0.65, 2),
            add_fraction=1.00,
            rationale="extreme drawdown — aggressive tranche, "
                      "consider lower strike if available",
        ),
    )
    return RiskTable(
        ticker=suggestion.ticker,
        max_loss_dollars=round(float(capital_deployed), 2),
        invalidation_spot=invalidation_spot,
        scaling_in_levels=rungs,
    )
