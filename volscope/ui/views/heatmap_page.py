"""
Heatmap — universe-wide IV view as a TradingView-style treemap.

v0.8.0 redesign — replaced the naive 20-col grid heatmap with a
proper sector-rectangle treemap (``plotly.graph_objects.Treemap``).

  • Rectangles are tickers.
  • Parent rectangles are sectors (collapse / drill-in supported by
    Plotly's native treemap path-navigation).
  • Rectangle SIZE is total option open-interest — the same
    universe-relevance signal TradingView uses for market-cap.
    Tickers with deeper option markets get more visual real-estate,
    which is the correct prioritisation for a vol research tool.
  • Rectangle COLOR is IV percentile on a continuous green→red
    gradient (cheap → rich).
  • Time-range selector switches the colour metric: latest IV pct
    (default), 1-week change, 1-month change. Operators see "what
    moved this week" at a glance — the original snapshot-only chart
    couldn't.

Click a rectangle to drill in (Plotly path) or select it and the
ticker-jump selectbox in the controls strip will route to Scope.
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from volscope.data.database import VolScopeDB
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"
_SANS = "DM Sans, Inter, system-ui, sans-serif"

_COLLAPSE_THRESHOLD = 100  # legacy threshold — kept for the "sector medians" toggle


def _percentile_color(pct: Optional[float]) -> str:
    """Map iv_percentile (0–100) to a hex color on a green→amber→red gradient."""
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        return COLORS.get("border", "#2a2d3e")
    p = max(0.0, min(100.0, float(pct)))
    if p < 20:
        return "#00d4aa"   # cheap — green
    if p < 40:
        return "#5bc8b0"   # below normal
    if p < 60:
        return "#8a8f9e"   # neutral — muted
    if p < 80:
        return "#ff9f43"   # above normal — amber
    return "#ff4466"       # rich — red


def _build_treemap_figure(
    df: pd.DataFrame,
    *,
    color_metric: str = "iv_percentile",
    color_range: tuple[float, float] = (0.0, 100.0),
) -> go.Figure:
    """TradingView-style sector treemap.

    Parameters
    ----------
    df
        ``daily_vol`` latest-snapshot frame with columns
        ``ticker``, ``sector``, ``iv_30d``, ``iv_percentile``,
        ``hv_20d`` (or ``hv_yz_30d``), ``total_open_interest``.
    color_metric
        Column to drive the rectangle colour. Default is
        ``iv_percentile`` (0-100); also accepts ``iv_change_1d`` or
        ``iv_change_30d`` for change-mode heatmaps where the
        gradient is symmetric around zero.
    color_range
        ``(cmin, cmax)`` for the colour scale.
    """
    if df.empty:
        return go.Figure().update_layout(
            paper_bgcolor=COLORS["bg"],
            plot_bgcolor=COLORS["bg"],
            height=200,
        )

    working = df.copy()
    if "sector" not in working.columns or working["sector"].isna().all():
        working["sector"] = "Unknown"
    working["sector"] = working["sector"].fillna("Unknown")

    # Rectangle size — prefer total OI (the relevance signal for a
    # vol-research tool: deeper option markets = more important).
    # Fall back to constant=1 if OI missing.
    if "total_open_interest" in working.columns:
        size_raw = working["total_open_interest"].fillna(0.0).clip(lower=0.0)
        # Add 1 so zero-OI rows still get *some* area (otherwise treemap
        # collapses them out entirely).
        working["_size"] = size_raw + 1.0
    else:
        working["_size"] = 1.0

    # Colour metric — clip + fill NaN to a neutral midpoint so missing
    # data doesn't get a bright red / green by accident.
    if color_metric in working.columns:
        cmin, cmax = color_range
        working["_color"] = (
            pd.to_numeric(working[color_metric], errors="coerce")
            .fillna((cmin + cmax) / 2.0)
            .clip(lower=cmin, upper=cmax)
        )
    else:
        working["_color"] = 50.0

    # Hover text — pack the headline numbers a vol trader cares about.
    def _fmt(v, suffix: str = "%", digits: int = 1) -> str:
        try:
            f = float(v)
            if pd.isna(f):
                return "—"
            return f"{f:.{digits}f}{suffix}"
        except (TypeError, ValueError):
            return "—"

    hover = []
    for _, row in working.iterrows():
        iv      = _fmt(row.get("iv_30d"))
        # Prefer matched-horizon Yang-Zhang HV30 (v0.7.1); fall back to CC HV20.
        hv      = _fmt(row.get("hv_yz_30d") or row.get("hv_20d"))
        perc    = _fmt(row.get("iv_percentile"), suffix="", digits=0)
        spread  = _fmt(row.get("iv_hv_spread_matched") or row.get("iv_hv_spread"),
                        suffix="", digits=1)
        oi      = row.get("total_open_interest")
        oi_str  = f"{int(oi):,}" if oi is not None and not pd.isna(oi) else "—"
        chg1d   = _fmt(row.get("iv_change_1d"), suffix="", digits=1)
        chg30d  = _fmt(row.get("iv_change_30d"), suffix="", digits=1)
        hover.append(
            f"<b>{row['ticker']}</b><br>"
            f"Sector: {row['sector']}<br>"
            f"IV 30d: {iv}<br>"
            f"HV: {hv}<br>"
            f"IV − HV: {spread}<br>"
            f"IV Percentile: {perc}<br>"
            f"OI: {oi_str}<br>"
            f"Δ1d: {chg1d} · Δ30d: {chg30d}"
        )
    working["_hover"] = hover

    # Use the existing per-percentile palette for the diverging IV-percentile
    # case; for symmetric change-mode use a red→neutral→green scale.
    is_change_mode = color_metric in ("iv_change_1d", "iv_change_30d")
    if is_change_mode:
        # Symmetric around zero: red = IV up (rich getting richer or
        # cheap getting expensive), green = IV down.
        colorscale = [
            [0.0, "#00d4aa"], [0.25, "#5bc8b0"], [0.5, "#8a8f9e"],
            [0.75, "#ff9f43"], [1.0, "#ff4466"],
        ]
        cmid = 0.0
        # Determine bounds dynamically — change-mode bounds are not 0..100.
        chg = working["_color"].abs()
        bound = max(5.0, float(chg.quantile(0.95)))
        color_range = (-bound, bound)
        working["_color"] = working["_color"].clip(-bound, bound)
        colorbar_title = (
            "Δ IV (1d)" if color_metric == "iv_change_1d" else "Δ IV (30d)"
        )
    else:
        colorscale = [
            [0.00, "#00d4aa"], [0.20, "#5bc8b0"], [0.50, "#8a8f9e"],
            [0.80, "#ff9f43"], [1.00, "#ff4466"],
        ]
        cmid = None
        colorbar_title = "IV Percentile"

    fig = go.Figure(
        go.Treemap(
            labels=working["ticker"].tolist(),
            parents=working["sector"].tolist(),
            values=working["_size"].tolist(),
            branchvalues="total",
            marker=dict(
                colors=working["_color"].tolist(),
                colorscale=colorscale,
                cmin=color_range[0],
                cmax=color_range[1],
                cmid=cmid,
                line=dict(width=1, color=COLORS["bg"]),
                colorbar=dict(
                    title=dict(
                        text=colorbar_title,
                        font=dict(family=_SANS, size=11, color=COLORS["muted"]),
                    ),
                    thickness=8,
                    len=0.55,
                    x=1.0,
                    xanchor="right",
                    tickfont=dict(family=_MONO, size=9, color=COLORS["muted"]),
                ),
            ),
            text=working["ticker"].tolist(),
            customdata=working["_hover"].tolist(),
            hovertemplate="%{customdata}<extra></extra>",
            textfont=dict(family=_MONO, size=11, color="#0a0b14"),
            tiling=dict(packing="squarify", pad=2),
            pathbar=dict(
                visible=True,
                side="top",
                thickness=22,
                textfont=dict(family=_SANS, size=12, color=COLORS["text"]),
            ),
        )
    )
    fig.update_layout(
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
        height=720,
        margin=dict(l=0, r=0, t=8, b=0),
    )
    return fig



def render_heatmap_page(db: VolScopeDB, settings: dict) -> None:
    """Render the Universe Heatmap page."""
    _MONO = "JetBrains Mono, SF Mono, Menlo, monospace"
    render_html(
        st,
        f'<div style="font-family:{_MONO};font-size:22px;font-weight:700;'
        f'color:{COLORS["text"]};margin-bottom:16px;">'
        f'<span style="color:{COLORS["accent2"]};">▦</span> HEATMAP'
        f'</div>',
    )

    try:
        latest = db.get_all_latest()
    except Exception:
        latest = pd.DataFrame()

    if latest.empty:
        render_html(
            st,
            f'<div style="color:{COLORS["muted"]};font-family:{_MONO};font-size:12px;">'
            f'No data yet — run <code>make scrape</code> to populate the universe.</div>',
        )
        return

    n_tickers = len(latest)

    # Controls — v0.8.0 redesign: color-metric selector + ticker jump.
    col_metric, col_jump = st.columns([3, 1])
    with col_metric:
        metric_label = st.radio(
            "Color metric",
            [
                "IV Percentile (snapshot)",
                "Δ IV — 1 day",
                "Δ IV — 30 days",
            ],
            index=0,
            horizontal=True,
            key="heatmap_metric",
            help=(
                "Snapshot mode: current IV percentile (0=cheap, 100=rich). "
                "Δ-mode: 1-day or 30-day IV change — red = IV rising, "
                "green = IV falling."
            ),
        )
        metric_to_col = {
            "IV Percentile (snapshot)": ("iv_percentile",  (0.0, 100.0)),
            "Δ IV — 1 day":             ("iv_change_1d",   (-5.0, 5.0)),
            "Δ IV — 30 days":           ("iv_change_30d",  (-10.0, 10.0)),
        }
        color_metric, color_range = metric_to_col[metric_label]

    with col_jump:
        # Search-as-you-type — filter the available tickers by substring
        # before the selectbox renders. Faster than typing the exact symbol
        # in a 280+ ticker universe.
        search_q = st.text_input(
            "Search ticker",
            placeholder="AAPL",
            key="heatmap_search",
            label_visibility="collapsed",
        )
        try:
            available = db.get_available_tickers() or []
        except Exception:
            available = []
        if search_q:
            q = search_q.strip().upper()
            options = [t for t in available if q in t.upper()][:50]
        else:
            options = available[:50]
        if options:
            picked = st.selectbox(
                "Jump",
                options,
                index=None,
                placeholder=f"Pick from {len(options)} match{'es' if len(options)!=1 else ''}",
                key="heatmap_jump_select",
                label_visibility="collapsed",
            )
            if picked:
                from volscope.ui.components.navigation import NavIntent, nav_to
                nav_to(NavIntent(page="Scope", ticker=str(picked), source="Heatmap"))
                st.rerun()

    # Legend
    render_html(
        st,
        f'<div style="display:flex;gap:16px;font-family:{_MONO};font-size:10px;'
        f'margin-bottom:8px;align-items:center;">'
        f'<span style="color:#00d4aa;">■ CHEAP (0–20)</span>'
        f'<span style="color:#5bc8b0;">■ BELOW NORMAL (20–40)</span>'
        f'<span style="color:#8a8f9e;">■ NEUTRAL (40–60)</span>'
        f'<span style="color:#ff9f43;">■ ELEVATED (60–80)</span>'
        f'<span style="color:#ff4466;">■ RICH (80–100)</span>'
        f'</div>',
    )

    fig = _build_treemap_figure(
        latest,
        color_metric=color_metric,
        color_range=color_range,
    )
    clicked = st.plotly_chart(
        fig,
        use_container_width=True,
        on_select="rerun",
        key="heatmap_treemap",
    )

    # Handle treemap click — navigate to Scope for clicked ticker.
    # Plotly Treemap selection returns points with the ``label`` field
    # holding the ticker symbol directly (much simpler than the prior
    # regex-extraction from the hover HTML).
    if clicked and hasattr(clicked, "selection"):
        sel = clicked.selection
        if hasattr(sel, "points") and sel.points:
            pt = sel.points[0]
            label = pt.get("label", "")
            if label and label in latest["ticker"].values:
                from volscope.ui.components.navigation import NavIntent, nav_to
                nav_to(NavIntent(page="Scope", ticker=str(label), source="Heatmap"))
                st.rerun()

    # Stats summary
    if "iv_percentile" in latest.columns:
        pct_col = latest["iv_percentile"].dropna()
        if not pct_col.empty:
            cheap_n  = int((pct_col < 20).sum())
            rich_n   = int((pct_col > 80).sum())
            normal_n = len(pct_col) - cheap_n - rich_n
            render_html(
                st,
                f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};margin-top:8px;">'
                f'{n_tickers} tickers &nbsp;·&nbsp; '
                f'<span style="color:#00d4aa;">{cheap_n} cheap</span> &nbsp;·&nbsp; '
                f'{normal_n} normal &nbsp;·&nbsp; '
                f'<span style="color:#ff4466;">{rich_n} rich</span>'
                f'</div>',
            )
