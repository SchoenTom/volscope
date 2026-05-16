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

# v0.9.2 cache-key fix: ``override_strike`` and ``override_expiry``
# were missing from the cache signature, so changing the operator's
# strike override didn't bust the cache and the Scenario Matrix /
# Greeks Surface kept serving stale results. Both are now first-
# class cache-key inputs. ``override_expiry_iso`` is the canonical
# ISO string (date objects are not hashable by Streamlit's cache).

@st.cache_data(show_spinner=False, ttl=600)
def _cached_scenario_matrix(
    template_name: str, spot: float, iv: float, dte: int, contracts: int,
    r: float, q: float,
    override_strike: float | None = None,
    override_expiry_iso: str | None = None,
) -> np.ndarray:
    """Build the spot×IV scenario heatmap once per parameter combo."""
    template = TEMPLATES[template_name]
    from datetime import date as _date
    exp_obj = _date.fromisoformat(override_expiry_iso) if override_expiry_iso else None
    mat = template.materialize(
        ticker="_cache", spot=spot, iv_pct=iv, dte=dte, contracts=contracts,
        override_strike=override_strike,
        override_expiry=exp_obj,
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
    override_strike: float | None = None,
    override_expiry_iso: str | None = None,
) -> dict[str, list[float]]:
    """Pre-compute the four greeks curves for the Surface tab.

    Returns a dict with keys delta/gamma/theta/vega each holding two
    sub-arrays (today, half-DTE) of length ``n_points``. Plotly
    consumes lists, so we cast to lists before returning so the cache
    payload is JSON-serialisable.
    """
    template = TEMPLATES[template_name]
    from datetime import date as _date
    exp_obj = _date.fromisoformat(override_expiry_iso) if override_expiry_iso else None
    mat = template.materialize(
        ticker="_cache", spot=spot, iv_pct=iv, dte=dte, contracts=contracts,
        override_strike=override_strike,
        override_expiry=exp_obj,
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
    # v0.9.7 — phase strip
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(
        st, page_name="Options Lab",
        ticker=st.session_state.get("selected_ticker"),
    )
    st.markdown("## ◈ Options Lab")
    st.caption(
        "OptionStrat-grade workbench — payoff, Greeks surface, scenario "
        "matrix, probability cone. BSM-priced. IV slider drives everything."
    )
    # v3 (2026-05-13): freshness bar so the trader knows whether the
    # spot / IV defaults being fed into materialise() are current.
    from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
    render_data_freshness_bar(db, compact=True)

    # ── CONTROLS BLOCK (v0.9.2 visual cohesion) ─────────────────────
    # Operator feedback: "der obere Teil gehört irgendwie nicht zum
    # unteren". Group all the input widgets (quick-start tiles,
    # expiry picker, builder strip, plot-range expander) inside one
    # bordered container so they visually read as the "controls"
    # half of the page. The results section below (payoff, metrics,
    # tabs) is separated by an explicit horizontal divider with a
    # "RESULTS" caption so the user always knows which half of the
    # page they're editing.
    render_html(
        st,
        f'<div style="margin:6px 0 4px 0;'
        f'font-family:\'DM Sans\',sans-serif;font-size:11px;'
        f'color:{COLORS["muted"]};letter-spacing:0.04em;font-weight:600;'
        f'text-transform:uppercase;">— CONTROLS —</div>',
    )

    with st.container(border=True):
        # ── Quick-start tiles ──
        _render_quickstart_tiles()
        # ── Builder strip ──
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

    # ── RESULTS divider (v0.9.2 visual cohesion) ─────────────────────
    render_html(
        st,
        f'<div style="margin:18px 0 8px 0;padding-top:14px;'
        f'border-top:1px solid {COLORS["border"]};'
        f'font-family:\'DM Sans\',sans-serif;font-size:11px;'
        f'color:{COLORS["muted"]};letter-spacing:0.04em;font-weight:600;'
        f'text-transform:uppercase;">— RESULTS · {template_name} · {ticker} ·'
        f' {contracts:,} contracts · {dte}d DTE —</div>',
    )

    # ── Spot-range sliders (v0.9.0) ─────────────────────────────────
    # Operator wanted absolute control over the x-axis: default 60%-
    # 140% is too tight for catastrophic-move analysis (e.g. SMCI
    # +400%, GME +1500%). Slider goes up to 5× current spot.
    with st.expander("Plot range — spot / move %", expanded=False):
        sc1, sc2, sc3 = st.columns([3, 3, 1])
        with sc1:
            spot_low_mult = st.slider(
                "Lower bound (× current spot)",
                min_value=0.05, max_value=1.0,
                value=float(st.session_state.get("ol_spot_low", 0.60)),
                step=0.05, key="ol_spot_low",
                help="Lower edge of the x-axis. 0.20 = −80 %, 0.05 = −95 %.",
            )
        with sc2:
            spot_high_mult = st.slider(
                "Upper bound (× current spot)",
                min_value=1.0, max_value=5.0,
                value=float(st.session_state.get("ol_spot_high", 1.40)),
                step=0.05, key="ol_spot_high",
                help="Upper edge of the x-axis. 2.0 = +100 %, 5.0 = +400 %.",
            )
        with sc3:
            # v0.9.1 — one-click reset back to the default 60-140 %
            # window. Operator-requested after stretching the axis
            # for catastrophic-move analysis and wanting to snap
            # back without dragging both sliders by hand.
            if st.button(
                "↺ Reset",
                key="ol_spot_range_reset",
                width='stretch',
                help="Restore the default 0.60×–1.40× spot range.",
            ):
                st.session_state["ol_spot_low"]  = 0.60
                st.session_state["ol_spot_high"] = 1.40
                st.rerun()

    # ── Payoff diagram ──────────────────────────────────────────────
    _render_payoff_diagram(
        mat, spot, iv, r, q,
        spot_low_mult=float(spot_low_mult),
        spot_high_mult=float(spot_high_mult),
    )

    # ── Metrics row ─────────────────────────────────────────────────
    _render_metrics_row(mat, spot, iv, r, q, dte)

    # ── Tabs ────────────────────────────────────────────────────────
    tab_surf, tab_g, tab_s, tab_t, tab_p, tab_u = st.tabs([
        "🗻 Payoff Surface",        # v0.9.0 — 3D P&L(spot, DTE)
        "📊 Greeks Surface",
        "▦ Scenario Matrix",
        "⏱ Time Decay",
        "📈 Probability Cone",
        "🕯 Underlying",
    ])
    with tab_surf:
        _render_payoff_surface(
            mat, spot, iv, r, q, dte,
            spot_low_mult=float(spot_low_mult),
            spot_high_mult=float(spot_high_mult),
        )
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

    # ── Paper-buy CTA (v0.9.1) ─────────────────────────────────────
    # Materialised strategy → paper_buy_strategy → positions /
    # paper_trades. Same engine path Pre-Trade has used since v0.3.x,
    # now reachable from Options Lab so the operator can act on a
    # candidate trade without switching pages.
    _render_paper_buy_cta(
        db,
        mat=mat,
        spot=spot,
        iv=iv,
        iv_perc=cfg.get("iv_perc"),
    )

    # Operator feedback 2026-05-16: "der options builder zeigt mir
    # nicht mein richtiges portfolio an, ich will mein eigenes". The
    # full portfolio lives on the Portfolio page; here we surface a
    # compact "currently held" sidebar-style block so the operator
    # has their book in view while designing the next trade.
    _render_my_open_positions(db)

    # v0.9.7 — cross-page weave footer
    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(
        st, page="Options Lab",
        ticker=st.session_state.get("selected_ticker"),
    )


def _render_paper_buy_cta(
    db,
    *,
    mat,
    spot: float,
    iv: float,
    iv_perc: Optional[float] = None,
) -> None:
    """Render the Paper Buy row at the bottom of Options Lab.

    Mirrors ``pretrade_page.py`` line ~480-540 BUY logic but lives
    here so the operator can buy a multi-leg structure straight from
    the Options-Lab builder without bouncing through Pre-Trade.

    Single source of truth for the *actual* engine call: the same
    ``volscope.data.paper_trader.paper_buy_strategy`` function both
    pages use. This keeps cash-debit, ledger journaling, and
    strategy-group bookkeeping identical across entry points.
    """
    from datetime import date as _date

    render_html(
        st,
        f'<div style="margin-top:22px;padding-top:14px;'
        f'border-top:1px solid {COLORS["border"]};'
        f'font-family:\'DM Sans\',sans-serif;font-size:13px;'
        f'font-weight:600;color:{COLORS["muted"]};letter-spacing:0.02em;">'
        f'PAPER TRADE — execute this candidate</div>',
    )
    render_html(
        st,
        f'<div style="background:{COLORS["surface"]};border-left:3px solid '
        f'{COLORS["accent"]};padding:10px 14px;border-radius:5px;margin:6px 0;'
        f'font-family:\'DM Sans\',sans-serif;font-size:12px;'
        f'color:{COLORS["text"]};">'
        f'Click <strong>▶ paper-buy</strong> to write '
        f'<strong>{mat.template_name}</strong> · '
        f'<strong>{len(mat.legs)} legs</strong> on '
        f'<strong>{mat.ticker}</strong> into the Portfolio paper engine. '
        f'No IBKR call, no real order; cash is debited from the paper '
        f'balance and the position appears in <em>Portfolio</em> on next '
        f'render.'
        f'</div>',
    )

    pb_col1, pb_col2, pb_col3 = st.columns([2, 2, 3])
    with pb_col1:
        do_buy = st.button(
            "▶ paper-buy this structure",
            key="ol_paper_buy",
            type="primary",
            width='stretch',
            help="Materialise all legs and insert as a Portfolio position.",
        )
    with pb_col2:
        do_open_portfolio = st.button(
            "▷ portfolio →",
            key="ol_open_portfolio",
            width='stretch',
            help="Jump to the Portfolio page (no insert).",
        )
    with pb_col3:
        render_html(
            st,
            f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;'
            f'color:{COLORS["muted"]};padding:8px 4px;line-height:1.3;">'
            f'BSM-priced entry · close anytime in Portfolio'
            f'</div>',
        )

    if do_buy:
        try:
            from volscope.data.paper_trader import paper_buy_strategy
            group_id, cash_after = paper_buy_strategy(
                db,
                mat,
                entry_iv_pct=float(iv),
                entry_iv_percentile=(
                    float(iv_perc) if iv_perc is not None else None
                ),
                spot=float(spot),
                scenario_hint="Options Lab",
            )
            st.success(
                f"Paper-bought · {mat.template_name} · {len(mat.legs)} legs · "
                f"group {group_id[-6:]} · cash ${cash_after:,.0f}",
            )
        except Exception as exc:                                # noqa: BLE001
            st.error(f"Paper-buy failed: {exc}")

    if do_open_portfolio:
        from volscope.ui.components.navigation import NavIntent, nav_to
        nav_to(NavIntent(page="Portfolio", ticker=mat.ticker,
                          source="Options Lab"))
        st.rerun()


def _render_my_open_positions(db) -> None:
    """Compact 'currently held' panel under the Lab CTA.

    Pulls active strategy groups via paper_trader.list_strategy_groups.
    Empty state when no positions exist — encourages the operator to
    use the paper-buy button above.
    """
    try:
        from volscope.data.paper_trader import list_strategy_groups
        groups = list_strategy_groups(db)
    except Exception:
        return
    with st.expander(
        f"📂 My open paper positions ({len(groups)})",
        expanded=False,
    ):
        if not groups:
            st.caption(
                "No active paper positions. Use the ▶ paper-buy "
                "button above to log your first trade."
            )
            return
        for g in groups[:20]:
            cols = st.columns([2, 2, 2, 1])
            with cols[0]:
                st.write(f"**{g.ticker}**")
            with cols[1]:
                st.write(g.strategy_template)
            with cols[2]:
                kind = "debit" if g.net_entry_debit > 0 else "credit"
                st.write(f"{kind} ${abs(g.net_entry_debit):,.0f}")
            with cols[3]:
                st.write(f"{g.n_legs} leg{'s' if g.n_legs != 1 else ''}")
        if len(groups) > 20:
            st.caption(f"… +{len(groups) - 20} more on the Portfolio page.")


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
        if st.button("Load preset", key="ol_load_preset", width='stretch'):
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


# ── Quick-start tiles ───────────────────────────────────────────────

# Each tile entry maps a user-facing label to:
#   * the canonical TEMPLATES key (so a click sets `ol_template`)
#   * a one-line "what it is" line
#   * a direction tag (long_vol / short_vol / neutral_vol) for chip colour
#   * an ASCII payoff icon — purely cosmetic but readable at a glance
#
# Order is intentional: read top-row left→right for "simplest → spreads",
# bottom-row left→right for "vol-plays → premium-harvest". This matches
# how OptionStrat and Unusual Whales group their preset rails.
_QUICKSTART_TILES = [
    # ── row 1: directional bets ──
    {"label": "Long Call",         "template": "Long Call",
     "blurb": "bullish · long vol",  "tag": "long_vol",   "icon": "↗"},
    {"label": "Long Put",          "template": "Long Put",
     "blurb": "bearish · long vol",  "tag": "long_vol",   "icon": "↘"},
    {"label": "Bull Call Spread",  "template": "Bull Call Spread",
     "blurb": "capped bullish",      "tag": "long_vol",   "icon": "⤴"},
    {"label": "Bear Put Spread",   "template": "Bear Put Spread",
     "blurb": "capped bearish",      "tag": "long_vol",   "icon": "⤵"},
    # ── row 2: vol & premium plays ──
    {"label": "Long Straddle",     "template": "Long Straddle",
     "blurb": "vol expansion",       "tag": "long_vol",   "icon": "⋁"},
    {"label": "Long Strangle",     "template": "Long Strangle",
     "blurb": "cheaper expansion",   "tag": "long_vol",   "icon": "⋀"},
    {"label": "Iron Condor",       "template": "Short Iron Condor",
     "blurb": "neutral · premium",   "tag": "short_vol",  "icon": "◇"},
    {"label": "Iron Butterfly",    "template": "Iron Butterfly",
     "blurb": "pin-the-strike",      "tag": "short_vol",  "icon": "◆"},
]

_QUICKSTART_TAG_COLOR = {
    "long_vol":     ("#00d4aa", "rgba(0, 212, 170, 0.10)"),    # accent
    "short_vol":    ("#ff9f43", "rgba(255, 159, 67, 0.10)"),   # amber
    "neutral_vol":  ("#5b8cff", "rgba(91, 140, 255, 0.10)"),   # accent2
}


def _render_quickstart_tiles() -> None:
    """OptionStrat / Unusual-Whales style preset rail.

    Renders 8 strategy tiles in a 4×2 grid above the builder strip.
    A click sets ``st.session_state["ol_template"]`` to the canonical
    TEMPLATES key, normalises DTE / contracts to safe defaults, and
    triggers a rerun. The selectbox below picks up the new template
    on its next instantiation because Streamlit honours
    ``st.session_state[key]`` as the initial value for keyed widgets.

    Visual choices:
      • Single chip per tile (direction colour, ~10px) — fast scan.
      • 1-line blurb instead of a paragraph — the in-app glossary
        carries the long form (tooltip() helper, v0.6.2).
      • Icon is intentionally an arrow / shape, NOT a Material symbol
        ligature — those can leak as literal text on slow font loads.

    No side effects beyond session_state + st.rerun() on click.
    """
    render_html(
        st,
        f'<div style="margin:6px 0 8px 0;'
        f'font-family:\'DM Sans\',sans-serif;font-size:11px;'
        f'color:{COLORS["muted"]};letter-spacing:0.02em;font-weight:500;">'
        f'QUICK START — click a strategy to load defaults</div>',
    )

    rows = [_QUICKSTART_TILES[:4], _QUICKSTART_TILES[4:]]
    for row in rows:
        cols = st.columns(4, gap="small")
        for col, tile in zip(cols, row):
            color, bg = _QUICKSTART_TAG_COLOR[tile["tag"]]
            with col:
                # The label is plain text because Streamlit's
                # `button(label=...)` does NOT parse markdown — we
                # render the chrome ourselves below the button so
                # the button itself stays accessible and screen-
                # reader friendly.
                clicked = st.button(
                    f"{tile['icon']}  {tile['label']}",
                    key=f"ol_qs_{tile['template']}",
                    width='stretch',
                    help=f"{tile['template']} — {tile['blurb']}",
                )
                render_html(
                    st,
                    f'<div style="margin-top:-4px;margin-bottom:8px;'
                    f'background:{bg};border:1px solid {color}33;'
                    f'border-radius:4px;padding:3px 6px;'
                    f'font-family:\'DM Sans\',sans-serif;font-size:10px;'
                    f'color:{color};text-align:center;">'
                    f'{tile["blurb"]}</div>',
                )
                if clicked:
                    # Set the strategy key BEFORE the rerun so the
                    # builder-strip selectbox initialises with the
                    # new template selected.
                    st.session_state["ol_template"] = tile["template"]
                    # Sensible defaults that work for every preset.
                    st.session_state["ol_dte"] = 30
                    st.session_state["ol_ctr"] = 1
                    st.rerun()


# ── Expiry picker (absolute-date layer, v0.8.0) ─────────────────────

def _next_friday(today: "date") -> "date":
    """Next Friday strictly after ``today`` (weekday 4)."""
    from datetime import timedelta
    days_ahead = (4 - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


def _next_third_friday(today: "date") -> "date":
    """Next 3rd Friday of any month strictly after ``today``.

    Monthly equity options expire on the 3rd Friday of every month
    — this is the most-traded standard expiry on US exchanges.
    """
    from datetime import date as _date, timedelta
    # Try this month's 3rd Friday; if it's already past, roll to next month.
    for offset in range(0, 3):
        year  = today.year  + ((today.month - 1 + offset) // 12)
        month = ((today.month - 1 + offset) % 12) + 1
        first = _date(year, month, 1)
        # First Friday of the month
        first_friday = first + timedelta(days=(4 - first.weekday()) % 7)
        third_friday = first_friday + timedelta(days=14)
        if third_friday > today:
            return third_friday
    return today + timedelta(days=30)


def _next_quarterly_friday(today: "date") -> "date":
    """Next 3rd Friday of Mar / Jun / Sep / Dec strictly after ``today``.

    Quarterly expiries are the deepest-OI monthlies on most names —
    LEAPS roll-down + index rebalancing both happen on the same day.
    """
    from datetime import date as _date, timedelta
    quarters = (3, 6, 9, 12)
    year = today.year
    for _ in range(8):                                       # at most 2 yrs
        for q in quarters:
            if (q < today.month) or (q == today.month and today.day >= 15):
                continue
            first = _date(year, q, 1)
            first_friday = first + timedelta(days=(4 - first.weekday()) % 7)
            third_friday = first_friday + timedelta(days=14)
            if third_friday > today:
                return third_friday
        year += 1
    return today + timedelta(days=90)


def _next_january_leaps(today: "date") -> "date":
    """The 3rd Friday of next January — standard LEAPS anchor."""
    from datetime import date as _date, timedelta
    target_year = today.year + 1 if today.month >= 1 else today.year
    first = _date(target_year, 1, 1)
    first_friday = first + timedelta(days=(4 - first.weekday()) % 7)
    return first_friday + timedelta(days=14)


def _render_expiry_picker() -> None:
    """Absolute-date expiry tiles + custom date input.

    Layout:
      [ ⚡ Weekly (Fri 22 Nov, 8d) ] [ 📆 Monthly (Fri 19 Dec, 35d) ]
      [ 📊 Quarterly (Fri 20 Mar 2026, 126d) ] [ 🗓 LEAPS (Jan 2027, 426d) ]
      [ Custom: <st.date_input> → DTE auto-set ]

    Each preset writes ``st.session_state["ol_dte"]`` and triggers a
    rerun; the existing DTE number_input in the builder strip then
    reads that value as its initial. Operator can still fine-tune
    the DTE manually after picking a preset.
    """
    from datetime import date as _date

    today = _date.today()
    presets = [
        ("⚡ Weekly",    _next_friday(today),          "Next Friday"),
        ("📆 Monthly",   _next_third_friday(today),    "Next 3rd Friday"),
        ("📊 Quarterly", _next_quarterly_friday(today), "Mar/Jun/Sep/Dec cycle"),
        ("🗓 LEAPS",      _next_january_leaps(today),    "Next January 3rd Friday"),
    ]

    render_html(
        st,
        f'<div style="margin:8px 0 6px 0;'
        f'font-family:\'DM Sans\',sans-serif;font-size:11px;'
        f'color:{COLORS["muted"]};letter-spacing:0.02em;font-weight:500;">'
        f'EXPIRY — pick a date or use a preset</div>',
    )

    cols = st.columns([1, 1, 1, 1, 2], gap="small")
    for col, (label, exp_date, blurb) in zip(cols[:4], presets):
        dte = (exp_date - today).days
        with col:
            clicked = st.button(
                f"{label}\n{exp_date.strftime('%d %b %y')} · {dte}d",
                key=f"ol_exp_preset_{label}",
                width='stretch',
                help=f"{blurb} — sets DTE to {dte}.",
            )
            if clicked:
                st.session_state["ol_dte"] = int(dte)
                st.rerun()
    with cols[4]:
        # Custom date input — read current DTE to seed the default.
        current_dte = int(st.session_state.get("ol_dte", 60) or 60)
        from datetime import timedelta
        default_exp = today + timedelta(days=current_dte)
        custom = st.date_input(
            "or pick a custom date",
            value=default_exp,
            min_value=today,
            max_value=today + timedelta(days=900),
            key="ol_exp_custom",
            help=(
                "Pick any expiry date — DTE updates automatically. "
                "Useful for matching a specific weekly / monthly / "
                "LEAPS contract from the chain."
            ),
            label_visibility="collapsed",
        )
        if custom and isinstance(custom, _date):
            new_dte = max(1, (custom - today).days)
            # Only rerun if user actually changed the value — otherwise
            # we'd be in a rerun loop on every page render.
            if new_dte != current_dte:
                st.session_state["ol_dte"] = int(new_dte)
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

    # Inline glossary tooltips — pull from the v0.6.2 centralised
    # glossary so every place that explains IV / DTE / Greeks reads
    # from one source of truth.
    from volscope.ui.glossary import tooltip

    # ── Expiry picker (v0.8.0 absolute-date layer) ─────────────────
    # IBKR / OptionStrat pattern: real option chains expose a list
    # of expiries by absolute date with the DTE in parentheses
    # ("Dec 19 '25 (24d)"). VolScope's seed-only chain doesn't have
    # those yet, so we synthesise the four most-traded expiry kinds:
    # the next weekly (Fri), the next monthly (3rd Fri of next
    # month), the next quarterly (Mar/Jun/Sep/Dec 3rd Fri), and a
    # one-year LEAPS. Each preset writes its absolute date into
    # ``st.session_state["ol_dte"]`` (computed in days from today)
    # so the existing DTE slider below picks it up as its initial
    # value. The relative DTE slider stays available for fast
    # iteration; the date picker is the absolute-precision path.
    _render_expiry_picker()

    c1, c2, c3, c4 = st.columns([2, 3, 1, 1])
    with c1:
        ticker = st.selectbox(
            "Ticker", available, index=available.index(cur), key="ol_ticker",
            help="The underlying symbol whose spot + IV the engine prices against.",
        )
    with c2:
        template_name = st.selectbox(
            "Strategy", list(TEMPLATES.keys()), index=0, key="ol_template",
            help="Pick one of the Quick-Start tiles above for sane defaults.",
        )
    with c3:
        # v0.9.2: cap raised from 200 to 100 000 — the prior limit was
        # an arbitrary "retail trader" bound. Hedge-fund-sized sizes
        # are now legal at the engine level; operator's own sizing
        # discipline (Kelly fraction in risk-thresholds.yaml) is the
        # actual brake.
        contracts = st.number_input(
            "Contracts", min_value=1, max_value=100_000,
            value=1, step=1, key="ol_ctr",
            help="Multiplier applied to every leg. 1 contract = 100 shares of underlying.",
        )
    with c4:
        # v0.9.2: DTE max raised from 900 to 2 500 (≈ 7 years) so
        # LEAPS up to the longest-dated published series fit.
        dte = st.number_input(
            "DTE", min_value=1, max_value=2_500,
            value=60, step=1, key="ol_dte",
            help=tooltip("DTE") or "Days to Expiration.",
        )

    # v0.9.1 — Ticker-change staleness fix.
    # When the operator switches ticker (SPY → EWZ) Streamlit keeps
    # the *previous* ``ol_spot`` / ``ol_iv`` values cached in
    # session_state, so the number_input below would re-initialise
    # to the OLD ticker's spot, not the new one. Detect the ticker
    # change here, BEFORE the spot/iv widgets render, and pop the
    # stale keys so they re-default cleanly from the new ticker's
    # latest scrape.
    _last_seen = st.session_state.get("ol_last_ticker_seen")
    if _last_seen is not None and _last_seen != ticker:
        for _k in ("ol_spot", "ol_iv", "ol_override_strike", "ol_override_expiry"):
            st.session_state.pop(_k, None)
    st.session_state["ol_last_ticker_seen"] = ticker

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
            help="Spot price of the underlying. Pre-filled from the latest scrape.",
        )
    with c6:
        iv = st.slider(
            "IV (%)", min_value=5.0, max_value=200.0,
            value=float(default_iv), step=0.5, key="ol_iv",
            help=tooltip("IV") or "Implied volatility — drives every BSM price below.",
        )
    with c7:
        r = st.number_input(
            "r (%)", min_value=0.0, max_value=15.0, value=4.5, step=0.25,
            format="%.2f", key="ol_r",
            help="Risk-free rate. 4.5% ≈ current 3-month T-bill yield.",
        ) / 100.0
    with c8:
        q = st.number_input(
            "q (%)", min_value=0.0, max_value=15.0, value=0.0, step=0.25,
            format="%.2f", key="ol_q",
            help="Continuous dividend yield. 0% for non-dividend names.",
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

def _render_payoff_diagram(
    mat, spot, iv, r, q,
    *,
    spot_low_mult: float = 0.60,
    spot_high_mult: float = 1.40,
):
    """v0.9.0: spot range is now slider-controlled (callers above).

    Defaults preserve the prior 60-140 % look for backward compat
    with any old call sites; the page-level wiring passes the live
    slider values so the operator can stretch the x-axis to ±400 %
    for catastrophic-move analysis.
    """
    S = np.linspace(spot * spot_low_mult, spot * spot_high_mult, _PNL_GRID_POINTS)
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
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})


# ── 3D Payoff Surface (v0.9.0) ─────────────────────────────────────

def _render_payoff_surface(
    mat, spot, iv, r, q, dte,
    *,
    spot_low_mult: float = 0.60,
    spot_high_mult: float = 1.40,
    n_spot: int = 60,
    n_time: int = 32,
) -> None:
    """Plotly ``go.Surface`` of P&L(spot, DTE) for the current trade.

    The 2D payoff line shows the P&L *at expiry*; the surface shows
    the full path — for every (spot, days-remaining) cell, compute
    the BSM-priced mark-to-market P&L. The surface morphs as DTE
    decreases toward zero, terminating at the expiry payoff curve at
    the front edge of the chart.

    Two reference planes overlay the surface:
      • Vertical translucent plane at ``spot`` (the current
        underlying price) so the operator sees where they stand.
      • Horizontal translucent plane at zero P&L so breakevens
        are the visible intersection between the surface and the
        z=0 plane.

    Grid resolution is intentionally modest (60 × 32) so the
    payoff-surface tab feels responsive even for multi-leg
    structures with expensive ``mat.net_premium`` calls.
    """
    if dte <= 0:
        st.info("Set a positive DTE in the builder strip above to render "
                 "the payoff surface.")
        return

    # v0.9.2 — Camera-position reset.
    # Plotly's 3D scene keeps the user's camera (rotation/zoom) across
    # reruns via the ``uirevision`` mechanism: same uirevision string
    # → camera preserved. Mutating the string forces a reset to the
    # default camera. The "↺ Reset view" button bumps a counter in
    # session_state which we mix into uirevision so the next render
    # has a fresh revision.
    rev_col, _ = st.columns([1, 7])
    with rev_col:
        if st.button(
            "↺ Reset view",
            key="ol_payoff_surface_view_reset",
            width='stretch',
            help="Snap the 3D camera back to the default angle.",
        ):
            st.session_state["ol_payoff_surface_view_rev"] = (
                int(st.session_state.get("ol_payoff_surface_view_rev", 0)) + 1
            )
            st.rerun()
    _view_rev = int(st.session_state.get("ol_payoff_surface_view_rev", 0))

    S = np.linspace(spot * spot_low_mult, spot * spot_high_mult, n_spot)
    # Time axis: 0 days remaining = expiry; ``dte`` = today.
    # Render in days-from-today rather than days-to-expiry so the
    # surface "morphs forward" — left edge = today, right edge = expiry.
    days_remaining = np.linspace(dte, 0.5, n_time)

    Z = np.zeros((n_time, n_spot))
    for i, dr in enumerate(days_remaining):
        T_i = max(1e-4, float(dr) / 365.0)
        # Vectorised over S via ``mat.net_premium`` — the materialised
        # template handles broadcasting internally.
        try:
            row = mat.net_premium(S, iv=iv, r=r, q=q, T=T_i)
            entry = mat.net_premium(spot, iv=iv, r=r, q=q, T=dte / 365.0)
            Z[i, :] = np.asarray(row) - float(entry)
        except Exception:                                       # noqa: BLE001
            # Some legs may not vectorise cleanly — fall back to a
            # Python loop. Still faster than skipping the row.
            entry = mat.net_premium(spot, iv=iv, r=r, q=q, T=dte / 365.0)
            for j, s in enumerate(S):
                try:
                    Z[i, j] = mat.net_premium(
                        float(s), iv=iv, r=r, q=q, T=T_i,
                    ) - float(entry)
                except Exception:                              # noqa: BLE001
                    Z[i, j] = 0.0

    # Divergent colour scale centred on zero so green is profit, red
    # is loss, and the breakeven line is the colourless ridge.
    z_max = float(np.nanmax(np.abs(Z))) or 1.0
    colorscale = [
        [0.0,  COLORS["candle_down"]],
        [0.5,  COLORS["bg"]],
        [1.0,  COLORS["candle_up"]],
    ]

    fig = go.Figure(data=[go.Surface(
        x=S,
        y=days_remaining,
        z=Z,
        colorscale=colorscale,
        cmid=0.0,
        cmin=-z_max,
        cmax= z_max,
        contours_z=dict(show=True, usecolormap=True, project_z=True),
        colorbar=dict(
            title=dict(
                text="P&L ($)",
                font=dict(family=_MONO, size=10, color=COLORS["muted"]),
            ),
            thickness=8, len=0.5,
            tickfont=dict(family=_MONO, size=9, color=COLORS["muted"]),
        ),
        opacity=0.92,
        showscale=True,
        # v0.9.0 — operator wanted real $ amounts on hover (rather
        # than the Plotly-default raw "x: 100.0, y: 30.0, z: 1234.5").
        hovertemplate=(
            "Spot: $%{x:,.2f}<br>"
            "Days remaining: %{y:.0f}<br>"
            "P&L: %{z:+$,.0f}<extra></extra>"
        ),
    )])

    # Vertical plane at current spot — implemented as a thin Surface
    # of the same Z dimensions so it renders correctly in 3D.
    plane_x = np.array([spot, spot])
    plane_y = np.array([days_remaining.min(), days_remaining.max()])
    plane_z = np.array([[-z_max, -z_max], [z_max, z_max]])
    fig.add_trace(go.Surface(
        x=plane_x, y=plane_y, z=plane_z.T,
        showscale=False,
        colorscale=[[0, COLORS["accent2"]], [1, COLORS["accent2"]]],
        opacity=0.10,
        hoverinfo="skip",
    ))

    # Zero-P&L horizontal plane — same trick.
    plane2_x = np.array([S.min(), S.max()])
    plane2_y = np.array([days_remaining.min(), days_remaining.max()])
    plane2_z = np.zeros((2, 2))
    fig.add_trace(go.Surface(
        x=plane2_x, y=plane2_y, z=plane2_z,
        showscale=False,
        colorscale=[[0, COLORS["muted"]], [1, COLORS["muted"]]],
        opacity=0.10,
        hoverinfo="skip",
    ))

    fig.update_layout(
        title=dict(
            text=f"PAYOFF SURFACE · P&L (spot × DTE) · {mat.template_name}",
            font=dict(color=COLORS["label"], size=11, family="DM Sans"),
            x=0.0, xanchor="left", y=0.97,
        ),
        paper_bgcolor=COLORS["bg"],
        scene=dict(
            xaxis=dict(
                title=dict(text="Spot",
                            font=dict(family="DM Sans", size=11,
                                       color=COLORS["muted"])),
                backgroundcolor=COLORS["bg"],
                gridcolor=COLORS["border"],
                tickfont=dict(family=_MONO, size=9, color=COLORS["text"]),
                tickformat="$,.0f",
            ),
            yaxis=dict(
                title=dict(text="Days remaining",
                            font=dict(family="DM Sans", size=11,
                                       color=COLORS["muted"])),
                backgroundcolor=COLORS["bg"],
                gridcolor=COLORS["border"],
                tickfont=dict(family=_MONO, size=9, color=COLORS["text"]),
            ),
            zaxis=dict(
                title=dict(text="P&L ($)",
                            font=dict(family="DM Sans", size=11,
                                       color=COLORS["muted"])),
                backgroundcolor=COLORS["bg"],
                gridcolor=COLORS["border"],
                tickfont=dict(family=_MONO, size=9, color=COLORS["text"]),
                tickformat="$,.0f",
            ),
            camera=dict(eye=dict(x=1.7, y=1.7, z=0.9)),
            aspectratio=dict(x=1.4, y=1.0, z=0.7),
        ),
        # Mix the operator-controlled revision counter into uirevision
        # so the "↺ Reset view" button cleanly invalidates the saved
        # camera. Same uirevision across renders ⇒ Plotly preserves
        # the user's rotation/zoom; new uirevision ⇒ camera resets.
        uirevision=f"payoff_surface_rev_{_view_rev}",
        height=520,
        margin=dict(l=0, r=0, t=44, b=0),
    )
    st.plotly_chart(fig, width='stretch',
                     config={"displayModeBar": False})


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

    # v0.9.2: Finanzen.net-style quick-stats row + sizing display.
    # Was operator-requested on Pre-Trade earlier; same operator now
    # asked why the strip wasn't on Options-Lab too.
    try:
        from volscope.analytics.option_metrics import compute_all
        # Pick the first leg as the "reference leg" for the quick-stats
        # — multi-leg structures have meaningful Aufgeld / Hebel only
        # at the per-leg level. The strip carries a small "leg N of M"
        # caption so the operator knows which leg is being reported.
        if mat.legs:
            leg0 = mat.legs[0]
            leg_premium = float(getattr(leg0, "entry_premium", 0.0) or 0.0)
            leg_strike  = float(leg0.strike)
            opt_type    = "call" if str(leg0.option_type).lower().startswith("c") else "put"
            qs = compute_all(
                spot=float(spot), strike=leg_strike, premium=leg_premium,
                option_type=opt_type, delta=float(g["delta"]), dte=int(dte),
                ratio=100.0,
            )
            qs_cells = [
                _ibkr_cell("AUFGELD",      f"{qs.aufgeld:+.2f}%"),
                _ibkr_cell("AUFGELD P.A.", f"{qs.aufgeld_pa:+.1f}%"),
                _ibkr_cell("HEBEL",        f"{qs.leverage:,.1f}×"),
                _ibkr_cell("OMEGA",        f"{qs.omega:,.2f}"),
                _ibkr_cell("BREAK-EVEN",   f"${qs.break_even:,.2f}"),
                _ibkr_cell("BE MOVE",      f"{qs.break_even_pct:+.2f}%"),
            ]
            render_html(
                st,
                '<div class="volscope-ibkr-row">' + "".join(qs_cells) + "</div>"
                + f'<div style="font-family:JetBrains Mono,monospace;'
                f'font-size:9px;color:{COLORS["muted"]};margin:2px 0 6px 4px;">'
                f'Reference leg 1 of {len(mat.legs)} · '
                f'{opt_type.upper()} K=${leg_strike:,.2f} · '
                f'premium ${leg_premium:.2f}'
                f'</div>'
            )
    except Exception:                                          # noqa: BLE001
        pass

    # Sizing summary — explicit anteilsberechnung the operator asked
    # to be made clearer. Capital at risk = |net| × contracts × 100
    # (for long structures with positive net debit, that's the full
    # premium; for short structures the BPR / margin is the broker's
    # answer, but the BSM-net is a reasonable proxy in paper-mode).
    try:
        n_contracts = int(mat.legs[0].contracts) if mat.legs else 1
        capital_at_risk = abs(net) * n_contracts * 100.0
        notional_value  = float(spot) * n_contracts * 100.0
        sizing_cells = [
            _ibkr_cell("CONTRACTS",       f"{n_contracts:,}"),
            _ibkr_cell("CAPITAL @ RISK",  f"${capital_at_risk:,.0f}"),
            _ibkr_cell("NOTIONAL",        f"${notional_value:,.0f}"),
            _ibkr_cell("LEVERAGE (NOTIONAL/RISK)",
                       f"{(notional_value / max(1.0, capital_at_risk)):,.1f}×"),
        ]
        render_html(
            st,
            '<div class="volscope-ibkr-row">' + "".join(sizing_cells) + "</div>",
        )
    except Exception:                                          # noqa: BLE001
        pass


# ── Tabs ───────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=600)
def _cached_greek_surface(
    template_name: str,
    greek_name: str,
    spot: float, iv: float, dte: int, contracts: int,
    r: float, q: float,
    override_strike: float | None,
    override_expiry_iso: str | None,
    *,
    spot_low: float = 0.70,
    spot_high: float = 1.30,
    n_spot: int = 40,
    n_time: int = 24,
) -> np.ndarray:
    """Compute a single Greek over (spot, days_remaining) as a 2-D array.

    Used by every 3-D Greek-surface render. Cache is keyed on the
    full materialise-input set INCLUDING strike/expiry overrides
    (the same staleness fix as the 2-D curves cache).
    """
    template = TEMPLATES[template_name]
    from datetime import date as _date
    exp_obj = _date.fromisoformat(override_expiry_iso) if override_expiry_iso else None
    mat = template.materialize(
        ticker="_cache", spot=spot, iv_pct=iv, dte=dte, contracts=contracts,
        override_strike=override_strike, override_expiry=exp_obj,
    )
    S = np.linspace(spot * spot_low, spot * spot_high, n_spot)
    days_remaining = np.linspace(max(1, dte), 0.5, n_time)
    Z = np.zeros((n_time, n_spot))
    for i, dr in enumerate(days_remaining):
        T_i = max(1e-4, float(dr) / 365.0)
        for j, s in enumerate(S):
            try:
                Z[i, j] = mat.greeks(float(s), iv=iv, r=r, q=q, T=T_i)[greek_name]
            except (KeyError, Exception):                      # noqa: BLE001
                Z[i, j] = 0.0
    return Z


def _render_one_greek_surface(
    mat, spot, iv, r, q, dte,
    *,
    greek_name: str,
    title: str,
    colorscale: list[list],
    cmid: float | None = 0.0,
    hover_unit: str = "",
    height: int = 420,
    surface_key: str,
) -> None:
    """Render a single 3-D Greek surface (spot × DTE → greek)."""
    _override_strike = float(mat.legs[0].strike) if mat.legs else None
    _override_expiry = (
        mat.legs[0].expiry.isoformat() if mat.legs and mat.legs[0].expiry else None
    )
    Z = _cached_greek_surface(
        mat.template_name, greek_name,
        float(spot), float(iv), int(dte),
        int(mat.legs[0].contracts) if mat.legs else 1,
        float(r), float(q),
        override_strike=_override_strike,
        override_expiry_iso=_override_expiry,
    )
    S = np.linspace(spot * 0.70, spot * 1.30, Z.shape[1])
    days_remaining = np.linspace(max(1, dte), 0.5, Z.shape[0])

    _view_rev = int(st.session_state.get(f"ol_{surface_key}_view_rev", 0))

    fig = go.Figure(data=[go.Surface(
        x=S, y=days_remaining, z=Z,
        colorscale=colorscale,
        cmid=cmid,
        contours_z=dict(show=True, usecolormap=True, project_z=True),
        colorbar=dict(
            title=dict(text=title,
                        font=dict(family=_MONO, size=10, color=COLORS["muted"])),
            thickness=8, len=0.5,
            tickfont=dict(family=_MONO, size=9, color=COLORS["muted"]),
        ),
        opacity=0.92,
        hovertemplate=(
            "Spot: $%{x:,.2f}<br>"
            "Days remaining: %{y:.0f}<br>"
            f"{title}: %{{z:+.4f}}{hover_unit}<extra></extra>"
        ),
    )])
    fig.update_layout(
        title=dict(
            text=f"{title} surface · {mat.template_name}",
            font=dict(color=COLORS["label"], size=11, family="DM Sans"),
            x=0.0, xanchor="left", y=0.97,
        ),
        paper_bgcolor=COLORS["bg"],
        scene=dict(
            xaxis=dict(title="Spot", backgroundcolor=COLORS["bg"],
                        gridcolor=COLORS["border"],
                        tickfont=dict(family=_MONO, size=9, color=COLORS["text"]),
                        tickformat="$,.0f"),
            yaxis=dict(title="Days remaining", backgroundcolor=COLORS["bg"],
                        gridcolor=COLORS["border"],
                        tickfont=dict(family=_MONO, size=9, color=COLORS["text"])),
            zaxis=dict(title=title, backgroundcolor=COLORS["bg"],
                        gridcolor=COLORS["border"],
                        tickfont=dict(family=_MONO, size=9, color=COLORS["text"])),
            camera=dict(eye=dict(x=1.7, y=1.7, z=0.9)),
            aspectratio=dict(x=1.4, y=1.0, z=0.7),
        ),
        uirevision=f"{surface_key}_rev_{_view_rev}",
        height=height,
        margin=dict(l=0, r=0, t=36, b=0),
    )
    st.plotly_chart(fig, width='stretch',
                     config={"displayModeBar": False})


def _render_greeks_surface(mat, spot, iv, r, q, dte):
    """v0.9.2 — Greeks rendered as a sub-tab grid of 3-D surfaces.

    Each Greek is its own surface over (spot, days_remaining):

      • Δ Delta   — directional sensitivity (-1..+1 for vanilla)
      • Γ Gamma   — Δ-of-Δ: the curvature "gamma wall" around strike
      • Θ Theta   — time decay ($/day)
      • ν Vega    — IV sensitivity ($/1 % IV move)
      • Vanna     — ∂Δ/∂σ — cross-sensitivity of delta to IV moves
      • Charm     — ∂Δ/∂t — pin-risk near expiry (Delta drift through time)
      • Volga     — ∂Vega/∂σ — convexity of vega (vol-of-vol exposure)

    Each surface has a per-surface "↺ Reset view" button that
    invalidates the operator's stored camera (rotation/zoom) and
    snaps back to the default angle.
    """
    sub_tabs = st.tabs([
        "Δ Delta", "Γ Gamma", "Θ Theta", "ν Vega",
        "Vanna ∂Δ/∂σ", "Charm ∂Δ/∂t", "Volga ∂ν/∂σ",
    ])

    surfaces = [
        ("delta",          "Delta",  [[0, COLORS["candle_down"]], [0.5, COLORS["bg"]], [1, COLORS["candle_up"]]], 0.0,  ""),
        ("gamma",          "Gamma",  [[0, COLORS["bg"]],          [0.5, COLORS["accent2"]], [1, COLORS["accent"]]], None, ""),
        ("theta_per_day",  "Theta/day", [[0, COLORS["candle_down"]], [0.5, COLORS["bg"]], [1, COLORS["candle_up"]]], 0.0, " $/day"),
        ("vega_per_1pct",  "Vega/1%",[[0, COLORS["bg"]],          [0.5, COLORS["accent2"]], [1, COLORS["accent"]]], None, " $/1%IV"),
        ("vanna",          "Vanna",  [[0, COLORS["candle_down"]], [0.5, COLORS["bg"]], [1, COLORS["candle_up"]]], 0.0,  ""),
        ("charm",          "Charm",  [[0, COLORS["candle_down"]], [0.5, COLORS["bg"]], [1, COLORS["candle_up"]]], 0.0,  ""),
        ("volga",          "Volga",  [[0, COLORS["bg"]],          [0.5, COLORS["accent2"]], [1, COLORS["accent"]]], None, ""),
    ]

    for tab, (key, label, cscale, cmid, unit) in zip(sub_tabs, surfaces):
        with tab:
            # Reset-view button per surface (camera-rotation memory is
            # per-uirevision).
            rev_col, _ = st.columns([1, 7])
            with rev_col:
                if st.button(
                    "↺ Reset view",
                    key=f"ol_greek_{key}_reset",
                    width='stretch',
                    help="Snap the 3D camera back to the default angle.",
                ):
                    st.session_state[f"ol_greek_{key}_view_rev"] = (
                        int(st.session_state.get(f"ol_greek_{key}_view_rev", 0)) + 1
                    )
                    st.rerun()
            try:
                _render_one_greek_surface(
                    mat, spot, iv, r, q, dte,
                    greek_name=key, title=label,
                    colorscale=cscale, cmid=cmid,
                    hover_unit=unit,
                    surface_key=f"greek_{key}",
                )
            except Exception as exc:                           # noqa: BLE001
                # The materialised template may not expose all
                # second-order greeks (Vanna/Charm/Volga are recent
                # additions). Show a friendly message rather than
                # crashing the whole tab.
                st.info(
                    f"This template does not yet expose **{label}** — "
                    f"skip. Detail: {type(exc).__name__}: {exc}",
                )


def _render_scenario_matrix(mat, spot, iv, r, q, dte):
    """Heatmap: spot shift × IV shift → P&L. Annotated.

    Heavy computation lives in ``_cached_scenario_matrix`` so the
    slider-drag UX is instant after the first frame.
    """
    _override_strike = float(mat.legs[0].strike) if mat.legs else None
    _override_expiry = (
        mat.legs[0].expiry.isoformat() if mat.legs and mat.legs[0].expiry else None
    )
    z = _cached_scenario_matrix(
        mat.template_name, float(spot), float(iv), int(dte),
        int(mat.legs[0].contracts), float(r), float(q),
        override_strike=_override_strike,
        override_expiry_iso=_override_expiry,
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
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})


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
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})


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
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})


