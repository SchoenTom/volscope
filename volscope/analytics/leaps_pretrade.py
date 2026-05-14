"""
Pre-trade execution checklist for LEAPS positions.

Four gates the trader must clear before clicking buy:

1. **Liquidity** — bid/ask spread, open interest, volume on the suggested
   contract. When live chain data is missing (today: ``options_snapshots``
   is empty) the gate degrades gracefully to a sector-rule fallback that
   uses the underlying's recent options activity from ``daily_vol``.
2. **Earnings blackout** — flag if next earnings is within ``blackout_days``;
   the post-earnings IV crush is part of the thesis but the user should
   know they are buying *before* a binary event.
3. **Data quality** — surface any STALE / SUSPECT / PARTIAL composite
   from :mod:`volscope.analytics.data_quality`.
4. **Order template** — broker-specific copy-paste string the user pastes
   into IBKR / Tastyworks / Trade Republic. No API calls.

Pure analytics, no DB writes. The dossier UI assembles a checklist row
per ``ChecklistRow`` and lights it green / amber / red.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from volscope.analytics.data_quality import composite_quality
from volscope.analytics.leaps_convergence import LeapsSuggestion


# ── Public dataclasses ───────────────────────────────────────────────────

@dataclass(frozen=True)
class ChecklistRow:
    """One row in the pre-trade checklist."""

    label:    str
    level:    str               # "GREEN" | "AMBER" | "RED" | "INFO"
    one_liner: str
    detail:   str = ""


@dataclass(frozen=True)
class PretradeChecklist:
    """Full pre-trade gate set for one suggestion + one source row."""

    ticker:           str
    rows:             tuple[ChecklistRow, ...]
    order_templates:  dict[str, str]
    blocked:          bool                 # True if any RED gate

    def green_count(self) -> int:
        return sum(1 for r in self.rows if r.level == "GREEN")


# ── Liquidity gate ───────────────────────────────────────────────────────

def evaluate_liquidity(
    suggestion: LeapsSuggestion,
    chain_row: Optional[pd.Series],
    underlying_row: Optional[pd.Series],
) -> ChecklistRow:
    """Decide if the suggested contract is tradeable.

    Two-tier evaluation:

    - If ``chain_row`` is non-None (a real ``options_snapshots`` row), use
      bid/ask/OI/volume directly. Spread ≤ 10 % mid + OI ≥ 100 + volume ≥ 50
      ⇒ GREEN. Any one missing ⇒ AMBER. Spread > 25 % mid ⇒ RED.
    - If chain data is unavailable, fall back to the underlying's options
      activity proxy from ``daily_vol`` (total_open_interest + put_call_ratio
      coverage). This is a sector-rule fallback — explicitly labelled as
      such in the one-liner so the user does not mistake it for a hard gate.
    """
    if chain_row is not None and not chain_row.empty:
        bid = float(chain_row.get("bid") or 0.0)
        ask = float(chain_row.get("ask") or 0.0)
        oi = int(chain_row.get("open_interest") or 0)
        vol = int(chain_row.get("volume") or 0)

        if bid <= 0 or ask <= 0:
            return ChecklistRow(
                label="Liquidity",
                level="RED",
                one_liner="no two-sided market — contract effectively untradeable",
            )

        mid = (bid + ask) / 2.0
        spread_pct = (ask - bid) / mid * 100.0 if mid > 0 else 100.0
        if spread_pct > 25.0:
            level = "RED"
        elif spread_pct > 10.0 or oi < 100 or vol < 50:
            level = "AMBER"
        else:
            level = "GREEN"
        return ChecklistRow(
            label="Liquidity",
            level=level,
            one_liner=f"spread {spread_pct:.1f}% · OI {oi} · vol {vol}",
            detail=(
                f"bid ${bid:.2f} · ask ${ask:.2f} · mid ${mid:.2f}"
            ),
        )

    # Sector-rule fallback — chain data missing.
    if underlying_row is not None and not underlying_row.empty:
        oi_total = underlying_row.get("total_open_interest")
        if oi_total is not None and not pd.isna(oi_total) and float(oi_total) >= 5_000:
            return ChecklistRow(
                label="Liquidity",
                level="AMBER",
                one_liner="no live chain — underlying options active",
                detail=(
                    "fallback rule: total OI on the chain ≥ 5 000. "
                    "Re-run after `make scrape-chains` for a hard read."
                ),
            )
    return ChecklistRow(
        label="Liquidity",
        level="AMBER",
        one_liner="no live chain — verify spread before lifting offer",
        detail=(
            "options_snapshots is empty for this ticker. The premium shown "
            "is a BSM model price; live ask may diverge by 20-50 %."
        ),
    )


# ── Earnings blackout ────────────────────────────────────────────────────

def evaluate_earnings_blackout(
    suggestion: LeapsSuggestion,
    next_earnings_date: Optional[date],
    today: Optional[date] = None,
    blackout_days: int = 7,
) -> ChecklistRow:
    """Flag binary-event proximity.

    The PYPL deck buys *after* earnings to capture the IV crush — i.e. the
    blackout is a *positive* setup, not a negative one. We surface it as
    INFO with explicit context rather than RED.
    """
    today = today or date.today()
    if next_earnings_date is None:
        return ChecklistRow(
            label="Earnings",
            level="INFO",
            one_liner="no scheduled earnings within tracked window",
        )
    delta = (next_earnings_date - today).days
    if delta < 0:
        return ChecklistRow(
            label="Earnings",
            level="INFO",
            one_liner=f"last earnings {abs(delta)}d ago — IV crush window open",
            detail=(
                "Buying within 4 weeks of earnings captures the post-event "
                "IV compression that makes the LEAPS cheap."
            ),
        )
    if delta <= blackout_days:
        return ChecklistRow(
            label="Earnings",
            level="AMBER",
            one_liner=f"earnings in {delta}d — binary event proximity",
            detail=(
                "Pre-earnings IV inflation will lift premium temporarily. "
                "Wait for the post-event crush unless you want directional "
                "exposure to the print."
            ),
        )
    if delta <= 30:
        return ChecklistRow(
            label="Earnings",
            level="INFO",
            one_liner=f"earnings in {delta}d — IV may inflate before",
        )
    return ChecklistRow(
        label="Earnings",
        level="GREEN",
        one_liner=f"earnings {delta}d out — clear runway",
    )


# ── Data quality ─────────────────────────────────────────────────────────

def evaluate_data_quality(
    underlying_row: pd.Series,
    history: Optional[pd.DataFrame] = None,
) -> ChecklistRow:
    """Lift the existing composite-quality report into a checklist row."""
    cq = composite_quality(underlying_row, history=history)
    level_map = {
        "OK":      "GREEN",
        "WARN":    "AMBER",
        "PARTIAL": "AMBER",
        "STALE":   "AMBER",
        "SUSPECT": "RED",
    }
    return ChecklistRow(
        label="Data quality",
        level=level_map.get(cq.overall_level, "AMBER"),
        one_liner=cq.one_liner,
        detail=f"composite level: {cq.overall_level}",
    )


# ── Order templates ──────────────────────────────────────────────────────

def build_order_templates(
    suggestion: LeapsSuggestion,
    contracts: int,
) -> dict[str, str]:
    """Build copy-pasteable order specs for the major retail brokers.

    Strings are deliberately structural — the user sees what to type
    rather than paying us to push an API request on their behalf.
    """
    expiry = suggestion.expiry.isoformat()
    strike = f"{suggestion.strike:.0f}"
    qty = max(1, contracts)
    return {
        "Interactive Brokers": (
            f"BUY {qty} {suggestion.ticker} {expiry} {strike} CALL "
            f"@ LIMIT {suggestion.est_premium:.2f}  (DAY, USD)"
        ),
        "Tastyworks": (
            f"BTO {qty} {suggestion.ticker} {expiry} {strike}C "
            f"@ {suggestion.est_premium:.2f}"
        ),
        "Trade Republic / Optionsschein": (
            f"Suche WKN für {suggestion.ticker} Call · Strike "
            f"${strike} · Laufzeit {expiry} · Hebel ~{1/max(0.01, suggestion.delta):.0f}× "
            f"· Aufgeld nicht über 10 %"
        ),
    }


# ── Orchestrator ─────────────────────────────────────────────────────────

def run_pretrade_checks(
    suggestion: LeapsSuggestion,
    underlying_row: pd.Series,
    history: Optional[pd.DataFrame] = None,
    chain_row: Optional[pd.Series] = None,
    next_earnings_date: Optional[date] = None,
    contracts: int = 1,
    today: Optional[date] = None,
) -> PretradeChecklist:
    """Run every gate and assemble the full checklist.

    The trader's mental model: "I'm not blocked unless something is RED.
    AMBER is a yellow light — proceed with eyes open. INFO is context."
    """
    rows = (
        evaluate_liquidity(suggestion, chain_row, underlying_row),
        evaluate_earnings_blackout(suggestion, next_earnings_date, today),
        evaluate_data_quality(underlying_row, history),
    )
    blocked = any(r.level == "RED" for r in rows)
    templates = build_order_templates(suggestion, contracts)
    return PretradeChecklist(
        ticker=suggestion.ticker,
        rows=rows,
        order_templates=templates,
        blocked=blocked,
    )
