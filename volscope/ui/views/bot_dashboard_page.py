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
    kpi_grid_html, render_html, section_rule_html,
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


def render_bot_dashboard_page(db: Any, settings: dict) -> None:
    """Render the operator-facing Bot Dashboard."""
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

    # ── Account strip ────────────────────────────────────────────────
    render_html(st, kpi_grid_html([
        ("NLV", "$0", None),
        ("BPR USED", "0%", None),
        ("CASH RESERVE", "100%", COLORS["accent"]),
        ("OPEN TRADES", "0", None),
        ("TODAY P&L", "$0", None),
        ("MTD P&L", "$0", None),
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

    # ── Open trades ──────────────────────────────────────────────────
    render_html(st, section_rule_html("OPEN TRADES"))
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

    # ── P&L equity curve ─────────────────────────────────────────────
    render_html(st, section_rule_html("EQUITY CURVE"))
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
