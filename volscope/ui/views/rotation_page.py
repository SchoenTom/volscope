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


def _compute_rrg_panel(
    sector_hist: pd.DataFrame,
    *,
    tail_weeks: int = 8,
    momentum_lookback_days: int = 21,
) -> dict[str, list[dict]]:
    """Compute Relative Rotation Graph (RRG) trails per sector.

    Adapts the Julius de Kempenaer 2005 RRG framework to volatility:

      • **RS-Ratio** = sector median IV percentile − cross-sector
        median IV percentile (centred around 0). Positive = sector vol
        is richer than the cross-sector benchmark, negative = cheaper.
      • **RS-Momentum** = N-day rate of change of RS-Ratio (default
        N=21 trading days ≈ one month).

    Both series are smoothed with a 5-day EMA to reduce the daily
    noise that would otherwise make the trails illegible.

    Quadrants (vol-semantics, NOT equity-rotation semantics):
      • TR  Vol Heating   — sector richer than benchmark, momentum up
      • BR  Vol Cooling   — sector richer, momentum down
      • BL  Vol Cold      — sector cheaper, momentum down
      • TL  Vol Warming   — sector cheaper, momentum up

    Returns a dict keyed by sector with a list of {date, x, y} points
    (most recent ``tail_weeks * 5`` trading days).
    """
    if sector_hist is None or sector_hist.empty:
        return {}
    if "median_perc" not in sector_hist.columns:
        return {}

    df = sector_hist[["date", "sector", "median_perc"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "sector"])

    # Cross-sector median per date (the "benchmark" for RRG).
    benchmark = (
        df.groupby("date")["median_perc"].median().rename("bench_perc")
    )
    df = df.merge(benchmark, left_on="date", right_index=True, how="left")

    # RS-Ratio = sector vs benchmark (in percentile-points).
    df["rs_ratio"] = df["median_perc"] - df["bench_perc"]

    panel: dict[str, list[dict]] = {}
    tail_days = max(10, tail_weeks * 5)

    for sector, g in df.groupby("sector"):
        g = g.sort_values("date").copy()
        if len(g) < momentum_lookback_days + 5:
            continue
        # Smooth ratio with 5-day EMA, then compute momentum as the
        # absolute change vs ``momentum_lookback_days`` days ago.
        g["rs_smooth"] = g["rs_ratio"].ewm(span=5, adjust=False).mean()
        g["rs_mom"] = (
            g["rs_smooth"] - g["rs_smooth"].shift(momentum_lookback_days)
        ).ewm(span=5, adjust=False).mean()
        tail = g.dropna(subset=["rs_smooth", "rs_mom"]).tail(tail_days)
        if tail.empty:
            continue
        panel[sector] = [
            {
                "date": ts.strftime("%Y-%m-%d"),
                "x": float(rs),
                "y": float(mom),
            }
            for ts, rs, mom in zip(
                tail["date"], tail["rs_smooth"], tail["rs_mom"]
            )
        ]
    return panel


