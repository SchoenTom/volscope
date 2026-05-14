"""
Pre-Trade Card — strike/maturity selection + P&L curve + Greeks.

When the user clicks "BUY" on a Discover or Command Center recommendation,
they land here. The page bridges from "vol is cheap" to actionable
execution: it presents a concrete option contract proposal, a P&L curve
across IV scenarios, the Greeks at entry, and a max-loss / max-gain
summary.

Inputs:
  - selected ticker (from session state)
  - selected strategy (from StrategyRec.name; defaults to "Long Put Spread")
  - max_alloc_usd  (from sidebar setting)

Computation:
  - Pull spot, iv_30d, iv_60d, iv_90d from latest daily_vol row
  - Run BSM-pricing across [-2σ, +2σ] IV scenarios for visualisation
  - Compute Greeks at entry via existing ``black_scholes`` module

This page is a v1 — it does NOT pull live option-chain bid/ask. Strikes
are estimated via BSM-implied-strike-from-delta. Future work hooks live
chains via ``options_scraper`` for executable strikes.
"""
from __future__ import annotations

import math
from html import escape
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from datetime import date as _date, timedelta as _timedelta


def _short_thesis(s: str, limit: int = 120) -> str:
    """Word-boundary truncation so card text never chops mid-word."""
    s = (s or "").replace("\n", " ").strip()
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"

from volscope.analytics.black_scholes import bs_delta, bs_gamma, bs_price, bs_theta, bs_vega
from volscope.analytics.data_quality import composite_quality, quality_badge_html
from volscope.ui.components.navigation import NavIntent, nav_to
from volscope.analytics.strategy_recommender import (
    StrategyRec,
    recommend_strategies,
    strategy_card_html,
)
from volscope.data.database import VolScopeDB
from volscope.ui.components.html_utils import page_banner_html, render_html
from volscope.ui.styles.theme import COLORS, rgba

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


