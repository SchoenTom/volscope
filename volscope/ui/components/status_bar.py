"""
Status bar — Bloomberg-style one-row ticker summary.

Renders at the top of any ticker-specific page (Scope / Options Lab /
LEAPS Dossier) so the trader always sees:

    PYPL · $45.37  −1.95%    IV30 30.4  HV20 25.1  Rank 12  Perc 8  Spread +5.3  ER 28d

Six to eight inline data points, color-coded by regime. Designed to
look like the IBKR symbol bar that pins to the workspace top.
"""
from __future__ import annotations

from html import escape
from typing import Any, Optional

import pandas as pd

from volscope.ui.components.html_utils import render_html
from volscope.ui.components.sparkline import sparkline_svg
from volscope.ui.styles.theme import COLORS, seq_color


def _f(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
        if v != v:   # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


def render_status_bar(
    *,
    ticker: str,
    history: pd.DataFrame,
    company_name: Optional[str] = None,
    sector: Optional[str] = None,
    days_to_earnings: Optional[int] = None,
) -> None:
    """Inject the top-of-page status strip for ``ticker``.

    Reads the last row of ``history`` for current values and uses the
    20-day tail of ``iv_30d`` as a sparkline source. Any missing field
    is shown as ``—`` so partial-data tickers don't break the row.
    """
    import streamlit as st

    if history is None or history.empty:
        return
    latest = history.iloc[-1]
    prev = history.iloc[-2] if len(history) >= 2 else None

    spot = _f(latest.get("spot_price"))
    iv30 = _f(latest.get("iv_30d"))
    hv20 = _f(latest.get("hv_20d"))
    rank = _f(latest.get("iv_rank"))
    perc = _f(latest.get("iv_percentile"))

    chg = chg_pct = None
    if prev is not None:
        spot_prev = _f(prev.get("spot_price"))
        if spot is not None and spot_prev is not None and spot_prev > 0:
            chg = spot - spot_prev
            chg_pct = (chg / spot_prev) * 100.0

    spread = (iv30 - hv20) if (iv30 is not None and hv20 is not None) else None
    iv_series = (
        history["iv_30d"].dropna().tail(20).tolist()
        if "iv_30d" in history.columns else []
    )
    spark = sparkline_svg(iv_series, width=58, height=14) if iv_series else ""

    # Color encoding for the deltas
    chg_color = (
        COLORS["accent"] if (chg or 0) >= 0
        else COLORS["warn"]
    )
    perc_bg = seq_color(perc, 0, 100) if perc is not None else COLORS["border"]
    rank_bg = seq_color(rank, 0, 100) if rank is not None else COLORS["border"]
    spread_color = (
        COLORS["warn"] if (spread or 0) > 0
        else COLORS["accent"] if (spread or 0) < 0
        else COLORS["muted"]
    )
    er_pill = ""
    if days_to_earnings is not None:
        if 0 <= days_to_earnings <= 7:
            er_color = COLORS["warn"]
            er_label = f"ER {days_to_earnings}d"
        elif days_to_earnings < 0:
            er_color = COLORS["amber"]
            er_label = f"post-ER {abs(days_to_earnings)}d"
        elif days_to_earnings <= 30:
            er_color = COLORS["amber"]
            er_label = f"ER {days_to_earnings}d"
        else:
            er_color = COLORS["label"]
            er_label = f"ER {days_to_earnings}d"
        er_pill = (
            f'<span class="vs-status-pill" style="color:{er_color};'
            f'border-color:{er_color}55;">{er_label}</span>'
        )

    def _fmt(v: Optional[float], suffix: str = "", precision: int = 1,
             signed: bool = False) -> str:
        if v is None:
            return "—"
        if signed:
            sign = "+" if v >= 0 else "−"
            return f"{sign}{abs(v):.{precision}f}{suffix}"
        return f"{v:.{precision}f}{suffix}"

    company_html = (
        f'<span class="vs-status-company">{escape(company_name)}</span>'
        if company_name else ""
    )
    sector_html = (
        f'<span class="vs-status-sector">{escape(sector)}</span>'
        if sector else ""
    )

    html = f'''
<div class="vs-status-bar">
  <div class="vs-status-left">
    <span class="vs-status-symbol">◈ {escape(ticker)}</span>
    {company_html}
    <span class="vs-status-spot">${spot:,.2f}</span>
    <span class="vs-status-chg" style="color:{chg_color};">
        {_fmt(chg, signed=True, precision=2)}
        {f"({_fmt(chg_pct, suffix='%', signed=True, precision=2)})" if chg_pct is not None else ""}
    </span>
  </div>
  <div class="vs-status-mid">
    <span class="vs-status-cell">
      <span class="vs-status-label">IV30</span>
      <span class="vs-status-val" style="color:{COLORS['accent']};">{_fmt(iv30, suffix='%')}</span>
    </span>
    <span class="vs-status-cell">
      <span class="vs-status-label">HV20</span>
      <span class="vs-status-val" style="color:{COLORS['accent2']};">{_fmt(hv20, suffix='%')}</span>
    </span>
    <span class="vs-status-cell" title="IV Rank — where current IV sits in its 52-week range (0 = lowest, 100 = highest)">
      <span class="vs-status-label">RANK</span>
      <span class="vs-status-val" style="background:{rank_bg};color:#0a0b0f;
            padding:1px 5px;border-radius:3px;font-weight:700;">
        {_fmt(rank, precision=0)}
      </span>
    </span>
    <span class="vs-status-cell" title="IV Percentile — % of the last year IV was below today's level">
      <span class="vs-status-label">PERC</span>
      <span class="vs-status-val" style="background:{perc_bg};color:#0a0b0f;
            padding:1px 5px;border-radius:3px;font-weight:700;">
        {_fmt(perc, precision=0)}
      </span>
    </span>
    <span class="vs-status-cell" title="IV minus realized vol (the volatility risk premium)">
      <span class="vs-status-label">SPREAD</span>
      <span class="vs-status-val" style="color:{spread_color};">
        {_fmt(spread, suffix='pt', signed=True)}
      </span>
    </span>
  </div>
  <div class="vs-status-right">
    <span class="vs-status-spark">{spark}</span>
    {er_pill}
    {sector_html}
  </div>
</div>'''
    render_html(st, html)
