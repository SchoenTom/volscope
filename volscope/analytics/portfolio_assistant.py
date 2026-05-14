"""
Portfolio Assistant — intelligent risk commentary for the user's
Optionsscheine portfolio.

For each open position the assistant generates a *specific, actionable*
commentary block: bad-entry retrospection ("you bought at IV percentile
78 — was rich"), forward Greek trajectory ("delta is 0.42 today; if spot
rises 5% delta climbs to 0.58 as gamma kicks in"), distance-to-barrier
warnings for knockouts, theta-decay timing, earnings-crush risk, and
explicit suggested actions ("consider rolling to longer dated").

This is the *killer feature* of VolScope as a personal hedge-fund tool:
it transforms passive vol data into an active advisor that watches the
positions the user actually holds.

The module is pure analytics. It consumes:
  - OptionsscheinSpec (the user's position)
  - current spot
  - current and entry IV (computed by ``optionsschein_lookup``)
  - daily vol history (for percentile context)
  - optional: upcoming earnings date

…and produces a ``PositionInsight`` with structured commentary.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
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
from volscope.analytics.optionsschein_lookup import (
    OptionsscheinSpec,
    days_to_expiry,
    distance_to_barrier_pct,
    is_knockout_dead,
)


# ── Output types ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GreekTrajectory:
    """Greek values now and across forward spot scenarios."""
    delta_now:   float
    gamma_now:   float
    vega_now:    float    # per 1% IV move
    theta_now:   float    # per day
    delta_at_minus_5pct: float
    delta_at_plus_5pct:  float
    delta_at_minus_10pct: float
    delta_at_plus_10pct:  float


@dataclass(frozen=True)
class EntryQuality:
    """Retrospective quality of the entry."""
    entry_iv_percentile: Optional[float]   # 0..100; high = entry was rich
    iv_change_since_entry_pp: Optional[float]   # exit_iv − entry_iv
    pnl_from_iv_change_pct: Optional[float]    # vega P&L proxy
    pnl_from_spot_change_pct: Optional[float]  # delta P&L proxy
    quality_label: str    # "EXCELLENT", "GOOD", "FAIR", "POOR", "BAD"


@dataclass(frozen=True)
class WarningFlag:
    """One severity-coded warning."""
    severity: str    # "info" | "watch" | "warn" | "alert"
    code:     str    # short identifier
    message:  str    # 1-line trader-facing


@dataclass(frozen=True)
class PositionInsight:
    """Full per-position commentary block."""
    spec:           OptionsscheinSpec
    current_spot:   float
    current_iv:     Optional[float]
    days_to_expiry: int
    is_dead:        bool
    moneyness_pct:  float    # (spot-strike)/strike for calls, inverted for puts; positive = ITM
    greeks:         GreekTrajectory
    entry_quality:  Optional[EntryQuality]
    warnings:       tuple[WarningFlag, ...]
    suggested_actions: tuple[str, ...]
    summary:        str      # 1-2 sentence headline


# ── Configuration ───────────────────────────────────────────────────────

_R = 0.04                # risk-free rate
_FORWARD_SPOT_MOVES = (-0.10, -0.05, 0.0, 0.05, 0.10)
_GOOD_ENTRY_PCT = 30.0   # entry below this percentile = good
_BAD_ENTRY_PCT = 70.0    # entry above this = bad
_EARNINGS_NEAR_DAYS = 7
_KO_DANGER_PCT = 5.0     # within 5% of barrier = alert
_KO_WATCH_PCT  = 12.0    # within 12% of barrier = watch
_THETA_ACCEL_DAYS = 30
_VEGA_PER_IV_PCT_OF_PREMIUM = 0.05  # 1pt IV move ≈ 5% premium for ATM 60d


# ── Greek trajectory ─────────────────────────────────────────────────────

def compute_greek_trajectory(
    spec:        OptionsscheinSpec,
    current_spot: float,
    current_iv:  float,
    asof:        Optional[date] = None,
) -> GreekTrajectory:
    """Compute current Greeks + delta at ±5% and ±10% spot scenarios."""
    asof = asof or date.today()
    dte = max(1, days_to_expiry(spec, asof=asof))
    T = dte / 365.0
    iv_dec = max(1e-4, current_iv / 100.0)

    delta = bs_delta(current_spot, spec.strike, T, _R, iv_dec, option_type=spec.option_type)
    gamma = bs_gamma(current_spot, spec.strike, T, _R, iv_dec)
    vega = bs_vega(current_spot, spec.strike, T, _R, iv_dec) / 100.0
    theta_per_yr = bs_theta(current_spot, spec.strike, T, _R, iv_dec, option_type=spec.option_type)
    theta = theta_per_yr / 365.0

    deltas: dict[float, float] = {}
    for shift in _FORWARD_SPOT_MOVES:
        S2 = current_spot * (1 + shift)
        deltas[shift] = bs_delta(S2, spec.strike, T, _R, iv_dec, option_type=spec.option_type)

    return GreekTrajectory(
        delta_now=round(delta, 4),
        gamma_now=round(gamma, 6),
        vega_now=round(vega, 4),
        theta_now=round(theta, 4),
        delta_at_minus_5pct=round(deltas[-0.05], 4),
        delta_at_plus_5pct=round(deltas[+0.05], 4),
        delta_at_minus_10pct=round(deltas[-0.10], 4),
        delta_at_plus_10pct=round(deltas[+0.10], 4),
    )


# ── Entry quality ────────────────────────────────────────────────────────

def assess_entry_quality(
    spec:               OptionsscheinSpec,
    current_iv:         float,
    entry_iv:           Optional[float],
    entry_iv_pctl:      Optional[float],
    current_spot:       float,
    spot_at_entry:      Optional[float] = None,
) -> EntryQuality:
    """Retrospective entry quality assessment.

    Quality label rules:
      - EXCELLENT  entry IV percentile ≤ 20 AND P&L positive
      - GOOD       entry IV percentile ≤ 30 OR (P&L positive AND entry < 50)
      - FAIR       entry IV percentile in 30..70
      - POOR       entry IV percentile in 70..85
      - BAD        entry IV percentile > 85 OR P&L sharply negative
    """
    iv_change = None
    pnl_iv = None
    if entry_iv is not None and current_iv is not None:
        iv_change = current_iv - entry_iv
        # Both long calls AND long puts have positive vega — IV rise lifts
        # premium for either side. (The spec models LONG positions only;
        # short-premium entries would invert this.) Convert IV-point change
        # to approximate % P&L via vega-of-premium proxy.
        if spec.option_type in ("call", "put"):
            pnl_iv = iv_change * _VEGA_PER_IV_PCT_OF_PREMIUM * 100.0  # in %

    pnl_spot = None
    if spot_at_entry is not None and current_spot is not None and spot_at_entry > 0:
        spot_move_pct = (current_spot - spot_at_entry) / spot_at_entry * 100.0
        # Approx leveraged move via delta — use 0.5 as fallback ATM proxy
        leveraged = spot_move_pct * 1.5    # crude proxy for OTM warrant leverage
        pnl_spot = -leveraged if spec.option_type == "put" else leveraged

    # Quality label
    label = "FAIR"
    if entry_iv_pctl is not None:
        if entry_iv_pctl <= 20:
            label = "EXCELLENT"
        elif entry_iv_pctl <= 30:
            label = "GOOD"
        elif entry_iv_pctl <= 70:
            label = "FAIR"
        elif entry_iv_pctl <= 85:
            label = "POOR"
        else:
            label = "BAD"
    # Override with P&L when available
    total_pnl = (pnl_iv or 0) + (pnl_spot or 0)
    if total_pnl < -30:
        label = "BAD"
    elif total_pnl > 30 and label in ("FAIR", "POOR"):
        label = "GOOD"

    return EntryQuality(
        entry_iv_percentile=(round(entry_iv_pctl, 1) if entry_iv_pctl is not None else None),
        iv_change_since_entry_pp=(round(iv_change, 2) if iv_change is not None else None),
        pnl_from_iv_change_pct=(round(pnl_iv, 1) if pnl_iv is not None else None),
        pnl_from_spot_change_pct=(round(pnl_spot, 1) if pnl_spot is not None else None),
        quality_label=label,
    )


# ── Warning generation ───────────────────────────────────────────────────

def generate_warnings(
    spec:        OptionsscheinSpec,
    current_spot: float,
    current_iv:  Optional[float],
    iv_pct_now:  Optional[float],
    earnings_in: Optional[int],
    greeks:      GreekTrajectory,
    is_dead:     bool,
    moneyness_pct: float,
) -> list[WarningFlag]:
    """Produce a list of severity-coded warnings for one position."""
    warnings: list[WarningFlag] = []

    # 1. Knockout breached
    if is_dead:
        warnings.append(WarningFlag(
            severity="alert", code="KO_DEAD",
            message=f"Knock-out barrier {spec.barrier:.2f} breached — position is worthless.",
        ))

    # 2. KO distance
    ko_dist = distance_to_barrier_pct(spec, current_spot)
    if ko_dist is not None and not is_dead:
        if ko_dist < _KO_DANGER_PCT:
            warnings.append(WarningFlag(
                severity="alert", code="KO_NEAR",
                message=f"Spot only {ko_dist:.1f}% from KO barrier — high knock-out risk.",
            ))
        elif ko_dist < _KO_WATCH_PCT:
            warnings.append(WarningFlag(
                severity="warn", code="KO_WATCH",
                message=f"Spot {ko_dist:.1f}% from KO barrier — watch closely.",
            ))

    # 3. Days to expiry / theta acceleration
    dte = days_to_expiry(spec)
    if dte == 0:
        warnings.append(WarningFlag(
            severity="alert", code="EXPIRED",
            message="Position has expired today.",
        ))
    elif dte < 7:
        warnings.append(WarningFlag(
            severity="alert", code="DTE_LOW",
            message=f"Only {dte} days to expiry — theta dominates remaining P&L.",
        ))
    elif dte < _THETA_ACCEL_DAYS:
        warnings.append(WarningFlag(
            severity="watch", code="THETA_ACCEL",
            message=f"{dte} days to expiry — theta acceleration zone (< {_THETA_ACCEL_DAYS}d).",
        ))

    # 4. Earnings risk
    if earnings_in is not None and 0 <= earnings_in <= _EARNINGS_NEAR_DAYS:
        warnings.append(WarningFlag(
            severity="warn", code="EARNINGS_NEAR",
            message=f"Earnings in {earnings_in} days — IV crush risk for premium-long holders.",
        ))

    # 5. Bad entry IV regime
    if iv_pct_now is not None and iv_pct_now >= 80 and spec.option_type in ("call", "put"):
        warnings.append(WarningFlag(
            severity="watch", code="IV_RICH",
            message=f"IV currently at {iv_pct_now:.0f} percentile — vol is rich; vega P&L unlikely if you're long.",
        ))

    # 6. Gamma trap (close to ATM, near expiry)
    if abs(moneyness_pct) < 5 and dte < 30 and dte > 0:
        warnings.append(WarningFlag(
            severity="watch", code="GAMMA_TRAP",
            message=f"Position near ATM with {dte}d to expiry — gamma swings can flip P&L sharply.",
        ))

    return warnings


# ── Suggested actions ───────────────────────────────────────────────────

def suggest_actions(
    spec:        OptionsscheinSpec,
    greeks:      GreekTrajectory,
    iv_pct_now:  Optional[float],
    entry_quality: Optional[EntryQuality],
    is_dead:     bool,
    earnings_in: Optional[int],
    moneyness_pct: float,
) -> list[str]:
    """Suggest 0-4 concrete next actions for the trader."""
    actions: list[str] = []
    if is_dead:
        actions.append("Mark position closed — KO triggered, no recovery possible.")
        return actions

    dte = days_to_expiry(spec)
    if dte < 7:
        actions.append("Decision required NOW: roll to longer dated, close, or accept expiry.")

    # Theta acceleration → consider roll
    if dte < _THETA_ACCEL_DAYS and dte >= 7 and abs(moneyness_pct) < 10:
        actions.append("Consider rolling to longer dated to escape theta-acceleration zone.")

    # Vol-rich + long premium → consider close/take profits
    if iv_pct_now is not None and iv_pct_now > 80 and spec.option_type in ("call", "put"):
        actions.append("IV is rich — partial profit-take may capture vega gain before mean-reversion.")

    # Bad entry → manage size
    if entry_quality and entry_quality.quality_label == "BAD":
        actions.append("Bad entry — limit add-ons; consider tax-loss-style cut and re-entry at better vol.")

    # Earnings approaching
    if earnings_in is not None and 0 <= earnings_in <= 3:
        actions.append("Earnings within 3 days — decide pre-print: hold for direction, or close to avoid crush.")

    return actions


# ── Composer ─────────────────────────────────────────────────────────────

from volscope.utils.timing import instrumented  # noqa: E402


@instrumented("analytics.position_insight")
def build_position_insight(
    spec:           OptionsscheinSpec,
    current_spot:   float,
    current_iv:     Optional[float],
    *,
    iv_history:     Optional[pd.DataFrame] = None,
    spot_at_entry:  Optional[float] = None,
    earnings_in:    Optional[int] = None,
    iv_pct_now:     Optional[float] = None,
    entry_iv_pctl:  Optional[float] = None,
    asof:           Optional[date] = None,
) -> PositionInsight:
    """Build the full PositionInsight for one position."""
    asof = asof or date.today()
    dte = days_to_expiry(spec, asof=asof)
    is_dead = is_knockout_dead(spec, current_spot)

    # Moneyness — positive = ITM
    if spec.option_type == "call":
        moneyness = (current_spot - spec.strike) / max(1e-9, spec.strike) * 100.0
    else:
        moneyness = (spec.strike - current_spot) / max(1e-9, spec.strike) * 100.0

    # Greeks (skip if no IV)
    if current_iv is not None and current_iv > 0 and dte > 0:
        greeks = compute_greek_trajectory(spec, current_spot, current_iv, asof=asof)
    else:
        greeks = GreekTrajectory(
            delta_now=0.0, gamma_now=0.0, vega_now=0.0, theta_now=0.0,
            delta_at_minus_5pct=0.0, delta_at_plus_5pct=0.0,
            delta_at_minus_10pct=0.0, delta_at_plus_10pct=0.0,
        )

    # Entry quality
    entry_q = None
    if current_iv is not None and (spec.entry_iv is not None or entry_iv_pctl is not None):
        entry_q = assess_entry_quality(
            spec=spec,
            current_iv=current_iv,
            entry_iv=spec.entry_iv,
            entry_iv_pctl=entry_iv_pctl,
            current_spot=current_spot,
            spot_at_entry=spot_at_entry,
        )

    warnings = tuple(generate_warnings(
        spec=spec,
        current_spot=current_spot,
        current_iv=current_iv,
        iv_pct_now=iv_pct_now,
        earnings_in=earnings_in,
        greeks=greeks,
        is_dead=is_dead,
        moneyness_pct=moneyness,
    ))
    actions = tuple(suggest_actions(
        spec=spec, greeks=greeks, iv_pct_now=iv_pct_now,
        entry_quality=entry_q, is_dead=is_dead,
        earnings_in=earnings_in, moneyness_pct=moneyness,
    ))

    summary = _build_summary(spec, current_spot, current_iv, dte, moneyness, is_dead, entry_q)

    return PositionInsight(
        spec=spec,
        current_spot=current_spot,
        current_iv=current_iv,
        days_to_expiry=dte,
        is_dead=is_dead,
        moneyness_pct=round(moneyness, 2),
        greeks=greeks,
        entry_quality=entry_q,
        warnings=warnings,
        suggested_actions=actions,
        summary=summary,
    )


def _build_summary(
    spec, current_spot, current_iv, dte, moneyness, is_dead, entry_q,
) -> str:
    """One-or-two-sentence headline for the insight card."""
    if is_dead:
        return f"{spec.underlying} {spec.option_type.upper()} {spec.strike} — KO TRIGGERED, position dead."

    moneyness_label = "ITM" if moneyness > 0 else "OTM"
    qual = f" · entry: {entry_q.quality_label}" if entry_q is not None else ""
    iv_str = f"{current_iv:.1f}%" if current_iv else "—"
    return (
        f"{spec.underlying} {spec.option_type.upper()} K={spec.strike} → "
        f"{abs(moneyness):.1f}% {moneyness_label}, "
        f"{dte}d to expiry, IV {iv_str}{qual}."
    )


# ── Portfolio aggregation ───────────────────────────────────────────────

@dataclass(frozen=True)
class PortfolioInsight:
    """Aggregated commentary across all positions."""
    n_positions:    int
    n_dead:         int
    n_warnings_alert:  int
    n_warnings_watch:  int
    headline:       str
    diversification_warnings: tuple[str, ...]


def aggregate_portfolio(insights: list[PositionInsight]) -> PortfolioInsight:
    """Roll up per-position insights into portfolio-level commentary."""
    if not insights:
        return PortfolioInsight(
            n_positions=0, n_dead=0,
            n_warnings_alert=0, n_warnings_watch=0,
            headline="No positions tracked.",
            diversification_warnings=(),
        )

    n_alert = sum(1 for ins in insights for w in ins.warnings if w.severity == "alert")
    n_watch = sum(1 for ins in insights for w in ins.warnings if w.severity == "watch")
    n_dead = sum(1 for ins in insights if ins.is_dead)

    # Concentration check
    by_underlying: dict[str, int] = {}
    for ins in insights:
        by_underlying[ins.spec.underlying] = by_underlying.get(ins.spec.underlying, 0) + 1
    div_warns: list[str] = []
    for tk, n in by_underlying.items():
        if n >= 3:
            div_warns.append(
                f"{n} positions in {tk} — concentrated; idiosyncratic risk amplified."
            )
    if len(by_underlying) <= 2 and len(insights) >= 3:
        div_warns.append(
            f"Only {len(by_underlying)} unique underlyings across {len(insights)} positions — low diversification."
        )

    if n_alert > 0:
        headline = f"⚠ {n_alert} position(s) need immediate attention."
    elif n_watch > 0:
        headline = f"{n_watch} position(s) on watch — monitor."
    elif n_dead > 0:
        headline = f"{n_dead} position(s) closed (KO triggered)."
    else:
        headline = f"{len(insights)} active positions — no critical warnings."

    return PortfolioInsight(
        n_positions=len(insights),
        n_dead=n_dead,
        n_warnings_alert=n_alert,
        n_warnings_watch=n_watch,
        headline=headline,
        diversification_warnings=tuple(div_warns),
    )
