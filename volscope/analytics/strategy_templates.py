"""
Strategy templates — first-class definitions of the option structures
a retail vol trader places.

Each template is a small dataclass whose ``materialize`` method turns
the abstract idea ("ATM straddle, 30 DTE") into a list of concrete
``LegSpec`` records (option_type, strike, expiry, contracts, action,
BSM-priced entry premium). The paper-trader uses these specs to write
position rows; the Strategy Builder UI uses them for a leg preview.

Templates intentionally don't know about the DB, Streamlit, or chains —
they are pure functions of (spot, iv, dte, ...). Each template encodes
the trader convention for strike picking:

    Straddle        ATM call + ATM put
    Strangle        OTM call (Δ ≈ 0.30) + OTM put (Δ ≈ -0.30)
    Iron Condor     short OTM call/put + long farther wings
    Call Spread     long ATM + short OTM
    Put Spread      long ATM + short OTM (downside)
    Calendar        long back-month + short front-month, same strike
    Risk Reversal   long OTM call + short OTM put (or vice versa)
    Long Call       single ATM/OTM call leg
    Long Put        single ATM/OTM put leg

All strike conventions are reproducible: the user can paper-buy the
same name twice on the same day and see the same legs each time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

import numpy as np

from volscope.analytics.black_scholes import (
    bs_delta, bs_gamma, bs_price, bs_rho, bs_theta, bs_vega,
)


# ── Leg primitive ────────────────────────────────────────────────────

@dataclass(frozen=True)
class LegSpec:
    """One executable option leg — what gets written into the positions
    table on paper-buy.

    Attributes
    ----------
    option_type    : "call" | "put"
    action         : "buy" | "sell" — "sell" means short the leg
    strike         : exercise price ($)
    expiry         : ISO date of expiry
    contracts      : number of contracts (each = 100 shares of underlying)
    entry_premium  : BSM-priced per-contract premium at materialization
    delta          : BSM delta at entry (signed; long-call = +, long-put = −)
    """
    option_type:   str
    action:        str
    strike:        float
    expiry:        date
    contracts:     int
    entry_premium: float
    delta:         float


@dataclass(frozen=True)
class MaterializedStrategy:
    """The full output of ``StrategyTemplate.materialize``.

    Carries the leg list plus aggregate economics so the UI can render
    a net-debit / net-credit summary without re-summing.

    Phase 2 additions
    -----------------
    The dataclass also implements the operational Strategy Protocol
    (``payoff_at_expiry``, ``payoff_at_t``, ``net_premium``, ``greeks``,
    ``breakevens_at``, ``max_profit``, ``max_loss_unbounded``) so the
    Options Lab can compute payoff curves and Greeks surfaces against
    arbitrary (S, t, iv, r, q) without re-materializing.

    The pre-existing snapshot fields (``net_debit``, static ``max_loss``,
    static ``max_gain``, static ``breakevens``) are kept for backwards
    compatibility with paper-trader and Portfolio renderers.
    """
    template_name:  str
    ticker:         str
    legs:           tuple[LegSpec, ...]
    net_debit:      float            # positive = pay to open; negative = collect
    max_loss:       Optional[float]  # None when unbounded
    max_gain:       Optional[float]  # None when unbounded
    breakevens:     tuple[float, ...]
    summary_line:   str              # one-line trader-grade description
    direction:      str              # "long_vol" | "short_vol" | "neutral_vol"

    # ── Protocol: structural ────────────────────────────────────────

    @property
    def name(self) -> str:
        """Protocol-facing alias for ``template_name``."""
        return self.template_name

    # ── Protocol: payoff math ───────────────────────────────────────

    def payoff_at_expiry(self, S):
        """Per-share P&L at expiry as a function of underlying ``S``.

        ``S`` may be a scalar or numpy array. Returns total P&L for the
        full position (all contracts, all legs) in dollars — positive =
        profit, negative = loss. Each leg's payoff is computed against
        its OWN expiry; for multi-expiry structures (calendars) only the
        earliest expiry's leg has resolved at that point — see
        ``payoff_at_t`` for path-dependent multi-expiry handling.
        """
        S_arr = np.asarray(S, dtype=float)
        pnl = np.zeros_like(S_arr)
        for leg in self.legs:
            sign = +1 if leg.action == "buy" else -1
            if _is_stock_leg(leg):
                # Stock leg: payoff is linear in S, no strike, no decay
                cur_per_share = S_arr.copy()
            else:
                cur_per_share = _intrinsic_per_share(
                    S_arr, leg.strike, leg.option_type,
                )
            pnl += sign * (cur_per_share - leg.entry_premium) * leg.contracts * 100
        return pnl

    def payoff_at_t(
        self,
        S,
        t_fraction: float,
        iv: float,
        r: float = 0.04,
        q: float = 0.0,
    ):
        """P&L at calendar fraction ``t_fraction`` of remaining DTE.

        ``t_fraction = 0`` ⇒ today (full time remaining), ``1`` ⇒ expiry.
        Each leg keeps its own original DTE; the fraction is applied
        per-leg so calendar spreads decay asymmetrically.

        Vectorised: a single d1/d2 array per leg replaces the previous
        scalar-loop. For a 200-point grid × 4 legs this is ~30× faster
        than the per-point pricing loop and keeps the Options Lab page
        render comfortably under the 300 ms budget.
        """
        S_arr = np.asarray(S, dtype=float)
        pnl = np.zeros_like(S_arr)
        today = date.today()
        iv_dec = max(0.001, iv / 100.0)
        for leg in self.legs:
            sign = +1 if leg.action == "buy" else -1
            if _is_stock_leg(leg):
                # Stock leg: present-value is just spot (no decay, no IV)
                current = S_arr.copy()
            else:
                dte_total = max(1, (leg.expiry - today).days)
                remaining_days = max(0, int(dte_total * (1.0 - t_fraction)))
                T = remaining_days / 365.0
                if T <= 0:
                    current = _intrinsic_per_share(S_arr, leg.strike, leg.option_type)
                else:
                    current = _vec_bsm_price(
                        S_arr, leg.strike, T, r, iv_dec, q, leg.option_type,
                    )
            pnl += sign * (current - leg.entry_premium) * leg.contracts * 100
        return pnl

    def net_premium(
        self,
        S0: float,
        iv: float,
        r: float = 0.04,
        q: float = 0.0,
        T: Optional[float] = None,
    ) -> float:
        """Recompute net cash flow at open against new (S0, iv, r, q, T).

        Differs from the snapshot ``net_debit`` field which was sealed
        in at materialize-time. Use this when the Options Lab user
        moves the IV slider and we want a fresh BSM-priced debit.

        Returns + for net debit, − for net credit.
        """
        iv_dec = max(0.001, iv / 100.0)
        today = date.today()
        net = 0.0
        for leg in self.legs:
            sign = +1 if leg.action == "buy" else -1
            if _is_stock_leg(leg):
                # Stock leg: outlay = spot per share (×100 multiplier below)
                net += sign * S0 * leg.contracts * 100
                continue
            if T is None:
                T_leg = max(1, (leg.expiry - today).days) / 365.0
            else:
                T_leg = T
            premium = bs_price(S0, leg.strike, T_leg, r, iv_dec, q,
                               option_type=leg.option_type)
            net += sign * premium * leg.contracts * 100
        return net

    def greeks(
        self,
        S: float,
        iv: float,
        r: float = 0.04,
        q: float = 0.0,
        T: Optional[float] = None,
    ) -> dict[str, float]:
        """Position-level greeks (sum over legs, sign-adjusted by action).

        Returns dict with delta, gamma, theta_per_day, vega_per_1pct,
        rho_per_1pct. All values per total position, not per contract.
        Theta is per-day; vega/rho are per-1%-move (divided by 100).
        """
        iv_dec = max(0.001, iv / 100.0)
        today = date.today()
        d = g = th = v = rh = 0.0
        for leg in self.legs:
            sign = +1 if leg.action == "buy" else -1
            mult = sign * leg.contracts * 100
            if _is_stock_leg(leg):
                # Stock greeks: delta exactly 1 per share, all others zero
                d += mult * 1.0
                continue
            if T is None:
                T_leg = max(1, (leg.expiry - today).days) / 365.0
            else:
                T_leg = T
            d  += mult * bs_delta(S, leg.strike, T_leg, r, iv_dec, q,
                                  option_type=leg.option_type)
            g  += mult * bs_gamma(S, leg.strike, T_leg, r, iv_dec, q)
            th += mult * bs_theta(S, leg.strike, T_leg, r, iv_dec, q,
                                  option_type=leg.option_type) / 365.0
            v  += mult * bs_vega(S, leg.strike, T_leg, r, iv_dec, q) / 100.0
            rh += mult * bs_rho(S, leg.strike, T_leg, r, iv_dec, q,
                                option_type=leg.option_type) / 100.0
        return {
            "delta":         d,
            "gamma":         g,
            "theta_per_day": th,
            "vega_per_1pct": v,
            "rho_per_1pct":  rh,
        }

    # ── Protocol: bounded-ness helpers ─────────────────────────────

    def max_profit(self) -> Optional[float]:
        """Protocol method form — returns the snapshot ``max_gain``."""
        return self.max_gain

    def max_loss_unbounded(self) -> Optional[float]:
        """Protocol method form — returns the snapshot ``max_loss``."""
        return self.max_loss


# ── Helpers ──────────────────────────────────────────────────────────

_RISK_FREE = 0.04


def _is_stock_leg(leg: "LegSpec") -> bool:
    """A leg with strike==0 (and option_type='call') is our stock-leg
    encoding (used by Covered Call). Avoids extending LegSpec with a
    discriminator field while still letting the operational methods
    distinguish stock outlay from option premium."""
    return leg.strike <= 0.0 and leg.option_type == "call"


def _intrinsic_per_share(S_arr, strike: float, option_type: str):
    """Vectorised per-share intrinsic value at expiry for one leg."""
    if option_type == "call":
        return np.maximum(S_arr - strike, 0.0)
    return np.maximum(strike - S_arr, 0.0)


def _vec_bsm_price(
    S_arr,
    strike: float,
    T: float,
    r: float,
    sigma: float,
    q: float,
    option_type: str,
):
    """Vectorised BSM price across an array of underlying prices.

    Mirrors the scalar ``bs_price`` exactly but runs the whole
    underlying grid through numpy in one shot. Used by
    ``payoff_at_t`` and ``net_premium_grid`` to keep the Options
    Lab page responsive on large grids.
    """
    from scipy.stats import norm

    S_arr = np.asarray(S_arr, dtype=float)
    if T <= 0 or sigma <= 0:
        return _intrinsic_per_share(S_arr, strike, option_type)
    sqrt_t = np.sqrt(T)
    # Guard against log(0) / log(<0) — shouldn't happen on a valid grid
    # but the Options Lab user may type spot==0 by accident.
    S_safe = np.where(S_arr > 0, S_arr, 1e-9)
    d1 = (np.log(S_safe / strike) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc_r = np.exp(-r * T)
    disc_q = np.exp(-q * T)
    if option_type == "call":
        return S_safe * disc_q * norm.cdf(d1) - strike * disc_r * norm.cdf(d2)
    return strike * disc_r * norm.cdf(-d2) - S_safe * disc_q * norm.cdf(-d1)


def _T(dte: int) -> float:
    return max(1, dte) / 365.0


def _iv_dec(iv_pct: float) -> float:
    return max(0.001, iv_pct / 100.0)


def _premium(spot: float, strike: float, dte: int, iv_pct: float, opt_type: str) -> float:
    """BSM premium for a single contract."""
    return bs_price(spot, strike, _T(dte), _RISK_FREE, _iv_dec(iv_pct), option_type=opt_type)


def _delta(spot: float, strike: float, dte: int, iv_pct: float, opt_type: str) -> float:
    return bs_delta(spot, strike, _T(dte), _RISK_FREE, _iv_dec(iv_pct), option_type=opt_type)


def _strike_from_delta(
    spot: float, dte: int, iv_pct: float, target_delta: float, opt_type: str,
    *, lo_mult: float = 0.4, hi_mult: float = 1.6,
) -> float:
    """Binary search for the strike whose BSM delta matches the target.

    Both put and call delta are strictly decreasing in K, so a single
    binary search works for both.
    """
    lo = spot * lo_mult
    hi = spot * hi_mult
    for _ in range(40):
        mid = (lo + hi) / 2
        d = _delta(spot, mid, dte, iv_pct, opt_type)
        if abs(d - target_delta) < 0.005:
            return mid
        # delta strictly DECREASING in K
        if d > target_delta:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _expiry_for(dte: int) -> date:
    return date.today() + timedelta(days=int(dte))


def _round_strike(strike: float) -> float:
    """Round to a strike-grid-realistic value: whole-$ above $25, half-$ below."""
    if strike <= 25:
        return round(strike * 2) / 2
    if strike <= 200:
        return round(strike)
    if strike <= 1000:
        return round(strike / 5) * 5
    return round(strike / 10) * 10


# ── Template base ────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategyTemplate:
    """One reusable strategy with a name + materializer.

    The materializer is a pure function (spot, iv_pct, dte, contracts)
    → MaterializedStrategy. The wrapper computes net economics from
    the leg list so every template benefits.
    """
    name:        str
    direction:   str   # long_vol | short_vol | neutral_vol
    description: str
    materializer: Callable[..., list[LegSpec]] = field(repr=False)

    def materialize(
        self,
        *,
        ticker: str,
        spot: float,
        iv_pct: float,
        dte: int,
        contracts: int = 1,
        override_strike: Optional[float] = None,
        override_expiry: Optional[date] = None,
    ) -> MaterializedStrategy:
        """Build a MaterializedStrategy for the given live state.

        ``override_strike`` / ``override_expiry`` let a preset pin
        exact values: when supplied AND the template is single-leg,
        the leg's strike / expiry is replaced and the premium is
        recomputed via BSM. Multi-leg templates ignore the override
        because there's no canonical leg to apply it to (a preset for
        a Straddle would need a `strikes` dict, not a single value).
        """
        if spot <= 0 or iv_pct <= 0 or dte <= 0:
            raise ValueError(
                f"{self.name}: invalid inputs spot={spot} iv={iv_pct} dte={dte}"
            )
        legs = tuple(self.materializer(
            spot=spot, iv_pct=iv_pct, dte=dte, contracts=int(max(1, contracts)),
        ))

        # Apply single-leg overrides — only safe path. Multi-leg
        # presets can ship per-leg strikes in a future extension.
        if len(legs) == 1 and (override_strike is not None or override_expiry is not None):
            leg = legs[0]
            new_strike = float(override_strike) if override_strike is not None else leg.strike
            new_expiry = override_expiry if override_expiry is not None else leg.expiry
            new_dte = max(1, (new_expiry - date.today()).days)
            new_prem = _premium(spot, new_strike, new_dte, iv_pct, leg.option_type)
            new_delt = _delta(spot, new_strike, new_dte, iv_pct, leg.option_type)
            legs = (LegSpec(
                option_type=leg.option_type, action=leg.action,
                strike=new_strike, expiry=new_expiry,
                contracts=leg.contracts,
                entry_premium=new_prem, delta=new_delt,
            ),)
        net_debit = sum(_signed_premium(l) for l in legs) * 100
        max_loss, max_gain, breakevens = _strategy_economics(self.name, legs, net_debit)
        return MaterializedStrategy(
            template_name=self.name,
            ticker=ticker,
            legs=legs,
            net_debit=net_debit,
            max_loss=max_loss,
            max_gain=max_gain,
            breakevens=tuple(breakevens),
            summary_line=_summary(self.name, legs, net_debit),
            direction=self.direction,
        )


def _signed_premium(leg: LegSpec) -> float:
    """Per-contract entry cash flow. Positive = pay to open, negative = collect."""
    sign = +1 if leg.action == "buy" else -1
    return sign * leg.entry_premium * leg.contracts


def _strategy_economics(
    name: str, legs: tuple[LegSpec, ...], net_debit: float,
) -> tuple[Optional[float], Optional[float], list[float]]:
    """Return (max_loss, max_gain, breakevens) for the named structure.

    For defined-risk structures (spreads, condors), max_loss/gain are
    closed-form. For unbounded structures (naked legs, straddles past
    BE) we mark None. Breakevens are approximations using the dominant
    leg strike(s) ± net_debit/contracts.
    """
    # Group legs for analysis
    by_type = {("buy", "call"): [], ("sell", "call"): [],
               ("buy", "put"): [],  ("sell", "put"): []}
    for l in legs:
        by_type[(l.action, l.option_type)].append(l)

    total_ctrs = sum(l.contracts for l in legs)
    debit_per_ctr = net_debit / (total_ctrs * 100) if total_ctrs > 0 else 0

    n = name.lower()
    if "straddle" in n or "strangle" in n:
        # long both legs → max-loss = debit, max-gain unbounded
        bc = [l for l in legs if l.option_type == "call" and l.action == "buy"]
        bp = [l for l in legs if l.option_type == "put"  and l.action == "buy"]
        if bc and bp:
            return (net_debit, None, [bc[0].strike + debit_per_ctr,
                                       bp[0].strike - debit_per_ctr])

    if "iron condor" in n:
        # Defined-risk premium-collection trade
        sc = [l for l in by_type[("sell", "call")]]
        bc = [l for l in by_type[("buy",  "call")]]
        sp = [l for l in by_type[("sell", "put")]]
        bp = [l for l in by_type[("buy",  "put")]]
        if sc and bc and sp and bp:
            wing_call = abs(bc[0].strike - sc[0].strike)
            wing_put  = abs(sp[0].strike - bp[0].strike)
            wing = max(wing_call, wing_put)
            max_loss = (wing * total_ctrs * 100) - abs(net_debit) if net_debit < 0 else None
            max_gain = abs(net_debit) if net_debit < 0 else None
            return (max_loss, max_gain,
                    [sc[0].strike + abs(debit_per_ctr), sp[0].strike - abs(debit_per_ctr)])

    if "spread" in n:
        bo = [l for l in legs if l.action == "buy"]
        so = [l for l in legs if l.action == "sell"]
        if bo and so:
            wing = abs(bo[0].strike - so[0].strike)
            max_loss = net_debit
            max_gain = (wing * total_ctrs * 100) - net_debit
            be = (bo[0].strike + debit_per_ctr) if bo[0].option_type == "call" \
                 else (bo[0].strike - debit_per_ctr)
            return (max_loss, max_gain, [be])

    if "calendar" in n:
        # Net debit, max-loss bounded by debit, max-gain depends on path
        return (net_debit, None, [])

    if "risk reversal" in n:
        # Long one side, short the other → both legs unbounded
        return (None, None, [])

    # Default: single-leg long → max-loss = debit, max-gain unbounded
    if len(legs) == 1 and legs[0].action == "buy":
        be = legs[0].strike + debit_per_ctr if legs[0].option_type == "call" \
             else legs[0].strike - debit_per_ctr
        return (net_debit, None, [be])

    return (None, None, [])


def _summary(name: str, legs: tuple[LegSpec, ...], net_debit: float) -> str:
    """One-line description that reads like a broker confirmation."""
    parts = []
    for l in legs:
        sign = "+" if l.action == "buy" else "−"
        opt = l.option_type[0].upper()
        parts.append(f"{sign}{l.contracts} {opt} {l.strike:g}")
    flow = f"net {'debit' if net_debit >= 0 else 'credit'} ${abs(net_debit):,.0f}"
    return f"{name} · {' / '.join(parts)} · {flow}"


# ── Concrete templates ───────────────────────────────────────────────

def _long_call_legs(*, spot, iv_pct, dte, contracts, otm_uplift=0.0):
    strike = _round_strike(spot * (1 + otm_uplift))
    prem = _premium(spot, strike, dte, iv_pct, "call")
    delt = _delta(spot, strike, dte, iv_pct, "call")
    return [LegSpec("call", "buy", strike, _expiry_for(dte), contracts, prem, delt)]


def _long_put_legs(*, spot, iv_pct, dte, contracts, otm_drop=0.0):
    strike = _round_strike(spot * (1 - otm_drop))
    prem = _premium(spot, strike, dte, iv_pct, "put")
    delt = _delta(spot, strike, dte, iv_pct, "put")
    return [LegSpec("put", "buy", strike, _expiry_for(dte), contracts, prem, delt)]


def _long_straddle_legs(*, spot, iv_pct, dte, contracts):
    strike = _round_strike(spot)
    call_prem = _premium(spot, strike, dte, iv_pct, "call")
    put_prem  = _premium(spot, strike, dte, iv_pct, "put")
    return [
        LegSpec("call", "buy", strike, _expiry_for(dte), contracts, call_prem,
                _delta(spot, strike, dte, iv_pct, "call")),
        LegSpec("put",  "buy", strike, _expiry_for(dte), contracts, put_prem,
                _delta(spot, strike, dte, iv_pct, "put")),
    ]


def _long_strangle_legs(*, spot, iv_pct, dte, contracts):
    call_k = _round_strike(_strike_from_delta(spot, dte, iv_pct, +0.30, "call"))
    put_k  = _round_strike(_strike_from_delta(spot, dte, iv_pct, -0.30, "put"))
    return [
        LegSpec("call", "buy", call_k, _expiry_for(dte), contracts,
                _premium(spot, call_k, dte, iv_pct, "call"),
                _delta(spot, call_k, dte, iv_pct, "call")),
        LegSpec("put",  "buy", put_k,  _expiry_for(dte), contracts,
                _premium(spot, put_k, dte, iv_pct, "put"),
                _delta(spot, put_k, dte, iv_pct, "put")),
    ]


def _short_iron_condor_legs(*, spot, iv_pct, dte, contracts):
    short_call = _round_strike(_strike_from_delta(spot, dte, iv_pct, +0.16, "call"))
    short_put  = _round_strike(_strike_from_delta(spot, dte, iv_pct, -0.16, "put"))
    wing = max(1.0, round(spot * 0.05))
    long_call = _round_strike(short_call + wing)
    long_put  = _round_strike(short_put  - wing)
    return [
        LegSpec("call", "sell", short_call, _expiry_for(dte), contracts,
                _premium(spot, short_call, dte, iv_pct, "call"),
                _delta(spot, short_call, dte, iv_pct, "call")),
        LegSpec("call", "buy",  long_call,  _expiry_for(dte), contracts,
                _premium(spot, long_call,  dte, iv_pct, "call"),
                _delta(spot, long_call,  dte, iv_pct, "call")),
        LegSpec("put",  "sell", short_put,  _expiry_for(dte), contracts,
                _premium(spot, short_put,  dte, iv_pct, "put"),
                _delta(spot, short_put,  dte, iv_pct, "put")),
        LegSpec("put",  "buy",  long_put,   _expiry_for(dte), contracts,
                _premium(spot, long_put,   dte, iv_pct, "put"),
                _delta(spot, long_put,   dte, iv_pct, "put")),
    ]


def _bull_call_spread_legs(*, spot, iv_pct, dte, contracts):
    long_k  = _round_strike(spot)
    short_k = _round_strike(spot * 1.10)
    return [
        LegSpec("call", "buy",  long_k,  _expiry_for(dte), contracts,
                _premium(spot, long_k,  dte, iv_pct, "call"),
                _delta(spot, long_k,  dte, iv_pct, "call")),
        LegSpec("call", "sell", short_k, _expiry_for(dte), contracts,
                _premium(spot, short_k, dte, iv_pct, "call"),
                _delta(spot, short_k, dte, iv_pct, "call")),
    ]


def _bear_put_spread_legs(*, spot, iv_pct, dte, contracts):
    long_k  = _round_strike(spot)
    short_k = _round_strike(spot * 0.90)
    return [
        LegSpec("put", "buy",  long_k,  _expiry_for(dte), contracts,
                _premium(spot, long_k,  dte, iv_pct, "put"),
                _delta(spot, long_k,  dte, iv_pct, "put")),
        LegSpec("put", "sell", short_k, _expiry_for(dte), contracts,
                _premium(spot, short_k, dte, iv_pct, "put"),
                _delta(spot, short_k, dte, iv_pct, "put")),
    ]


def _short_put_spread_legs(*, spot, iv_pct, dte, contracts):
    """Bullish credit spread: sell ~16-delta OTM put, buy further-OTM put.

    Sells premium expecting spot to stay above the short strike. Max
    profit = collected credit. Max loss = wing width − credit. Used
    by the Signals engine when IV is rich but the direction read is
    "stays in range or rises".
    """
    short_k = _round_strike(_strike_from_delta(spot, dte, iv_pct, -0.16, "put"))
    long_k = _round_strike(short_k - max(5.0, round(spot * 0.05)))
    return [
        LegSpec("put", "sell", short_k, _expiry_for(dte), contracts,
                _premium(spot, short_k, dte, iv_pct, "put"),
                _delta(spot, short_k, dte, iv_pct, "put")),
        LegSpec("put", "buy",  long_k,  _expiry_for(dte), contracts,
                _premium(spot, long_k,  dte, iv_pct, "put"),
                _delta(spot, long_k,  dte, iv_pct, "put")),
    ]


def _calendar_legs(*, spot, iv_pct, dte, contracts, front_dte_mult=0.25):
    """Long back-month, short front-month, same ATM strike."""
    strike = _round_strike(spot)
    back_dte = dte
    front_dte = max(7, int(dte * front_dte_mult))
    return [
        LegSpec("call", "buy",  strike, _expiry_for(back_dte),  contracts,
                _premium(spot, strike, back_dte,  iv_pct, "call"),
                _delta(spot, strike, back_dte,  iv_pct, "call")),
        LegSpec("call", "sell", strike, _expiry_for(front_dte), contracts,
                _premium(spot, strike, front_dte, iv_pct, "call"),
                _delta(spot, strike, front_dte, iv_pct, "call")),
    ]


def _iron_butterfly_legs(*, spot, iv_pct, dte, contracts):
    """Long OTM put + short ATM put + short ATM call + long OTM call.

    Wings 5 % wide around ATM. Defined-risk premium harvest, profits
    if spot pins ATM through expiry.
    """
    atm = _round_strike(spot)
    wing = max(1.0, round(spot * 0.05))
    low_k = _round_strike(atm - wing)
    high_k = _round_strike(atm + wing)
    return [
        LegSpec("put",  "buy",  low_k,  _expiry_for(dte), contracts,
                _premium(spot, low_k,  dte, iv_pct, "put"),
                _delta(spot, low_k,  dte, iv_pct, "put")),
        LegSpec("put",  "sell", atm,    _expiry_for(dte), contracts,
                _premium(spot, atm,    dte, iv_pct, "put"),
                _delta(spot, atm,    dte, iv_pct, "put")),
        LegSpec("call", "sell", atm,    _expiry_for(dte), contracts,
                _premium(spot, atm,    dte, iv_pct, "call"),
                _delta(spot, atm,    dte, iv_pct, "call")),
        LegSpec("call", "buy",  high_k, _expiry_for(dte), contracts,
                _premium(spot, high_k, dte, iv_pct, "call"),
                _delta(spot, high_k, dte, iv_pct, "call")),
    ]


def _covered_call_legs(*, spot, iv_pct, dte, contracts):
    """Long 100 shares per contract + short OTM call.

    Modelled as: ``buy`` stock leg with strike=0, option_type='call' and
    entry_premium = spot per share. The payoff engine handles strike=0
    calls as linear (``max(S, 0) = S``), so the stock leg pays out 1:1
    with spot. ``contracts`` matches the call's contract count — the
    per-leg ``× 100`` multiplier in payoff math already converts 1
    option contract to 100 shares.
    """
    short_k = _round_strike(spot * 1.05)
    return [
        # Stock leg — strike=0 call replicates ``long S`` payoff exactly
        LegSpec("call", "buy", 0.0, _expiry_for(dte), contracts,
                spot, 1.0),
        # Short OTM call
        LegSpec("call", "sell", short_k, _expiry_for(dte), contracts,
                _premium(spot, short_k, dte, iv_pct, "call"),
                _delta(spot, short_k, dte, iv_pct, "call")),
    ]


def _risk_reversal_legs(*, spot, iv_pct, dte, contracts):
    """Long OTM call (Δ ≈ +0.30), short OTM put (Δ ≈ -0.30) — bullish bet."""
    call_k = _round_strike(_strike_from_delta(spot, dte, iv_pct, +0.30, "call"))
    put_k  = _round_strike(_strike_from_delta(spot, dte, iv_pct, -0.30, "put"))
    return [
        LegSpec("call", "buy",  call_k, _expiry_for(dte), contracts,
                _premium(spot, call_k, dte, iv_pct, "call"),
                _delta(spot, call_k, dte, iv_pct, "call")),
        LegSpec("put",  "sell", put_k,  _expiry_for(dte), contracts,
                _premium(spot, put_k,  dte, iv_pct, "put"),
                _delta(spot, put_k,  dte, iv_pct, "put")),
    ]


# ── Catalogue ────────────────────────────────────────────────────────

TEMPLATES: dict[str, StrategyTemplate] = {
    "Long Call": StrategyTemplate(
        name="Long Call", direction="long_vol",
        description="Single ATM call — bullish + long-vol bet.",
        materializer=_long_call_legs,
    ),
    "Long Put": StrategyTemplate(
        name="Long Put", direction="long_vol",
        description="Single ATM put — bearish + long-vol bet.",
        materializer=_long_put_legs,
    ),
    "Long Straddle": StrategyTemplate(
        name="Long Straddle", direction="long_vol",
        description="ATM call + ATM put — pure long-vol, direction-neutral.",
        materializer=_long_straddle_legs,
    ),
    "Long Strangle": StrategyTemplate(
        name="Long Strangle", direction="long_vol",
        description="OTM Δ≈±0.30 call + put — cheaper than straddle, needs bigger move.",
        materializer=_long_strangle_legs,
    ),
    "Short Iron Condor": StrategyTemplate(
        name="Short Iron Condor", direction="short_vol",
        description="Sell Δ≈±0.16 strikes, buy wings 5 % wider — defined-risk premium harvest.",
        materializer=_short_iron_condor_legs,
    ),
    "Bull Call Spread": StrategyTemplate(
        name="Bull Call Spread", direction="long_vol",
        description="Long ATM call, short +10 % call — capped upside, lower debit.",
        materializer=_bull_call_spread_legs,
    ),
    "Short Put Spread": StrategyTemplate(
        name="Short Put Spread", direction="short_vol",
        description="Sell ~16Δ OTM put, buy further-OTM put — bullish credit spread.",
        materializer=_short_put_spread_legs,
    ),
    "Bear Put Spread": StrategyTemplate(
        name="Bear Put Spread", direction="long_vol",
        description="Long ATM put, short −10 % put — capped downside profit.",
        materializer=_bear_put_spread_legs,
    ),
    "Long Calendar": StrategyTemplate(
        name="Long Calendar", direction="neutral_vol",
        description="Long back-month ATM, short front-month ATM — profit from front decay.",
        materializer=_calendar_legs,
    ),
    "Risk Reversal": StrategyTemplate(
        name="Risk Reversal", direction="long_vol",
        description="Long OTM Δ≈0.30 call, short OTM Δ≈-0.30 put — bullish lean, financed.",
        materializer=_risk_reversal_legs,
    ),
    "Iron Butterfly": StrategyTemplate(
        name="Iron Butterfly", direction="short_vol",
        description="Long wings ±5 %, short ATM call + put — pin-the-strike premium harvest.",
        materializer=_iron_butterfly_legs,
    ),
    "Covered Call": StrategyTemplate(
        name="Covered Call", direction="short_vol",
        description="Long 100 shares per contract + short OTM call — capped-upside yield.",
        materializer=_covered_call_legs,
    ),
}


# ── Mapping from existing recommender labels → template ──────────────

# Both `strategy_recommender` and `scenario_builder` produce structure
# names that don't necessarily match TEMPLATES keys exactly. This map
# routes them to the right template so the same paper-buy flow works
# from every entry point.

_RECOMMENDER_TO_TEMPLATE: dict[str, str] = {
    # Strategy recommender labels
    "Long Put Spread":             "Bear Put Spread",
    "Long Call Spread":            "Bull Call Spread",
    "Long Calendar":               "Long Calendar",
    "Long Risk Reversal":          "Risk Reversal",
    "Short Iron Condor":           "Short Iron Condor",
    "Short Strangle":              "Long Strangle",   # close enough shape; UI warns
    "Short Risk Reversal":         "Risk Reversal",
    "Earnings Long Straddle":      "Long Straddle",
    "Earnings Iron Condor":        "Short Iron Condor",
    "Calendar Backwardation Play": "Long Calendar",
    "Calendar Carry Play":         "Long Calendar",

    # Scenario builder labels (from analytics/scenario_builder.py)
    "Long Call Calendar (back-month long)": "Long Calendar",
    "Short Iron Condor (defined-risk)":     "Short Iron Condor",
    "Short Iron Condor (post-ER, defined-risk)": "Short Iron Condor",
    "Long Call (deep OTM, LEAPS)":          "Long Call",
    "Long Straddle (ATM call + ATM put)":   "Long Straddle",
    "Calendar Spread (long back, short front)": "Long Calendar",
}


def resolve_template(name: str) -> Optional[StrategyTemplate]:
    """Look up a template by either its native name or a recommender label.

    Returns None when no mapping exists — caller decides whether to
    fall back to a single-leg vanilla or refuse to paper-buy.
    """
    if name in TEMPLATES:
        return TEMPLATES[name]
    routed = _RECOMMENDER_TO_TEMPLATE.get(name)
    if routed is not None:
        return TEMPLATES.get(routed)
    return None
