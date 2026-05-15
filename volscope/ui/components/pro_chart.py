"""
Pro Chart — TradingView/IBKR-grade candlestick + volume + IV overlay.

Single public entry point ``render_pro_chart(df, …)`` returns a
``plotly.graph_objects.Figure``. The caller hands it to Streamlit via
``st.plotly_chart(fig, width='stretch')``.

Architecture
------------
- 3-row subplot when an IV column is requested (price / volume / IV)
- 2-row subplot otherwise (price / volume)
- Y-axis on the RIGHT for the price row (IBKR convention)
- Range-selector buttons (1M, 3M, 6M, YTD, 1Y, 2Y, ALL)
- Hidden range-slider (Streamlit page space is precious)
- Spike lines + crosshair on hover
- Hidden weekends + holidays via ``rangebreaks``
- All colours sourced from ``volscope.ui.styles.theme.COLORS``
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from volscope.ui.styles.theme import COLORS, rgba

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"
_SANS = "DM Sans, -apple-system, sans-serif"

# Range-selector buttons — match TradingView's defaults
_RANGE_BUTTONS = [
    dict(count=1,  label="1M",  step="month", stepmode="backward"),
    dict(count=3,  label="3M",  step="month", stepmode="backward"),
    dict(count=6,  label="6M",  step="month", stepmode="backward"),
    dict(count=1,  label="YTD", step="year",  stepmode="todate"),
    dict(count=1,  label="1Y",  step="year",  stepmode="backward"),
    dict(count=2,  label="2Y",  step="year",  stepmode="backward"),
    dict(step="all", label="ALL"),
]


def render_pro_chart(
    df: pd.DataFrame,
    title: str,
    *,
    iv_column: Optional[str] = "iv_30d",
    show_volume: bool = True,
    show_range_selector: bool = True,
    height: int = 700,
    currency_prefix: str = "$",
) -> go.Figure:
    """
    Build a production-grade candlestick figure.

    Parameters
    ----------
    df
        DataFrame indexed by ``date`` (or with a ``date`` column).
        Required columns: ``open, high, low, close``. Optional:
        ``volume`` and the IV column named in ``iv_column``.
    title
        Top-left chart title (rendered small, label-grey).
    iv_column
        Name of the column to plot as the IV overlay. Pass ``None`` to
        skip the IV row entirely.
    show_volume
        When True, render the volume bars in their own subplot row.
    show_range_selector
        When True, expose 1M/3M/6M/YTD/1Y/2Y/ALL buttons above the chart.
    height
        Total figure height in px. Defaults to 700 for a full-page
        view; pass ~360 for embedding inside another page.
    currency_prefix
        ``$`` for USD, ``€`` for EUR. Drives the y-axis tick prefix.
    """
    df = _normalize_frame(df)
    has_iv = (
        iv_column is not None
        and iv_column in df.columns
        and df[iv_column].notna().any()
    )
    has_volume = (
        show_volume
        and "volume" in df.columns
        and df["volume"].notna().any()
    )

    # ── Subplot layout — collapses cleanly when an extra row is absent.
    row_specs = [[dict(secondary_y=False)]]
    row_heights = [1.0]
    if has_volume:
        row_specs.append([dict(secondary_y=False)])
        row_heights.append(0.18)
    if has_iv:
        row_specs.append([dict(secondary_y=False)])
        row_heights.append(0.18)
    # Re-normalise so price row keeps the dominant share
    if len(row_heights) > 1:
        remaining = 1.0 - sum(row_heights[1:])
        row_heights = [remaining] + row_heights[1:]

    fig = make_subplots(
        rows=len(row_specs),
        cols=1,
        shared_xaxes=True,
        row_heights=row_heights,
        vertical_spacing=0.02,
        specs=row_specs,
    )

    # ── Candlesticks (row 1) ────────────────────────────────────────
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            increasing_line_color=COLORS["candle_up"],
            decreasing_line_color=COLORS["candle_down"],
            increasing_fillcolor=COLORS["candle_up"],
            decreasing_fillcolor=COLORS["candle_down"],
            line=dict(width=1),
            name="Price",
            showlegend=False,
            hoverlabel=dict(
                bgcolor="rgba(13,14,20,0.95)",
                bordercolor=COLORS["border"],
                font=dict(family=_MONO, size=11, color=COLORS["text"]),
            ),
        ),
        row=1, col=1,
    )

    # ── Volume (row 2) ──────────────────────────────────────────────
    vol_row = None
    iv_row = None
    if has_volume:
        vol_row = 2
        colors = [
            COLORS["candle_up"] if float(c) >= float(o) else COLORS["candle_down"]
            for o, c in zip(df["open"], df["close"])
        ]
        fig.add_trace(
            go.Bar(
                x=df.index, y=df["volume"],
                marker_color=colors,
                marker_line_width=0,
                opacity=0.5,
                showlegend=False,
                name="Volume",
                hovertemplate="Vol %{y:.3s}<extra></extra>",
            ),
            row=vol_row, col=1,
        )

    # ── IV overlay (row 3) ──────────────────────────────────────────
    if has_iv:
        iv_row = 3 if has_volume else 2
        iv_series = df[iv_column].astype(float)
        median = float(iv_series.median())
        q25 = float(iv_series.quantile(0.25))
        q75 = float(iv_series.quantile(0.75))

        # Subtle shaded band 25–75 percentile
        fig.add_trace(
            go.Scatter(
                x=df.index, y=[q75] * len(df.index),
                mode="lines",
                line=dict(color=COLORS["iv_overlay"], width=0),
                showlegend=False, hoverinfo="skip",
            ),
            row=iv_row, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df.index, y=[q25] * len(df.index),
                mode="lines",
                fill="tonexty",
                fillcolor=rgba(COLORS["iv_overlay"], 0.10),
                line=dict(color=COLORS["iv_overlay"], width=0),
                showlegend=False, hoverinfo="skip",
            ),
            row=iv_row, col=1,
        )
        # Median dashed reference
        fig.add_trace(
            go.Scatter(
                x=df.index, y=[median] * len(df.index),
                mode="lines",
                line=dict(color=COLORS["muted"], width=1, dash="dot"),
                showlegend=False,
                hovertemplate=f"median {median:.1f} %<extra></extra>",
            ),
            row=iv_row, col=1,
        )
        # IV line itself
        fig.add_trace(
            go.Scatter(
                x=df.index, y=iv_series,
                mode="lines",
                line=dict(color=COLORS["iv_overlay"], width=2.0, shape="spline"),
                showlegend=False,
                name="IV 30 d",
                hovertemplate="IV %{y:.1f} %<extra></extra>",
            ),
            row=iv_row, col=1,
        )

    # ── Layout ──────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(color=COLORS["label"], size=11, family=_SANS),
            x=0.0, xanchor="left", y=0.985,
        ),
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        margin=dict(l=12, r=58, t=46 if show_range_selector else 28, b=28),
        hovermode="x unified",
        dragmode="zoom",
        hoverlabel=dict(
            bgcolor="rgba(13,14,20,0.95)",
            bordercolor=COLORS["border"],
            font=dict(family=_MONO, size=11, color=COLORS["text"]),
        ),
        showlegend=False,
    )

    # X-axes — hide weekends, optional range selector on the bottom-most axis
    for r in range(1, len(row_specs) + 1):
        fig.update_xaxes(
            row=r, col=1,
            gridcolor="rgba(255,255,255,0.03)",
            tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            rangebreaks=[dict(bounds=["sat", "mon"])],
            showspikes=True,
            spikemode="across",
            spikecolor=COLORS["spike"],
            spikethickness=1,
            spikedash="dot",
        )
    if show_range_selector:
        fig.update_xaxes(
            row=1, col=1,
            rangeslider=dict(visible=False),
            rangeselector=dict(
                buttons=_RANGE_BUTTONS,
                bgcolor="rgba(0,0,0,0)",
                activecolor=rgba(COLORS["candle_up"], 0.18),
                bordercolor=COLORS["border"],
                borderwidth=1,
                font=dict(family=_MONO, size=9, color=COLORS["muted"]),
                x=0.0, y=1.06,
            ),
        )
    else:
        fig.update_xaxes(row=1, col=1, rangeslider=dict(visible=False))

    # Y-axes — RIGHT side for price; thin grid throughout
    price_min = float(df["low"].min())
    price_max = float(df["high"].max())
    pad = (price_max - price_min) * 0.04 if price_max > price_min else 1.0
    fig.update_yaxes(
        row=1, col=1,
        side="right",
        gridcolor="rgba(255,255,255,0.03)",
        tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
        # Use the d3 currency format directive instead of tickprefix so
        # negative ticks render as "-$50" (sign first), not "$-50".
        # The directive maps `$` → user-supplied currency_prefix at runtime.
        tickformat=f"{currency_prefix},.2f" if currency_prefix in ("$",)
                    else f",.2f",
        tickprefix=("" if currency_prefix == "$" else currency_prefix),
        range=[price_min - pad, price_max + pad],
        showspikes=True,
        spikemode="across",
        spikecolor=COLORS["spike"],
        spikethickness=1,
        spikedash="dot",
    )
    if vol_row is not None:
        fig.update_yaxes(
            row=vol_row, col=1,
            side="right",
            gridcolor="rgba(255,255,255,0.03)",
            tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            tickformat="~s",   # SI suffix: 1.5M, 350k, …
            title=dict(
                text="VOL",
                font=dict(family=_SANS, size=8, color=COLORS["label"]),
                standoff=4,
            ),
        )
    if iv_row is not None:
        fig.update_yaxes(
            row=iv_row, col=1,
            side="right",
            gridcolor="rgba(255,255,255,0.03)",
            tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            ticksuffix=" %",
            tickformat=".0f",
            title=dict(
                text="IV",
                font=dict(family=_SANS, size=8, color=COLORS["label"]),
                standoff=4,
            ),
        )

    return fig


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical input: DatetimeIndex + lowercase OHLCV columns.

    Accepts both `date` column and DatetimeIndex; both lower- and
    upper-case column names. Returns a sorted copy.
    """
    if df is None or df.empty:
        return pd.DataFrame(
            index=pd.DatetimeIndex([], name="date"),
            columns=["open", "high", "low", "close", "volume"],
        )
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "date" in df.columns:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    else:
        df.index = pd.to_datetime(df.index)
    return df.sort_index()
