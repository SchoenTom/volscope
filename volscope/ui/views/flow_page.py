"""
Flow — Capital Flow Proxy.

Detects institutional flow signatures from public options data:
OI growth, low Volume/OI ratio, PCR shift, IV-HV divergence, volume clustering.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from volscope.analytics.capital_flow import (
    FlowDivergence,
    compute_flow_components,
    compute_flow_score,
    detect_flow_divergence,
)
from volscope.data.database import VolScopeDB
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"
_SANS = "DM Sans, Inter, system-ui, sans-serif"


def _flow_colorscale() -> list:
    """0 = cold/quiet (blue), 50 = neutral (grey), 100 = hot/active (amber-red)."""
    return [
        [0.0, COLORS["accent"]],
        [0.3, COLORS["accent2"]],
        [0.5, COLORS["muted"]],
        [0.7, COLORS["amber"]],
        [1.0, COLORS["warn"]],
    ]


def _flow_color(score: float) -> str:
    """Single color for a flow score value."""
    if score >= 65:
        return COLORS["warn"]
    if score >= 55:
        return COLORS["amber"]
    if score <= 35:
        return COLORS["accent"]
    if score <= 45:
        return COLORS["accent2"]
    return COLORS["muted"]


def _build_flow_heatmap(flow_df: pd.DataFrame, lookback_days: int = 180) -> go.Figure:
    """Sector × time heatmap coloured by flow_score (0-100)."""
    _empty_fig = go.Figure()
    _empty_fig.update_layout(
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
        height=200,
        annotations=[dict(
            text="No flow data yet — load tickers and run  make sectors.",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False,
            font=dict(color=COLORS["muted"], family=_MONO, size=12),
        )],
    )

    if flow_df is None or flow_df.empty or "flow_score" not in flow_df.columns:
        return _empty_fig

    df = flow_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if lookback_days > 0:
        cutoff = df["date"].max() - pd.Timedelta(days=lookback_days)
        df = df[df["date"] >= cutoff]
    if df.empty:
        return _empty_fig

    sectors = sorted(df["sector"].unique())
    dates = sorted(df["date"].unique())
    pivot = df.pivot_table(index="sector", columns="date", values="flow_score", aggfunc="mean")
    pivot = pivot.reindex(index=sectors, columns=dates)

    hover = []
    for i, sector in enumerate(sectors):
        row_hover = []
        for j, d in enumerate(dates):
            val = pivot.iloc[i, j] if i < len(pivot) else None
            val_str = f"{val:.1f}" if val is not None and not pd.isna(val) else "—"
            row_hover.append(f"<b>{sector}</b><br>Date: {str(d)[:10]}<br>Flow: {val_str}")
        hover.append(row_hover)

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values.tolist(),
            x=[str(d)[:10] for d in dates],
            y=sectors,
            colorscale=_flow_colorscale(),
            zmin=0,
            zmax=100,
            hoverinfo="text",
            text=hover,
            colorbar=dict(
                title=dict(text="Flow", font=dict(family=_MONO, size=10, color=COLORS["muted"])),
                tickfont=dict(family=_MONO, size=9, color=COLORS["muted"]),
                thickness=10,
                len=0.8,
            ),
        )
    )
    fig.update_layout(
        paper_bgcolor=COLORS["card"],
        plot_bgcolor=COLORS["card"],
        height=max(180, len(sectors) * 30 + 80),
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        xaxis=dict(
            tickfont=dict(family=_MONO, size=9, color=COLORS["muted"]),
            showgrid=False,
            nticks=8,
        ),
        yaxis=dict(
            tickfont=dict(family=_MONO, size=10, color=COLORS["text"]),
            showgrid=False,
        ),
        margin=dict(l=120, r=40, t=20, b=40),
    )
    return fig


def _ranking_bars_html(sector_flows: list[tuple[str, float]]) -> str:
    """Horizontal bar chart (HTML) of sectors ranked by current flow score."""
    if not sector_flows:
        return f'<div style="color:{COLORS["muted"]};font-family:\'{_MONO}\';font-size:12px;">No flow data.</div>'

    rows = []
    for sector, score in sector_flows:
        color = _flow_color(score)
        bar_w = max(2, int(score))
        rows.append(
            f'<div style="margin-bottom:6px;">'
            f'<div style="display:flex;align-items:center;gap:8px;font-family:\'{_MONO}\';">'
            f'<span style="min-width:160px;font-size:11px;color:{COLORS["text"]};'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{sector[:22]}</span>'
            f'<div style="flex:1;background:{COLORS["border"]};border-radius:2px;height:8px;">'
            f'<div style="width:{bar_w}%;background:{color};height:8px;border-radius:2px;"></div>'
            f'</div>'
            f'<span style="min-width:36px;text-align:right;font-size:11px;color:{color};'
            f'font-weight:600;">{score:.1f}</span>'
            f'</div>'
            f'</div>'
        )

    return (
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:8px;padding:14px 16px;">'
        f'<div style="font-family:\'{_MONO}\';font-size:9px;color:{COLORS["label"]};'
        f'text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;">'
        f'Flow Score &nbsp;·&nbsp; 0=quiet &nbsp;·&nbsp; 100=active'
        f'</div>'
        f'{"".join(rows)}'
        f'</div>'
    )


def _divergence_cards_html(divergences: list[FlowDivergence]) -> str:
    """Cards for accumulation / distribution alerts."""
    if not divergences:
        return (
            f'<div style="color:{COLORS["muted"]};font-family:\'{_MONO}\';font-size:12px;'
            f'padding:12px;background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
            f'border-radius:8px;">'
            f'No divergence signals detected. Flow and price are moving together, '
            f'or there is insufficient history (need ≥6 sector data points).'
            f'</div>'
        )

    cards = []
    for div in divergences[:6]:
        is_acc = div.signal == "ACCUMULATION"
        # Stronger green/red split per Pillar 5 — was green/amber before,
        # now green/red so the buy-vs-sell signal is unmistakable at a
        # glance. Amber would conflate with WATCH severity used elsewhere.
        accent = COLORS["accent"] if is_acc else COLORS["warn"]
        label = "ACCUMULATION" if is_acc else "DISTRIBUTION"
        icon = "▲" if is_acc else "▼"
        desc = (
            "Flow rising, price not following — possible institutional accumulation"
            if is_acc
            else "Flow falling, price not following — possible quiet distribution"
        )
        price_str = (
            f"{div.price_change_5d:+.2f}%"
            if div.price_change_5d is not None
            else "—"
        )
        cards.append(
            f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
            f'border-left:4px solid {accent};border-radius:8px;padding:12px 16px;margin-bottom:8px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
            f'<span style="font-family:\'{_MONO}\';font-size:13px;color:{COLORS["text"]};font-weight:600;">'
            f'{div.sector}</span>'
            f'<span style="background:{accent}22;color:{accent};padding:2px 8px;border-radius:4px;'
            f'font-size:11px;font-weight:600;">{icon} {label}</span>'
            f'</div>'
            f'<div style="font-family:\'{_MONO}\';font-size:11px;color:{COLORS["muted"]};line-height:1.6;">'
            f'Flow score: <span style="color:{accent};font-weight:600;">{div.flow_score:.1f}</span>'
            f'&nbsp;·&nbsp; 5d Δ: <span style="color:{accent};">{div.flow_change_5d:+.1f}</span>'
            f'&nbsp;·&nbsp; IV proxy 5d: <span style="color:{COLORS["text"]};">{price_str}</span>'
            f'</div>'
            f'<div style="margin-top:6px;font-size:10px;color:{COLORS["label"]};">{desc}</div>'
            f'</div>'
        )

    return "".join(cards)


def _disclaimer_html() -> str:
    return (
        f'<div style="margin-top:16px;padding:10px 14px;background:{COLORS["card"]};'
        f'border:1px solid {COLORS["border"]};border-radius:6px;'
        f'font-family:\'{_MONO}\';font-size:10px;color:{COLORS["label"]};line-height:1.6;">'
        f'<strong style="color:{COLORS["muted"]};">⚠ Disclaimer:</strong> '
        f'All signals are proxy-based, derived from public options data. '
        f'Not validated against 13F filings or actual institutional order flow. '
        f'Treat as a screening tool, not a confirmed institutional signal. '
        f'Not financial advice.'
        f'</div>'
    )


@st.cache_data(ttl=300, show_spinner=False)
def _compute_flow_cached(sector_hist_json: str) -> tuple[str, str]:
    """Cache-friendly wrapper: take JSON in, return flow_df and scores as JSON."""
    import json
    sh = pd.read_json(sector_hist_json, orient="records")
    if sh.empty:
        return "[]", "[]"
    components = compute_flow_components(sh)
    scores = compute_flow_score(components)
    return components.to_json(orient="records"), scores.to_json(orient="records")


def render_flow_page(db: VolScopeDB, settings: dict) -> None:
    """Render the Capital Flow Proxy page."""
    render_html(
        st,
        f"""
        <div style="margin-bottom:18px;">
          <div style="font-family:'{_MONO}';font-size:22px;font-weight:700;
                      color:{COLORS['text']};letter-spacing:0.04em;">
            ◈ Flow
          </div>
          <div style="color:{COLORS['muted']};font-size:12px;margin-top:2px;">
            capital flow proxy — OI growth · Vol/OI · PCR shift · IV-HV divergence · volume clustering
          </div>
        </div>
        """,
    )

    # ── Load sector history ─────────────────────────────────────────────
    sector_hist = pd.DataFrame()
    try:
        sector_hist = db.get_sector_history()
    except Exception:
        pass

    if sector_hist.empty:
        try:
            full_df = db.con.execute(
                "SELECT date, sector, ticker, iv_30d, iv_percentile, hv_20d, "
                "put_call_ratio, total_call_volume, total_put_volume, total_open_interest "
                "FROM daily_vol WHERE sector IS NOT NULL ORDER BY date, sector"
            ).fetchdf()
        except Exception:
            full_df = pd.DataFrame()
        if not full_df.empty:
            from volscope.ui.components.cached_data import (
                compute_sector_aggregates_cached, make_cache_key,
            )
            sector_hist = compute_sector_aggregates_cached(
                make_cache_key(db), full_df,
            )

    if sector_hist.empty:
        render_html(
            st,
            f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
            f'border-left:3px solid {COLORS["accent2"]};border-radius:6px;'
            f'padding:12px 16px;font-family:\'{_MONO}\';font-size:12px;color:{COLORS["muted"]};">'
            f'No sector data found. Load tickers first, then run '
            f'<code style="background:{COLORS["border"]};padding:1px 5px;border-radius:3px;">'
            f'make sectors</code> to aggregate sector-level data.</div>',
        )
        render_html(st, _disclaimer_html())
        return

    # ── Compute flow ────────────────────────────────────────────────────
    with st.spinner("Computing flow components..."):
        components = compute_flow_components(sector_hist)
        flow_df = compute_flow_score(components)

    if flow_df.empty:
        render_html(
            st,
            f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
            f'border-left:3px solid {COLORS["amber"]};border-radius:6px;'
            f'padding:12px 16px;font-family:\'{_MONO}\';font-size:12px;color:{COLORS["muted"]};">'
            f'Insufficient data to compute flow scores — need at least 3 data points per sector.</div>',
        )
        render_html(st, _disclaimer_html())
        return

    # ── Controls ────────────────────────────────────────────────────────
    col_ctrl, _ = st.columns([1, 4])
    with col_ctrl:
        window_label = st.selectbox(
            "Heatmap window",
            ["3M", "6M", "1Y", "ALL"],
            index=1,
            label_visibility="collapsed",
        )
    window_days = {"3M": 90, "6M": 180, "1Y": 365, "ALL": 0}[window_label]

    # ── Summary stats (current flow scores per sector) ──────────────────
    latest_flow = (
        flow_df.sort_values("date")
        .groupby("sector")
        .last()
        .reset_index()
        .sort_values("flow_score", ascending=False)
    )
    n_hot = int((latest_flow["flow_score"] >= 65).sum())
    n_quiet = int((latest_flow["flow_score"] <= 35).sum())
    n_sectors = len(latest_flow)

    render_html(
        st,
        f"""
        <div style="display:flex;gap:16px;margin-bottom:16px;font-family:'{_MONO}';">
          <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
                      border-radius:6px;padding:8px 16px;text-align:center;">
            <div style="color:{COLORS['warn']};font-size:18px;font-weight:700;">{n_hot}</div>
            <div style="color:{COLORS['muted']};font-size:10px;text-transform:uppercase;">Active Flow</div>
          </div>
          <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
                      border-radius:6px;padding:8px 16px;text-align:center;">
            <div style="color:{COLORS['accent']};font-size:18px;font-weight:700;">{n_quiet}</div>
            <div style="color:{COLORS['muted']};font-size:10px;text-transform:uppercase;">Quiet</div>
          </div>
          <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
                      border-radius:6px;padding:8px 16px;text-align:center;">
            <div style="color:{COLORS['text']};font-size:18px;font-weight:700;">{n_sectors}</div>
            <div style="color:{COLORS['muted']};font-size:10px;text-transform:uppercase;">Sectors</div>
          </div>
        </div>
        """,
    )

    # ── Flow views (v0.8.0 redesign) ────────────────────────────────────
    # Operator feedback: the dense sector × date heatmap was hard to
    # parse at-a-glance. New default is a sortable horizontal bar
    # chart of the CURRENT flow score per sector with the heatmap
    # retained as a secondary tab for time-series analysis.
    tab_bars, tab_heatmap = st.tabs([
        "█ Flow ranking",
        "▦ Flow time-series",
    ])

    with tab_bars:
        sort_col1, _ = st.columns([1, 4])
        with sort_col1:
            sort_mode = st.selectbox(
                "Sort",
                ["By score ▼", "By score ▲", "By name"],
                index=0,
                key="flow_bars_sort",
                label_visibility="collapsed",
            )
        if sort_mode == "By score ▼":
            ranked = latest_flow.sort_values("flow_score", ascending=False)
        elif sort_mode == "By score ▲":
            ranked = latest_flow.sort_values("flow_score", ascending=True)
        else:
            ranked = latest_flow.sort_values("sector", ascending=True)

        # Plotly horizontal bar chart — clearer than the legacy HTML
        # bars at a glance and supports proper hover with the
        # underlying component breakdown.
        sectors_x = ranked["sector"].tolist()
        scores_x = ranked["flow_score"].astype(float).tolist()
        bar_colors = [
            COLORS["warn"]  if s >= 65 else
            COLORS["amber"] if s >= 35 else
            COLORS["accent"]
            for s in scores_x
        ]
        fig_bars = go.Figure(go.Bar(
            x=scores_x,
            y=sectors_x,
            orientation="h",
            marker=dict(color=bar_colors, line=dict(width=0)),
            text=[f"{s:.0f}" for s in scores_x],
            textposition="outside",
            textfont=dict(family=_MONO, size=10, color=COLORS["text"]),
            hovertemplate="<b>%{y}</b><br>Flow score: %{x:.1f}<extra></extra>",
        ))
        # Vertical reference lines at 35 (quiet ↑) and 65 (active ↑).
        for thresh, label, color in (
            (35, "quiet", COLORS["accent"]),
            (65, "active", COLORS["warn"]),
        ):
            fig_bars.add_vline(
                x=thresh,
                line=dict(color=color, width=1, dash="dot"),
                annotation_text=label,
                annotation_position="top",
                annotation_font=dict(family=_MONO, size=9, color=color),
            )
        fig_bars.update_layout(
            paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
            height=max(280, len(sectors_x) * 26 + 80),
            margin=dict(l=140, r=24, t=24, b=24),
            font=dict(family=_MONO, color=COLORS["text"], size=10),
            xaxis=dict(
                title=dict(
                    text="Flow score (0 = quiet, 100 = active)",
                    font=dict(family=_SANS, size=11, color=COLORS["muted"]),
                ),
                range=[0, 110],
                gridcolor=COLORS["border"],
                zerolinecolor=COLORS["border"],
            ),
            yaxis=dict(
                tickfont=dict(family=_MONO, size=10, color=COLORS["text"]),
                gridcolor=COLORS["border"],
                autorange="reversed",  # highest at top when sorted desc
            ),
            showlegend=False,
            bargap=0.25,
        )
        st.plotly_chart(fig_bars, use_container_width=True,
                         config={"displayModeBar": False})

    with tab_heatmap:
        render_html(
            st,
            f'<div style="font-family:\'{_SANS}\';font-size:11px;'
            f'color:{COLORS["muted"]};margin-bottom:6px;">'
            f'Sector × date flow score over the selected window. '
            f'Use this view to spot persistent vs ephemeral flow.</div>',
        )
        fig_heat = _build_flow_heatmap(flow_df, lookback_days=window_days)
        st.plotly_chart(fig_heat, use_container_width=True,
                         config={"displayModeBar": False})

    st.divider()

    # ── Divergence alerts (kept — these are the actionable signal) ──────
    render_html(
        st,
        f'<div style="font-family:\'{_MONO}\';font-size:11px;color:{COLORS["label"]};'
        f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">'
        f'Divergence Alerts</div>',
    )
    divergences = detect_flow_divergence(flow_df, sector_hist=sector_hist)
    render_html(st, _divergence_cards_html(divergences))

    st.divider()

    # ── Component breakdown expander ────────────────────────────────────
    with st.expander("Component breakdown — all sectors", expanded=False):
        latest_comp = (
            components.sort_values("date")
            .groupby("sector")
            .last()
            .reset_index()
        )
        z_display_cols = [c for c in ["oi_change_z", "vol_oi_ratio_z", "pcr_shift_z", "iv_hv_div_z", "cluster_z"]
                          if c in latest_comp.columns]
        if not latest_comp.empty and z_display_cols:
            display_df = latest_comp[["sector"] + z_display_cols].copy()
            display_df = display_df.rename(columns={
                "oi_change_z": "OI Chg z",
                "vol_oi_ratio_z": "Vol/OI z",
                "pcr_shift_z": "PCR z",
                "iv_hv_div_z": "IV-HV z",
                "cluster_z": "Cluster z",
            })
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    col: st.column_config.NumberColumn(col, format="%+.2f")
                    for col in display_df.columns if col != "sector"
                },
            )
        else:
            st.caption("No component data available.")

    render_html(st, _disclaimer_html())
