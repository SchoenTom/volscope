"""
Rotation — Sector Rotation Engine.

Shows sector vol regimes (HOT/NEUTRAL/COLD), momentum, a time-series heatmap,
and Markov-like rotation predictions ("Energy HOT → Industrials follows in ~21d").
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from volscope.analytics.sector_rotation import (
    SectorRegime,
    classify_sector_regime,
    compute_rotation_matrix,
    compute_sector_aggregates,
    compute_sector_momentum,
    get_current_rotation_snapshot,
)
from volscope.data.database import VolScopeDB
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS, HEATMAP_SCALE

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"
_SANS = "DM Sans, Inter, system-ui, sans-serif"

_REGIME_COLORS = {
    "HOT": COLORS["warn"],
    "NEUTRAL": COLORS["muted"],
    "COLD": COLORS["accent"],
}
_TREND_ARROW = {
    "HEATING": "▲",
    "COOLING": "▼",
    "STABLE": "—",
}
_TREND_COLOR = {
    "HEATING": COLORS["amber"],
    "COOLING": COLORS["accent2"],
    "STABLE": COLORS["muted"],
}


def _perc_colorscale() -> list:
    return [list(stop) for stop in HEATMAP_SCALE]


def _build_sector_heatmap(agg: pd.DataFrame, lookback_days: int = 180) -> go.Figure:
    """Build a time-series heatmap: y=sectors, x=dates, z=median_perc."""
    if agg is None or agg.empty:
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor=COLORS["bg"],
            plot_bgcolor=COLORS["bg"],
            height=200,
            annotations=[dict(
                text="No sector data yet — run  make sectors  to aggregate.",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False,
                font=dict(color=COLORS["muted"], family=_MONO, size=12),
            )],
        )
        return fig

    # Filter to lookback window
    agg = agg.copy()
    agg["date"] = pd.to_datetime(agg["date"])
    if lookback_days > 0:
        cutoff = agg["date"].max() - pd.Timedelta(days=lookback_days)
        agg = agg[agg["date"] >= cutoff]

    sectors = sorted(agg["sector"].unique())
    dates = sorted(agg["date"].unique())

    # Build z matrix (sectors × dates)
    pivot = agg.pivot_table(index="sector", columns="date", values="median_perc", aggfunc="median")
    pivot = pivot.reindex(index=sectors, columns=dates)

    z = pivot.values.tolist()
    x_labels = [str(d)[:10] for d in dates]
    y_labels = sectors

    hover = []
    for i, sector in enumerate(sectors):
        row_hover = []
        for j, d in enumerate(dates):
            val = pivot.iloc[i, j] if i < len(pivot) else None
            val_str = f"{val:.0f}%" if val is not None and not pd.isna(val) else "—"
            row_hover.append(f"<b>{sector}</b><br>Date: {str(d)[:10]}<br>IV Pct: {val_str}")
        hover.append(row_hover)

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=x_labels,
            y=y_labels,
            colorscale=_perc_colorscale(),
            zmin=0,
            zmax=100,
            hoverinfo="text",
            text=hover,
            colorbar=dict(
                title=dict(text="IV Pct", font=dict(family=_MONO, size=10, color=COLORS["muted"])),
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
            gridcolor=COLORS["border"],
            showgrid=False,
            nticks=8,
        ),
        yaxis=dict(
            tickfont=dict(family=_MONO, size=10, color=COLORS["text"]),
            gridcolor=COLORS["border"],
            showgrid=False,
        ),
        margin=dict(l=120, r=40, t=20, b=40),
    )
    return fig


def _regime_strip_html(regimes: list[SectorRegime]) -> str:
    if not regimes:
        return (
            f'<div style="color:{COLORS["muted"]};font-family:\'JetBrains Mono\',monospace;'
            f'font-size:12px;">No regime data.</div>'
        )

    rows = []
    for r in regimes:
        rc = _REGIME_COLORS.get(r.regime, COLORS["muted"])
        arrow = _TREND_ARROW.get(r.trend, "—")
        ac = _TREND_COLOR.get(r.trend, COLORS["muted"])
        perc_str = f"{r.current_perc:.0f}%" if r.current_perc is not None else "—"
        mom5_str = f"{r.momentum_5d:+.1f}" if r.momentum_5d is not None else "—"
        rows.append(
            f'<div style="display:flex;align-items:center;gap:10px;padding:5px 10px;'
            f'border-bottom:1px solid {COLORS["border"]};font-family:\'{_MONO}\';">'
            f'<span style="min-width:160px;color:{COLORS["text"]};font-size:12px;font-weight:500;">{r.sector[:22]}</span>'
            f'<span style="background:{rc}22;color:{rc};padding:2px 8px;border-radius:4px;'
            f'font-size:11px;font-weight:600;min-width:64px;text-align:center;">{r.regime}</span>'
            f'<span style="color:{ac};font-size:13px;min-width:20px;text-align:center;">{arrow}</span>'
            f'<span style="color:{COLORS["muted"]};font-size:11px;min-width:50px;">{perc_str}</span>'
            f'<span style="color:{ac};font-size:11px;min-width:50px;">{mom5_str}</span>'
            f'<span style="color:{COLORS["label"]};font-size:10px;">z={r.regime_z:+.1f}</span>'
            f'</div>'
        )

    header = (
        f'<div style="display:flex;gap:10px;padding:4px 10px;'
        f'border-bottom:1px solid {COLORS["border"]};'
        f'font-family:\'{_MONO}\';font-size:9px;color:{COLORS["label"]};text-transform:uppercase;letter-spacing:1px;">'
        f'<span style="min-width:160px;">Sector</span>'
        f'<span style="min-width:64px;">Regime</span>'
        f'<span style="min-width:20px;"></span>'
        f'<span style="min-width:50px;">IV Pct</span>'
        f'<span style="min-width:50px;">5d Δ</span>'
        f'<span>z-score</span>'
        f'</div>'
    )
    return (
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:8px;overflow:hidden;">'
        f'{header}{"".join(rows)}</div>'
    )


def _prediction_cards_html(predictions: list[dict]) -> str:
    if not predictions:
        return (
            f'<div style="color:{COLORS["muted"]};font-family:\'{_MONO}\';font-size:12px;'
            f'padding:12px;background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
            f'border-radius:8px;">'
            f'Not enough history to compute rotation predictions. '
            f'Run <code>make sectors</code> after accumulating 2+ weeks of data.</div>'
        )

    cards = []
    seen: set[str] = set()
    for p in predictions[:6]:
        key = f"{p['leader']}->{p['follower']}"
        if key in seen:
            continue
        seen.add(key)
        pct = int(p["probability"] * 100)
        bar_w = max(4, pct)
        leader_c = _REGIME_COLORS.get(p["leader_regime"], COLORS["muted"])
        cards.append(
            f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
            f'border-left:4px solid {leader_c};border-radius:8px;padding:12px 16px;margin-bottom:8px;">'
            f'<div style="font-family:\'{_MONO}\';font-size:12px;color:{COLORS["text"]};font-weight:600;">'
            f'<span style="color:{leader_c};">{p["leader"]}</span>'
            f' <span style="color:{COLORS["label"]};">→</span> '
            f'<span style="color:{COLORS["text"]};">{p["follower"]}</span>'
            f'</div>'
            f'<div style="margin-top:6px;font-size:10px;color:{COLORS["muted"]};">'
            f'follows within ~{p["lead_days_estimate"]}d &nbsp;·&nbsp; '
            f'<span style="color:{COLORS["text"]};font-weight:600;">{pct}% historical probability</span>'
            f'</div>'
            f'<div style="margin-top:6px;background:{COLORS["border"]};border-radius:2px;height:4px;">'
            f'<div style="width:{bar_w}%;background:{leader_c};height:4px;border-radius:2px;"></div>'
            f'</div>'
            f'</div>'
        )

    return (
        "".join(cards) if cards
        else f'<div style="color:{COLORS["muted"]};font-size:12px;">No predictions.</div>'
    )


def _load_data(db: VolScopeDB) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load sector history from DB and full daily_vol for on-the-fly aggregation."""
    try:
        sector_hist = db.get_sector_history()
    except Exception:
        sector_hist = pd.DataFrame()

    if sector_hist.empty:
        # Fall back to computing aggregates on the fly from daily_vol
        try:
            full_df = db.con.execute(
                "SELECT date, sector, ticker, iv_30d, iv_percentile, hv_20d, "
                "put_call_ratio, total_call_volume, total_put_volume, total_open_interest "
                "FROM daily_vol WHERE sector IS NOT NULL ORDER BY date, sector"
            ).fetchdf()
        except Exception:
            full_df = pd.DataFrame()
        if not full_df.empty:
            sector_hist = compute_sector_aggregates(full_df)

    return sector_hist, pd.DataFrame()


