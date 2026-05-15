"""
Persistent regime header — 32 px strip mounted on the top-traffic
pages so the operator always knows the global vol state.

Anatomy
=======
| REGIME chip | SIGNAL | VIX | MEDIAN IVR | (right-aligned data freshness) |

The regime chip is colour-coded:
  • VOL_CRUSHED → cyan-green (#00d4aa)
  • VOL_CHEAP   → emerald   (#10b981)
  • VOL_FAIR    → blue      (#5b8cff)
  • VOL_RICH    → amber     (#ff9f43)
  • VOL_EXTREME → red       (#ff4466)
  • VOL_CRISIS  → deep red  (#dc2626)
  • unknown / no data → muted grey

Signals are derived from the regime via a stable lookup table and
mirror the v0.9.0 vol-regime taxonomy (Gelato-extraction adaptation).

Pure presentation — no DB writes, no side-effects beyond rendering.
Mount via ``render_regime_header(db)`` near the top of each high-
traffic page.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from volscope.data.database import VolScopeDB
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"

_REGIME_CONFIG = {
    "VOL_CRUSHED": (COLORS["accent"],  "LONG VEGA · debit spreads / LEAPS"),
    "VOL_CHEAP":   ("#10b981",          "BIAS LONG VEGA"),
    "VOL_FAIR":    (COLORS["accent2"], "NEUTRAL · scalp"),
    "VOL_RICH":    (COLORS["amber"],    "BIAS SHORT VEGA"),
    "VOL_EXTREME": (COLORS["warn"],     "SHORT VEGA · iron condors / strangles"),
    "VOL_CRISIS":  ("#dc2626",          "DEFENSIVE / CASH"),
    None:          (COLORS["muted"],    "no regime data"),
}


def _broad_market_regime(latest: pd.DataFrame) -> str:
    """Pick the broad-market regime from SPY (or fall back to the
    median across index ETFs in the latest snapshot).
    """
    for proxy in ("SPY", "^GSPC", "QQQ", "^NDX"):
        row = latest[latest["ticker"] == proxy]
        if not row.empty:
            r = row.iloc[0].get("vol_regime")
            if isinstance(r, str) and r:
                return r
    # Fallback — modal regime across the whole universe.
    if "vol_regime" in latest.columns:
        modes = latest["vol_regime"].dropna()
        if not modes.empty:
            return str(modes.mode().iloc[0])
    return ""


def render_regime_header(db: VolScopeDB) -> None:
    """Render the persistent regime / signal / VIX / IVR strip.

    Layout is HTML-only (no Streamlit widgets) so it adds zero
    rerun cost. Reads:
      • The latest snapshot via ``db.get_all_latest()`` (already
        cached by the caller pages' v0.6.2 ``get_all_latest_cached``).
      • The latest VIX level from ``daily_vol`` for ``^VIX``.

    Failures are silent — the bar simply renders empty hyphens rather
    than crash the page header.
    """
    # v0.9.2 perf: route through the cached helper so the 32-px
    # header strip on Command / Discover / Scope / Pre-Trade / Bot
    # doesn't refetch the full universe snapshot on every page rerun.
    try:
        from volscope.ui.components.cached_data import (
            get_all_latest_cached, make_cache_key,
        )
        latest = get_all_latest_cached(make_cache_key(db), db)
    except Exception:                                          # noqa: BLE001
        latest = pd.DataFrame()

    # Regime + signal lookup.
    regime = _broad_market_regime(latest) if not latest.empty else ""
    color, signal = _REGIME_CONFIG.get(regime, _REGIME_CONFIG[None])

    # VIX level — most recent close.
    vix_str = "—"
    try:
        vix_hist = db.get_ticker_history("^VIX")
        if vix_hist is not None and not vix_hist.empty:
            vix = pd.to_numeric(vix_hist["spot_price"], errors="coerce").dropna()
            if not vix.empty:
                vix_str = f"{float(vix.iloc[-1]):.1f}"
    except Exception:                                          # noqa: BLE001
        pass

    # Median IVR across the universe.
    ivr_str = "—"
    if "iv_rank" in latest.columns:
        ivr = pd.to_numeric(latest["iv_rank"], errors="coerce").dropna()
        if not ivr.empty:
            ivr_str = f"{float(ivr.median()):.0f}"

    # Snapshot freshness (last scrape).
    snap_str = "—"
    try:
        last = db.get_last_scrape_date()
        if last is not None:
            snap_str = last.isoformat()
    except Exception:                                          # noqa: BLE001
        pass

    regime_display = regime.replace("_", " ") if regime else "—"

    render_html(
        st_target := __import__("streamlit"),
        f'<div style="display:flex;align-items:center;gap:14px;'
        f'padding:6px 12px;margin:0 0 12px 0;'
        f'background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-left:3px solid {color};border-radius:6px;'
        f'font-family:\'DM Sans\',sans-serif;font-size:12px;'
        f'min-height:32px;">'

        # Regime chip
        f'<span style="background:{color}1a;color:{color};'
        f'border:1px solid {color}55;padding:3px 10px;border-radius:4px;'
        f'font-family:{_MONO};font-size:11px;font-weight:700;'
        f'letter-spacing:0.04em;">{regime_display}</span>'

        # Signal text
        f'<span style="color:{COLORS["text"]};">{signal}</span>'

        # Right-aligned strip: VIX / IVR / freshness
        f'<span style="margin-left:auto;color:{COLORS["muted"]};'
        f'font-family:{_MONO};font-size:11px;'
        f'font-variant-numeric:tabular-nums;">'
        f'VIX <span style="color:{COLORS["text"]};font-weight:600;">{vix_str}</span>'
        f'<span style="margin:0 8px;color:{COLORS["border"]};">·</span>'
        f'Univ IVR <span style="color:{COLORS["text"]};font-weight:600;">{ivr_str}</span>'
        f'<span style="margin:0 8px;color:{COLORS["border"]};">·</span>'
        f'<span style="color:{COLORS["muted"]};">last scrape {snap_str}</span>'
        f'</span>'
        f'</div>',
    )
