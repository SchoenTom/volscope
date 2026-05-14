"""
Vol Signal — combined IV-percentile + VRP buy/wait/rich signal.

Answers the core question in one badge: "buy vol now, or wait?"

Two independent signals are combined:
  1. IV Percentile — is this vol historically cheap relative to its own
     past year? (percentile rank in [0, 100])
  2. VRP = iv_30d / hv_20d — are options priced above or below realized vol?
     VRP < 1 means options are cheap vs what the stock actually moved.

When both agree the signal is STRONG. When only one agrees it is a LEAN.
When they disagree or neither fires the signal is WAIT (neutral).

This module has zero UI dependencies — import freely from analytics,
data, or test code without pulling in Streamlit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# ── Signal thresholds ──────────────────────────────────────────────────────
# Calibrated for a long-vol buyer perspective (DAX/Nasdaq puts, knock-outs).
# The user wants to *buy* cheap vol, so cheap signals are the actionable ones.

_PERC_BUY_STRONG  = 25.0   # both signals need perc below this for STRONG BUY
_PERC_BUY_LEAN    = 35.0   # solo perc signal needs to be below this
_PERC_RICH_LEAN   = 65.0   # solo perc signal needs to be above this
_PERC_RICH_STRONG = 75.0   # both signals need perc above this for STRONG RICH

_VRP_BUY_STRONG   = 0.95   # options < 95% of realized → cheap vs realized
_VRP_BUY_LEAN     = 1.00   # options below realized (any discount)
_VRP_RICH_LEAN    = 1.00   # options above realized (any premium)
_VRP_RICH_STRONG  = 1.05   # options > 105% of realized → rich vs realized


@dataclass(frozen=True)
class VolSignal:
    """
    Immutable trading signal combining IV percentile and VRP.

    Attributes
    ----------
    label    : Human-readable label.
               One of: "BUY VOL" | "LEAN BUY" | "WAIT" |
                        "LEAN RICH" | "RICH" | "NO DATA"
    category : Machine-readable category for color mapping.
               One of: "buy" | "lean_buy" | "neutral" |
                        "lean_rich" | "rich" | "no_data"
    strong   : True when BOTH percentile and VRP agree — higher conviction.
    reason   : One-line explanation shown under the badge (e.g.
               "perc 18 · VRP 0.87× — both signals cheap").
    """

    label:    str
    category: str
    strong:   bool
    reason:   str


def _safe_float(v: object) -> Optional[float]:
    """Return float(v) if valid and finite, else None."""
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def compute_signal(
    iv_percentile: object,
    iv_30d: object,
    hv_20d: object,
) -> VolSignal:
    """
    Compute a buy/wait/rich signal from IV percentile and VRP.

    Parameters
    ----------
    iv_percentile : float-like | None
        IV percentile in [0, 100].  Low = historically cheap.
    iv_30d : float-like | None
        30-day ATM implied volatility in percent.
    hv_20d : float-like | None
        20-day historical (realized) volatility in percent.

    Returns
    -------
    VolSignal
        Immutable signal object.  Never raises.
    """
    perc = _safe_float(iv_percentile)
    iv   = _safe_float(iv_30d)
    hv   = _safe_float(hv_20d)

    if perc is None or iv is None or hv is None or hv <= 0:
        return VolSignal(
            label="NO DATA",
            category="no_data",
            strong=False,
            reason="insufficient data",
        )

    vrp = iv / hv

    # Boolean flags for threshold crossings
    perc_cheap      = perc < _PERC_BUY_STRONG
    perc_lean_cheap = perc < _PERC_BUY_LEAN
    perc_rich       = perc > _PERC_RICH_STRONG
    perc_lean_rich  = perc > _PERC_RICH_LEAN

    vrp_cheap      = vrp < _VRP_BUY_STRONG
    vrp_lean_cheap = vrp < _VRP_BUY_LEAN
    vrp_rich       = vrp > _VRP_RICH_STRONG
    vrp_lean_rich  = vrp > _VRP_RICH_LEAN

    # ── BUY signals ─────────────────────────────────────────────────────
    # Strong BUY: both signals agree it's cheap
    if perc_cheap and vrp_cheap:
        return VolSignal(
            label="BUY VOL",
            category="buy",
            strong=True,
            reason=f"perc {perc:.0f} · VRP {vrp:.2f}× — both signals cheap",
        )

    # Lean BUY variant A: one signal strongly cheap, other not pushing rich
    if perc_cheap and not vrp_lean_rich:
        return VolSignal(
            label="LEAN BUY",
            category="lean_buy",
            strong=False,
            reason=f"perc {perc:.0f} — historically cheap",
        )
    if vrp_cheap and not perc_lean_rich:
        return VolSignal(
            label="LEAN BUY",
            category="lean_buy",
            strong=False,
            reason=f"VRP {vrp:.2f}× — cheap vs realized",
        )

    # Lean BUY variant B: both signals mildly cheap
    if perc_lean_cheap and vrp_lean_cheap:
        return VolSignal(
            label="LEAN BUY",
            category="lean_buy",
            strong=False,
            reason=f"perc {perc:.0f} · VRP {vrp:.2f}× — mildly cheap",
        )

    # ── RICH signals ─────────────────────────────────────────────────────
    # Strong RICH: both signals agree it's expensive
    if perc_rich and vrp_rich:
        return VolSignal(
            label="RICH",
            category="rich",
            strong=True,
            reason=f"perc {perc:.0f} · VRP {vrp:.2f}× — both signals rich",
        )

    # Lean RICH variant A: one signal strongly rich, other not pushing cheap
    if perc_rich and not vrp_lean_cheap:
        return VolSignal(
            label="LEAN RICH",
            category="lean_rich",
            strong=False,
            reason=f"perc {perc:.0f} — historically expensive",
        )
    if vrp_rich and not perc_lean_cheap:
        return VolSignal(
            label="LEAN RICH",
            category="lean_rich",
            strong=False,
            reason=f"VRP {vrp:.2f}× — expensive vs realized",
        )

    # Lean RICH variant B: both signals mildly rich
    if perc_lean_rich and vrp_lean_rich:
        return VolSignal(
            label="LEAN RICH",
            category="lean_rich",
            strong=False,
            reason=f"perc {perc:.0f} · VRP {vrp:.2f}× — mildly rich",
        )

    # ── Neutral ──────────────────────────────────────────────────────────
    return VolSignal(
        label="WAIT",
        category="neutral",
        strong=False,
        reason=f"perc {perc:.0f} · VRP {vrp:.2f}× — mixed or neutral",
    )


def market_summary(signals: list[VolSignal]) -> str:
    """
    One-sentence summary of the signal distribution across multiple tickers.

    Returns a plain string suitable for rendering as a subheading,
    e.g. "3 of 4 positions cheap · consider sizing up".
    Empty string if `signals` is empty.
    """
    if not signals:
        return ""

    data_signals = [s for s in signals if s.category != "no_data"]
    if not data_signals:
        return "No vol data — run make scrape to populate your positions"

    buy_count  = sum(1 for s in data_signals if s.category in ("buy", "lean_buy"))
    rich_count = sum(1 for s in data_signals if s.category in ("rich", "lean_rich"))
    total      = len(data_signals)

    strong_buys = sum(1 for s in data_signals if s.category == "buy")

    if strong_buys == total:
        return f"All {total} positions strongly cheap — strong buy signal across the board"
    if buy_count >= math.ceil(total * 0.75):
        verb = "strongly " if strong_buys >= buy_count // 2 else ""
        return f"{buy_count} of {total} positions {verb}cheap · consider sizing up"
    if rich_count >= math.ceil(total * 0.75):
        return f"{rich_count} of {total} positions rich · wait for vol to fall"
    if buy_count > rich_count:
        return f"{buy_count} cheap · {rich_count} rich · bias toward buying"
    if rich_count > buy_count:
        return f"{rich_count} rich · {buy_count} cheap · wait for better entry"
    return "Signals mixed across your positions"
