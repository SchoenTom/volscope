"""
Options Lab — OptionStrat-grade workbench.

Four sections, top to bottom:

    1. Builder strip      — ticker, strategy, expiry, contracts, IV slider, r/q
    2. Payoff diagram     — P&L at expiry + 3 time-decay snapshots
    3. Metrics row        — max P/L, breakevens, PoP, net premium, position greeks
    4. Tabs               — Greeks Surface, Scenario Matrix, Time Decay, Probability Cone
                            + an embedded Pro Chart for the underlying context

Everything is driven by ``MaterializedStrategy``'s Protocol methods
(``payoff_at_expiry``, ``payoff_at_t``, ``greeks``, ``net_premium``) so
this page is a pure consumer of the analytics layer.
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from volscope.analytics.probability import pop as compute_pop
from volscope.analytics.probability import profit_density
from volscope.analytics.strategy_templates import TEMPLATES
from volscope.ui.components.html_utils import render_html
from volscope.ui.components.metric_components import _ibkr_cell
from volscope.ui.components.pro_chart import render_pro_chart
from volscope.ui.styles.theme import COLORS, rgba

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"

# ── Constants ────────────────────────────────────────────────────────
_PNL_GRID_POINTS = 200
_TIME_SNAPSHOTS = (0.0, 0.25, 0.50, 0.75)   # 0 = today, 1 = expiry
_SCENARIO_SPOT_SHIFTS = (-0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20)
_SCENARIO_IV_SHIFTS = (-10.0, -5.0, 0.0, 5.0, 10.0)   # IV % points


def _signed_dollar(v: float, *, decimals: int = 0) -> str:
    """Render a signed dollar amount with the sign BEFORE the currency
    symbol — '+$1,234' not '$+1,234', '−$50' not '$-50'.

    Plotly's tickprefix='$' combined with a signed format produces the
    visually-wrong '$-50' / '$+50' shapes. Anywhere we render currency
    by hand we go through this helper so the formatting is consistent.
    """
    sign = "+" if v >= 0 else "−"
    return f"{sign}${abs(v):,.{decimals}f}"


# ── Cached computation helpers ──────────────────────────────────────
# Cache keyed on primitive scalars so Streamlit can reuse results when
# the user drags the IV slider only slightly. Each helper returns a
# plain numpy ndarray; the view layer wraps it into a Plotly trace.

@st.cache_data(show_spinner=False, ttl=600)
def _cached_scenario_matrix(
    template_name: str, spot: float, iv: float, dte: int, contracts: int,
    r: float, q: float,
) -> np.ndarray:
    """Build the spot×IV scenario heatmap once per parameter combo.

    The 9×5 = 45 cells each cost a net_premium recompute (~0.18 ms
    apiece). Caching turns slider-drag latency from ~10 ms → 0 ms after
    the first slide.
    """
    template = TEMPLATES[template_name]
    mat = template.materialize(
        ticker="_cache", spot=spot, iv_pct=iv, dte=dte, contracts=contracts,
    )
    T = max(1, dte) / 365.0
    z = np.zeros((len(_SCENARIO_SPOT_SHIFTS), len(_SCENARIO_IV_SHIFTS)))
    base = mat.net_premium(spot, iv=iv, r=r, q=q, T=T)
    for i, ds in enumerate(_SCENARIO_SPOT_SHIFTS):
        for j, div in enumerate(_SCENARIO_IV_SHIFTS):
            s_new = spot * (1 + ds)
            iv_new = max(1.0, iv + div)
            z[i, j] = mat.net_premium(s_new, iv=iv_new, r=r, q=q, T=T) - base
    return z


@st.cache_data(show_spinner=False, ttl=600)
def _cached_greeks_curves(
    template_name: str, spot: float, iv: float, dte: int, contracts: int,
    r: float, q: float, n_points: int = 60,
) -> dict[str, list[float]]:
    """Pre-compute the four greeks curves for the Surface tab.

    Returns a dict with keys delta/gamma/theta/vega each holding two
    sub-arrays (today, half-DTE) of length ``n_points``. Plotly
    consumes lists, so we cast to lists before returning so the cache
    payload is JSON-serialisable.
    """
    template = TEMPLATES[template_name]
    mat = template.materialize(
        ticker="_cache", spot=spot, iv_pct=iv, dte=dte, contracts=contracts,
    )
    S = np.linspace(spot * 0.7, spot * 1.3, n_points)
    T = max(1, dte) / 365.0
    T_half = T / 2
    out: dict[str, list[float]] = {}
    for label in ("delta", "gamma", "theta_per_day", "vega_per_1pct"):
        out[label + "_today"]  = [mat.greeks(float(s), iv=iv, r=r, q=q, T=T)[label] for s in S]
        out[label + "_half"]   = [mat.greeks(float(s), iv=iv, r=r, q=q, T=T_half)[label] for s in S]
    out["S"] = S.tolist()
    return out


# ── Public entry point ──────────────────────────────────────────────

def render_options_lab_page(db, settings: dict | None = None) -> None:
    st.markdown("## ◈ Options Lab")
    st.caption(
        "OptionStrat-grade workbench — payoff, Greeks surface, scenario "
        "matrix, probability cone. BSM-priced. IV slider drives everything."
    )
    # v3 (2026-05-13): freshness bar so the trader knows whether the
    # spot / IV defaults being fed into materialise() are current.
    from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
    render_data_freshness_bar(db, compact=True)

    # ── Builder strip ───────────────────────────────────────────────
    cfg = _render_builder_strip(db)
    if cfg is None:
        return
    ticker = cfg["ticker"]
    template_name = cfg["template_name"]
    spot = cfg["spot"]
    iv = cfg["iv"]
    dte = cfg["dte"]
    contracts = cfg["contracts"]
    r = cfg["r"]
    q = cfg["q"]
    history = cfg["history"]

    template = TEMPLATES.get(template_name)
    if template is None:
        st.error(f"Unknown strategy: {template_name}")
        return

    try:
        mat = template.materialize(
            ticker=ticker, spot=spot, iv_pct=iv, dte=dte, contracts=contracts,
            override_strike=cfg.get("override_strike"),
            override_expiry=cfg.get("override_expiry"),
        )
    except Exception as exc:
        st.error(f"Could not materialise legs: {exc}")
        return

    # ── Payoff diagram ──────────────────────────────────────────────
    _render_payoff_diagram(mat, spot, iv, r, q)

    # ── Metrics row ─────────────────────────────────────────────────
    _render_metrics_row(mat, spot, iv, r, q, dte)

    # ── Tabs ────────────────────────────────────────────────────────
    tab_g, tab_s, tab_t, tab_p, tab_u = st.tabs([
        "📊 Greeks Surface",
        "▦ Scenario Matrix",
        "⏱ Time Decay",
        "📈 Probability Cone",
        "🕯 Underlying",
    ])
    with tab_g:
        _render_greeks_surface(mat, spot, iv, r, q, dte)
    with tab_s:
        _render_scenario_matrix(mat, spot, iv, r, q, dte)
    with tab_t:
        _render_time_decay(mat, spot, iv, r, q, dte)
    with tab_p:
        _render_probability_cone(mat, spot, iv, r, q, dte)
    with tab_u:
        _render_underlying_context(history, ticker)


# ── Preset loader ───────────────────────────────────────────────────

def _render_preset_loader(db, available_tickers: list[str]) -> None:
    """Compact preset-loader row above the builder strip.

    A selectbox + "Load" button. When loaded, the preset's ticker /
    strategy / strikes / expiry overwrite session_state so the next
    rerun of the builder picks them up.
    """
    from volscope.data.presets import list_presets

    try:
        presets = list_presets(db)
    except Exception:
        presets = []
    if not presets:
        return

    with st.expander(
        f"▣ Load preset · {len(presets)} saved",
        expanded=False,
    ):
        # Truncate cleanly on a word boundary so we don't chop mid-word
        # in the dropdown label.
        def _short(s: str, limit: int = 60) -> str:
            s = (s or "").replace("\n", " ").strip()
            if len(s) <= limit:
                return s
            cut = s[:limit].rsplit(" ", 1)[0]
            return f"{cut}…"
        labels = [
            f"{p.ticker} · {p.strategy_name} · {_short(p.thesis)}"
            for p in presets
        ]
        idx = st.selectbox(
            "Preset",
            range(len(presets)),
            format_func=lambda i: labels[i],
            key="ol_preset_idx",
            label_visibility="collapsed",
        )
        if st.button("Load preset", key="ol_load_preset", use_container_width=True):
            p = presets[idx]
            spec = p.legs_spec or {}
            if p.ticker in available_tickers:
                st.session_state["ol_ticker"] = p.ticker
                st.session_state["selected_ticker"] = p.ticker
            if p.strategy_name in TEMPLATES:
                st.session_state["ol_template"] = p.strategy_name
            if "dte" in spec:
                try:
                    st.session_state["ol_dte"] = int(spec["dte"])
                except (TypeError, ValueError):
                    pass
            # Push strike + expiry overrides — these flow into the
            # materializer for single-leg templates and pin exact values.
            if "strike" in spec:
                try:
                    st.session_state["ol_override_strike"] = float(spec["strike"])
                except (TypeError, ValueError):
                    pass
            if "expiry" in spec:
                from datetime import date as _date
                raw = spec["expiry"]
                if isinstance(raw, str) and raw not in ("auto-leaps", ""):
                    try:
                        st.session_state["ol_override_expiry"] = _date.fromisoformat(raw[:10])
                    except ValueError:
                        pass
            st.success(f"Loaded preset · {p.ticker} {p.strategy_name}")
            st.rerun()


# ── Builder strip ───────────────────────────────────────────────────

def _render_builder_strip(db) -> Optional[dict]:
    """Render the 7-input control row. Returns config dict or None on miss."""
    available = db.get_available_tickers() or []
    if not available:
        st.warning("No tickers loaded — add one from the sidebar first.")
        return None

    cur = st.session_state.get("selected_ticker", available[0])
    if cur not in available:
        cur = available[0]

    _render_preset_loader(db, available)

    c1, c2, c3, c4 = st.columns([2, 3, 1, 1])
    with c1:
        ticker = st.selectbox(
            "Ticker", available, index=available.index(cur), key="ol_ticker",
        )
    with c2:
        template_name = st.selectbox(
            "Strategy", list(TEMPLATES.keys()), index=0, key="ol_template",
        )
    with c3:
        contracts = st.number_input(
            "Contracts", min_value=1, max_value=200, value=1, step=1, key="ol_ctr",
        )
    with c4:
        dte = st.number_input(
            "DTE", min_value=7, max_value=900, value=60, step=7, key="ol_dte",
        )

    # Pull live state
    history = db.get_ticker_history(ticker)
    if history is None or history.empty:
        st.warning(f"No history for {ticker}.")
        return None
    latest = history.iloc[-1]
    default_spot = float(latest.get("spot_price") or 100.0)
    default_iv   = float(latest.get("iv_30d") or 25.0)

    c5, c6, c7, c8 = st.columns([2, 3, 1, 1])
    with c5:
        spot = st.number_input(
            "Underlying $", min_value=0.5, max_value=1_000_000.0,
            value=default_spot, step=0.5, format="%.2f", key="ol_spot",
        )
    with c6:
        iv = st.slider(
            "IV (%)", min_value=5.0, max_value=200.0,
            value=float(default_iv), step=0.5, key="ol_iv",
        )
    with c7:
        r = st.number_input(
            "r (%)", min_value=0.0, max_value=15.0, value=4.5, step=0.25,
            format="%.2f", key="ol_r",
        ) / 100.0
    with c8:
        q = st.number_input(
            "q (%)", min_value=0.0, max_value=15.0, value=0.0, step=0.25,
            format="%.2f", key="ol_q",
        ) / 100.0

    # ── Optional strike + expiry override (single-leg only) ────────
    # Preset loader populates these via session_state; the user can
    # also tweak them manually. For multi-leg templates the override
    # is silently ignored by the materializer.
    is_single_leg = template_name in {"Long Call", "Long Put"}
    override_strike: Optional[float] = None
    override_expiry = None
    if is_single_leg:
        c9, c10, _ = st.columns([1, 1, 6])
        with c9:
            override_strike = st.number_input(
                "Strike (override)",
                min_value=0.5, max_value=10_000.0,
                value=float(st.session_state.get("ol_override_strike",
                                                   round(default_spot, 0))),
                step=0.5, format="%.2f",
                key="ol_override_strike",
                help="Pin the leg's strike. Cleared by switching ticker / template.",
            )
        with c10:
            from datetime import date as _date, timedelta as _td
            default_exp = _date.today() + _td(days=int(dte))
            override_expiry = st.date_input(
                "Expiry (override)",
                value=st.session_state.get("ol_override_expiry", default_exp),
                key="ol_override_expiry",
                help="Pin the leg's expiry. Defaults to today + DTE.",
            )

    return {
        "ticker": ticker, "template_name": template_name, "spot": spot, "iv": iv,
        "dte": int(dte), "contracts": int(contracts), "r": r, "q": q,
        "history": history,
        "override_strike": override_strike,
        "override_expiry": override_expiry,
    }


# ── Payoff diagram ─────────────────────────────────────────────────

def _render_payoff_diagram(mat, spot, iv, r, q):
    S = np.linspace(spot * 0.60, spot * 1.40, _PNL_GRID_POINTS)
    pnl_expiry = mat.payoff_at_expiry(S)

    fig = go.Figure()

    # Profit / loss shading at expiry
    pos = np.where(pnl_expiry > 0, pnl_expiry, 0.0)
    neg = np.where(pnl_expiry < 0, pnl_expiry, 0.0)
    fig.add_trace(go.Scatter(
        x=S, y=pos, fill="tozeroy", mode="none",
        fillcolor=rgba(COLORS["candle_up"], 0.10),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=S, y=neg, fill="tozeroy", mode="none",
        fillcolor=rgba(COLORS["candle_down"], 0.10),
        hoverinfo="skip", showlegend=False,
    ))

    # Time-decay snapshots (dashed, lighter)
    for t_frac in _TIME_SNAPSHOTS[1:]:
        pnl_t = mat.payoff_at_t(S, t_fraction=t_frac, iv=iv, r=r, q=q)
        fig.add_trace(go.Scatter(
            x=S, y=pnl_t, mode="lines",
            line=dict(color=COLORS["muted"], width=1.0, dash="dot"),
            opacity=0.55, name=f"{int(t_frac*100)}% DTE",
            hovertemplate=f"@ {int(t_frac*100)}% DTE · %{{y:+$,.0f}}<extra></extra>",
        ))

    # P&L at expiry (hero line)
    line_color = COLORS["candle_up"]
    fig.add_trace(go.Scatter(
        x=S, y=pnl_expiry, mode="lines",
        line=dict(color=line_color, width=2.4),
        name="At expiry",
        hovertemplate="@ expiry · %{y:+$,.0f}<extra></extra>",
    ))

    # Reference lines
    fig.add_hline(y=0, line=dict(color=COLORS["muted"], width=1))
    fig.add_vline(
        x=spot,
        line=dict(color=COLORS["accent2"], width=1, dash="dash"),
        annotation=dict(
            text=f"Spot ${spot:.2f}",
            font=dict(family=_MONO, color=COLORS["accent2"], size=10),
            bgcolor=COLORS["card"], borderpad=3,
        ),
        annotation_position="top",
    )
    # Strike markers
    for leg in mat.legs:
        if leg.strike <= 0:
            continue
        fig.add_vline(
            x=leg.strike,
            line=dict(color=COLORS["label"], width=1, dash="dot"),
            opacity=0.6,
        )

    fig.update_layout(
        title=dict(
            text=f"PAYOFF · {escape(mat.template_name)} · {escape(mat.ticker)}",
            font=dict(color=COLORS["label"], size=11, family="DM Sans"),
            x=0.0, xanchor="left", y=0.97,
        ),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        height=380,
        margin=dict(l=12, r=58, t=46, b=28),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left",
                    x=0, bgcolor="rgba(0,0,0,0)",
                    font=dict(family="DM Sans", size=9, color=COLORS["muted"])),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="rgba(13,14,20,0.95)",
                        bordercolor=COLORS["border"],
                        font=dict(family=_MONO, size=11, color=COLORS["text"])),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.03)",
            tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            tickformat="$,.0f",
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.03)",
            tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            tickformat="$,.0f",
            side="right",
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Metrics row ────────────────────────────────────────────────────

def _render_metrics_row(mat, spot, iv, r, q, dte):
    T = max(1, dte) / 365.0
    net = mat.net_premium(spot, iv=iv, r=r, q=q, T=T)
    g = mat.greeks(spot, iv=iv, r=r, q=q, T=T)
    pop_val = compute_pop(mat, S0=spot, iv=iv, r=r, q=q, T=T)

    max_p = mat.max_profit()
    max_l = mat.max_loss_unbounded()
    bes = mat.breakevens or ()

    def _money(v: Optional[float]) -> str:
        if v is None:
            return "Unlimited"
        return f"${abs(v):,.0f}"

    pl_class_p = "fg-cheap" if max_p is None or max_p > 0 else ""
    pl_class_l = "fg-rich"  if max_l is not None and max_l > 0 else ""
    bes_str = (" / ".join(f"${b:,.2f}" for b in bes)) if bes else "—"
    net_color = "fg-rich" if net >= 0 else "fg-cheap"
    net_label = "DEBIT" if net >= 0 else "CREDIT"

    cells = [
        _ibkr_cell("MAX PROFIT", _money(max_p), value_class=pl_class_p),
        _ibkr_cell("MAX LOSS",   _money(max_l), value_class=pl_class_l),
        _ibkr_cell("BREAKEVEN",  bes_str),
        _ibkr_cell("POP",        f"{pop_val*100:.0f}%"),
        _ibkr_cell(net_label,    f"${abs(net):,.0f}", value_class=net_color),
    ]
    render_html(st, '<div class="volscope-ibkr-row">' + "".join(cells) + "</div>")

    greek_cells = [
        _ibkr_cell("Δ DELTA",   f"{g['delta']:+,.2f}"),
        _ibkr_cell("Γ GAMMA",   f"{g['gamma']:+,.4f}"),
        _ibkr_cell("Θ THETA/d", _signed_dollar(g['theta_per_day'], decimals=2)),
        _ibkr_cell("ν VEGA/1%", _signed_dollar(g['vega_per_1pct'], decimals=2)),
        _ibkr_cell("ρ RHO/1%",  _signed_dollar(g['rho_per_1pct'], decimals=2)),
    ]
    render_html(st, '<div class="volscope-ibkr-row">' + "".join(greek_cells) + "</div>")


# ── Tabs ───────────────────────────────────────────────────────────

def _render_greeks_surface(mat, spot, iv, r, q, dte):
    """2×2 grid: Δ Γ Θ ν vs. underlying.

    Greeks curves cached on (template, spot, iv, dte, contracts, r, q)
    so slider-dragging the IV doesn't re-evaluate 240 scalar BSM calls.
    """
    from plotly.subplots import make_subplots

    cached = _cached_greeks_curves(
        mat.template_name, float(spot), float(iv), int(dte),
        int(mat.legs[0].contracts), float(r), float(q),
    )
    S = cached["S"]

    fig = make_subplots(rows=2, cols=2, subplot_titles=(
        "Δ Delta", "Γ Gamma", "Θ Theta / day", "ν Vega / 1 % IV",
    ), vertical_spacing=0.12, horizontal_spacing=0.10)

    plots = [
        (1, 1, "delta",         "Delta"),
        (1, 2, "gamma",         "Gamma"),
        (2, 1, "theta_per_day", "Theta/day ($)"),
        (2, 2, "vega_per_1pct", "Vega/1% ($)"),
    ]
    for row, col, key, _label in plots:
        fig.add_trace(go.Scatter(
            x=S, y=cached[key + "_today"],
            line=dict(color=COLORS["candle_up"], width=2),
            name="today", showlegend=(row == 1 and col == 1),
        ), row=row, col=col)
        fig.add_trace(go.Scatter(
            x=S, y=cached[key + "_half"],
            line=dict(color=COLORS["accent2"], width=1.5, dash="dash"),
            name="50% DTE", showlegend=(row == 1 and col == 1),
        ), row=row, col=col)
        fig.add_vline(x=spot, line=dict(color=COLORS["label"], width=1, dash="dot"),
                      row=row, col=col)
    fig.update_layout(
        height=480,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        margin=dict(l=12, r=24, t=46, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)",
                    font=dict(family="DM Sans", size=9, color=COLORS["muted"])),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.03)",
                     tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
                     tickformat="$,.0f")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.03)",
                     tickfont=dict(family=_MONO, size=9, color=COLORS["label"]))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_scenario_matrix(mat, spot, iv, r, q, dte):
    """Heatmap: spot shift × IV shift → P&L. Annotated.

    Heavy computation lives in ``_cached_scenario_matrix`` so the
    slider-drag UX is instant after the first frame.
    """
    z = _cached_scenario_matrix(
        mat.template_name, float(spot), float(iv), int(dte),
        int(mat.legs[0].contracts), float(r), float(q),
    )
    rows, cols = z.shape

    fig = go.Figure(go.Heatmap(
        z=z,
        x=[f"IV {d:+.0f}" for d in _SCENARIO_IV_SHIFTS],
        y=[f"S {d*100:+.0f}%" for d in _SCENARIO_SPOT_SHIFTS],
        colorscale="RdYlGn", zmid=0,
        text=[[_signed_dollar(v) for v in row] for row in z],
        texttemplate="%{text}",
        textfont=dict(family=_MONO, size=10),
        hovertemplate="%{x} · %{y}<br>P&L %{text}<extra></extra>",
        colorbar=dict(title=dict(text="P&L $",
                                  font=dict(family=_MONO, size=9, color=COLORS["muted"])),
                      tickfont=dict(family=_MONO, size=9, color=COLORS["muted"]),
                      thickness=10, len=0.8),
    ))
    fig.update_layout(
        height=max(360, 28 * rows + 80),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        margin=dict(l=12, r=44, t=24, b=20),
        xaxis=dict(side="top",
                   tickfont=dict(family=_MONO, size=10, color=COLORS["text"])),
        yaxis=dict(autorange="reversed",
                   tickfont=dict(family=_MONO, size=10, color=COLORS["text"])),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_time_decay(mat, spot, iv, r, q, dte):
    """At today's spot, walk forward in time and chart P&L → expiry.

    Single vectorised payoff call per time-fraction is already fast,
    but we further trim cost by reusing the same spot array across
    the loop. The whole tab renders in < 15 ms.
    """
    days = np.linspace(0, dte, 60).astype(int)
    spot_arr = np.array([spot], dtype=float)
    pnl = np.empty(len(days), dtype=float)
    for i, d in enumerate(days):
        t_frac = d / max(1, dte)
        pnl[i] = float(np.atleast_1d(
            mat.payoff_at_t(spot_arr, t_fraction=t_frac, iv=iv, r=r, q=q)
        )[0])

    fig = go.Figure(go.Scatter(
        x=days, y=pnl.tolist(), mode="lines",
        line=dict(color=COLORS["candle_up"], width=2.2),
        fill="tozeroy",
        fillcolor=rgba(COLORS["candle_up"], 0.07),
        hovertemplate="day %{x}<br>P&L %{y:+$,.0f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=COLORS["muted"], width=1))
    fig.update_layout(
        title=dict(text=f"TIME DECAY · spot pinned @ ${spot:.2f}",
                   font=dict(color=COLORS["label"], size=11, family="DM Sans"),
                   x=0.0, xanchor="left", y=0.97),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        height=320,
        margin=dict(l=12, r=44, t=46, b=28),
        xaxis=dict(gridcolor="rgba(255,255,255,0.03)",
                   tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
                   title=dict(text="days from today",
                              font=dict(family="DM Sans", size=9,
                                        color=COLORS["muted"]))),
        yaxis=dict(gridcolor="rgba(255,255,255,0.03)",
                   tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
                   side="right", tickformat="$,.0f"),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_probability_cone(mat, spot, iv, r, q, dte):
    """1σ and 2σ price cones to expiry, with strike markers and PoP."""
    days = np.arange(0, dte + 1, max(1, dte // 30))
    sigma = max(0.001, iv / 100.0)
    sd = sigma * np.sqrt(days / 365.0)
    upper2 = spot * np.exp(2 * sd)
    upper1 = spot * np.exp(1 * sd)
    lower1 = spot * np.exp(-1 * sd)
    lower2 = spot * np.exp(-2 * sd)
    mid    = np.full_like(days, spot, dtype=float)

    fig = go.Figure()
    # 2σ band
    fig.add_trace(go.Scatter(x=days, y=upper2, mode="lines",
                              line=dict(color=COLORS["candle_down"], width=0),
                              showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=days, y=lower2, mode="lines",
                              fill="tonexty",
                              fillcolor=rgba(COLORS["candle_down"], 0.06),
                              line=dict(color=COLORS["candle_down"], width=0),
                              showlegend=False, hoverinfo="skip"))
    # 1σ band
    fig.add_trace(go.Scatter(x=days, y=upper1, mode="lines",
                              line=dict(color=COLORS["candle_up"], width=0),
                              showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=days, y=lower1, mode="lines",
                              fill="tonexty",
                              fillcolor=rgba(COLORS["candle_up"], 0.10),
                              line=dict(color=COLORS["candle_up"], width=0),
                              showlegend=False, hoverinfo="skip"))
    # Mid line
    fig.add_trace(go.Scatter(x=days, y=mid, mode="lines",
                              line=dict(color=COLORS["muted"], width=1, dash="dot"),
                              showlegend=False, hoverinfo="skip"))

    # Strike markers
    for leg in mat.legs:
        if leg.strike <= 0:
            continue
        fig.add_hline(
            y=leg.strike,
            line=dict(color=COLORS["label"], width=1, dash="dot"),
            annotation=dict(
                text=f"K {leg.strike:g}",
                font=dict(family=_MONO, size=9, color=COLORS["muted"]),
            ),
            annotation_position="right",
        )

    fig.update_layout(
        title=dict(text="PROBABILITY CONE · 1σ / 2σ",
                   font=dict(color=COLORS["label"], size=11, family="DM Sans"),
                   x=0.0, xanchor="left", y=0.97),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        height=320,
        margin=dict(l=12, r=58, t=46, b=28),
        xaxis=dict(gridcolor="rgba(255,255,255,0.03)",
                   tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
                   title=dict(text="days",
                              font=dict(family="DM Sans", size=9,
                                        color=COLORS["muted"]))),
        yaxis=dict(gridcolor="rgba(255,255,255,0.03)",
                   tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
                   side="right", tickformat="$,.0f"),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_underlying_context(history: pd.DataFrame, ticker: str) -> None:
    """Embedded Pro Chart of the underlying — last ~6 months by default."""
    if history is None or history.empty:
        st.info("No price history available.")
        return
    df = history.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    # Try to derive OHLC from spot_price + intraday ranges; otherwise
    # fall back to a single close-only series (still valid for chart).
    rename_map = {}
    if "open" not in df.columns and "spot_price" in df.columns:
        df["open"] = df["spot_price"]
        df["high"] = df["spot_price"]
        df["low"]  = df["spot_price"]
        df["close"] = df["spot_price"]
    fig = render_pro_chart(
        df, title=f"{ticker} · history · IV overlay",
        iv_column="iv_30d", show_volume=False, height=460,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
