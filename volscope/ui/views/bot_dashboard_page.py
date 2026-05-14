"""
Bot Dashboard — Phase 1 scaffold.

The autonomous bot's primary operator-facing view. Pure read-only:
*never* execute trades from this page. Execution happens in the
scheduler (Phase 2). This view answers: "what is the bot doing, why,
and how exposed am I?"

Sections (top to bottom):
1. Account strip — NLV, BPR%, cash reserve, daily P&L, MTD P&L
2. Greek strip — portfolio Δ, Γ, V (vega), Θ
3. Regime gauge — HMM p_calm probability + state label
4. Live signals table — sortable by composite score, with gate badges
5. Open trades — current MTM, %-of-PT-reached, DTE-to-21
6. Recent signals_log — last 50 decisions with WHY
7. P&L equity curve from bot_pnl_daily

Status: scaffold renders structure with placeholder data. Phase 2
wires it to real bot_* tables once the scheduler is populating them.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from volscope.ui.components.html_utils import (
    kpi_grid_html, page_banner_html, render_html, section_rule_html,
)
from volscope.ui.styles.theme import COLORS

_MONO = "JetBrains Mono"


def _empty_signals_message() -> str:
    return (
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:8px;padding:24px;text-align:center;">'
        f'<div style="color:{COLORS["muted"]};font-size:13px;'
        f'font-family:\'{_MONO}\';">'
        f'BOT NOT YET LIVE — Phase 1 scaffold renders shape only.'
        f'</div>'
        f'<div style="color:{COLORS["label"]};font-size:11px;margin-top:6px;'
        f'font-family:\'{_MONO}\';">'
        f'Scheduler + paper engine land in Phase 2.'
        f'</div>'
        f'</div>'
    )


def _regime_card(p_calm: float | None) -> str:
    """Render an inline HMM regime card."""
    if p_calm is None:
        return (
            f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
            f'border-radius:8px;padding:14px 16px;">'
            f'<div style="color:{COLORS["label"]};font-size:10px;letter-spacing:0.1em;">REGIME</div>'
            f'<div style="color:{COLORS["muted"]};font-size:13px;margin-top:4px;'
            f'font-family:\'{_MONO}\';">HMM not fit — Phase 2</div>'
            f'</div>'
        )
    state = "CALM" if p_calm >= 0.6 else ("MIXED" if p_calm >= 0.4 else "STRESS")
    state_color = (COLORS["accent"] if state == "CALM"
                    else COLORS["warn"] if state == "STRESS"
                    else COLORS["muted"])
    return (
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:8px;padding:14px 16px;">'
        f'<div style="color:{COLORS["label"]};font-size:10px;letter-spacing:0.1em;">REGIME</div>'
        f'<div style="display:flex;align-items:baseline;gap:8px;margin-top:4px;">'
        f'<div style="color:{state_color};font-size:18px;font-weight:600;'
        f'font-family:\'{_MONO}\';">{state}</div>'
        f'<div style="color:{COLORS["muted"]};font-size:11px;'
        f'font-family:\'{_MONO}\';">p_calm = {p_calm:.2f}</div>'
        f'</div>'
        f'</div>'
    )


@st.fragment(run_every="30s")
def _live_signals_fragment(db: Any) -> None:
    """Auto-refreshes every 30s without re-running the whole page.

    Streamlit fragments rerun in isolation — the rest of the dashboard
    stays put while this panel polls ``bot_signals_log``. Acceptable
    poll cost (one tiny indexed SELECT) for the operator-felt
    "this feels live during market hours" win.
    """
    try:
        signals_df = db.con.execute(
            "SELECT snapshot_date, underlying, direction, composite_score, "
            "decision FROM bot_signals_log "
            "ORDER BY snapshot_date DESC, composite_score DESC LIMIT 50"
        ).fetchdf()
    except Exception:
        signals_df = pd.DataFrame()
    if signals_df.empty:
        render_html(st, _empty_signals_message())
    else:
        st.dataframe(signals_df, hide_index=True, use_container_width=True)


@st.fragment(run_every="30s")
def _open_trades_fragment(db: Any) -> None:
    """Open paper-trades panel — refreshes independently every 30s."""
    try:
        open_df = db.con.execute(
            "SELECT trade_id, strategy, underlying, direction, status, "
            "opened_at, capital_at_risk FROM bot_trades "
            "WHERE status NOT IN ('CLOSED','EXPIRED','ABANDONED','ASSIGNED') "
            "ORDER BY opened_at DESC"
        ).fetchdf()
    except Exception:
        open_df = pd.DataFrame()
    if open_df.empty:
        render_html(st, _empty_signals_message())
    else:
        st.dataframe(open_df, hide_index=True, use_container_width=True)


@st.fragment(run_every="30s")
def _equity_curve_fragment(db: Any) -> None:
    """NLV equity curve — refreshes independently every 30s."""
    try:
        pnl_df = db.con.execute(
            "SELECT date, nlv FROM bot_pnl_daily ORDER BY date"
        ).fetchdf()
    except Exception:
        pnl_df = pd.DataFrame()
    if pnl_df.empty:
        render_html(st, _empty_signals_message())
    else:
        st.line_chart(pnl_df.set_index("date")["nlv"], height=240)


def render_bot_dashboard_page(db: Any, settings: dict) -> None:
    """Render the operator-facing Bot Dashboard."""
    # v0.9.0 — persistent vol-regime header strip.
    from volscope.ui.components.regime_header import render_regime_header
    render_regime_header(db)

    render_html(
        st,
        page_banner_html(
            title="Bot Dashboard",
            what="autonomous paper engine — operator read-only view",
            when="twice/day max during market hours",
        ),
    )
    render_html(
        st,
        f"""
        <div style="margin-bottom:18px;">
          <div style="font-family:'{_MONO}';font-size:22px;font-weight:700;
                      color:{COLORS['text']};letter-spacing:0.04em;">
            ◈ Bot Dashboard
          </div>
          <div style="color:{COLORS['muted']};font-size:12px;margin-top:2px;">
            autonomous IV mean-reversion · paper engine (Phase 2 wires this live)
          </div>
        </div>
        """,
    )

    # ── Account strip — pulls real data from bot_pnl_daily + bot_trades ──
    try:
        latest_pnl = db.con.execute(
            "SELECT nlv, bpr_used, cash, realized_pnl, unrealized_pnl, "
            "open_positions FROM bot_pnl_daily ORDER BY date DESC LIMIT 1"
        ).fetchone()
    except Exception:
        latest_pnl = None
    try:
        open_count = db.con.execute(
            "SELECT COUNT(*) FROM bot_trades "
            "WHERE status NOT IN ('CLOSED','EXPIRED','ABANDONED','ASSIGNED','REJECTED','ROLLED')"
        ).fetchone()[0]
    except Exception:
        open_count = 0
    try:
        mtd_pnl = db.con.execute(
            "SELECT COALESCE(SUM(realized_pnl),0) FROM bot_trades "
            "WHERE status='CLOSED' AND DATE_TRUNC('month', closed_at) = DATE_TRUNC('month', CURRENT_DATE)"
        ).fetchone()[0] or 0.0
    except Exception:
        mtd_pnl = 0.0

    nlv = float(latest_pnl[0]) if latest_pnl and latest_pnl[0] else 0.0
    bpr = float(latest_pnl[1]) if latest_pnl and latest_pnl[1] else 0.0
    today_pnl = float(latest_pnl[3]) if latest_pnl and latest_pnl[3] else 0.0
    today_color = COLORS["accent"] if today_pnl > 0 else (COLORS["warn"] if today_pnl < 0 else None)
    mtd_color = COLORS["accent"] if mtd_pnl > 0 else (COLORS["warn"] if mtd_pnl < 0 else None)

    render_html(st, kpi_grid_html([
        ("NLV", f"${nlv:,.0f}" if nlv else "$0", None),
        ("BPR USED", f"{bpr:.0%}" if bpr else "0%", None),
        ("CASH RESERVE", f"{1-bpr:.0%}" if bpr else "100%", COLORS["accent"]),
        ("OPEN TRADES", str(open_count), None),
        ("TODAY P&L", f"${today_pnl:+,.0f}" if today_pnl else "$0", today_color),
        ("MTD P&L", f"${mtd_pnl:+,.0f}" if mtd_pnl else "$0", mtd_color),
    ], variant="compact"))

    # ── Greek strip ──────────────────────────────────────────────────
    render_html(st, section_rule_html("PORTFOLIO GREEKS"))
    render_html(st, kpi_grid_html([
        ("DELTA", "0.00", None),
        ("GAMMA", "0.00", None),
        ("VEGA",  "$0",   None),
        ("THETA", "$0",   None),
    ], variant="compact"))

    # ── Regime gauge ─────────────────────────────────────────────────
    render_html(st, section_rule_html("REGIME"))
    render_html(st, _regime_card(None))

    # ── Live signals table ───────────────────────────────────────────
    render_html(st, section_rule_html("LIVE SIGNALS"))
    _live_signals_fragment(db)

    # ── Open trades ──────────────────────────────────────────────────
    render_html(st, section_rule_html("OPEN TRADES"))
    _open_trades_fragment(db)

    # ── P&L equity curve ─────────────────────────────────────────────
    render_html(st, section_rule_html("EQUITY CURVE"))
    _equity_curve_fragment(db)

    # ── Backtest / Closed-trade performance ──────────────────────────
    render_html(st, section_rule_html("BACKTEST · CLOSED-TRADE PERFORMANCE"))
    try:
        from volscope.analytics.paper_backtest import report_from_closed_trades
        rpt = report_from_closed_trades(db)
        if rpt.n_trades == 0:
            render_html(st, _empty_signals_message())
        else:
            pf_str = f"{rpt.profit_factor:.2f}" if rpt.profit_factor != float("inf") else "∞"
            render_html(st, kpi_grid_html([
                ("TRADES", str(rpt.n_trades), None),
                ("WIN RATE", f"{rpt.win_rate:.0%}", COLORS["accent"] if rpt.win_rate > 0.6 else None),
                ("PROFIT FACTOR", pf_str, COLORS["accent"] if rpt.profit_factor > 1.2 else COLORS["warn"]),
                ("EXPECTANCY", f"${rpt.expectancy:+,.0f}", None),
                ("SHARPE", f"{rpt.sharpe:+.2f}", COLORS["accent"] if rpt.sharpe > 0.5 else None),
                ("MAX DD", f"${rpt.max_drawdown:,.0f}", COLORS["warn"]),
            ], variant="compact"))
    except Exception as exc:
        render_html(st, f'<div style="color:{COLORS["muted"]};font-size:11px;">'
                         f'Backtest unavailable: {exc}</div>')