def render_pretrade_page(db: VolScopeDB, settings: dict) -> None:
    """Render the Pre-Trade Card view."""
    ticker = st.session_state.get("selected_ticker", "QQQ")

    render_html(
        st,
        page_banner_html(
            title="Pre-Trade",
            what="single-leg sizing tool with live greeks + RoR",
            when="right before paper-buying",
        ),
    )

    render_html(
        st,
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid {COLORS["border"]};">'
        f'<div style="font-family:{_MONO};font-size:20px;font-weight:700;color:{COLORS["text"]};">'
        f'<span style="color:{COLORS["accent"]};">▷</span> PRE-TRADE · {ticker}'
        f'</div>'
        f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};">'
        f'BSM-priced · v1'
        f'</div>'
        f'</div>',
    )

    history = db.get_ticker_history(ticker)
    if history is None or history.empty:
        st.info(f"No data for {ticker} — load it on Scanner or Discover first.")
        return

    latest = history.iloc[-1]
    spot       = _safe_float(latest.get("spot_price"))
    iv_30d     = _safe_float(latest.get("iv_30d"))
    iv_60d     = _safe_float(latest.get("iv_60d"))
    iv_90d     = _safe_float(latest.get("iv_90d"))
    iv_perc    = _safe_float(latest.get("iv_percentile"))
    skew_25    = _safe_float(latest.get("iv_skew_25d"))

    if spot is None or spot <= 0:
        st.warning(f"{ticker} has no usable spot price — run a scrape first.")
        return
    if iv_30d is None or iv_30d <= 0:
        st.warning(f"{ticker} has no usable IV — run a scrape first.")
        return

    # Show data-quality badge so the trader knows when calculations rest on
    # stale or incomplete data. Pricing 60d-DTE Greeks off a 1-month-old
    # iv_30d alone is misleading and the badge says so explicitly.
    quality = composite_quality(latest, history=history)
    if quality.overall_level != "OK":
        render_html(
            st,
            f'<div style="margin-bottom:10px;display:flex;align-items:center;gap:8px;">'
            f'<span style="color:{COLORS["muted"]};font-family:{_MONO};font-size:11px;">'
            f'data quality:</span> {quality_badge_html(quality)}</div>',
        )

    term_slope = (iv_60d - iv_30d) if (iv_60d is not None and iv_30d is not None) else None
    if term_slope is None:
        st.caption(
            "ℹ Term-structure (iv_60d) unavailable — calendar-spread "
            "recommendations and 60-day Greek pricing fall back to iv_30d."
        )

    # ── Strategy selector ────────────────────────────────────────────
    recs = recommend_strategies(
        iv_percentile=iv_perc,
        skew_25=skew_25,
        term_slope=term_slope,
    )
    rec_names = [r.name for r in recs]

    # Comparison toggle (Pillar C): pick 2-3 strategies, see them side-by-side
    compare_mode = st.toggle(
        "Compare strategies side-by-side",
        value=False,
        key="pretrade_compare_mode",
        help="Render up to 3 strategies in parallel columns with shared P&L chart.",
    )
    if compare_mode:
        _render_comparison_view(
            st=st, ticker=ticker, recs=recs, rec_names=rec_names,
            spot=spot, iv_30d=iv_30d, iv_60d=iv_60d, iv_90d=iv_90d,
            settings=settings,
        )
        return

    # ── Top-3 recommendation cards (replaces single-dropdown UX) ────
    # Show the top 3 ranked structures as cards. Each card shows the
    # one-liner thesis + a "Build this" button that loads the detail
    # view below for that strategy. Reduces the friction of "I had to
    # pick from a dropdown to even see what was on offer".
    chosen_key = "pretrade_chosen_strategy"
    if chosen_key not in st.session_state or st.session_state[chosen_key] not in rec_names:
        st.session_state[chosen_key] = rec_names[0]

    render_html(
        st,
        f'<div style="font-family:{_MONO};font-size:9px;letter-spacing:1.4px;'
        f'text-transform:uppercase;color:{COLORS["label"]};margin:4px 0 6px 0;'
        f'font-weight:600;">▸ ranked suggestions</div>',
    )
    top_recs = recs[:3]
    rec_cols = st.columns(len(top_recs))
    for col, rec in zip(rec_cols, top_recs):
        with col:
            is_active = (st.session_state[chosen_key] == rec.name)
            border = COLORS["accent"] if is_active else COLORS["border"]
            score_color = (
                COLORS["accent"] if rec.score >= 70
                else COLORS["amber"] if rec.score >= 50
                else COLORS["muted"]
            )
            render_html(
                st,
                f'<div style="background:{COLORS["card"]};border:1px solid {border};'
                f'border-left:3px solid {score_color};border-radius:6px;'
                f'padding:10px 12px;margin-bottom:6px;min-height:120px;'
                f'font-family:{_MONO};">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                f'<span style="font-size:12px;font-weight:700;color:{COLORS["text"]};">'
                f'{escape(rec.name)}</span>'
                f'<span style="font-size:11px;font-weight:600;color:{score_color};">'
                f'{rec.score:.0f}</span>'
                f'</div>'
                f'<div style="font-size:9px;letter-spacing:0.8px;text-transform:uppercase;'
                f'color:{score_color};margin-top:2px;">'
                f'{escape(rec.direction.replace("_", " "))} · {escape(rec.risk_profile)}'
                f'</div>'
                f'<div style="font-size:10px;color:{COLORS["muted"]};margin-top:6px;'
                f'line-height:1.4;">{escape(_short_thesis(rec.thesis))}</div>'
                f'</div>',
            )
            if st.button(
                ("● selected" if is_active else "▷ build this"),
                key=f"pt_pick_{rec.name}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state[chosen_key] = rec.name
                st.rerun()

    chosen = next(r for r in recs if r.name == st.session_state[chosen_key])

    # Detailed full-width strategy card (existing renderer)
    render_html(
        st,
        f'<div style="font-family:{_MONO};font-size:9px;letter-spacing:1.4px;'
        f'text-transform:uppercase;color:{COLORS["label"]};margin:14px 0 6px 0;'
        f'font-weight:600;">▸ build details — {chosen.name}</div>',
    )
    render_html(st, strategy_card_html(chosen))

    # Inline backtest hit-rate — pulls calibrated stats from
    # strategy_calibration so the trader sees historical edge before sizing.
    try:
        from volscope.analytics.strategy_calibration import get_stats_for
        stats = get_stats_for(chosen.name, ticker=ticker) or get_stats_for(chosen.name)
        if stats is not None and stats.n_trades > 0:
            scope = "this ticker" if stats.ticker == ticker else "universe"
            render_html(
                st,
                f'<div style="font-family:{_MONO};background:{COLORS["bg"]};'
                f'border-left:3px solid {COLORS["accent2"]};border-radius:6px;'
                f'padding:8px 12px;margin-top:6px;font-size:11px;color:{COLORS["text"]};">'
                f'<span style="color:{COLORS["accent2"]};font-weight:700;">historical ({scope}):</span> '
                f'{stats.hit_rate*100:.0f}% hit · '
                f'payoff {stats.payoff_ratio:.2f}× · '
                f'Sharpe {stats.sharpe:+.2f} · '
                f'n={stats.n_trades}'
                f'</div>',
            )
    except Exception:
        pass

    if not chosen.legs:
        st.info("WAIT — no executable structure at this vol regime.")
        return

    # All-legs descriptor — shows EVERY leg of the structure (call/put,
    # strike, target delta) so the trader doesn't think the page is
    # pricing only the lead. The Greeks/Sizing below price the lead leg
    # but the trader now sees the full multi-leg picture upfront.
    if len(chosen.legs) > 1:
        with st.expander(f"All {len(chosen.legs)} legs of {chosen.name}", expanded=True):
            for i, leg_desc in enumerate(chosen.legs, 1):
                render_html(
                    st,
                    f'<div style="font-family:{_MONO};font-size:11px;'
                    f'color:{COLORS["text"]};padding:3px 0;border-bottom:1px solid {COLORS["border"]};">'
                    f'<span style="color:{COLORS["muted"]};">leg {i}:</span> {leg_desc}'
                    f'</div>',
                )
            render_html(
                st,
                f'<div style="font-family:{_MONO};font-size:10px;color:{COLORS["muted"]};'
                f'margin-top:6px;">'
                f'Greeks + P&amp;L curve below price the LEAD leg only. Multi-leg P&amp;L '
                f'aggregation requires live chain quotes (planned).'
                f'</div>',
            )

    # ── Maturity slider ──────────────────────────────────────────────
    dte = st.slider(
        "Days to expiry (primary leg)",
        min_value=14, max_value=180,
        value=int(chosen.target_dte) if chosen.target_dte > 0 else 60,
        step=7,
        help="The Pre-Trade card prices Greeks and P&L at this DTE.",
    )

    # Pick IV based on DTE proximity to 30/60/90/180
    iv_used = _pick_iv_for_dte(dte, iv_30d, iv_60d, iv_90d)
    iv_dec  = iv_used / 100.0    # convert percent to decimal for BSM
    T = dte / 365.0

    # Estimate strike from target delta (binary search on bs_delta).
    target_delta = chosen.target_delta
    option_type = "put" if target_delta < 0 else "call"
    strike = _strike_from_delta(spot, T, iv_dec, target_delta, option_type)

    # ── Greeks at entry ──────────────────────────────────────────────
    delta = bs_delta(spot, strike, T, 0.04, iv_dec, option_type=option_type)
    gamma = bs_gamma(spot, strike, T, 0.04, iv_dec)
    vega  = bs_vega(spot, strike, T, 0.04, iv_dec) / 100.0   # per 1% IV move
    theta = bs_theta(spot, strike, T, 0.04, iv_dec, option_type=option_type) / 365.0
    entry_price = bs_price(spot, strike, T, 0.04, iv_dec, option_type=option_type)

    cols = st.columns(5)
    _kpi(cols[0], "Spot",        f"${spot:,.2f}")
    _kpi(cols[1], "Strike",      f"${strike:,.2f}")
    _kpi(cols[2], "Entry Price", f"${entry_price:.2f}")
    _kpi(cols[3], "IV used",     f"{iv_used:.1f}%")
    _kpi(cols[4], "DTE",         f"{dte}d")

    cols = st.columns(4)
    _kpi(cols[0], "Δ Delta",   f"{delta:+.3f}")
    _kpi(cols[1], "Γ Gamma",   f"{gamma:.4f}")
    _kpi(cols[2], "ν Vega",    f"${vega:.2f} /1% IV")
    _kpi(cols[3], "Θ Theta",   f"${theta:.2f} /day")

    # ── P&L curve across IV scenarios ────────────────────────────────
    iv_scenarios_pct = np.linspace(max(2.0, iv_used - 20.0), iv_used + 20.0, 41)
    pnl_per_contract = []
    for iv_s in iv_scenarios_pct:
        new_price = bs_price(spot, strike, T, 0.04, iv_s / 100.0, option_type=option_type)
        pnl_per_contract.append(new_price - entry_price)

    pnl_df = pd.DataFrame({
        "iv_scenario_pct": iv_scenarios_pct,
        "pnl_per_contract": pnl_per_contract,
    })

    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pnl_df["iv_scenario_pct"], y=pnl_df["pnl_per_contract"],
        mode="lines",
        line=dict(color=COLORS["accent"], width=2),
        fill="tozeroy",
        fillcolor=rgba(COLORS["accent"], 0.13),
        name="P&L per contract",
    ))
    fig.add_vline(x=iv_used, line_dash="dot", line_color=COLORS["muted"],
                  annotation_text=f"current IV {iv_used:.1f}%",
                  annotation_position="top")
    fig.add_hline(y=0, line_color=COLORS["border"])
    fig.update_layout(
        title="P&L per contract vs IV scenario (one leg, BSM)",
        xaxis_title="IV scenario (%)",
        yaxis_title="P&L per contract ($)",
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        font=dict(family=_MONO, color=COLORS["text"]),
        height=320, margin=dict(l=40, r=20, t=50, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Sizing summary ───────────────────────────────────────────────
    max_alloc = float(settings.get("max_alloc_usd", 10_000))
    n_contracts = max(1, int(max_alloc / max(0.01, entry_price * 100)))
    max_loss = entry_price * n_contracts * 100   # full premium for long-only legs
    render_html(
        st,
        f'<div style="font-family:{_MONO};background:{COLORS["card"]};'
        f'border:1px solid {COLORS["border"]};border-left:3px solid {COLORS["accent"]};'
        f'border-radius:6px;padding:12px 14px;margin-top:10px;">'
        f'<div style="color:{COLORS["accent"]};font-weight:700;margin-bottom:4px;">'
        f'Sizing Summary @ ${max_alloc:,.0f} cap'
        f'</div>'
        f'<div style="color:{COLORS["text"]};font-size:11px;">'
        f'{n_contracts} contracts · entry ${entry_price * n_contracts * 100:,.0f} · '
        f'max-loss ${max_loss:,.0f} (long premium)'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};font-size:10px;margin-top:4px;">'
        f'Pre-trade v1 prices the lead leg only. Spread structures (condor, '
        f'risk reversal) reduce both max-loss and max-gain — wire live chain '
        f'data for executable quotes.'
        f'</div>'
        f'</div>',
    )

    # ── Paper-buy → Portfolio ──────────────────────────────────────
    # Two-button row: paper-buy (writes a position row directly) and a
    # quick-jump to review it on the Portfolio page. Paper-buy persists
    # to DuckDB so the Portfolio page sees it on next render.
    expiry_iso = (_date.today() + _timedelta(days=int(dte))).isoformat()
    pb_col1, pb_col2, pb_col3 = st.columns([2, 2, 3])
    with pb_col1:
        do_buy = st.button(
            f"▶ paper-buy {n_contracts}×",
            key="pretrade_paper_buy",
            type="primary",
            use_container_width=True,
            help=f"Insert this trade into the portfolio: {n_contracts} × {chosen.name} "
                 f"strike ${strike:,.2f} expiry {expiry_iso}.",
        )
    with pb_col2:
        do_open = st.button(
            "▷ portfolio →",
            key="pretrade_open_portfolio",
            use_container_width=True,
            help="Switch to the Portfolio page (no insert).",
        )
    with pb_col3:
        render_html(
            st,
            f'<div style="font-family:{_MONO};font-size:9px;color:{COLORS["muted"]};'
            f'padding:8px 4px;line-height:1.3;">'
            f'paper-buy persists to DB · close anytime in Portfolio · '
            f'BSM entry-price, no live chain quote'
            f'</div>',
        )

    if do_buy:
        try:
            # Multi-leg paper-buy via the paper-trader engine. Resolves
            # the strategy name to a template, materialises legs from
            # the live state, debits cash, journals the event. If no
            # template matches (e.g. a one-off recommender label),
            # falls back to single-leg insert so the user never gets
            # blocked.
            from volscope.analytics.strategy_templates import resolve_template
            from volscope.data.paper_trader import paper_buy_strategy

            template = resolve_template(chosen.name)
            if template is None:
                # Fallback: single-leg vanilla
                new_id = db.add_position(
                    ticker=ticker,
                    entry_date=_date.today(),
                    entry_iv_30d=float(iv_used),
                    entry_iv_percentile=(float(iv_perc) if iv_perc is not None else None),
                    notes=f"Paper-buy via Pre-Trade · {chosen.name} (single-leg fallback)",
                    option_type=option_type,
                    strike=float(strike),
                    expiry=_date.today() + _timedelta(days=int(dte)),
                    instrument_type="vanilla",
                    contracts=int(n_contracts),
                    entry_premium=float(entry_price),
                    spot_at_entry=float(spot),
                )
                st.success(
                    f"Paper-bought · single-leg · position #{new_id} · {n_contracts} × "
                    f"{ticker} ${strike:,.2f} {option_type} · entry ${entry_price:.2f}."
                )
            else:
                mat = template.materialize(
                    ticker=ticker, spot=float(spot), iv_pct=float(iv_used),
                    dte=int(dte), contracts=int(n_contracts),
                )
                group_id, cash_after = paper_buy_strategy(
                    db, mat,
                    entry_iv_pct=float(iv_used),
                    entry_iv_percentile=(float(iv_perc) if iv_perc is not None else None),
                    spot=float(spot),
                    scenario_hint="Pre-Trade",
                )
                st.success(
                    f"Bought · {mat.template_name} · {len(mat.legs)} legs · "
                    f"group {group_id[-6:]} · cash ${cash_after:,.0f}"
                )
        except Exception as exc:
            st.error(f"Paper-buy failed: {exc}")

    if do_open:
        nav_to(NavIntent(
            page="Portfolio",
            ticker=ticker,
            source="Pre-Trade",
        ))
        st.rerun()


# ── Internals ────────────────────────────────────────────────────────────

def _safe_float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _pick_iv_for_dte(dte: int, iv30: Optional[float], iv60: Optional[float],
                     iv90: Optional[float]) -> float:
    """Pick the closest available IV for the requested DTE."""
    candidates = [(30, iv30), (60, iv60), (90, iv90)]
    candidates = [(d, v) for d, v in candidates if v is not None and v > 0]
    if not candidates:
        return 30.0   # safe default
    closest = min(candidates, key=lambda dv: abs(dv[0] - dte))
    return float(closest[1])


def _strike_from_delta(
    spot: float,
    T: float,
    iv_dec: float,
    target_delta: float,
    option_type: str,
    tol: float = 0.005,
) -> float:
    """Binary search for the strike whose BSM delta matches target_delta.

    Brackets the search by ±60% around spot which covers all reasonable
    deltas at typical IV levels.
    """
    lo = spot * 0.4
    hi = spot * 1.6
    for _ in range(40):
        mid = (lo + hi) / 2
        d = bs_delta(spot, mid, T, 0.04, iv_dec, option_type=option_type)
        if abs(d - target_delta) < tol:
            return mid
        # Both put and call delta are STRICTLY DECREASING in strike:
        #   put:  K↑  → d ↓ (from ~0 at deep OTM to ~−1 at deep ITM)
        #   call: K↑  → d ↓ (from ~+1 at deep ITM to ~0 at deep OTM)
        # So the search direction is the same in both cases:
        #   d < target → delta too small for this K → strike too high → hi = mid
        #   d > target → delta too large for this K → strike too low  → lo = mid
        if d > target_delta:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _kpi(col, label: str, value: str) -> None:
    """Render one KPI tile in the requested column."""
    render_html(
        col,
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:6px;padding:10px 12px;">'
        f'<div style="color:{COLORS["label"]};font-size:9px;text-transform:uppercase;'
        f'letter-spacing:1px;font-family:{_MONO};">{label}</div>'
        f'<div style="font-family:{_MONO};font-size:16px;font-weight:700;'
        f'color:{COLORS["text"]};margin-top:2px;">{value}</div>'
        f'</div>',
    )


# ──────────────────────────────────────────────────────────────────────────
# Strategy Comparison view (Pillar C)
# ──────────────────────────────────────────────────────────────────────────

def _price_strategy(
    rec,
    spot:    float,
    dte:     int,
    iv_30d:  float,
    iv_60d:  Optional[float],
    iv_90d:  Optional[float],
) -> dict:
    """Pure pricing of one strategy at the given spot/DTE/IV.

    Returns a dict with: strike, option_type, delta, gamma, vega, theta,
    entry_price, iv_used, iv_scenarios (list of pcts), pnl_curve (list of $).

    Mirrors the math of the single-strategy view so apples-to-apples.
    """
    iv_used = _pick_iv_for_dte(dte, iv_30d, iv_60d, iv_90d)
    iv_dec  = iv_used / 100.0
    T = dte / 365.0
    target_delta = rec.target_delta
    option_type = "put" if target_delta < 0 else "call"
    strike = _strike_from_delta(spot, T, iv_dec, target_delta, option_type)

    delta = bs_delta(spot, strike, T, 0.04, iv_dec, option_type=option_type)
    gamma = bs_gamma(spot, strike, T, 0.04, iv_dec)
    vega  = bs_vega(spot, strike, T, 0.04, iv_dec) / 100.0
    theta = bs_theta(spot, strike, T, 0.04, iv_dec, option_type=option_type) / 365.0
    entry_price = bs_price(spot, strike, T, 0.04, iv_dec, option_type=option_type)

    iv_scenarios = list(np.linspace(max(2.0, iv_used - 20.0), iv_used + 20.0, 41))
    pnl_curve = [
        bs_price(spot, strike, T, 0.04, s / 100.0, option_type=option_type) - entry_price
        for s in iv_scenarios
    ]

    return {
        "rec":          rec,
        "strike":       strike,
        "option_type":  option_type,
        "delta":        delta,
        "gamma":        gamma,
        "vega":         vega,
        "theta":        theta,
        "entry_price":  entry_price,
        "iv_used":      iv_used,
        "iv_scenarios": iv_scenarios,
        "pnl_curve":    pnl_curve,
        "dte":          dte,
    }


def _render_comparison_view(
    st,
    ticker:    str,
    recs:      list,
    rec_names: list[str],
    spot:      float,
    iv_30d:    float,
    iv_60d:    Optional[float],
    iv_90d:    Optional[float],
    settings:  dict,
) -> None:
    """Side-by-side rendering of 2-3 strategies + shared P&L chart."""
    import plotly.graph_objects as go
    from datetime import date as _date, timedelta as _timedelta

    # Default to top 2 strategies — most useful comparison
    actionable = [r for r in recs if r.name != "WAIT"]
    default_pick = [r.name for r in actionable[:2]]

    chosen_names = st.multiselect(
        "Strategies to compare (max 3)",
        options=rec_names,
        default=default_pick,
        max_selections=3,
        help="Side-by-side view with shared DTE + shared P&L curve.",
    )
    if not chosen_names:
        st.info("Pick 1-3 strategies to compare.")
        return

    chosen_recs = [next(r for r in recs if r.name == n) for n in chosen_names]

    # Filter out WAIT placeholders
    chosen_recs = [r for r in chosen_recs if r.legs]
    if not chosen_recs:
        st.warning("All selected strategies are WAIT — nothing to price.")
        return

    # Shared DTE slider
    dte = st.slider(
        "Days to expiry (shared across compared strategies)",
        min_value=14, max_value=180, step=7,
        value=int(chosen_recs[0].target_dte) if chosen_recs[0].target_dte > 0 else 60,
        key="pretrade_compare_dte",
    )

    # Price each strategy in parallel
    priced = [_price_strategy(r, spot, dte, iv_30d, iv_60d, iv_90d) for r in chosen_recs]

    # Side-by-side columns
    cols = st.columns(len(priced))
    palette = [COLORS["accent"], COLORS["accent2"], COLORS["amber"]]
    for col, p, color in zip(cols, priced, palette):
        rec = p["rec"]
        with col:
            render_html(
                col,
                f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
                f'border-left:3px solid {color};border-radius:8px;padding:12px 14px;'
                f'margin-bottom:8px;font-family:{_MONO};">'
                f'<div style="color:{color};font-weight:700;font-size:13px;">'
                f'{rec.name}</div>'
                f'<div style="color:{COLORS["muted"]};font-size:11px;margin-top:4px;'
                f'min-height:34px;">{rec.thesis}</div>'
                f'</div>',
            )
            kpi_cols = col.columns(2)
            _kpi(kpi_cols[0], "Strike", f"${p['strike']:,.2f}")
            _kpi(kpi_cols[1], "Entry",  f"${p['entry_price']:.2f}")
            kpi_cols = col.columns(2)
            _kpi(kpi_cols[0], "Δ",  f"{p['delta']:+.3f}")
            _kpi(kpi_cols[1], "ν",  f"${p['vega']:.2f}/1%")
            kpi_cols = col.columns(2)
            _kpi(kpi_cols[0], "Θ",  f"${p['theta']:.2f}/d")
            _kpi(kpi_cols[1], "IV", f"{p['iv_used']:.1f}%")

            # Inline backtest hit-rate
            try:
                from volscope.analytics.strategy_calibration import get_stats_for
                stats = get_stats_for(rec.name, ticker=ticker) or get_stats_for(rec.name)
                if stats is not None and stats.n_trades > 0:
                    render_html(
                        col,
                        f'<div style="font-family:{_MONO};font-size:10px;'
                        f'color:{COLORS["muted"]};margin-top:6px;">'
                        f'hist: <span style="color:{color};font-weight:600;">'
                        f'{stats.hit_rate*100:.0f}%</span> hit · '
                        f'Sharpe {stats.sharpe:+.2f} · n={stats.n_trades}'
                        f'</div>',
                    )
            except Exception:
                pass

            if col.button(
                f"▷ Save {rec.name} to Portfolio",
                key=f"compare_save_{rec.name}",
                use_container_width=True,
            ):
                from volscope.ui.components.navigation import NavIntent, nav_to
                nav_to(NavIntent(
                    page="Portfolio",
                    ticker=ticker,
                    source="Pre-Trade",
                    payload={
                        "underlying":      ticker,
                        "option_type":     p["option_type"],
                        "strike":          float(p["strike"]),
                        "expiry":          (_date.today() + _timedelta(days=int(dte))).isoformat(),
                        "instrument_type": "vanilla",
                        "contracts":       1,
                        "entry_premium":   float(p["entry_price"]),
                        "spot_at_entry":   float(spot),
                        "entry_date":      _date.today().isoformat(),
                    },
                ))
                st.rerun()

    # Shared P&L curve
    fig = go.Figure()
    for p, color in zip(priced, palette):
        fig.add_trace(go.Scatter(
            x=p["iv_scenarios"], y=p["pnl_curve"],
            mode="lines", name=p["rec"].name,
            line=dict(color=color, width=2),
        ))
    fig.add_hline(y=0, line_color=COLORS["border"])
    iv_now = priced[0]["iv_used"]
    fig.add_vline(
        x=iv_now, line_dash="dot", line_color=COLORS["muted"],
        annotation_text=f"current IV {iv_now:.1f}%",
        annotation_position="top",
    )
    fig.update_layout(
        title="P&L per contract vs IV scenario (shared comparison)",
        xaxis_title="IV scenario (%)",
        yaxis_title="P&L per contract ($)",
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        font=dict(family=_MONO, color=COLORS["text"]),
        height=360, margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h", y=-0.18),
    )
    st.plotly_chart(fig, use_container_width=True)
