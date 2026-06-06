"""Plotly chart builders for VolScope dark-terminal theme."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from volscope.ui.styles.theme import COLORS, rgba


_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"
_SANS = "DM Sans, -apple-system, sans-serif"


def _base_layout(title: str = "") -> dict:
    """
    IBKR/TradingView-style chart layout.

    Conventions:
      - Transparent paper + plot bg so charts inherit the page surface.
      - Y-axis on the RIGHT — that is where TradingView, IBKR TWS and
        Bloomberg place price/value axes; leftside is treated as a
        Streamlit-default tell.
      - Tighter margins (l=12 r=44 t=28 b=28) than the historic
        l=48 r=24 t=52 b=40, because the page already supplies padding.
      - Mono tickfonts with tabular numerals so digits line up.
    """
    return dict(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=dict(
            text=title,
            font=dict(color=COLORS["label"], size=11, family=_SANS),
            x=0.0,
            xanchor="left",
            y=0.97,
        ),
        font=dict(color=COLORS["text"], family=_MONO, size=10),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.03)",
            zerolinecolor="rgba(255,255,255,0.05)",
            linecolor="rgba(255,255,255,0.05)",
            tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            showgrid=True,
            gridwidth=1,
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.03)",
            zerolinecolor="rgba(255,255,255,0.05)",
            linecolor="rgba(255,255,255,0.05)",
            tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            showgrid=True,
            gridwidth=1,
            side="right",
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(13,14,20,0.95)",
            bordercolor=COLORS["border"],
            font=dict(family=_MONO, size=11, color=COLORS["text"]),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(family=_SANS, size=9, color=COLORS["muted"]),
        ),
        margin=dict(l=12, r=44, t=28, b=28),
    )


def _range_selector() -> dict:
    return dict(
        buttons=[
            dict(count=1, label="1M", step="month", stepmode="backward"),
            dict(count=3, label="3M", step="month", stepmode="backward"),
            dict(count=6, label="6M", step="month", stepmode="backward"),
            dict(count=1, label="1Y", step="year", stepmode="backward"),
            dict(step="all", label="ALL"),
        ],
        bgcolor=COLORS["surface"],
        bordercolor=COLORS["border"],
        activecolor=COLORS["accent"],
        font=dict(family=_MONO, color=COLORS["muted"], size=10),
        x=0.01,
        y=1.08,
    )


def _add_regime_bands(fig: go.Figure, history: pd.DataFrame, x) -> None:
    """Shade the chart background by Bayesian vol-regime (migration 008).

    Contiguous runs of the same regime become a faint coloured vrect, so the
    trader instantly sees whether a given historical IV level sat in a calm
    or a crisis regime. Silent no-op when the column is absent / all-null
    (e.g. a DB scraped before the regime writer was fixed).
    """
    if "vol_regime" not in history.columns or history["vol_regime"].isna().all():
        return
    # Keys match the actual labels written by compute_vol_regime
    # (VOL_CRUSHED / VOL_CHEAP / VOL_FAIR / VOL_RICH / VOL_EXTREME /
    # VOL_CRISIS), compared lower-cased. Bare aliases kept as a safety net.
    cmap = {
        "vol_crushed": rgba(COLORS["accent"], 0.05),
        "vol_cheap":   rgba(COLORS["accent"], 0.04),
        "vol_fair":    rgba(COLORS["accent2"], 0.04),
        "vol_rich":    rgba(COLORS["amber"], 0.05),
        "vol_extreme": rgba(COLORS["amber"], 0.07),
        "vol_crisis":  rgba(COLORS["warn"], 0.08),
        "crushed":     rgba(COLORS["accent"], 0.05),
        "cheap":       rgba(COLORS["accent"], 0.04),
        "fair":        rgba(COLORS["accent2"], 0.04),
        "rich":        rgba(COLORS["amber"], 0.05),
        "extreme":     rgba(COLORS["amber"], 0.07),
        "crisis":      rgba(COLORS["warn"], 0.08),
    }
    xv = list(x)
    regimes = list(history["vol_regime"])
    n = len(regimes)
    i = 0
    while i < n:
        r = regimes[i]
        if r is None or (isinstance(r, float) and pd.isna(r)):
            i += 1
            continue
        j = i
        while j + 1 < n and regimes[j + 1] == r:
            j += 1
        color = cmap.get(str(r).lower())
        if color is not None and j > i:
            fig.add_vrect(x0=xv[i], x1=xv[j], fillcolor=color,
                          line_width=0, layer="below")
        i = j + 1


def create_iv_hv_chart(
    history: pd.DataFrame, ticker: str, earnings_dates: list | None = None
) -> go.Figure:
    fig = go.Figure()
    has_iv  = "iv_30d" in history.columns and history["iv_30d"].notna().any()
    has_hv  = "hv_20d" in history.columns and history["hv_20d"].notna().any()
    has_hv60 = "hv_60d" in history.columns and history["hv_60d"].notna().any()

    if history.empty or not (has_iv or has_hv):
        layout = _base_layout(f"{ticker} — IMPLIED vs REALIZED (no data)")
        layout["height"] = 300
        fig.update_layout(**layout)
        return fig

    x = history["date"] if "date" in history.columns else history.index

    # ── Directional vol-premium ribbon — the chart's whole thesis ──
    # Fill the band BETWEEN implied and realized vol, coloured by sign:
    # green where IV sits below realized (options cheap), red where IV sits
    # above realized (options rich). This makes the page's one question the
    # dominant visual. Four zero-width traces using fill="tonexty".
    if has_iv and has_hv:
        _iv = history["iv_30d"]
        _hv = history["hv_20d"]
        _pair = pd.concat([_iv, _hv], axis=1)
        _upper = _pair.max(axis=1)
        _lower = _pair.min(axis=1)
        # rich band (IV above HV) → warn red
        fig.add_trace(go.Scatter(x=x, y=_hv, mode="lines", line=dict(width=0),
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=_upper, mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor=rgba(COLORS["warn"], 0.13),
                                 hoverinfo="skip", showlegend=False))
        # cheap band (IV below HV) → accent green
        fig.add_trace(go.Scatter(x=x, y=_hv, mode="lines", line=dict(width=0),
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=_lower, mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor=rgba(COLORS["accent"], 0.13),
                                 hoverinfo="skip", showlegend=False))

    # HV 60d (background context) — thinnest, most muted
    if has_hv60:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=history["hv_60d"],
                mode="lines",
                name="HV 60d",
                line=dict(color=COLORS["accent2"], width=1.0, dash="dot"),
                opacity=0.55,
                hovertemplate="HV 60d · %{y:.1f}%<extra></extra>",
            )
        )

    # HV 20d (primary realized reference)
    if has_hv:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=history["hv_20d"],
                mode="lines",
                name="HV 20d",
                line=dict(color=COLORS["accent2"], width=1.8, dash="dash"),
                hovertemplate="HV 20d · %{y:.1f}%<extra></extra>",
            )
        )

    # IV 30d (hero line — thickest, most prominent, subtle area fill)
    if has_iv:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=history["iv_30d"],
                mode="lines",
                name="IV 30d",
                line=dict(color=COLORS["accent"], width=2.4, shape="spline"),
                hovertemplate="IV 30d · %{y:.1f}%<extra></extra>",
            )
        )

    _add_regime_bands(fig, history, x)
    _add_earnings_markers(fig, earnings_dates)
    _add_today_gap(fig, history, label="STALE")

    layout = _base_layout(f"{ticker} — IMPLIED vs REALIZED VOLATILITY")
    # The hero chart of VolScope — give it room.
    layout["height"] = 440
    layout["xaxis"]["rangeselector"] = _range_selector()
    layout["yaxis"]["ticksuffix"] = "%"
    layout["yaxis"]["rangemode"] = "tozero"
    # Premium chart polish (terminal feel): horizontal-only dotted grid +
    # a cursor crosshair spike, so the data lines stay the loudest thing.
    layout["xaxis"]["showgrid"] = False
    layout["xaxis"]["showspikes"] = True
    layout["xaxis"]["spikemode"] = "across"
    layout["xaxis"]["spikethickness"] = 1
    layout["xaxis"]["spikedash"] = "solid"
    layout["xaxis"]["spikecolor"] = COLORS["spike"]
    layout["xaxis"]["spikesnap"] = "cursor"
    layout["yaxis"]["gridcolor"] = "rgba(255,255,255,0.04)"
    layout["yaxis"]["griddash"] = "dot"
    fig.update_layout(**layout)
    return fig


def _add_today_gap(
    fig: go.Figure,
    history: pd.DataFrame,
    *,
    yref: str = "paper",
    label: str = "STALE",
) -> None:
    """Visualise the gap between the last data row and today.

    When `today() − last_scrape_date > 0`, render:
      - a vertical line at the last data point (subtle)
      - a hashed/shaded band from last_data_date → today (warns the
        viewer that no data exists in that range)
      - a TODAY marker at the right edge
      - an annotation "+Nd stale" inside the band

    No-ops when data is already current (gap ≤ 0).
    """
    from datetime import date as _date
    import pandas as pd

    if history is None or history.empty or "date" not in history.columns:
        return
    try:
        last_data = pd.to_datetime(history["date"].iloc[-1]).date()
    except Exception:
        return

    today = _date.today()
    if last_data >= today:
        return  # already current — no gap

    age = (today - last_data).days

    # Colour scales with age — fresher gap is amber, deeply stale is red.
    if age <= 2:
        band_color = COLORS["amber"]
    elif age <= 7:
        band_color = COLORS["amber"]
    else:
        band_color = COLORS["warn"]

    # Shaded band from last_data → today
    fig.add_vrect(
        x0=last_data, x1=today,
        fillcolor=band_color, opacity=0.07,
        layer="below", line_width=0,
    )
    # Vertical dotted line at last data row
    fig.add_vline(
        x=last_data,
        line=dict(color=COLORS["muted"], width=1, dash="dot"),
        opacity=0.6,
    )
    # TODAY marker (solid vertical at right edge)
    fig.add_vline(
        x=today,
        line=dict(color=band_color, width=1.4, dash="solid"),
        opacity=0.85,
    )
    # Annotation inside the band — placed at the midpoint so it's
    # readable on both wide and narrow ranges.
    from datetime import timedelta as _td
    mid = last_data + _td(days=age // 2)
    fig.add_annotation(
        x=mid,
        y=1.0, yref=yref,
        text=f"{label} · +{age}d",
        showarrow=False,
        font=dict(color=band_color, size=9, family=_MONO),
        bgcolor=COLORS["card"],
        bordercolor=band_color,
        borderwidth=1,
        borderpad=3,
        yshift=-4,
    )
    # Small "TODAY" label at the right edge
    fig.add_annotation(
        x=today, y=0.0, yref=yref,
        text="TODAY",
        showarrow=False,
        font=dict(color=band_color, size=8, family=_MONO),
        bgcolor=COLORS["card"],
        bordercolor=band_color,
        borderwidth=1,
        borderpad=2,
        yshift=12,
        xshift=-22,
    )


def _add_earnings_markers(fig: go.Figure, earnings_dates: list | None) -> None:
    """Gold dashed vlines + ER badge — single source for all chart builders."""
    if not earnings_dates:
        return
    for ed in earnings_dates:
        fig.add_vline(
            x=ed,
            line=dict(color=COLORS["gold"], width=1, dash="dash"),
            opacity=0.45,
        )
        fig.add_annotation(
            x=ed,
            y=1.0,
            yref="paper",
            text="ER",
            showarrow=False,
            font=dict(color=COLORS["gold"], size=9, family=_MONO),
            bgcolor=COLORS["card"],
            bordercolor=COLORS["gold"],
            borderwidth=1,
            borderpad=3,
            yshift=-4,
        )


def create_spread_chart(
    history: pd.DataFrame, earnings_dates: list | None = None
) -> go.Figure:
    fig = go.Figure()
    if (
        history.empty
        or "iv_30d" not in history.columns
        or "hv_20d" not in history.columns
        or not history["iv_30d"].notna().any()
        or not history["hv_20d"].notna().any()
    ):
        layout = _base_layout("IV − HV SPREAD (no data)")
        layout["height"] = 200
        fig.update_layout(**layout)
        return fig

    x = history["date"] if "date" in history.columns else history.index
    spread = history["iv_30d"] - history["hv_20d"]
    colors = [COLORS["warn"] if s > 0 else COLORS["accent"] for s in spread.fillna(0)]
    fig.add_trace(
        go.Bar(
            x=x,
            y=spread,
            marker_color=colors,
            marker_line_width=0,
            name="Spread",
            hovertemplate="Spread · %{y:+.1f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line=dict(color=COLORS["muted"], width=1.5))
    _add_earnings_markers(fig, earnings_dates)
    _add_today_gap(fig, history, label="STALE")
    layout = _base_layout("IV − HV SPREAD (IV − HV 20d)")
    layout["height"] = 200
    layout["xaxis"]["rangeselector"] = _range_selector()
    layout["yaxis"]["ticksuffix"] = "%"
    layout["bargap"] = 0.1
    fig.update_layout(**layout)
    return fig


def create_iv_range_bar(history: pd.DataFrame, lookback_days: int = 252) -> go.Figure:
    """
    52-week IV range visualization — a horizontal bar showing where current IV
    sits inside the min/max range, with shaded cheap/rich zones.

    The gut-punch moment: one glance tells you "IV is at the bottom of the year."
    """
    fig = go.Figure()
    layout = _base_layout("52-WEEK IV RANGE")
    layout["yaxis"]["visible"] = False
    layout["yaxis"]["range"] = [0, 1]
    layout["xaxis"]["gridcolor"] = COLORS["border"]
    layout["xaxis"]["ticksuffix"] = "%"
    layout["showlegend"] = False
    layout["height"] = 130
    layout["margin"] = dict(l=24, r=24, t=52, b=32)

    if history.empty or "iv_30d" not in history.columns:
        fig.update_layout(**layout)
        return fig

    window = history.tail(lookback_days).dropna(subset=["iv_30d"])
    if window.empty:
        fig.update_layout(**layout)
        return fig

    iv_min = float(window["iv_30d"].min())
    iv_max = float(window["iv_30d"].max())
    iv_now = float(window["iv_30d"].iloc[-1])
    if iv_max == iv_min:
        iv_max = iv_min + 1.0

    span = iv_max - iv_min
    cheap_end = iv_min + 0.20 * span
    rich_start = iv_min + 0.80 * span

    # Cheap zone (green)
    fig.add_shape(
        type="rect",
        x0=iv_min,
        x1=cheap_end,
        y0=0,
        y1=1,
        fillcolor=COLORS["accent"],
        opacity=0.15,
        line=dict(width=0),
    )
    # Rich zone (red)
    fig.add_shape(
        type="rect",
        x0=rich_start,
        x1=iv_max,
        y0=0,
        y1=1,
        fillcolor=COLORS["warn"],
        opacity=0.15,
        line=dict(width=0),
    )
    # Full range bar
    fig.add_trace(
        go.Scatter(
            x=[iv_min, iv_max],
            y=[0.5, 0.5],
            mode="lines",
            line=dict(color=COLORS["muted"], width=4),
            hoverinfo="skip",
        )
    )
    # Current IV marker
    fig.add_trace(
        go.Scatter(
            x=[iv_now],
            y=[0.5],
            mode="markers+text",
            marker=dict(
                size=22,
                color=COLORS["accent"],
                line=dict(color=COLORS["bg"], width=2),
                symbol="diamond",
            ),
            text=[f"<b>{iv_now:.1f}%</b>"],
            textposition="top center",
            textfont=dict(color=COLORS["accent"], size=13),
            hovertemplate="Current IV: %{x:.2f}%<extra></extra>",
        )
    )
    fig.add_annotation(
        x=iv_min,
        y=0.5,
        text=f"MIN {iv_min:.1f}%",
        showarrow=False,
        yshift=-22,
        font=dict(color=COLORS["muted"], size=10, family=_MONO),
    )
    fig.add_annotation(
        x=iv_max,
        y=0.5,
        text=f"MAX {iv_max:.1f}%",
        showarrow=False,
        yshift=-22,
        font=dict(color=COLORS["muted"], size=10, family=_MONO),
    )

    pct = (iv_now - iv_min) / span * 100.0
    if pct < 20:
        verdict = f"CHEAP · bottom {pct:.0f}% of 52w"
        verdict_color = COLORS["accent"]
    elif pct > 80:
        verdict = f"RICH · top {100 - pct:.0f}% of 52w"
        verdict_color = COLORS["warn"]
    else:
        verdict = f"NORMAL · {pct:.0f}% through 52w"
        verdict_color = COLORS["text"]
    # Plotly accepts HTML in title text; we keep it minimal and inline.
    layout["title"] = dict(
        text=(
            "52-WEEK IV RANGE&nbsp;&nbsp;"
            f"<span style='color:{verdict_color};font-family:{_MONO};font-size:11px;'>● {verdict}</span>"
        ),
        font=dict(color=COLORS["text"], size=14, family=_SANS),
        x=0.01,
        xanchor="left",
    )
    layout["xaxis"]["range"] = [iv_min - 0.05 * span, iv_max + 0.05 * span]
    fig.update_layout(**layout)
    return fig


def create_term_structure_chart(history: pd.DataFrame) -> go.Figure:
    """
    IV term structure for the most recent row — up to 4 points (30d/60d/90d/180d).

    The slope tells the user whether the vol surface is in contango (upward
    sloping, longer-dated richer, calm regime) or backwardation (near-dated
    richer, stress regime). Points with None are skipped; as few as two valid
    points render a useful curve.
    """
    fig = go.Figure()
    layout = _base_layout("IV TERM STRUCTURE")
    layout["height"] = 160
    layout["margin"] = dict(l=48, r=24, t=52, b=40)
    layout["yaxis"]["ticksuffix"] = "%"
    layout["showlegend"] = False

    if history.empty or "iv_30d" not in history.columns:
        fig.update_layout(**layout)
        return fig

    latest = history.iloc[-1]
    _candidates = [(30, latest.get("iv_30d")), (60, latest.get("iv_60d")),
                   (90, latest.get("iv_90d")), (180, latest.get("iv_180d"))]
    pts = [(d, float(v)) for d, v in _candidates
           if v is not None and not pd.isna(v)]

    if len(pts) < 2:
        fig.update_layout(**layout)
        return fig

    xs = [d for d, _ in pts]
    ys = [v for _, v in pts]
    slope = ys[-1] - ys[0]

    # ── Time-travel ghost overlay ──────────────────────────────────────
    # Faint -7d / -30d term-structure curves behind the current one, so the
    # trader sees at a glance whether the whole curve parallel-shifted,
    # twisted, or flattened over the last week / month. Zero new controls,
    # zero new DB queries — just older rows of the same history frame.
    def _row_pts(row) -> list[tuple[int, float]]:
        cand = [(30, row.get("iv_30d")), (60, row.get("iv_60d")),
                (90, row.get("iv_90d")), (180, row.get("iv_180d"))]
        return [(d, float(v)) for d, v in cand
                if v is not None and not pd.isna(v) and d in xs]

    ghost_ys: list[float] = list(ys)
    for _back, _label, _op in ((30, "−30d", 0.32), (7, "−7d", 0.55)):
        if len(history) > _back:
            gpts = _row_pts(history.iloc[-(_back + 1)])
            if len(gpts) >= 2:
                gx = [d for d, _ in gpts]
                gy = [v for _, v in gpts]
                ghost_ys += gy
                fig.add_trace(go.Scatter(
                    x=gx, y=gy, mode="lines+markers",
                    line=dict(color=COLORS["muted"], width=1, dash="dot"),
                    marker=dict(size=5, color=COLORS["muted"]),
                    opacity=_op, hoverinfo="skip", showlegend=False,
                ))
                fig.add_annotation(
                    x=gx[-1], y=gy[-1], text=_label, showarrow=False,
                    xshift=15, font=dict(color=COLORS["muted"], size=8, family=_MONO),
                )

    if slope > 0.5:
        verdict = f"CONTANGO · +{slope:.1f}pt"
        verdict_color = COLORS["accent2"]
        commentary = "longer-dated richer — calm regime"
    elif slope < -0.5:
        verdict = f"BACKWARDATION · {slope:+.1f}pt"
        verdict_color = COLORS["warn"]
        commentary = "near-dated richer — stress signal"
    else:
        verdict = f"FLAT · {slope:+.1f}pt"
        verdict_color = COLORS["muted"]
        commentary = "curve is neutral"

    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers+text",
            line=dict(color=COLORS["accent"], width=2.5),
            marker=dict(
                size=14,
                color=COLORS["accent"],
                line=dict(color=COLORS["bg"], width=2),
                symbol="circle",
            ),
            text=[f"{v:.1f}%" for v in ys],
            textposition="top center",
            textfont=dict(color=COLORS["text"], size=11, family=_MONO),
            hoverinfo="skip",
        )
    )

    tick_labels = {30: "30d", 60: "60d", 90: "90d", 180: "180d"}
    layout["title"] = dict(
        text=(
            "IV TERM STRUCTURE&nbsp;&nbsp;"
            f"<span style='color:{verdict_color};font-family:{_MONO};font-size:11px;'>● {verdict}</span>"
            f"&nbsp;<span style='color:{COLORS['muted']};font-size:10px;'>{commentary}</span>"
        ),
        font=dict(color=COLORS["text"], size=14, family=_SANS),
        x=0.01,
        xanchor="left",
    )
    layout["xaxis"]["tickvals"] = xs
    layout["xaxis"]["ticktext"] = [tick_labels.get(d, f"{d}d") for d in xs]
    layout["xaxis"]["range"] = [xs[0] - 10, xs[-1] + 22]
    # y-range spans current + ghost curves so nothing clips.
    pad = max(1.0, (max(ghost_ys) - min(ghost_ys)) * 0.6)
    layout["yaxis"]["range"] = [min(ghost_ys) - pad, max(ghost_ys) + pad]
    fig.update_layout(**layout)
    return fig


def create_vol_cone_chart(history: pd.DataFrame) -> go.Figure:
    """Volatility cone — realized-vol percentile bands across horizons.

    The cone is the chart a vol trader opens first each morning: it shows,
    for each look-back window (10d … 252d), the 5/25/50/75/95th percentile
    band of that window's own realized vol over the past ~2y, with the
    CURRENT realized vol overlaid as dots. A dot near the top of its band
    means realized vol is historically stretched at that horizon; near the
    bottom means it's compressed. Reads the close series already in the
    daily_vol history frame — no new query.
    """
    from volscope.analytics.vol_cones import compute_vol_cone

    fig = go.Figure()
    layout = _base_layout("VOLATILITY CONE")
    layout["height"] = 300
    layout["margin"] = dict(l=52, r=28, t=52, b=40)
    layout["yaxis"]["ticksuffix"] = "%"
    layout["showlegend"] = False

    if history is None or history.empty or "spot_price" not in history.columns:
        fig.update_layout(**layout)
        return fig
    spot = history["spot_price"].dropna()
    if len(spot) < 30:
        fig.update_layout(**layout)
        return fig

    cone = compute_vol_cone(spot, ticker="X")
    pts = [p for p in cone.points if p.percentiles]
    if len(pts) < 2:
        fig.update_layout(**layout)
        return fig

    xs = [p.window for p in pts]

    def _band(pct: int) -> list:
        return [p.percentiles.get(pct) for p in pts]

    p5, p25, p50, p75, p95 = _band(5), _band(25), _band(50), _band(75), _band(95)

    # 5–95 envelope (light), then 25–75 body (denser) via fill='tonexty'.
    fig.add_trace(go.Scatter(x=xs, y=p95, mode="lines", line=dict(width=0),
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=xs, y=p5, mode="lines", line=dict(width=0),
                             fill="tonexty", fillcolor=rgba(COLORS["accent2"], 0.07),
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=xs, y=p75, mode="lines", line=dict(width=0),
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=xs, y=p25, mode="lines", line=dict(width=0),
                             fill="tonexty", fillcolor=rgba(COLORS["accent2"], 0.16),
                             hoverinfo="skip", showlegend=False))
    # Median line.
    fig.add_trace(go.Scatter(x=xs, y=p50, mode="lines",
                             line=dict(color=COLORS["muted"], width=1.5, dash="dash"),
                             hoverinfo="skip", showlegend=False))

    # Current realized-vol dots, coloured by where they sit in their band.
    cx, cy, ccolor, ctext = [], [], [], []
    for p in pts:
        if p.current_vol is None:
            continue
        perc = p.current_perc
        if perc is not None and perc >= 75:
            col = COLORS["warn"]
        elif perc is not None and perc <= 25:
            col = COLORS["accent"]
        else:
            col = COLORS["text"]
        cx.append(p.window)
        cy.append(p.current_vol)
        ccolor.append(col)
        ctext.append(
            f"{p.window}d · RV {p.current_vol:.1f}%"
            + (f" · {perc:.0f}th pct" if perc is not None else "")
        )
    if cx:
        fig.add_trace(go.Scatter(
            x=cx, y=cy, mode="lines+markers",
            line=dict(color=COLORS["accent"], width=2),
            marker=dict(size=11, color=ccolor, line=dict(color=COLORS["bg"], width=2)),
            text=ctext, hoverinfo="text", showlegend=False,
        ))

    layout["title"] = dict(
        text=(
            "VOLATILITY CONE&nbsp;&nbsp;"
            f"<span style='color:{COLORS['muted']};font-family:{_MONO};font-size:10px;'>"
            f"{cone.summary}</span>"
        ),
        font=dict(color=COLORS["text"], size=14, family=_SANS),
        x=0.01, xanchor="left",
    )
    layout["xaxis"]["tickvals"] = xs
    layout["xaxis"]["ticktext"] = [f"{w}d" for w in xs]
    fig.update_layout(**layout)
    return fig


def create_command_term_structure(tickers_data: dict[str, dict]) -> go.Figure:
    """
    Multi-ticker term structure chart for the Command Center.

    For each ticker we draw a curve across up to 4 points (30d/60d/90d/180d).
    Blue = contango (calm, longer-dated richer), amber = backwardation (stress,
    near-dated richer). Multiple curves on one axis make relative slopes
    instantly readable — you can see at a glance which positions are in stress.

    Tickers with fewer than 2 valid IV points are silently skipped.
    """
    fig = go.Figure()
    layout = _base_layout("TERM STRUCTURE — YOUR MARKETS")
    layout["height"] = 280
    layout["yaxis"]["ticksuffix"] = "%"
    layout["hovermode"] = "closest"
    layout["showlegend"] = True
    layout["legend"] = dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(family=_MONO, size=10, color=COLORS["muted"]),
        x=1.0,
        xanchor="right",
        y=1.0,
    )

    has_data = False
    all_xs: list[int] = []
    for ticker, row in tickers_data.items():
        _candidates = [(30, row.get("iv_30d")), (60, row.get("iv_60d")),
                       (90, row.get("iv_90d")), (180, row.get("iv_180d"))]
        pts = [(d, float(v)) for d, v in _candidates
               if v is not None and not pd.isna(v)]
        if len(pts) < 2:
            continue

        xs = [d for d, _ in pts]
        ys = [v for _, v in pts]
        all_xs.extend(xs)
        color = COLORS["accent2"] if ys[-1] >= ys[0] else COLORS["amber"]
        has_data = True
        text_labels = [f"{ys[0]:.1f}"] + [""] * (len(ys) - 2) + [f"{ys[-1]:.1f}%"]
        text_pos = ["middle left"] + ["top center"] * (len(ys) - 2) + ["middle right"]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines+markers+text",
                name=ticker,
                line=dict(color=color, width=2.5),
                marker=dict(
                    size=10,
                    color=color,
                    line=dict(color=COLORS["bg"], width=1.5),
                ),
                text=text_labels,
                textposition=text_pos,
                textfont=dict(color=color, size=10, family=_MONO),
                hovertemplate=f"{ticker}  %{{x}}d → %{{y:.1f}}%<extra></extra>",
            )
        )

    if not has_data:
        layout["title"]["text"] = "TERM STRUCTURE — no data yet (run scrape)"
        # Fall back to showing the full 4-point axis so the chart isn't empty
        layout["xaxis"]["tickvals"] = [30, 60, 90, 180]
        layout["xaxis"]["ticktext"] = ["30d", "60d", "90d", "180d"]
        layout["xaxis"]["range"] = [20, 195]
    else:
        # Dynamic axis: show only the maturities that actually have data.
        unique_xs = sorted(set(all_xs))
        tick_labels = {30: "30d", 60: "60d", 90: "90d", 180: "180d"}
        layout["xaxis"]["tickvals"] = unique_xs
        layout["xaxis"]["ticktext"] = [tick_labels.get(d, f"{d}d") for d in unique_xs]
        pad = max(5, (unique_xs[-1] - unique_xs[0]) * 0.12)
        layout["xaxis"]["range"] = [unique_xs[0] - pad, unique_xs[-1] + pad]

    fig.update_layout(**layout)
    return fig


def create_vrp_bar(tickers_data: dict[str, dict]) -> go.Figure:
    """
    Horizontal bar chart of IV/RV ratio (Variance Risk Premium) per ticker.

    Ratio = iv_30d / hv_20d:
        < 0.9  → green  (options cheap vs realized — buying vol is favored)
        > 1.1  → red    (options rich — selling vol is favored)
        0.9–1.1 → gray  (neutral)

    A reference line at 1.0 marks fair value. This answers in one glance
    whether the options market is over- or under-pricing realized risk.
    """
    fig = go.Figure()
    layout = _base_layout("IV / RV RATIO  (VRP)")
    layout["height"] = 280
    layout["hovermode"] = "y unified"
    layout["margin"] = dict(l=80, r=36, t=52, b=40)
    layout["showlegend"] = False
    # Horizontal bar — ticker labels belong on the LEFT, not on the right
    # like a price axis. Override the global default.
    layout["yaxis"]["side"] = "left"
    layout["xaxis"]["title"] = dict(
        text="iv_30d / hv_20d",
        font=dict(size=10, color=COLORS["muted"]),
    )

    tickers_list: list[str] = []
    ratios: list[float] = []
    colors: list[str] = []

    for ticker, row in tickers_data.items():
        iv30 = row.get("iv_30d")
        hv20 = row.get("hv_20d")
        if iv30 is None or hv20 is None or pd.isna(iv30) or pd.isna(hv20):
            continue
        iv30_f, hv20_f = float(iv30), float(hv20)
        if hv20_f <= 0:
            continue
        ratio = iv30_f / hv20_f
        tickers_list.append(ticker)
        ratios.append(ratio)
        if ratio < 0.9:
            colors.append(COLORS["accent"])
        elif ratio > 1.1:
            colors.append(COLORS["warn"])
        else:
            colors.append(COLORS["muted"])

    if not tickers_list:
        layout["title"]["text"] = "IV / RV RATIO — no data yet"
        fig.update_layout(**layout)
        return fig

    fig.add_trace(
        go.Bar(
            x=ratios,
            y=tickers_list,
            orientation="h",
            marker_color=colors,
            marker_line_width=0,
            hovertemplate="%{y}  VRP · %{x:.2f}×<extra></extra>",
        )
    )
    fig.add_vline(
        x=1.0,
        line=dict(color=COLORS["text"], width=1.5, dash="dot"),
        annotation=dict(
            text="FAIR",
            font=dict(color=COLORS["muted"], size=9, family=_MONO),
            bgcolor=COLORS["card"],
            borderpad=2,
        ),
        annotation_position="top",
    )
    fig.update_layout(**layout)
    return fig


def create_percentile_chart(
    history: pd.DataFrame, earnings_dates: list | None = None
) -> go.Figure:
    fig = go.Figure()
    if (
        history.empty
        or "iv_percentile" not in history.columns
        or not history["iv_percentile"].notna().any()
    ):
        fig.update_layout(**_base_layout("IV PERCENTILE — 52 WEEKS (no data)"))
        return fig
    x = history["date"] if "date" in history.columns else history.index

    # Shaded background zones — green below 20 (cheap), red above 80 (rich).
    fig.add_hrect(
        y0=0,
        y1=20,
        fillcolor="rgba(0,212,170,0.10)",
        line_width=0,
        layer="below",
    )
    fig.add_hrect(
        y0=80,
        y1=100,
        fillcolor="rgba(255,68,102,0.10)",
        line_width=0,
        layer="below",
    )

    fig.add_trace(
        go.Scatter(
            x=x,
            y=history["iv_percentile"],
            fill="tozeroy",
            mode="lines",
            line=dict(color=COLORS["accent2"], width=1.8),
            fillcolor="rgba(91,140,255,0.15)",
            name="IV Percentile",
        )
    )
    fig.add_hline(
        y=20,
        line=dict(color=COLORS["accent"], width=1, dash="dot"),
        annotation=dict(
            text="CHEAP", font=dict(color=COLORS["accent"], size=9, family=_MONO)
        ),
        annotation_position="top right",
    )
    fig.add_hline(
        y=80,
        line=dict(color=COLORS["warn"], width=1, dash="dot"),
        annotation=dict(
            text="RICH", font=dict(color=COLORS["warn"], size=9, family=_MONO)
        ),
        annotation_position="bottom right",
    )
    _add_earnings_markers(fig, earnings_dates)
    _add_today_gap(fig, history, label="STALE")
    layout = _base_layout("IV PERCENTILE — 52 WEEKS")
    layout["yaxis"]["range"] = [0, 100]
    layout["yaxis"]["ticksuffix"] = "%"
    fig.update_layout(**layout)
    return fig


def create_intraday_price_chart(
    bars: pd.DataFrame,
    ticker: str,
    timeframe: str = "1D",
) -> go.Figure:
    """
    Price + volume chart for intraday (1D / 5D) or monthly (1M) bars.

    `bars` must have columns: Open, High, Low, Close, Volume with a
    DatetimeIndex. When the DataFrame is empty, returns an empty figure.

    timeframe is used only for the title label.
    """
    fig = go.Figure()
    layout = _base_layout(f"PRICE — {ticker}  [{timeframe}]")
    layout["height"] = 260
    layout["margin"] = dict(l=48, r=24, t=52, b=40)

    if bars is None or bars.empty:
        fig.update_layout(**layout)
        return fig

    needed = {"Open", "High", "Low", "Close"}
    if not needed.issubset(bars.columns):
        fig.update_layout(**layout)
        return fig

    has_volume = "Volume" in bars.columns and bars["Volume"].notna().any()

    # Direction colour for the line — green if last close ≥ first open
    # (period up), red otherwise. Subtle area fill underneath the line.
    open_first = float(bars["Open"].iloc[0])
    close_last = float(bars["Close"].iloc[-1])
    is_up = close_last >= open_first
    line_color = COLORS["accent"] if is_up else COLORS["warn"]
    fill_color = rgba(line_color, 0.07)

    # Use a price LINE chart (close prices) — user-requested over
    # candlesticks. Cleaner read on intraday + monthly views, lets
    # multi-day comparisons surface the overall trajectory.
    price_trace = go.Scatter(
        x=bars.index,
        y=bars["Close"],
        mode="lines",
        line=dict(color=line_color, width=2.0, shape="spline"),
        fill="tozeroy",
        fillcolor=fill_color,
        name="Close",
        hovertemplate="$%{y:.2f}<extra></extra>",
    )

    if has_volume:
        from plotly.subplots import make_subplots
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.78, 0.22],
            vertical_spacing=0.03,
        )
        fig.add_trace(price_trace, row=1, col=1)

        # Volume bars below — coloured per bar by intraday direction.
        bar_colors = [
            COLORS["accent"] if float(c) >= float(o) else COLORS["warn"]
            for o, c in zip(bars["Open"], bars["Close"])
        ]
        fig.add_trace(
            go.Bar(
                x=bars.index,
                y=bars["Volume"],
                marker_color=bar_colors,
                marker_line_width=0,
                name="Volume",
                opacity=0.45,
                showlegend=False,
                hovertemplate="Vol %{y:,.0f}<extra></extra>",
            ),
            row=2, col=1,
        )

        # Sane Y-range — start near min(close) instead of 0 so the line
        # uses the chart's vertical real estate. Padding 2 % each side.
        y_min = float(bars["Close"].min())
        y_max = float(bars["Close"].max())
        pad = (y_max - y_min) * 0.05 if y_max > y_min else max(0.5, y_max * 0.01)

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=280,
            margin=dict(l=12, r=44, t=28, b=28),
            title=dict(
                text=f"PRICE — {ticker}  [{timeframe}]",
                font=dict(color=COLORS["label"], size=11, family=_SANS),
                x=0.0, xanchor="left", y=0.97,
            ),
            font=dict(color=COLORS["text"], family=_MONO, size=10),
            xaxis=dict(
                rangeslider=dict(visible=False),
                gridcolor="rgba(255,255,255,0.03)",
                tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            ),
            xaxis2=dict(
                gridcolor="rgba(255,255,255,0.03)",
                tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            ),
            yaxis=dict(
                gridcolor="rgba(255,255,255,0.03)",
                tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
                side="right",
                range=[y_min - pad, y_max + pad],
                tickformat="$,.2f",
            ),
            yaxis2=dict(
                gridcolor="rgba(255,255,255,0.03)",
                tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
                side="right",
                showticklabels=True,
            ),
            hovermode="x unified",
            hoverlabel=dict(
                bgcolor="rgba(13,14,20,0.95)",
                bordercolor=COLORS["border"],
                font=dict(family=_MONO, size=11, color=COLORS["text"]),
            ),
            showlegend=False,
        )
    else:
        fig = go.Figure()
        fig.add_trace(price_trace)
        y_min = float(bars["Close"].min())
        y_max = float(bars["Close"].max())
        pad = (y_max - y_min) * 0.05 if y_max > y_min else max(0.5, y_max * 0.01)
        layout["xaxis"]["rangeslider"] = dict(visible=False)
        layout["yaxis"]["range"] = [y_min - pad, y_max + pad]
        layout["yaxis"]["tickformat"] = "$,.2f"
        layout["yaxis"].pop("ticksuffix", None)
        layout["yaxis"].pop("tickprefix", None)
        fig.update_layout(**layout)

    return fig


def create_sector_heatmap(
    sector_history: pd.DataFrame,
    window_label: str = "3M",
) -> go.Figure:
    """
    Sector rotation heatmap: y=sectors, x=dates, color=median_iv_percentile.

    Green = cheap vol, red = rich vol. Used on the Rotation page.
    `sector_history` must have columns: sector, date, median_perc.
    `window_label` is shown in the title for context only.
    """
    if sector_history is None or sector_history.empty:
        fig = go.Figure()
        fig.update_layout(
            **_base_layout(f"Sector Vol Heatmap — {window_label}"),
            height=280,
        )
        return fig

    df = sector_history.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["median_perc"] = pd.to_numeric(df["median_perc"], errors="coerce")

    pivot = df.pivot_table(index="sector", columns="date", values="median_perc", aggfunc="median")
    pivot = pivot.sort_index()
    # Densify: most "sparse" cells come from a single missing scrape, not from
    # the sector actually having no data. Forward-fill along the time axis
    # within each sector, then backward-fill for the leading edge. NaN cells
    # only remain when the sector was never scraped — those stay visibly empty.
    if not pivot.empty:
        pivot = pivot.ffill(axis=1).bfill(axis=1)

    # Custom colorscale: green (cheap) → amber (normal) → red (rich)
    colorscale = [
        [0.0, "#00d4aa"],
        [0.2, "#00d4aa"],
        [0.5, "#8a8f9e"],
        [0.8, "#ff9f43"],
        [1.0, "#ff4466"],
    ]

    hover_text = []
    for sector in pivot.index:
        row_hover = []
        for dt in pivot.columns:
            val = pivot.loc[sector, dt]
            val_str = f"{val:.0f}" if pd.notna(val) else "—"
            row_hover.append(f"<b>{sector}</b><br>{dt.strftime('%Y-%m-%d')}<br>IV Pct: {val_str}")
        hover_text.append(row_hover)

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[d.strftime("%Y-%m-%d") for d in pivot.columns],
            y=list(pivot.index),
            colorscale=colorscale,
            zmin=0,
            zmax=100,
            hoverinfo="text",
            text=hover_text,
            colorbar=dict(
                title=dict(text="IV Pct", font=dict(color=COLORS["muted"], size=10, family=_MONO)),
                tickfont=dict(color=COLORS["muted"], size=9, family=_MONO),
                thickness=10,
                len=0.8,
            ),
        )
    )

    layout = _base_layout(f"Sector Vol Heatmap — {window_label}")
    layout.update(
        height=max(260, 36 * len(pivot.index) + 80),
        xaxis=dict(
            gridcolor=COLORS["border"],
            tickfont=dict(family=_MONO, size=9, color=COLORS["muted"]),
            nticks=8,
        ),
        yaxis=dict(
            gridcolor=COLORS["border"],
            tickfont=dict(family=_MONO, size=10, color=COLORS["muted"]),
            autorange="reversed",
        ),
        margin=dict(l=130, r=60, t=52, b=40),
    )
    fig.update_layout(**layout)
    return fig


def create_skew_chart(history: pd.DataFrame) -> go.Figure:
    """
    25-delta skew over time: put_IV(25Δ) minus call_IV(25Δ).

    Positive = put-rich (normal equity skew). Negative = call-rich (unusual).
    A horizontal reference line at y=0 marks the neutral level.

    Title is color-coded: RICH (>5pt) in warn color, CHEAP (<-5pt) in accent,
    neutral (-2 to +2) labeled 'neutral'.
    """
    fig = go.Figure()
    layout = _base_layout("25Δ SKEW (no data)")
    layout["height"] = 180
    layout["margin"] = dict(l=48, r=24, t=52, b=40)
    layout["yaxis"]["ticksuffix"] = "pt"
    layout["showlegend"] = False

    if history.empty or "iv_skew_25d" not in history.columns:
        fig.update_layout(**layout)
        return fig

    df = history.dropna(subset=["iv_skew_25d"])
    if df.empty:
        fig.update_layout(**layout)
        return fig

    x = df["date"] if "date" in df.columns else df.index
    y = df["iv_skew_25d"].astype(float)
    latest = float(y.iloc[-1])

    if latest > 5.0:
        label = f"RICH · {latest:+.1f}pt"
        label_color = COLORS["warn"]
    elif latest < -5.0:
        label = f"CHEAP · {latest:+.1f}pt"
        label_color = COLORS["accent"]
    elif -2.0 < latest < 2.0:
        label = f"neutral · {latest:+.1f}pt"
        label_color = COLORS["muted"]
    else:
        label = f"{latest:+.1f}pt"
        label_color = COLORS["text"]

    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            line=dict(color=COLORS["accent2"], width=2),
            hovertemplate="Skew · %{y:+.1f}pt<extra></extra>",
        )
    )
    fig.add_shape(
        type="line",
        x0=x.iloc[0],
        x1=x.iloc[-1],
        y0=0.0,
        y1=0.0,
        xref="x",
        yref="y",
        line=dict(color=COLORS["muted"], width=1, dash="dot"),
    )
    _add_today_gap(fig, history, label="STALE")

    layout["title"] = dict(
        text=(
            "25Δ SKEW&nbsp;&nbsp;"
            f"<span style='color:{label_color};font-family:{_MONO};font-size:11px;'>● {label}</span>"
        ),
        font=dict(color=COLORS["text"], size=14, family=_SANS),
        x=0.01,
        xanchor="left",
    )
    layout["xaxis"]["rangeselector"] = _range_selector()
    fig.update_layout(**layout)
    return fig


# ── Backtest charts ───────────────────────────────────────────────────────────

# Category → color for backtest charts
_BT_COLORS = {
    "buy":       "#26de81",   # green
    "lean_buy":  "#9be6c6",   # pale green
    "neutral":   "#8a8f9e",   # gray
    "lean_rich": "#ffb347",   # amber
    "rich":      "#ff4466",   # red
}


def create_backtest_hit_rate_chart(rolling_df: pd.DataFrame) -> go.Figure:
    """
    Rolling 3-month BUY-signal hit rate over time.

    Parameters
    ----------
    rolling_df : DataFrame with columns date and hit_rate (from
                 volscope.analytics.backtest.rolling_hit_rate).
    """
    fig = go.Figure()
    layout = _base_layout("ROLLING HIT RATE (BUY signals, 3-month window)")
    layout["height"] = 220
    layout["yaxis"]["tickformat"] = ".0%"
    layout["yaxis"]["range"] = [0, 1]
    layout["showlegend"] = False

    if rolling_df.empty:
        fig.update_layout(**layout)
        return fig

    fig.add_trace(
        go.Scatter(
            x=rolling_df["date"],
            y=rolling_df["hit_rate"],
            mode="lines",
            line=dict(color=_BT_COLORS["buy"], width=2),
            fill="tozeroy",
            fillcolor="rgba(38,222,129,0.08)",
            hovertemplate="Hit Rate · %{y:.0%}<extra></extra>",
        )
    )
    # 50% reference line
    fig.add_shape(
        type="line",
        x0=rolling_df["date"].iloc[0],
        x1=rolling_df["date"].iloc[-1],
        y0=0.5,
        y1=0.5,
        xref="x",
        yref="y",
        line=dict(color=COLORS["muted"], width=1, dash="dot"),
    )
    layout["xaxis"]["rangeselector"] = _range_selector()
    fig.update_layout(**layout)
    return fig


def create_backtest_distribution_chart(signals_df: pd.DataFrame) -> go.Figure:
    """
    Histogram of iv_change_pct grouped by signal category.

    Shows how IV moved (positive = rose, negative = fell) in the hold window
    following each signal type. BUY bars are green, RICH bars red, WAIT gray.
    """
    fig = go.Figure()
    layout = _base_layout("IV CHANGE DISTRIBUTION by signal (hold period)")
    layout["height"] = 260
    layout["xaxis"]["ticksuffix"] = "%"
    layout["xaxis"]["title"] = dict(text="IV change % over hold window", font=dict(size=10))
    layout["barmode"] = "overlay"
    layout["showlegend"] = True

    if signals_df.empty:
        fig.update_layout(**layout)
        return fig

    cat_labels = {
        "buy": "BUY VOL",
        "lean_buy": "LEAN BUY",
        "neutral": "WAIT",
        "lean_rich": "LEAN RICH",
        "rich": "RICH",
    }
    for cat in ("buy", "lean_buy", "neutral", "lean_rich", "rich"):
        sub = signals_df[signals_df["signal_cat"] == cat]["iv_change_pct"].dropna()
        if sub.empty:
            continue
        fig.add_trace(
            go.Histogram(
                x=sub,
                name=cat_labels[cat],
                marker_color=_BT_COLORS[cat],
                opacity=0.65,
                nbinsx=30,
                hovertemplate=cat_labels[cat] + " · count %{y}<extra></extra>",
            )
        )

    fig.update_layout(**layout)
    return fig
