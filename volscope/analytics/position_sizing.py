"""
Position Sizing Calculator — signal-based lot sizing with rough vega P&L estimate.

Answers the trader's follow-up question after seeing a BUY signal:
"OK, but *how much* should I put on, and what's my rough P&L if IV moves?"

For Tom's instruments (long-dated DAX/Nasdaq puts, MSTR/SNOW knock-outs) the
dominant risk driver is vega — IV level at entry relative to current IV.
The P&L estimate uses a first-order vega approximation valid for ATM options:

    rough_pnl_pct ≈ (IV_current − IV_entry) / IV_entry × 100 %

This means: if you entered when IV was 25% and it is now 28%, the option
premium has risen by roughly (28−25)/25×100 = 12%.  It is an approximation
(ignores theta, skew, gamma), so we label it "rough estimate" throughout.

Dependencies: none beyond standard lib + dataclasses.
No network access, no DB access — pure function.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from volscope.ui.styles.theme import COLORS


# ── Signal categories known to the system ────────────────────────────────────
# Mirrors the category strings produced by volscope.analytics.signal.compute_signal().
# Defined here so position_sizing is self-contained and testable without signal.py.
ALL_SIGNAL_CATEGORIES: tuple[str, ...] = (
    "buy",
    "lean_buy",
    "neutral",
    "lean_rich",
    "rich",
    "no_data",
)


# ── Sizing rules ──────────────────────────────────────────────────────────────

SIZE_MULTIPLIERS: dict[str, float] = {
    "buy":       1.00,   # Strong BUY  → full intended allocation
    "lean_buy":  0.50,   # Lean BUY   → half size (lower conviction)
    "neutral":   0.00,   # WAIT       → no position
    "lean_rich": 0.00,   # Lean RICH  → no position (avoid buying expensive vol)
    "rich":      0.00,   # RICH       → no position
    "no_data":   0.00,   # No data    → no position (can't assess risk)
}

SIZE_LABELS: dict[str, str] = {
    "buy":       "Full position",
    "lean_buy":  "Half position",
    "neutral":   "No position — wait",
    "lean_rich": "No position — vol expensive",
    "rich":      "No position — vol expensive",
    "no_data":   "No position — no data",
}

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SizingResult:
    """
    Immutable sizing recommendation for a single ticker + signal.

    Attributes
    ----------
    signal_category    : VolSignal category string (e.g. "buy", "lean_buy").
    size_multiplier    : Fraction of max_allocation to deploy (0.0–1.0).
    size_label         : Human-readable sizing advice.
    max_allocation     : User's intended maximum allocation (USD).
    suggested_allocation : max_allocation × size_multiplier (USD).
    entry_iv           : IV at entry (%) — None when no trade journal entry.
    current_iv         : IV right now (%) — None when DB has no data.
    iv_change_pp       : current_iv − entry_iv in percentage-point terms.
                         Positive = IV rose (good for long-vol buyer).
    rough_pnl_pct      : Approx % change in option premium since entry.
                         Formula: iv_change_pp / entry_iv × 100.
    rough_pnl_usd      : rough_pnl_pct / 100 × suggested_allocation (USD).
    """

    signal_category:     str
    size_multiplier:     float
    size_label:          str
    max_allocation:      float
    suggested_allocation: float
    entry_iv:            Optional[float]
    current_iv:          Optional[float]
    iv_change_pp:        Optional[float]
    rough_pnl_pct:       Optional[float]
    rough_pnl_usd:       Optional[float]


# ── Core computation ──────────────────────────────────────────────────────────

def compute_sizing(
    signal_category: str,
    max_allocation: float,
    entry_iv: Optional[float] = None,
    current_iv: Optional[float] = None,
) -> SizingResult:
    """
    Compute a position sizing recommendation from a signal category.

    Parameters
    ----------
    signal_category : VolSignal.category string.
                      Unknown categories map to zero allocation.
    max_allocation  : Maximum intended position size (USD).
    entry_iv        : IV at trade entry (%, e.g. 25.0). Optional — only used
                      to compute the vega P&L estimate.
    current_iv      : Current IV (%, e.g. 28.0). Optional — same as above.

    Returns
    -------
    SizingResult
        Immutable result.  Never raises.
    """
    multiplier       = SIZE_MULTIPLIERS.get(signal_category, 0.0)
    label            = SIZE_LABELS.get(signal_category, "No position")
    suggested        = max_allocation * multiplier

    iv_change_pp: Optional[float]  = None
    rough_pnl_pct: Optional[float] = None
    rough_pnl_usd: Optional[float] = None

    # Vega P&L estimate — only when both IVs are valid and entry is positive
    entry_ok   = _valid(entry_iv) and entry_iv > 0  # type: ignore[operator]
    current_ok = _valid(current_iv)

    if entry_ok and current_ok:
        iv_change_pp  = float(current_iv) - float(entry_iv)  # type: ignore[arg-type]
        rough_pnl_pct = iv_change_pp / float(entry_iv) * 100.0  # type: ignore[arg-type]
        rough_pnl_usd = rough_pnl_pct / 100.0 * suggested

    return SizingResult(
        signal_category=signal_category,
        size_multiplier=multiplier,
        size_label=label,
        max_allocation=max_allocation,
        suggested_allocation=suggested,
        entry_iv=float(entry_iv) if _valid(entry_iv) else None,  # type: ignore[arg-type]
        current_iv=float(current_iv) if _valid(current_iv) else None,  # type: ignore[arg-type]
        iv_change_pp=iv_change_pp,
        rough_pnl_pct=rough_pnl_pct,
        rough_pnl_usd=rough_pnl_usd,
    )


# ── HTML display ──────────────────────────────────────────────────────────────

def sizing_summary_html(result: Optional[SizingResult]) -> str:
    """
    Compact HTML summary for a single SizingResult.

    Designed to sit inside the Position Sizer expander on the Command Center.
    Returns empty string when result is None (safe to concatenate).

    Layout:
        SIZE LABEL             SUGGESTED ALLOCATION
        ──────────────────── · ────────────────────
        [P&L estimate row — only when IV data available]

    Color coding:
        BUY / LEAN BUY  → green   (accent)
        WAIT            → muted   (no position)
        RICH / LEAN RICH → red    (warn)
    """
    if result is None:
        return ""

    # Signal color
    cat = result.signal_category
    if cat in ("buy", "lean_buy"):
        color = COLORS["accent"]
    elif cat in ("rich", "lean_rich"):
        color = COLORS["warn"]
    else:
        color = COLORS["muted"]

    # Suggested allocation string
    if result.suggested_allocation > 0:
        alloc_str = f"${result.suggested_allocation:,.0f}"
    else:
        alloc_str = "—"

    # P&L row
    pnl_html = ""
    if result.rough_pnl_pct is not None and result.rough_pnl_usd is not None:
        pnl_color = COLORS["accent"] if result.rough_pnl_pct >= 0 else COLORS["warn"]
        sign      = "+" if result.rough_pnl_pct >= 0 else ""
        minus     = "−" if result.rough_pnl_pct < 0 else ""
        abs_pnl   = abs(result.rough_pnl_usd)
        pnl_html  = (
            f'<div style="margin-top:6px;font-family:{_MONO};font-size:10px;">'
            f'<span style="color:{COLORS["muted"]};">Entry IV {result.entry_iv:.1f}%  →  '
            f'Now {result.current_iv:.1f}%'
            f'  ({sign}{result.iv_change_pp:+.1f}pp)</span>'  # type: ignore[arg-type]
            f'&nbsp;&nbsp;'
            f'<span style="color:{pnl_color};font-weight:600;">'
            f'Est. P&amp;L {minus}${abs_pnl:,.0f} ({sign}{result.rough_pnl_pct:.1f}%)</span>'
            f'</div>'
        )

    return (
        f'<div style="padding:8px 0;">'
        f'<div style="display:flex;align-items:baseline;justify-content:space-between;'
        f'gap:12px;">'
        f'<span style="font-family:{_MONO};font-size:11px;color:{color};font-weight:600;">'
        f'{result.size_label}</span>'
        f'<span style="font-family:{_MONO};font-size:13px;font-weight:700;'
        f'color:{color if result.suggested_allocation > 0 else COLORS["muted"]};">'
        f'{alloc_str}</span>'
        f'</div>'
        f'{pnl_html}'
        f'</div>'
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid(v: object) -> bool:
    """Return True if v is a finite, non-None number."""
    if v is None:
        return False
    try:
        f = float(v)  # type: ignore[arg-type]
        return not (math.isnan(f) or math.isinf(f))
    except (TypeError, ValueError):
        return False
