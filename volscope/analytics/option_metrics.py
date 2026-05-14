"""
Finanzen.net-style option quick-stats.

VolScope already exposes IV, Δ, Γ, Θ, Vega via the BSM solver. This
module adds the operator-facing *evaluation* metrics that German
retail platforms (finanzen.net / OnVista) show next to those: the
Aufgeld / Hebel / Omega / break-even-move family.

All functions are pure numpy — no DB / Streamlit dependencies.

Glossary
========
- **Aufgeld (Premium %)** — the percentage premium the operator
  pays over the intrinsic value. For a call: ``(spot + premium − strike) / spot − 1`` × 100.
  Positive = paying time-value; near-zero = deep ITM with no
  time-value left.
- **Aufgeld p.a.** — Aufgeld annualised to the option's tenor;
  ``aufgeld * 365 / dte``. Lets the operator compare a 30-day
  vs a 1-year option's premium cost on equal footing.
- **Hebel (Leverage)** — ``(spot / premium) * ratio``. Crude
  "how much underlying does one option control per dollar of
  premium" — *not* the effective P&L leverage (that's Omega).
- **Omega (Effective leverage)** — ``Hebel × |Δ|``. The true
  expected P&L sensitivity: a 1 % move in the underlying produces
  approximately Omega % move in the option's price.
- **Break-even Punkt** — the spot price at expiry where the option
  trade is flat. For a long call: ``strike + premium``.
- **Break-even Move %** — ``(break_even − spot) / spot * 100`` —
  the percentage the underlying must move from today's spot for
  the trade to be flat at expiry.
- **Innerer Wert (intrinsic value)** — payoff if exercised today.
- **Zeitwert (time value)** — ``premium − intrinsic``. Always ≥ 0
  for European-style options before expiry.

Conventions
-----------
- ``premium``, ``spot``, ``strike`` are positive floats (the option
  price the operator would PAY).
- ``option_type`` is ``"call"`` or ``"put"``.
- ``ratio`` is the option-to-share multiplier. US-listed options are
  always 100 shares per contract — pass ``ratio=100``. German
  warrants (Optionsscheine) typically use 0.01 / 0.1 — pass the real
  number from the product factsheet.
- ``dte`` is in calendar days. Year basis is 365.
- All percentages are returned as *percents* (5.0, not 0.05) to
  match how finanzen.net displays them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OptionType = Literal["call", "put"]


# ── Primitives ──────────────────────────────────────────────────────

def intrinsic_value(
    spot: float, strike: float, option_type: OptionType,
) -> float:
    """Payoff if the option were exercised today."""
    if option_type == "call":
        return max(0.0, spot - strike)
    return max(0.0, strike - spot)


def time_value(
    premium: float, spot: float, strike: float, option_type: OptionType,
) -> float:
    """``premium − intrinsic`` — the operator's pure time-value cost.

    Clamped to ≥ 0; numerical noise around deep-ITM strikes can push
    BSM-priced premium slightly below intrinsic, and finanzen.net
    likewise reports a 0 floor rather than a tiny negative.
    """
    return max(0.0, premium - intrinsic_value(spot, strike, option_type))


def break_even_price(
    strike: float, premium: float, option_type: OptionType,
) -> float:
    """The spot price at expiry where the option trade is flat.

    Long call: ``strike + premium``. Long put: ``strike − premium``.
    Short positions are symmetric; the helper treats ``premium`` as
    a positive cost the operator paid.
    """
    if option_type == "call":
        return strike + premium
    return strike - premium


def break_even_move_pct(
    spot: float, strike: float, premium: float, option_type: OptionType,
) -> float:
    """Percentage move from spot needed to break even at expiry."""
    if spot <= 0:
        return 0.0
    be = break_even_price(strike, premium, option_type)
    return (be - spot) / spot * 100.0


def aufgeld_pct(
    spot: float, strike: float, premium: float, option_type: OptionType,
) -> float:
    """Premium-over-intrinsic, as a percent of the underlying.

    For a long call:
        Aufgeld = (strike + premium − spot) / spot × 100

    The break-even spot at expiry is ``strike + premium``. ``Aufgeld``
    expresses how far the underlying must rise from today's spot
    to make the trade break even, as a percent.

    For a long put, the symmetric quantity:
        Aufgeld = (spot − strike + premium) / spot × 100
    """
    if spot <= 0:
        return 0.0
    if option_type == "call":
        return (strike + premium - spot) / spot * 100.0
    return (spot - strike + premium) / spot * 100.0


def aufgeld_pa_pct(aufgeld: float, dte: int) -> float:
    """Annualised Aufgeld — ``aufgeld * 365 / dte``.

    Lets the operator compare premium cost across tenors on equal
    footing: a 5 % Aufgeld at 30 DTE is 60 % p.a.; at 365 DTE it's
    5 % p.a. — the per-day cost of buying time.
    """
    if dte <= 0:
        return 0.0
    return aufgeld * 365.0 / dte


def leverage(
    spot: float, premium: float, *, ratio: float = 100.0,
) -> float:
    """Crude leverage = ``(spot / premium) * ratio``.

    For US-listed options the ratio is 100 (one contract controls
    100 shares). For German Optionsscheine read the ratio off the
    product factsheet (typically 0.01–1.0).
    """
    if premium <= 0:
        return 0.0
    return (spot / premium) * ratio


def omega(leverage_val: float, delta: float) -> float:
    """Effective P&L leverage = ``Hebel × |Δ|``.

    Omega is the empirically more useful number than raw Hebel:
    a 1 % move in the underlying produces approximately Omega % move
    in the option's price (to first order). Hebel alone overstates
    the sensitivity because deep-OTM options have small Δ.
    """
    return leverage_val * abs(float(delta))


# ── Bundled result ─────────────────────────────────────────────────

@dataclass(frozen=True)
class OptionMetrics:
    """All operator-facing quick-stats for one option leg."""
    intrinsic:        float
    time_value:       float
    break_even:       float
    break_even_pct:   float       # percent move from spot
    aufgeld:          float       # percent
    aufgeld_pa:       float       # percent annualised
    leverage:         float       # raw Hebel
    omega:            float       # effective leverage = Hebel × |Δ|


def compute_all(
    *,
    spot:        float,
    strike:      float,
    premium:     float,
    option_type: OptionType,
    delta:       float,
    dte:         int,
    ratio:       float = 100.0,
) -> OptionMetrics:
    """Convenience: compute every quick-stat in one call.

    Mirrors the finanzen.net option-detail panel exactly so callers
    that just want "show me all the German-warrant numbers" don't
    have to wire seven helpers individually.
    """
    intr = intrinsic_value(spot, strike, option_type)
    tv   = time_value(premium, spot, strike, option_type)
    be   = break_even_price(strike, premium, option_type)
    be_p = break_even_move_pct(spot, strike, premium, option_type)
    af   = aufgeld_pct(spot, strike, premium, option_type)
    af_a = aufgeld_pa_pct(af, dte)
    lev  = leverage(spot, premium, ratio=ratio)
    om   = omega(lev, delta)
    return OptionMetrics(
        intrinsic=intr,
        time_value=tv,
        break_even=be,
        break_even_pct=be_p,
        aufgeld=af,
        aufgeld_pa=af_a,
        leverage=lev,
        omega=om,
    )