def _render_underlying_context(history: pd.DataFrame, ticker: str) -> None:
    """Embedded TradingView-style chart of the underlying.

    Uses ``streamlit-lightweight-charts`` with real OHLCV from yfinance
    + an IV-30 overlay from our daily_vol. Falls back to the legacy
    Plotly pro_chart helper if the lwc wrapper isn't available
    (fresh-checkout / pip-missing situations).
    """
    if history is None or history.empty:
        st.info("No price history available.")
        return

    # Range selector — operator picks the lookback. Default 5y so the
    # cycle-trough / cycle-peak context is visible without an extra
    # click. Cached fetches inside fetch_daily_ohlcv mean re-selection
    # is cheap.
    import streamlit as _st
    _range_options = ["1y", "2y", "5y", "10y", "max"]
    _range_pick = _st.radio(
        "Price-chart lookback",
        _range_options,
        index=2,
        horizontal=True,
        key=f"opt_lab_range_{ticker}",
        label_visibility="collapsed",
    )

    # Prefer the TradingView path. Anything that can break in here
    # (yfinance rate limit, missing dep, malformed history) is caught
    # below — we then degrade to the Plotly pro_chart we had before.
    try:
        from volscope.ui.components.lwc_chart import (
            fetch_daily_ohlcv, price_chart_lwc, render_lwc_safe,
        )
        ohlcv = fetch_daily_ohlcv(ticker, period=_range_pick)
        spec, key = price_chart_lwc(
            history,
            ohlcv=ohlcv,
            height=420,
            with_volume=True,
            with_iv_overlay=True,
            title=f"{ticker} · {_range_pick.upper()} · IV30 overlay",
        )
        if spec and render_lwc_safe(spec, key=f"opt_lab_{key}_{ticker}_{_range_pick}"):
            return                                              # success path
    except Exception:                                           # noqa: BLE001
        pass

    # Plotly fallback — the old Pro Chart helper, unchanged.
    df = history.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    if "open" not in df.columns and "spot_price" in df.columns:
        df["open"]  = df["spot_price"]
        df["high"]  = df["spot_price"]
        df["low"]   = df["spot_price"]
        df["close"] = df["spot_price"]
    fig = render_pro_chart(
        df, title=f"{ticker} · history · IV overlay",
        iv_column="iv_30d", show_volume=False, height=460,
    )
    st.plotly_chart(fig, width='stretch', config={"displayModeBar": False})