def render_rotation_page(db: VolScopeDB, settings: dict) -> None:
    """Render the Sector Rotation Engine page."""
    render_html(
        st,
        f"""
        <div style="margin-bottom:18px;">
          <div style="font-family:'{_MONO}';font-size:22px;font-weight:700;
                      color:{COLORS['text']};letter-spacing:0.04em;">
            ◈ Rotation
          </div>
          <div style="color:{COLORS['muted']};font-size:12px;margin-top:2px;">
            sector volatility regime — who's heating, who's cooling, who's next
          </div>
        </div>
        """,
    )

    # ── Load data ──────────────────────────────────────────────────────
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
            sector_hist = compute_sector_aggregates(full_df)

    if sector_hist.empty:
        render_html(
            st,
            f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
            f'border-left:3px solid {COLORS["accent2"]};border-radius:6px;'
            f'padding:12px 16px;font-family:\'{_MONO}\';font-size:12px;color:{COLORS["muted"]};">'
            f'No sector data found. Load tickers first, then run '
            f'<code style="background:{COLORS["border"]};padding:1px 5px;border-radius:3px;">'
            f'make sectors</code> to aggregate sector-level volatility.</div>',
        )
        return

    # ── Controls ───────────────────────────────────────────────────────
    col_ctrl1, col_ctrl2, _ = st.columns([1, 1, 3])
    with col_ctrl1:
        window_label = st.selectbox(
            "Heatmap window",
            ["3M", "6M", "1Y", "ALL"],
            index=1,
            label_visibility="collapsed",
        )
    window_days = {"3M": 90, "6M": 180, "1Y": 365, "ALL": 0}[window_label]

    # ── Compute regime ─────────────────────────────────────────────────
    regimes = classify_sector_regime(sector_hist)
    with st.spinner("Computing rotation matrix..."):
        matrix = compute_rotation_matrix(sector_hist, lag=21)
    predictions = get_current_rotation_snapshot(regimes, matrix, top_n=3)

    # ── Summary stats ──────────────────────────────────────────────────
    n_hot = sum(1 for r in regimes if r.regime == "HOT")
    n_cold = sum(1 for r in regimes if r.regime == "COLD")
    n_heating = sum(1 for r in regimes if r.trend == "HEATING")
    render_html(
        st,
        f"""
        <div style="display:flex;gap:16px;margin-bottom:16px;font-family:'{_MONO}';">
          <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
                      border-radius:6px;padding:8px 16px;text-align:center;">
            <div style="color:{COLORS['warn']};font-size:18px;font-weight:700;">{n_hot}</div>
            <div style="color:{COLORS['muted']};font-size:10px;text-transform:uppercase;">HOT</div>
          </div>
          <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
                      border-radius:6px;padding:8px 16px;text-align:center;">
            <div style="color:{COLORS['accent']};font-size:18px;font-weight:700;">{n_cold}</div>
            <div style="color:{COLORS['muted']};font-size:10px;text-transform:uppercase;">COLD</div>
          </div>
          <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
                      border-radius:6px;padding:8px 16px;text-align:center;">
            <div style="color:{COLORS['amber']};font-size:18px;font-weight:700;">{n_heating}</div>
            <div style="color:{COLORS['muted']};font-size:10px;text-transform:uppercase;">HEATING</div>
          </div>
          <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};
                      border-radius:6px;padding:8px 16px;text-align:center;">
            <div style="color:{COLORS['text']};font-size:18px;font-weight:700;">{len(regimes)}</div>
            <div style="color:{COLORS['muted']};font-size:10px;text-transform:uppercase;">SECTORS</div>
          </div>
        </div>
        """,
    )

    # ── Heatmap ────────────────────────────────────────────────────────
    render_html(
        st,
        f'<div style="font-family:\'{_MONO}\';font-size:11px;color:{COLORS["label"]};'
        f'text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">IV Percentile Heatmap</div>',
    )
    heatmap_col = "median_perc" if "median_perc" in sector_hist.columns else None
    if heatmap_col:
        fig = _build_sector_heatmap(sector_hist, lookback_days=window_days)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.divider()

    # ── Regime strip + predictions ─────────────────────────────────────
    left, right = st.columns([3, 2])

    with left:
        render_html(
            st,
            f'<div style="font-family:\'{_MONO}\';font-size:11px;color:{COLORS["label"]};'
            f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">Current Regimes</div>',
        )
        render_html(st, _regime_strip_html(regimes))

    with right:
        render_html(
            st,
            f'<div style="font-family:\'{_MONO}\';font-size:11px;color:{COLORS["label"]};'
            f'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">Rotation Predictions</div>',
        )
        render_html(st, _prediction_cards_html(predictions))

    st.divider()

    # ── Momentum table ─────────────────────────────────────────────────
    with st.expander("Momentum table — all sectors", expanded=False):
        if regimes:
            rows = []
            for r in regimes:
                rows.append({
                    "Sector": r.sector,
                    "Regime": r.regime,
                    "IV Pct": r.current_perc,
                    "5d Δ": r.momentum_5d,
                    "21d Δ": r.momentum_21d,
                    "z-score": r.regime_z,
                    "Trend": r.trend,
                })
            mom_df = pd.DataFrame(rows)
            st.dataframe(
                mom_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Regime": st.column_config.TextColumn("Regime"),
                    "IV Pct": st.column_config.NumberColumn("IV Pct", format="%.1f"),
                    "5d Δ": st.column_config.NumberColumn("5d Δ", format="%+.1f"),
                    "21d Δ": st.column_config.NumberColumn("21d Δ", format="%+.1f"),
                    "z-score": st.column_config.NumberColumn("z", format="%+.2f"),
                },
            )

    # ── Run script hint ────────────────────────────────────────────────
    render_html(
        st,
        f'<div style="margin-top:12px;font-family:\'{_MONO}\';font-size:10px;'
        f'color:{COLORS["label"]};padding:8px 12px;background:{COLORS["card"]};'
        f'border:1px solid {COLORS["border"]};border-radius:6px;">'
        f'Run <code style="color:{COLORS["text"]};">make sectors</code> after each daily scrape '
        f'to refresh sector aggregates.</div>',
    )
