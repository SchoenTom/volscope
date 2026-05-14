"""
Heatmap — universe-wide IV percentile at a glance.

One colored cell per ticker, grouped by sector. Green = cheap vol,
red = rich vol. Click a cell to navigate to Scope for that ticker.
Collapse to sector averages when more than 100 tickers are present.
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

_COLLAPSE_THRESHOLD = 100  # collapse to sector averages above this count


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


def _build_heatmap_figure(df: pd.DataFrame, group_by_sector: bool) -> go.Figure:
    """
    Build a Plotly heatmap from the universe latest snapshot.

    Each cell is coloured by iv_percentile.  When group_by_sector is True,
    we aggregate to sector medians (used for large universes).
    """
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor=COLORS["bg"],
            plot_bgcolor=COLORS["bg"],
            height=200,
        )
        return fig

    working = df.copy()
    if "sector" not in working.columns or working["sector"].isna().all():
        working["sector"] = "Unknown"
    working["sector"] = working["sector"].fillna("Unknown")

    if group_by_sector:
        # Collapse to sector medians
        agg = (
            working.groupby("sector")["iv_percentile"]
            .median()
            .reset_index()
            .rename(columns={"iv_percentile": "pct_median"})
        )
        agg["label"] = agg["sector"].str[:12]
        agg["pct_display"] = agg["pct_median"]
        # Sort by percentile so cheapest sectors appear first
        agg = agg.sort_values("pct_median")
        tickers_list = agg["label"].tolist()
        pcts = agg["pct_median"].tolist()
        hover_texts = [
            f"<b>{row['sector']}</b><br>Median IV Pct: {row['pct_median']:.0f}%"
            for _, row in agg.iterrows()
        ]
        title_suffix = " (sector medians)"
    else:
        working = working.sort_values(["sector", "iv_percentile"])
        tickers_list = working["ticker"].tolist()
        pcts = working["iv_percentile"].tolist()
        hover_texts = []
        for _, row in working.iterrows():
            iv = row.get("iv_30d")
            pct = row.get("iv_percentile")
            iv_str = f"{iv:.1f}%" if iv is not None and not math.isnan(float(iv)) else "—"
            pct_str = f"{pct:.0f}%" if pct is not None and not math.isnan(float(pct)) else "—"
            sector = row.get("sector") or "—"
            hover_texts.append(
                f"<b>{row['ticker']}</b><br>IV 30d: {iv_str}<br>IV Pct: {pct_str}<br>Sector: {sector}"
            )
        title_suffix = ""

    colors_list = [_percentile_color(p) for p in pcts]

    # Layout: pack into rows of ~20 cells
    n = len(tickers_list)
    n_cols = min(n, 20)
    n_rows = math.ceil(n / n_cols)

    # Pad to fill the grid
    pad = n_rows * n_cols - n
    tickers_padded = tickers_list + [""] * pad
    pcts_padded = pcts + [None] * pad
    colors_padded = colors_list + [COLORS["bg"]] * pad
    hover_padded = hover_texts + [""] * pad

    # Reshape to (n_rows × n_cols) grids
    z_colors = [colors_padded[i * n_cols:(i + 1) * n_cols] for i in range(n_rows)]
    text_grid = [tickers_padded[i * n_cols:(i + 1) * n_cols] for i in range(n_rows)]
    hover_grid = [hover_padded[i * n_cols:(i + 1) * n_cols] for i in range(n_rows)]

    # Use numeric z values for Plotly colorscale, but we override colors manually
    # via a custom colorscale mapping each unique color to a z value 0..1.
    unique_colors = list(dict.fromkeys(c for c in colors_padded if c != COLORS["bg"]))
    color_to_z: dict[str, float] = {}
    for i, c in enumerate(unique_colors):
        color_to_z[c] = i / max(len(unique_colors) - 1, 1)

    z_vals = [
        [color_to_z.get(c, -1.0) if c != COLORS["bg"] else -1.0
         for c in row]
        for row in z_colors
    ]

    colorscale = [[color_to_z[c], c] for c in unique_colors]
    if len(colorscale) == 1:
        colorscale = [[0.0, colorscale[0][1]], [1.0, colorscale[0][1]]]

    fig = go.Figure(
        go.Heatmap(
            z=z_vals,
            text=text_grid,
            customdata=hover_grid,
            texttemplate="%{text}",
            hovertemplate="%{customdata}<extra></extra>",
            colorscale=colorscale,
            showscale=False,
            xgap=3,
            ygap=3,
            # Dynamic font scaling — at >100 tickers cell labels collide.
            # Empirically, total cells / chart width ≈ width / size, so
            # size shrinks as ticker count grows but never below 7px.
            textfont=dict(
                family=_MONO,
                size=max(7, min(11, int(800 / max(n, 1)))),
                color=COLORS["bg"],
            ),
        )
    )

    fig.update_layout(
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
        height=max(140, n_rows * 42 + 80),
        margin=dict(l=0, r=0, t=52, b=0),
        title=dict(
            text=f"IV PERCENTILE HEATMAP{title_suffix}",
            font=dict(color=COLORS["text"], size=14, family=_SANS),
            x=0.01,
            xanchor="left",
        ),
        xaxis=dict(
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            fixedrange=True,
        ),
        yaxis=dict(
            showticklabels=False,
            showgrid=False,
            zeroline=False,
            fixedrange=True,
        ),
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
    group_by_sector = n_tickers > _COLLAPSE_THRESHOLD

    # Controls
    col_ctrl, col_jump = st.columns([3, 1])
    with col_ctrl:
        if n_tickers > _COLLAPSE_THRESHOLD:
            view_mode = st.radio(
                "View",
                ["Per ticker", "Sector averages"],
                index=1,
                horizontal=True,
                key="heatmap_view_mode",
            )
            group_by_sector = view_mode == "Sector averages"
        else:
            group_by_sector = False

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

    fig = _build_heatmap_figure(latest, group_by_sector)
    clicked = st.plotly_chart(
        fig,
        use_container_width=True,
        on_select="rerun",
        key="heatmap_chart",
    )

    # Handle cell click — navigate to Scope for clicked ticker
    if clicked and hasattr(clicked, "selection"):
        sel = clicked.selection
        if hasattr(sel, "points") and sel.points:
            pt = sel.points[0]
            # customdata holds the hover text; extract ticker from first token
            cd = pt.get("customdata", "")
            if cd and isinstance(cd, str) and "<b>" in cd:
                raw = cd.split("<b>")[1].split("</b>")[0].strip()
                if raw and raw in latest["ticker"].values:
                    st.session_state["selected_ticker"] = raw
                    st.session_state["active_page"] = "Scope"
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
