"""
Strategy Builder page — pick a vola scenario, get a fully-specified
trade idea (structure, DTE, strike rule, target greeks, thesis).

Thin orchestration over `analytics.scenario_builder` + the live ticker
state in DuckDB. No new analytics live here — the page is presentation
only.
"""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from volscope.analytics.scenario_builder import (
    SCENARIO_HINTS,
    SCENARIO_LABELS,
    Scenario,
    build_scenario_recommendation,
    scenario_card_html,
)
from volscope.analytics.strategy_templates import resolve_template
from volscope.data.paper_trader import (
    get_cash_balance,
    paper_buy_strategy,
)
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS


def _days_to_next_earnings(db, ticker: str) -> int | None:
    """Return days until the next earnings date, or None when unknown.

    Negative values mean the most recent ER is in the past (used by
    the post-ER scenarios).
    """
    try:
        df = db.get_upcoming_earnings(
            ticker, pd.Timestamp("1970-01-01").date()
        )
    except Exception:
        return None
    if df is None or df.empty:
        return None
    try:
        today = pd.Timestamp.today().normalize()
        future = df[pd.to_datetime(df["earnings_date"]) >= today]
        if not future.empty:
            return int(
                (pd.to_datetime(future["earnings_date"].iloc[0]) - today).days
            )
        # Most recent past ER
        past = df[pd.to_datetime(df["earnings_date"]) < today]
        if not past.empty:
            return int(
                (pd.to_datetime(past["earnings_date"].iloc[-1]) - today).days
            )
    except Exception:
        return None
    return None


