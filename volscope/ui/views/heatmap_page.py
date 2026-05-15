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
from html import escape
from typing import Optional

import numpy as np
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

    # Drop rows where the *colour* metric is fully missing — they
    # would be coloured to the midpoint and just clutter the canvas.
    # Also drop where iv_30d is missing entirely (a ticker with no IV
    # is not interesting to a vol-research tool).
    if "iv_30d" in working.columns:
        working = working[pd.notna(working["iv_30d"])]
    if working.empty:
        return go.Figure().update_layout(
            paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"], height=200,
        )

    # Rectangle size — prefer total OI (deeper option markets = more
    # important). Add 1 so zero-OI rows still get *some* area
    # (otherwise treemap collapses them out entirely).
    if "total_open_interest" in working.columns:
        working["_size"] = (
            working["total_open_interest"].fillna(0.0).clip(lower=0.0) + 1.0
        )
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

    # ── Hover text — VECTORISED ───────────────────────────────────
    # The previous per-row ``iterrows()`` loop with ~8 ``row.get()``
    # lookups per row was the dominant cost on the heatmap render
    # (~200ms at 800 rows). Building the strings via pandas
    # vector-string-ops collapses that to ~5ms.
    #
    # The matched-HV fallback also fixes a subtle bug: ``a or b``
    # falls through to ``b`` when ``a`` is exactly 0.0, which is a
    # legitimate (if rare) HV value. We use ``np.where(notna(a), a, b)``
    # so only true-NaN triggers the fallback.
    # Helper: always return a numeric Series of len(working). When a
    # column is missing from the DataFrame, ``DataFrame.get`` returns
    # None, and ``pd.to_numeric(None)`` collapses to a scalar NaN —
    # not a Series. The ``.map()`` calls below would then crash with
    # ``'numpy.float64' object has no attribute 'map'``. Wrapping
    # via ``_col_series`` guarantees a Series result regardless.
    def _col_series(name: str) -> pd.Series:
        if name in working.columns:
            return pd.to_numeric(working[name], errors="coerce")
        return pd.Series(np.nan, index=working.index, dtype=float)

    hv_yz = _col_series("hv_yz_30d")
    hv_cc = _col_series("hv_20d")
    hv = pd.Series(np.where(hv_yz.notna(), hv_yz, hv_cc), index=working.index)

    spread_m = _col_series("iv_hv_spread_matched")
    spread_l = _col_series("iv_hv_spread")
    spread = pd.Series(
        np.where(spread_m.notna(), spread_m, spread_l), index=working.index,
    )

    iv      = _col_series("iv_30d")
    perc    = _col_series("iv_percentile")
    oi      = _col_series("total_open_interest")
    chg1d   = _col_series("iv_change_1d")
    chg30d  = _col_series("iv_change_30d")

    def _vec_fmt(s: pd.Series, suffix: str = "%", digits: int = 1) -> pd.Series:
        out = s.map(lambda v: f"{v:.{digits}f}{suffix}" if pd.notna(v) else "—")
        return out.astype(str)

    iv_s     = _vec_fmt(iv,   suffix="%", digits=1)
    hv_s     = _vec_fmt(hv,   suffix="%", digits=1)
    spread_s = _vec_fmt(spread, suffix="", digits=1)
    perc_s   = _vec_fmt(perc, suffix="", digits=0)
    oi_s     = oi.map(lambda v: f"{int(v):,}" if pd.notna(v) else "—").astype(str)
    chg1d_s  = _vec_fmt(chg1d,  suffix="", digits=1)
    chg30d_s = _vec_fmt(chg30d, suffix="", digits=1)

    working["_hover"] = (
        "<b>" + working["ticker"].astype(str) + "</b><br>" +
        "Sector: " + working["sector"].astype(str) + "<br>" +
        "IV 30d: " + iv_s + "<br>" +
        "HV: " + hv_s + "<br>" +
        "IV − HV: " + spread_s + "<br>" +
        "IV Percentile: " + perc_s + "<br>" +
        "OI: " + oi_s + "<br>" +
        "Δ1d: " + chg1d_s + " · Δ30d: " + chg30d_s
    )

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

    # v0.9.2 perf: cached snapshot — the treemap re-renders on every
    # color-metric / search interaction; the snapshot doesn't change
    # between rerruns so caching saves a DuckDB read per click.
    try:
        from volscope.ui.components.cached_data import (
            get_all_latest_cached, make_cache_key,
        )
        latest = get_all_latest_cached(make_cache_key(db), db)
    except Exception:                                          # noqa: BLE001
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

    # Build the figure inside a cached wrapper so subsequent reruns
    # (radio toggle / sidebar interaction) replay an existing
    # Plotly-spec dict instead of rebuilding the 800+ hover strings
    # and re-running the squarify tiling. ``_df`` is underscore-
    # prefixed to skip the (very expensive) DataFrame hash; the
    # ``cache_key`` carries the snapshot date.
    from volscope.ui.components.cached_data import make_cache_key

    @st.cache_data(ttl=600, show_spinner=False)
    def _cached_treemap_spec(
        cache_key: str,
        color_metric: str,
        color_range_t: tuple[float, float],
        _df: pd.DataFrame,
    ) -> dict:
        return _build_treemap_figure(
            _df, color_metric=color_metric, color_range=color_range_t,
        ).to_dict()

    with st.spinner("Rendering universe treemap …", show_time=False):
        try:
            spec = _cached_treemap_spec(
                make_cache_key(db),
                color_metric,
                tuple(color_range),
                latest,
            )
            fig = go.Figure(spec)
        except Exception as exc:                                # noqa: BLE001
            render_html(
                st,
                f'<div style="color:#ff4466;font-family:{_MONO};font-size:12px;'
                f'background:{COLORS["surface"]};border:1px solid #ff4466;'
                f'border-radius:6px;padding:12px;margin:8px 0;">'
                f'<b>Treemap build failed:</b> {escape(str(exc))}<br>'
                f'<span style="color:{COLORS["muted"]};font-size:10px;">'
                f'Run <code>make repair-iv</code> to fix NULL iv_30d rows then '
                f'reload the page.</span></div>',
            )
            return

    # Diagnostic banner: how many rows did the treemap actually plot?
    # When < 60% of the universe makes it through (NULL iv_30d filter
    # in _build_treemap_figure) the heatmap looks suspiciously sparse.
    plotted = int(pd.notna(pd.to_numeric(latest.get("iv_30d"), errors="coerce")).sum())
    if plotted < int(n_tickers * 0.6):
        render_html(
            st,
            f'<div style="color:{COLORS["amber"]};font-family:{_MONO};font-size:11px;'
            f'background:{COLORS["surface"]};border-left:3px solid {COLORS["amber"]};'
            f'padding:8px 12px;margin:4px 0 8px;border-radius:0 4px 4px 0;">'
            f'⚠ Only {plotted} of {n_tickers} tickers plotted ({n_tickers - plotted} '
            f'missing iv_30d). Run <code>make repair-iv</code> in your terminal to '
            f'backfill — or <code>make scrape</code> for fresh chains.</div>',
        )

    clicked = st.plotly_chart(
        fig,
        width='stretch',
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
