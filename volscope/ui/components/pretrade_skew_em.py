"""UI rendering for the Skew-Adjusted Expected Move + Front/Back IV +
OI Heatmap suite. Designed to drop into Pre-Trade or Options Lab.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go

from volscope.analytics.expected_move_skew import (
    compute_skew_adjusted_em,
)
from volscope.analytics.front_back_iv import (
    decompose_front_back_iv,
)
from volscope.analytics.oi_heatmap import compute_oi_heatmap
from volscope.ui.components.glossary import glossary
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS


def _esc_attr(s: str) -> str:
    """HTML-attribute-safe (just escape the double-quote that ends title=)."""
    return (s or "").replace('"', "'")


def render_skew_em_block(
    st, ticker: str, chain_df: pd.DataFrame, *, spot: float, dte_days: int,
) -> None:
    """Asymmetric Expected Move card with skew interpretation."""
    def _no_data(reason: str) -> None:
        # Surface WHY the card is empty instead of returning silently —
        # the live option chain is the usual culprit (Yahoo rate-limit,
        # weekend, or a chain with no per-strike IV / delta).
        render_html(
            st,
            f'<div style="background:{COLORS["surface"]};border:1px solid '
            f'{COLORS["border"]};border-left:3px solid {COLORS["amber"]};'
            f'border-radius:6px;padding:12px 16px;margin:10px 0;'
            f'font-family:JetBrains Mono,monospace;font-size:11px;'
            f'color:{COLORS["muted"]};">Skew-adjusted expected move '
            f'unavailable for {ticker} — {reason}. The live option chain '
            f'(yfinance) may be rate-limited or thin right now; try again '
            f'shortly.</div>',
        )

    if chain_df is None or chain_df.empty:
        _no_data("no live option-chain rows returned")
        return
    em = compute_skew_adjusted_em(chain_df, spot=spot, dte_days=dte_days)
    if em is None or (em.upside_pct is None and em.downside_pct is None):
        _no_data("the chain lacks usable per-strike IV")
        return

    skew_color = COLORS["warn"] if (em.skew_25d or 0) > 5 else COLORS["accent"]
    asym = em.asymmetry_ratio()
    asym_str = f"{asym:.2f}×" if asym else "n/a"

    # Tooltips via title= attribute on each cell — all wording sourced
    # from glossary.py (master plan §3 Stream A).
    tt_skew     = _esc_attr(glossary("iv_skew_25d"))
    tt_em_skew  = _esc_attr(glossary("expected_move_skew_adjusted"))
    tt_em_naive = _esc_attr(glossary("expected_move"))
    render_html(
        st,
        f'<div style="background:{COLORS["surface"]};border:1px solid {COLORS["border"]};'
        f'border-left:3px solid {skew_color};border-radius:6px;padding:14px 18px;'
        f'margin:10px 0;font-family:DM Sans,sans-serif;" title="{tt_em_skew}">'
        f'<div style="color:{skew_color};font-weight:700;letter-spacing:0.5px;'
        f'font-size:12px;margin-bottom:6px;">SKEW-ADJUSTED EXPECTED MOVE · '
        f'{ticker} · {dte_days}d</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;'
        f'font-family:JetBrains Mono,monospace;font-size:12px;'
        f'color:{COLORS["text"]};">'
        f'<div title="{tt_skew}"><span style="color:{COLORS["muted"]};">25Δ Skew</span><br>'
        f'<b>{em.skew_25d:+.1f} vol-pts</b></div>'
        f'<div title="{tt_em_skew}"><span style="color:{COLORS["muted"]};">Upside (25Δ Call)</span><br>'
        f'<b style="color:{COLORS["accent"]};">+{em.upside_pct:.2f}% · ${em.em_dollar_up:.2f}</b></div>'
        f'<div title="{tt_em_skew}"><span style="color:{COLORS["muted"]};">Downside (25Δ Put)</span><br>'
        f'<b style="color:{COLORS["warn"]};">-{em.downside_pct:.2f}% · ${em.em_dollar_down:.2f}</b></div>'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};font-size:11px;margin-top:8px;'
        f'font-family:JetBrains Mono,monospace;" title="{tt_em_naive}">'
        f'Naive symmetric EM: ±{em.em_symmetric_pct:.2f}%   '
        f'   asymmetry: {asym_str}   '
        f'   {"put-skewed → downside richer" if em.is_put_skewed() else "balanced / call-skewed"}'
        f'</div></div>',
    )


def render_front_back_block(
    st, ticker: str, *,
    front_iv: Optional[float],
    front_dte: Optional[int],
    back_iv: Optional[float],
    back_dte: Optional[int],
) -> None:
    """Event-premium extraction from front-vs-back month IVs."""
    if front_iv is None or back_iv is None or front_dte is None or back_dte is None:
        return
    decomp = decompose_front_back_iv(
        front_iv=front_iv, front_dte=front_dte,
        back_iv=back_iv, back_dte=back_dte,
    )
    if decomp is None:
        return
    edge_color = (
        COLORS["warn"] if decomp.raw_spread >= 30 else
        COLORS["amber"] if decomp.raw_spread >= 15 else
        COLORS["accent"]
    )
    event_iv_str = (
        f"{decomp.event_premium_iv:.0f}%" if decomp.event_premium_iv else "n/a"
    )
    tt_front = _esc_attr(glossary("iv_30d"))
    tt_back  = _esc_attr(glossary("iv_90d"))
    tt_event = _esc_attr(glossary("event_premium_iv"))
    render_html(
        st,
        f'<div style="background:{COLORS["surface"]};border:1px solid {COLORS["border"]};'
        f'border-left:3px solid {edge_color};border-radius:6px;padding:14px 18px;'
        f'margin:10px 0;font-family:DM Sans,sans-serif;" title="{tt_event}">'
        f'<div style="color:{edge_color};font-weight:700;letter-spacing:0.5px;'
        f'font-size:12px;margin-bottom:6px;">FRONT vs BACK IV · {ticker}</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:18px;'
        f'font-family:JetBrains Mono,monospace;font-size:12px;'
        f'color:{COLORS["text"]};">'
        f'<div title="{tt_front}"><span style="color:{COLORS["muted"]};">Front ({decomp.front_dte}d)</span><br>'
        f'<b>{decomp.front_iv:.0f}%</b></div>'
        f'<div title="{tt_back}"><span style="color:{COLORS["muted"]};">Back ({decomp.back_dte}d)</span><br>'
        f'<b>{decomp.back_iv:.0f}%</b></div>'
        f'<div><span style="color:{COLORS["muted"]};">Raw spread</span><br>'
        f'<b style="color:{edge_color};">{decomp.raw_spread:+.0f} vol-pts</b></div>'
        f'<div title="{tt_event}"><span style="color:{COLORS["muted"]};">Isolated event-IV</span><br>'
        f'<b style="color:{edge_color};">{event_iv_str}</b></div>'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};font-size:11px;margin-top:8px;line-height:1.5;">'
        f'{decomp.interpretation}'
        f'</div></div>',
    )


def render_oi_heatmap_block(
    st, ticker: str, chain_df: pd.DataFrame, *, spot: Optional[float] = None,
) -> None:
    """Bar chart of OI by strike with put / call coloring + max-pain marker."""
    result = compute_oi_heatmap(chain_df)
    if result is None or result.by_strike.empty:
        return
    by_strike = result.by_strike

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=by_strike["strike"],
        y=by_strike["put_oi"],
        name="Put OI",
        marker_color=COLORS.get("warn", "#ff4466"),
        opacity=0.85,
    ))
    fig.add_trace(go.Bar(
        x=by_strike["strike"],
        y=by_strike["call_oi"],
        name="Call OI",
        marker_color=COLORS.get("accent", "#00d4aa"),
        opacity=0.85,
    ))
    shapes = []
    annotations = []
    if result.max_pain_strike is not None:
        shapes.append(dict(
            type="line",
            x0=result.max_pain_strike, x1=result.max_pain_strike,
            y0=0, y1=1, yref="paper",
            line=dict(color=COLORS.get("text", "#fff"), dash="dot", width=1.5),
        ))
        annotations.append(dict(
            x=result.max_pain_strike, y=1.02, yref="paper",
            text=f"max pain {result.max_pain_strike:.0f}",
            showarrow=False, font=dict(size=10, color=COLORS.get("text", "#fff")),
        ))
    if spot is not None:
        shapes.append(dict(
            type="line",
            x0=spot, x1=spot, y0=0, y1=1, yref="paper",
            line=dict(color=COLORS.get("amber", "#ff9f43"), width=1.5),
        ))
        annotations.append(dict(
            x=spot, y=1.07, yref="paper",
            text=f"spot {spot:.2f}",
            showarrow=False, font=dict(size=10, color=COLORS.get("amber", "#ff9f43")),
        ))
    fig.update_layout(
        barmode="group",
        paper_bgcolor=COLORS.get("bg", "#0a0b14"),
        plot_bgcolor=COLORS.get("bg", "#0a0b14"),
        height=320,
        margin=dict(l=12, r=12, t=44, b=20),
        shapes=shapes,
        annotations=annotations,
        legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center"),
        xaxis=dict(title="Strike", color=COLORS.get("muted", "#8a8f9e"), gridcolor=COLORS.get("border", "#2a2d3e")),
        yaxis=dict(title="Open Interest", color=COLORS.get("muted", "#8a8f9e"), gridcolor=COLORS.get("border", "#2a2d3e")),
    )
    tt_oi   = _esc_attr(glossary("total_open_interest"))
    tt_pcr  = _esc_attr(glossary("put_call_ratio"))
    tt_pain = _esc_attr(glossary("max_pain"))

    # v0.9.11 — None-safe formatting. Vol Insights crashed the whole
    # page with "TypeError: unsupported format string passed to
    # NoneType.__format__" whenever the chain had no puts (or no
    # calls) — overall_pcr returns None in that case. Operator hit
    # this repeatedly on 2026-05-19 ("VOLINSIGHTS DAUERFEHLER!!").
    def _fmt_int(v):
        return f"{v:,}" if isinstance(v, (int, float)) and v is not None else "—"
    def _fmt_pcr(v):
        return f"{v:.2f}" if isinstance(v, (int, float)) and v is not None else "—"
    def _fmt_strike(v):
        if v is None: return "—"
        try: return f"${float(v):,.0f}"
        except Exception: return "—"

    render_html(
        st,
        f'<div style="color:{COLORS["accent2"] if "accent2" in COLORS else COLORS["accent"]};'
        f'font-weight:700;letter-spacing:0.5px;font-size:12px;margin:14px 0 4px;'
        f'font-family:DM Sans,sans-serif;" title="{tt_oi}">OI HEATMAP · {ticker}</div>'
        f'<div style="color:{COLORS["muted"]};font-size:11px;'
        f'font-family:JetBrains Mono,monospace;margin-bottom:4px;" title="{tt_pcr}">'
        f'Total Call OI: {_fmt_int(result.total_call_oi)}   '
        f'· Total Put OI: {_fmt_int(result.total_put_oi)}   '
        f'· PCR: {_fmt_pcr(result.overall_pcr)}   '
        f'· support {_fmt_strike(result.support_strike)}   '
        f'· resistance {_fmt_strike(result.resistance_strike)}'
        f'</div>',
    )
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
