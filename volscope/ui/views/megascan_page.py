"""
Mega-Scan page — the Giga Screen.

Single page that surfaces the universe across six axes simultaneously:
cheapest / richest / movers up / movers down / crowded / highest edge.
Plus a hero-strip of five KPIs, a universe scatter plot, and a 24-column
master CSV export.

Layout (2026-05-03 redesign):
  - Header strip: brand mark + universe-context (loaded / curated / snapshot)
  - Hero KPI strip: 5 tiles, each clickable
  - Tabbed rankings (six tabs): each tab shows TOP-25 in a scrollable card
    with full ticker context. Tabs are FAST to switch — single content swap
    rather than 6 simultaneously rendered tiles.
  - Universe scatter (collapsible expander)
  - Master CSV export

The data prep is cached for 5 minutes via st.cache_data so flipping
between tabs / refreshing the sidebar doesn't re-run the full pipeline.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from volscope.analytics.megascan import (
    RANKINGS,
    RankingSpec,
    UniverseKPI,
    apply_ranking,
    build_full_page_data,
    build_master_csv,
    universe_kpis,
)
from volscope.data.database import VolScopeDB
from volscope.data.ticker_universe import all_tickers
from volscope.ui.components.cached_data import get_all_latest_cached, make_cache_key
from volscope.ui.components.html_utils import render_html
from volscope.ui.components.navigation import NavIntent, nav_to
from volscope.ui.styles.theme import CHART_PALETTE, COLORS

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


# ── Cached page-data composer ─────────────────────────────────────────
# 5-minute TTL keeps the page snappy across tab-switches and minor
# interactions while still picking up new scrapes within minutes.

@st.cache_data(ttl=300, show_spinner=False)
def _build_page_data_cached(latest_hash: str, _latest: pd.DataFrame):
    """Streamlit-cache wrapper for build_full_page_data.

    The latest_hash key forces cache invalidation when the underlying
    snapshot changes (we hash the full DataFrame in the caller).
    """
    return build_full_page_data(_latest)


def render_megascan_page(db: VolScopeDB, settings: dict) -> None:
    """Top-level renderer for the Mega-Scan page."""
    # Cached snapshot — avoids re-hitting DuckDB on every interaction.
    latest = get_all_latest_cached(make_cache_key(db), db)

    # Header — explicit context: curated universe vs DB snapshot vs latest
    curated = len(all_tickers())
    loaded = len(latest)
    snap_date = (
        pd.to_datetime(latest["date"].max()).date().isoformat()
        if not latest.empty and "date" in latest.columns else "—"
    )
    render_html(
        st,
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid {COLORS["border"]};">'
        f'<div style="font-family:{_MONO};font-size:22px;font-weight:700;color:{COLORS["text"]};">'
        f'<span style="color:{COLORS["accent"]};">◎</span> MEGA SCAN'
        f'</div>'
        f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};">'
        f'<span style="color:{COLORS["text"]};">{loaded}</span> loaded · '
        f'<span style="color:{COLORS["muted"]};">{curated}</span> curated · '
        f'<span style="color:{COLORS["text"]};">{snap_date}</span>'
        f'</div>'
        f'</div>',
    )

    if latest.empty:
        st.info(
            "No data in the universe yet. Open the Discover page and click "
            "**Load Starter Pack** — Mega-Scan needs the snapshot to rank against."
        )
        return

    # Cache key: the snapshot date + ticker count is enough granularity.
    # If the user runs `make scrape` the date will move and the cache invalidates.
    cache_key = f"{snap_date}-{loaded}"
    page_data = _build_page_data_cached(cache_key, latest)

    # ── Hero KPI strip ───────────────────────────────────────────
    _render_hero_strip(st, page_data.kpis)

    st.write("")  # 8px breathing room

    # ── Tabbed rankings — fast switch, scrollable per tab ───────
    _render_rankings_tabbed(st, page_data.rankings)

    # ── Universe scatter (collapsible — heavy Plotly render) ────
    with st.expander("📊 Universe scatter (IV percentile × spread)", expanded=False):
        _render_universe_scatter(st, page_data.scatter_df)

    # ── Export ──────────────────────────────────────────────────
    _render_export(st, page_data)


# ── Hero strip ─────────────────────────────────────────────────────────

def _render_hero_strip(st_module, kpis: list[UniverseKPI]) -> None:
    """Five KPI tiles. Clicking sets selected_ticker + active_page=Scope."""
    cols = st_module.columns(5)
    for col, kpi in zip(cols, kpis):
        with col:
            render_html(
                col,
                f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
                f'border-left:3px solid {kpi.color};border-radius:6px;padding:12px 14px;'
                f'height:90px;font-family:{_MONO};">'
                f'<div style="color:{COLORS["label"]};font-size:9px;letter-spacing:1.4px;'
                f'text-transform:uppercase;font-weight:600;">{kpi.label}</div>'
                f'<div style="color:{kpi.color};font-size:16px;font-weight:700;'
                f'margin-top:2px;line-height:1.2;">{kpi.value}</div>'
                f'<div style="color:{COLORS["muted"]};font-size:10px;margin-top:4px;">'
                f'{kpi.sublabel}</div>'
                f'</div>',
            )
            if kpi.target:
                if col.button(f"◈ {kpi.target}", key=f"megascan_kpi_{kpi.label}",
                               use_container_width=True):
                    nav_to(NavIntent(page="Scope", ticker=kpi.target,
                                     source="Mega-Scan"))
                    st_module.rerun()


# ── Tabbed rankings ────────────────────────────────────────────────────

def _render_rankings_tabbed(
    st_module,
    rankings: list[tuple[RankingSpec, pd.DataFrame]],
) -> None:
    """Six rankings as tabs — fast switch, scroll within each tile."""
    tab_labels = [spec.title for spec, _ in rankings]
    tabs = st_module.tabs(tab_labels)
    for tab, (spec, df) in zip(tabs, rankings):
        with tab:
            _render_ranking_scrollable(tab, spec, df)


def _render_ranking_scrollable(tab, spec: RankingSpec, df: pd.DataFrame) -> None:
    """Scrollable ranking card showing top-N rows.

    The internal container uses overflow-y so the page itself stays
    short even when N is large. A header dropdown lets the user
    quickly open any ticker in Scope.
    """
    if df.empty:
        tab.caption("no candidates match this ranking")
        return

    # Quick-open dropdown — one-click jump to Scope for any ranked ticker
    head_left, head_right = tab.columns([3, 1])
    with head_left:
        render_html(
            tab,
            f'<div style="font-family:{_MONO};font-size:10px;color:{COLORS["muted"]};'
            f'margin-bottom:8px;">'
            f'showing top <span style="color:{COLORS["text"]};font-weight:600;">{len(df)}</span> '
            f'sorted by <span style="color:{spec.accent_color};">{spec.sort_key}</span> '
            f'({"asc" if spec.ascending else "desc"})'
            f'</div>',
        )
    with head_right:
        ticker_options = df["ticker"].astype(str).tolist()
        picked = tab.selectbox(
            "Open in Scope",
            ticker_options,
            index=None,
            placeholder="◈ open ticker",
            key=f"megascan_open_{spec.title}",
            label_visibility="collapsed",
        )
        if picked:
            nav_to(NavIntent(page="Scope", ticker=str(picked), source="Mega-Scan"))
            tab.rerun()

    # Scrollable rows. Each row is rendered in a small column-grid so the
    # ticker label + sort value + context wrap cleanly.
    rows_html: list[str] = []
    for rank_idx, (_, row) in enumerate(df.iterrows(), start=1):
        ticker = row.get("ticker", "?")
        company = row.get("company_name") or row.get("sector") or ""
        sort_v = row.get(spec.sort_key)
        sort_str = (
            f"{float(sort_v):+.1f}" if spec.sort_key in ("iv_change_1d", "iv_change_30d")
            else f"{float(sort_v):.0f}" if pd.notna(sort_v)
            else "—"
        )

        # Subtitle — the second line of context
        ctx_parts = []
        if pd.notna(row.get("iv_30d")):
            ctx_parts.append(f"iv {float(row['iv_30d']):.1f}%")
        if spec.sort_key != "iv_percentile" and pd.notna(row.get("iv_percentile")):
            ctx_parts.append(f"perc {float(row['iv_percentile']):.0f}")
        if spec.sort_key != "iv_change_1d" and pd.notna(row.get("iv_change_1d")):
            ctx_parts.append(f"Δ1d {float(row['iv_change_1d']):+.1f}")
        if pd.notna(row.get("total_open_interest")):
            oi = int(row["total_open_interest"])
            ctx_parts.append(f"OI {oi:,}")
        ctx = " · ".join(ctx_parts)

        rows_html.append(
            f'<div style="display:grid;grid-template-columns:30px 1fr 80px;'
            f'gap:10px;padding:8px 10px;border-bottom:1px solid {COLORS["border"]};'
            f'align-items:center;font-family:{_MONO};">'
            # rank
            f'<div style="color:{COLORS["muted"]};font-size:11px;font-weight:600;">'
            f'#{rank_idx:02d}</div>'
            # ticker + company + ctx (stacked)
            f'<div style="min-width:0;">'
            f'<div style="color:{COLORS["text"]};font-size:13px;font-weight:700;'
            f'font-feature-settings:\'tnum\';">{ticker}'
            f'<span style="color:{COLORS["muted"]};font-weight:400;font-size:11px;'
            f'margin-left:6px;">{company}</span>'
            f'</div>'
            f'<div style="color:{COLORS["muted"]};font-size:10px;margin-top:2px;">'
            f'{ctx}</div>'
            f'</div>'
            # sort value (right-aligned, accent color)
            f'<div style="color:{spec.accent_color};font-size:14px;font-weight:700;'
            f'text-align:right;font-feature-settings:\'tnum\';">{sort_str}</div>'
            f'</div>'
        )

    # Single scrollable container — height capped, content scrolls inside.
    render_html(
        tab,
        f'<div style="max-height:500px;overflow-y:auto;border:1px solid {COLORS["border"]};'
        f'border-left:3px solid {spec.accent_color};border-radius:6px;background:{COLORS["card"]};">'
        + "".join(rows_html) +
        f'</div>',
    )


# ── Scatter ────────────────────────────────────────────────────────────

def _render_universe_scatter(st_module, scatter_df: pd.DataFrame) -> None:
    """IV percentile (x) × IV-HV spread (y), color=sector, size=OI."""
    if scatter_df.empty:
        st_module.caption("Not enough data to scatter — needs iv_percentile + iv_30d + hv_20d.")
        return

    sectors = (
        scatter_df["sector"].fillna("Other").unique().tolist()
        if "sector" in scatter_df.columns else ["Other"]
    )
    color_map = {
        s: CHART_PALETTE[i % len(CHART_PALETTE)]
        for i, s in enumerate(sectors)
    }

    fig = go.Figure()
    for sector in sectors:
        sub = (
            scatter_df[scatter_df["sector"] == sector]
            if "sector" in scatter_df.columns
            else scatter_df
        )
        if sub.empty:
            continue
        sizes = (sub["size"] ** 0.5 / 50).clip(lower=4, upper=20)
        hover = (
            sub["ticker"].astype(str)
            + " · " + sub.get("company", pd.Series([""] * len(sub))).astype(str)
            + "<br>perc=" + sub["x"].round(1).astype(str)
            + "<br>spread=" + sub["y"].round(2).astype(str)
        )
        fig.add_trace(go.Scatter(
            x=sub["x"], y=sub["y"], mode="markers",
            marker=dict(color=color_map[sector], size=sizes,
                        line=dict(width=0.5, color="#000")),
            name=str(sector), text=hover, hovertemplate="%{text}<extra></extra>",
        ))

    fig.update_layout(
        title="",
        xaxis_title="IV percentile (vs own 52w)",
        yaxis_title="IV − HV spread (pp)",
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        font=dict(family=_MONO, color=COLORS["text"], size=11),
        height=420, margin=dict(l=40, r=20, t=20, b=40),
        legend=dict(orientation="h", y=-0.2),
    )
    fig.add_hline(y=0, line_color=COLORS["border"], line_width=1)
    fig.add_vline(x=20, line_color=COLORS["border"], line_dash="dot", line_width=0.7)
    fig.add_vline(x=80, line_color=COLORS["border"], line_dash="dot", line_width=0.7)
    st_module.plotly_chart(fig, use_container_width=True)


# ── Export ─────────────────────────────────────────────────────────────

def _render_export(st_module, page_data) -> None:
    st_module.markdown("### Export")
    st_module.caption(
        "Master CSV — 24 fixed columns (ticker, sector, IVs, HVs, ranks, "
        "edge_score, quality, ...). Schema is locked across releases."
    )
    st_module.download_button(
        label="📥 Master CSV (24 columns)",
        data=page_data.csv_text.encode("utf-8"),
        file_name=f"volscope_megascan_{date.today().isoformat()}.csv",
        mime="text/csv",
        key="megascan_master_csv",
    )