def _build_rrg_figure(panel: dict[str, list[dict]]) -> go.Figure:
    """Render an RRG scatter with quadrant background + per-sector trails.

    Each sector gets a coloured line tracing its last ``tail_weeks``
    of (RS-Ratio, RS-Momentum). The head (most recent point) is a
    large filled marker with the sector label; the tail fades to
    illustrate direction of travel.
    """
    fig = go.Figure()
    if not panel:
        fig.update_layout(
            paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
            height=480,
            annotations=[dict(
                text="Not enough sector history for RRG — need ≥ 30 trading "
                     "days of sector aggregates.",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False,
                font=dict(family=_MONO, size=12, color=COLORS["muted"]),
            )],
        )
        return fig

    # Compute symmetric bounds so quadrants are visually centred.
    all_x = [pt["x"] for pts in panel.values() for pt in pts]
    all_y = [pt["y"] for pts in panel.values() for pt in pts]
    bound_x = max(8.0, max(abs(v) for v in all_x))
    bound_y = max(4.0, max(abs(v) for v in all_y))
    bound_x *= 1.15
    bound_y *= 1.15

    # Quadrant background shapes.
    q_alpha = "0.05"
    fig.add_shape(type="rect", xref="x", yref="y",
                  x0=0, x1=bound_x, y0=0, y1=bound_y,
                  fillcolor=f"rgba(255, 68, 102, {q_alpha})", line=dict(width=0),
                  layer="below")
    fig.add_shape(type="rect", xref="x", yref="y",
                  x0=0, x1=bound_x, y0=-bound_y, y1=0,
                  fillcolor=f"rgba(255, 159, 67, {q_alpha})", line=dict(width=0),
                  layer="below")
    fig.add_shape(type="rect", xref="x", yref="y",
                  x0=-bound_x, x1=0, y0=-bound_y, y1=0,
                  fillcolor=f"rgba(0, 212, 170, {q_alpha})", line=dict(width=0),
                  layer="below")
    fig.add_shape(type="rect", xref="x", yref="y",
                  x0=-bound_x, x1=0, y0=0, y1=bound_y,
                  fillcolor=f"rgba(91, 140, 255, {q_alpha})", line=dict(width=0),
                  layer="below")

    # Quadrant labels — vol-semantics, anchored in corners.
    label_font = dict(family=_MONO, size=11, color=COLORS["muted"])
    fig.add_annotation(x=bound_x * 0.94, y=bound_y * 0.94, xref="x", yref="y",
                       text="VOL HEATING", showarrow=False, font=label_font,
                       xanchor="right", yanchor="top")
    fig.add_annotation(x=bound_x * 0.94, y=-bound_y * 0.94, xref="x", yref="y",
                       text="VOL COOLING", showarrow=False, font=label_font,
                       xanchor="right", yanchor="bottom")
    fig.add_annotation(x=-bound_x * 0.94, y=-bound_y * 0.94, xref="x", yref="y",
                       text="VOL COLD", showarrow=False, font=label_font,
                       xanchor="left", yanchor="bottom")
    fig.add_annotation(x=-bound_x * 0.94, y=bound_y * 0.94, xref="x", yref="y",
                       text="VOL WARMING", showarrow=False, font=label_font,
                       xanchor="left", yanchor="top")

    # Centre cross.
    fig.add_shape(type="line", x0=-bound_x, x1=bound_x, y0=0, y1=0,
                  line=dict(color=COLORS["border"], width=1, dash="dot"),
                  layer="below")
    fig.add_shape(type="line", x0=0, x1=0, y0=-bound_y, y1=bound_y,
                  line=dict(color=COLORS["border"], width=1, dash="dot"),
                  layer="below")

    # Per-sector trail + head marker. Colour cycles through a
    # categorical palette deterministically by sorted name so the
    # legend ordering matches across reruns.
    palette = [
        "#00d4aa", "#5b8cff", "#ff9f43", "#ff4466", "#a78bfa",
        "#06b6d4", "#fbbf24", "#f472b6", "#34d399", "#60a5fa",
        "#fb923c", "#e879f9", "#22d3ee", "#facc15",
    ]
    for i, sector in enumerate(sorted(panel.keys())):
        pts = panel[sector]
        if not pts:
            continue
        col = palette[i % len(palette)]
        xs = [p["x"] for p in pts]
        ys = [p["y"] for p in pts]
        # Trail (fading line, no markers).
        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode="lines",
            line=dict(color=col, width=2),
            opacity=0.55,
            name=sector,
            hovertemplate=(
                f"<b>{sector}</b><br>"
                "RS-Ratio: %{x:.2f}<br>"
                "RS-Mom: %{y:.2f}<extra></extra>"
            ),
            legendgroup=sector,
            showlegend=True,
        ))
        # Head marker — slightly bigger circle with the sector label.
        fig.add_trace(go.Scatter(
            x=[xs[-1]], y=[ys[-1]],
            mode="markers+text",
            marker=dict(size=14, color=col,
                        line=dict(color=COLORS["bg"], width=2)),
            text=[sector[:12]],
            textposition="top center",
            textfont=dict(family=_MONO, size=10, color=COLORS["text"]),
            hovertemplate=(
                f"<b>{sector}</b><br>"
                "RS-Ratio: %{x:.2f}<br>"
                "RS-Mom: %{y:.2f}<extra></extra>"
            ),
            legendgroup=sector,
            showlegend=False,
        ))

    fig.update_layout(
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
        height=560,
        margin=dict(l=40, r=20, t=30, b=40),
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        xaxis=dict(
            title=dict(
                text="RS-Ratio (sector IV pct − benchmark)",
                font=dict(family=_SANS, size=11, color=COLORS["muted"]),
            ),
            range=[-bound_x, bound_x],
            gridcolor=COLORS["border"],
            zerolinecolor=COLORS["border"],
            zeroline=False,
        ),
        yaxis=dict(
            title=dict(
                text="RS-Momentum (21-day Δ)",
                font=dict(family=_SANS, size=11, color=COLORS["muted"]),
            ),
            range=[-bound_y, bound_y],
            gridcolor=COLORS["border"],
            zerolinecolor=COLORS["border"],
            zeroline=False,
        ),
        legend=dict(
            orientation="v",
            yanchor="top", y=1.0,
            xanchor="left", x=1.02,
            bgcolor="rgba(0,0,0,0)",
            font=dict(family=_MONO, size=9, color=COLORS["text"]),
        ),
    )
    return fig


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
            from volscope.ui.components.cached_data import (
                compute_sector_aggregates_cached, make_cache_key,
            )
            sector_hist = compute_sector_aggregates_cached(
                make_cache_key(db), full_df,
            )

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
    except Exception as exc:                                        # noqa: BLE001
        # Falls back to direct daily_vol query below; log so the
        # operator can tell the difference between "sector_daily table
        # never populated" (normal on fresh DB) and "DB corruption".
        import logging as _lg
        _lg.getLogger("volscope.ui.rotation").warning(
            "get_sector_history() failed; falling back to direct query: %s", exc,
        )

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

    # ── Rotation views (RRG default, heatmap secondary) ────────────────
    # v0.8.0 redesign: the dense sector × date heatmap was the
    # operator's #2 "Schandfleck" complaint. The new Relative Rotation
    # Graph (Julius de Kempenaer 2005) plots each sector as a head +
    # trail across two intuitive axes (vs benchmark on x, momentum on
    # y) so the same data reads as "what's heating up, what's cooling
    # off" in one glance. The legacy heatmap is preserved as the
    # second tab for operators who want the dense time-series view.
    tab_rrg, tab_heatmap = st.tabs([
        "↻ Rotation Graph (RRG)",
        "▦ IV Percentile Heatmap",
    ])
    with tab_rrg:
        render_html(
            st,
            f'<div style="font-family:\'{_SANS}\';font-size:11px;'
            f'color:{COLORS["muted"]};margin-bottom:6px;">'
            f'Each sector as a head + 8-week trail. '
            f'<span style="color:#ff4466;">●</span> heating, '
            f'<span style="color:#ff9f43;">●</span> cooling, '
            f'<span style="color:#00d4aa;">●</span> cold, '
            f'<span style="color:#5b8cff;">●</span> warming.'
            f'</div>',
        )
        rrg_panel = _compute_rrg_panel(sector_hist, tail_weeks=8)
        fig_rrg = _build_rrg_figure(rrg_panel)
        st.plotly_chart(fig_rrg, width='stretch',
                         config={"displayModeBar": False})

    with tab_heatmap:
        heatmap_col = "median_perc" if "median_perc" in sector_hist.columns else None
        if heatmap_col:
            fig = _build_sector_heatmap(sector_hist, lookback_days=window_days)
            st.plotly_chart(fig, width='stretch',
                             config={"displayModeBar": False})

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
                width='stretch',
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