def render_strategy_builder_page(db, settings: dict | None = None) -> None:
    # v0.9.7 — 4-phase orientation strip (master plan §2)
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name='Builder', ticker=st.session_state.get('selected_ticker'))
    st.markdown("## ◈ Strategy Builder")
    st.caption(
        "Pick a thesis, get a fully-specified trade idea. Strike, DTE, "
        "greeks profile, the why — and what kills it."
    )
    from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
    render_data_freshness_bar(db, compact=True)

    # ── Ticker + scenario picker ────────────────────────────────────
    available = db.get_available_tickers() or []
    if not available:
        render_html(
            st,
            f'<div style="background:{COLORS["surface"]};border-left:3px solid {COLORS["amber"]};'
            f'border-radius:6px;padding:12px 16px;margin-top:12px;'
            f'font-family:JetBrains Mono,monospace;font-size:12px;color:{COLORS["text"]};">'
            f'⚠ No tickers loaded. Add one via the sidebar before using the builder.'
            f'</div>',
        )
        return

    default_idx = 0
    cur = st.session_state.get("selected_ticker")
    if cur in available:
        default_idx = available.index(cur)

    col1, col2 = st.columns([1, 2])
    with col1:
        ticker = st.selectbox("Ticker", available, index=default_idx, key="sb_ticker")
    with col2:
        scenario_value = st.selectbox(
            "Scenario",
            list(SCENARIO_LABELS.keys()),
            format_func=lambda s: SCENARIO_LABELS[s],
            key="sb_scenario",
        )

    # Hint line for the selected scenario
    render_html(
        st,
        f'<div style="font-family:JetBrains Mono,monospace;font-size:11px;'
        f'color:{COLORS["muted"]};margin:4px 0 12px 0;">'
        f'<strong style="color:{COLORS["text"]};">when to use:</strong> '
        f'{escape(SCENARIO_HINTS.get(scenario_value, ""))}'
        f'</div>',
    )

    # ── Pull live state for this ticker ─────────────────────────────
    history = db.get_ticker_history(ticker)
    if history.empty:
        render_html(
            st,
            f'<div style="color:{COLORS["muted"]};font-family:JetBrains Mono,monospace;'
            f'font-size:11px;padding:6px 0;">'
            f'No history for {escape(ticker)} — run <code>make scrape</code>.'
            f'</div>',
        )
        return

    latest = history.iloc[-1]

    def _f(name: str) -> float | None:
        v = latest.get(name)
        try:
            return float(v) if v is not None and not pd.isna(v) else None
        except (TypeError, ValueError):
            return None

    iv_30d        = _f("iv_30d")
    iv_percentile = _f("iv_percentile")
    iv_rank       = _f("iv_rank")
    hv_20d        = _f("hv_20d")
    spot          = _f("spot_price")
    days_to_er    = _days_to_next_earnings(db, ticker)

    # ── State strip — what the builder is using as inputs ───────────
    from volscope.ui.components.metric_components import _ibkr_cell
    cells = [
        _ibkr_cell("SPOT",     f"${spot:.2f}" if spot is not None else "—"),
        _ibkr_cell("IV 30D",   f"{iv_30d:.1f}%" if iv_30d is not None else "—",
                   value_class="fg-cheap"),
        _ibkr_cell("HV 20D",   f"{hv_20d:.1f}%" if hv_20d is not None else "—",
                   value_class="fg-mid"),
        _ibkr_cell("IV PERC",  f"{iv_percentile:.0f}" if iv_percentile is not None else "—"),
        _ibkr_cell("IV RANK",  f"{iv_rank:.0f}" if iv_rank is not None else "—"),
        _ibkr_cell("DAYS TO ER",
                   f"{days_to_er:+d}d" if days_to_er is not None else "—",
                   value_class=("fg-warn" if days_to_er is not None and 0 <= days_to_er <= 7 else "")),
    ]
    render_html(
        st,
        '<div class="volscope-ibkr-row">' + "".join(cells) + "</div>",
    )

    # ── Build + render the recommendation card ──────────────────────
    rec = build_scenario_recommendation(
        scenario_value,
        iv_30d=iv_30d,
        iv_percentile=iv_percentile,
        iv_rank=iv_rank,
        hv_20d=hv_20d,
        spot=spot,
        days_to_earnings=days_to_er,
    )
    render_html(st, scenario_card_html(rec))

    # ── Paper-buy this strategy ─────────────────────────────────────
    # Resolve the recommended structure to an executable template,
    # materialise legs with the live state, show a broker-style
    # preview, and let the user paper-buy 1-click.
    template = resolve_template(rec.structure)
    if template is None or spot is None or iv_30d is None:
        render_html(
            st,
            f'<div style="background:{COLORS["surface"]};border-left:3px solid {COLORS["amber"]};'
            f'border-radius:6px;padding:10px 14px;margin-top:8px;'
            f'font-family:JetBrains Mono,monospace;font-size:11px;color:{COLORS["text"]};">'
            f'⚠ Paper-buy unavailable — '
            f'{"no matching template for " + escape(rec.structure) if template is None else "missing live spot/IV"}.'
            f'</div>',
        )
        return

    # Sizing controls. v0.9.2: caps raised (200 → 100 000, 900d → 2 500d)
    # for parity with Options Lab and to remove the arbitrary retail-
    # only ceiling. Operator-side risk discipline is the actual brake.
    s_col1, s_col2, _ = st.columns([1, 1, 4])
    with s_col1:
        contracts = st.number_input(
            "Contracts",
            min_value=1, max_value=100_000, value=1, step=1,
            key="sb_contracts",
        )
    with s_col2:
        dte_override = st.number_input(
            "DTE",
            min_value=1, max_value=2_500,
            value=int(rec.target_dte), step=1,
            key="sb_dte",
            help="Days to expiry for the primary leg.",
        )

    try:
        mat = template.materialize(
            ticker=ticker, spot=float(spot), iv_pct=float(iv_30d),
            dte=int(dte_override), contracts=int(contracts),
        )
    except Exception as exc:
        st.error(f"Could not materialise legs: {exc}")
        return

    # Leg preview — broker-style
    cash = get_cash_balance(db)
    cash_after = cash - mat.net_debit
    debit_label = "DEBIT (pay)" if mat.net_debit >= 0 else "CREDIT (collect)"
    debit_color = COLORS["warn"] if mat.net_debit >= 0 else COLORS["accent"]

    leg_rows = ""
    for leg in mat.legs:
        action_sign = "+" if leg.action == "buy" else "−"
        action_color = COLORS["accent"] if leg.action == "buy" else COLORS["warn"]
        leg_rows += (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:4px 0;font-size:11px;border-bottom:1px solid {COLORS["border"]};">'
            f'<span style="color:{action_color};font-weight:600;">'
            f'{action_sign}{leg.contracts} {leg.option_type.upper()} {leg.strike:g}</span>'
            f'<span style="color:{COLORS["muted"]};">'
            f'exp {leg.expiry.isoformat()} · Δ {leg.delta:+.2f}'
            f'</span>'
            f'<span style="color:{COLORS["text"]};font-weight:600;">'
            f'${leg.entry_premium:.2f}'
            f'</span></div>'
        )

    max_loss_str = f"${mat.max_loss:,.0f}" if mat.max_loss is not None else "unbounded"
    max_gain_str = f"${mat.max_gain:,.0f}" if mat.max_gain is not None else "unbounded"
    breakevens_str = (
        " / ".join(f"${b:,.2f}" for b in mat.breakevens) if mat.breakevens else "—"
    )

    insufficient = cash_after < 0
    cash_after_color = COLORS["warn"] if insufficient else COLORS["text"]

    render_html(
        st,
        f'''
<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};
            border-left:3px solid {COLORS["accent"]};border-radius:8px;
            padding:14px 18px;margin-top:14px;font-family:JetBrains Mono,monospace;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid {COLORS["border"]};">
    <div>
      <div style="font-size:9px;letter-spacing:1.4px;color:{COLORS["label"]};
                   text-transform:uppercase;font-weight:600;">order ticket</div>
      <div style="font-size:14px;font-weight:700;color:{COLORS["text"]};margin-top:2px;">
        {escape(mat.template_name)} · {escape(ticker)}
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:9px;letter-spacing:1.4px;color:{COLORS["label"]};
                   text-transform:uppercase;font-weight:600;">{debit_label}</div>
      <div style="font-size:18px;font-weight:700;color:{debit_color};">
        ${abs(mat.net_debit):,.0f}
      </div>
    </div>
  </div>

  <div style="margin-bottom:10px;">{leg_rows}</div>

  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;
              font-size:10px;color:{COLORS["muted"]};">
    <div>
      <div style="color:{COLORS["label"]};text-transform:uppercase;letter-spacing:1px;">max loss</div>
      <div style="color:{COLORS["warn"]};font-weight:600;font-size:12px;">{max_loss_str}</div>
    </div>
    <div>
      <div style="color:{COLORS["label"]};text-transform:uppercase;letter-spacing:1px;">max gain</div>
      <div style="color:{COLORS["accent"]};font-weight:600;font-size:12px;">{max_gain_str}</div>
    </div>
    <div>
      <div style="color:{COLORS["label"]};text-transform:uppercase;letter-spacing:1px;">breakeven</div>
      <div style="color:{COLORS["text"]};font-weight:600;font-size:12px;">{breakevens_str}</div>
    </div>
    <div>
      <div style="color:{COLORS["label"]};text-transform:uppercase;letter-spacing:1px;">cash after</div>
      <div style="color:{cash_after_color};font-weight:600;font-size:12px;">${cash_after:,.0f}</div>
    </div>
  </div>
</div>''',
    )

    bt_col1, bt_col2, bt_col3 = st.columns([2, 2, 3])
    with bt_col1:
        do_buy = st.button(
            "▶ paper-buy",
            key="sb_paper_buy",
            type="primary",
            width='stretch',
            disabled=insufficient,
            help=(
                "Insufficient cash" if insufficient
                else f"Debit ${mat.net_debit:,.0f} · open {len(mat.legs)} legs in Portfolio"
            ),
        )
    with bt_col2:
        if st.button("▷ portfolio →", key="sb_open_portfolio_2", width='stretch'):
            from volscope.ui.components.navigation import NavIntent, nav_to
            nav_to(NavIntent(page="Portfolio", ticker=ticker, source="StrategyBuilder"))
            st.rerun()
    with bt_col3:
        render_html(
            st,
            f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;'
            f'color:{COLORS["muted"]};padding:8px 4px;line-height:1.3;">'
            f'cash ${cash:,.0f} · {len(mat.legs)} legs · simulated broker'
            f'</div>',
        )

    if do_buy:
        try:
            group_id, cash_after_real = paper_buy_strategy(
                db, mat,
                entry_iv_pct=float(iv_30d),
                entry_iv_percentile=(float(iv_percentile) if iv_percentile is not None else None),
                spot=float(spot),
                scenario_hint=SCENARIO_LABELS.get(scenario_value, ""),
            )
            st.success(
                f"Bought · {mat.template_name} · {len(mat.legs)} legs · "
                f"group {group_id[-6:]} · cash ${cash_after_real:,.0f}"
            )
        except Exception as exc:
            st.error(f"Paper-buy failed: {exc}")

    # ── Footer caveat ───────────────────────────────────────────────
    render_html(
        st,
        f'<div style="margin-top:14px;padding:10px 14px;background:{COLORS["surface"]};'
        f'border:1px solid {COLORS["border"]};border-radius:6px;'
        f'font-family:JetBrains Mono,monospace;font-size:10px;color:{COLORS["muted"]};'
        f'line-height:1.5;">'
        f'<strong style="color:{COLORS["text"]};">how this works:</strong> the builder '
        f'reads the latest scrape for {escape(ticker)} and feeds it into a deterministic '
        f'rules engine. No ML, no overfit — just a clean mapping from vol-state to a '
        f'trader-recognisable structure. Confidence drops to <em>low</em> when the '
        f'scenario fires on incomplete data; flags surface what was missing.'
        f'</div>',
    )

    # v0.9.7 — cross-page weave footer (master plan §4)
    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(st, page='Builder', ticker=st.session_state.get('selected_ticker'))
