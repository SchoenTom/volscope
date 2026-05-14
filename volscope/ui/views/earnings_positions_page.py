"""
Earnings Trades — separate view of all paper-bought ER trades.

Filters the global ``positions`` table to the rows whose
``strategy_group_id`` carries the "Earnings Hub" scenario hint.
Renders one row per strategy group with:

  ticker · template · ER date · days-to/from ER · current MTM P/L

Adds a top-line summary: count open · count past-ER (needs close) ·
total unrealised P/L.

Wired into the sidebar under EXECUTION as "Earnings Trades".
"""
from __future__ import annotations

from datetime import date
from html import escape
from typing import Optional

import pandas as pd
import streamlit as st

from volscope.data.paper_trader import (
    get_cash_balance,
    list_strategy_groups,
    paper_close_strategy,
)
from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS


def render_earnings_positions_page(db, settings: dict | None = None) -> None:
    st.markdown("## ◈ Earnings Trades")
    st.caption(
        "Paper-bought earnings positions. Auto-tracks countdown to "
        "(or days since) the print and the live BSM-marked P/L."
    )
    render_data_freshness_bar(db, compact=True)

    # ── Pull groups, filter to earnings-tagged trades ───────────────
    groups = list_strategy_groups(db)
    er_groups = [g for g in groups if _is_earnings_group(g)]

    if not er_groups:
        render_html(
            st,
            f'<div class="volscope-empty-state">'
            f'<div class="volscope-empty-headline">No open earnings trades.</div>'
            f'<div class="volscope-empty-body">'
            f'Paper-buy a tile from the <strong>Earnings Hub</strong> to '
            f'see it here. Each trade carries an automatic ER countdown '
            f'and live mark-to-market.</div></div>',
        )
        return

    # Decorate each group with its earnings_date + countdown
    decorated = []
    for g in er_groups:
        er_dt = _extract_er_date(g)
        days = (er_dt - date.today()).days if er_dt else None
        decorated.append({
            "group": g,
            "er_date": er_dt,
            "days_to_er": days,
        })
    decorated.sort(
        key=lambda d: (d["days_to_er"] is None,
                       d["days_to_er"] if d["days_to_er"] is not None else 999),
    )

    # ── Top-line summary ─────────────────────────────────────────────
    n_open = len(decorated)
    n_past = sum(1 for d in decorated if d["days_to_er"] is not None
                  and d["days_to_er"] < 0)
    cash = get_cash_balance(db)
    render_html(
        st,
        f'<div style="display:flex;gap:14px;align-items:baseline;'
        f'padding:8px 12px;background:{COLORS["card"]};border-radius:6px;'
        f'border-left:3px solid {COLORS["accent"]};font-family:JetBrains Mono,monospace;'
        f'margin-bottom:12px;">'
        f'<div><span style="font-size:9px;color:{COLORS["label"]};text-transform:uppercase;'
        f'letter-spacing:1.4px;">positions</span> '
        f'<strong style="color:{COLORS["text"]};font-size:14px;margin-left:6px;">'
        f'{n_open}</strong></div>'
        f'<div><span style="font-size:9px;color:{COLORS["label"]};text-transform:uppercase;'
        f'letter-spacing:1.4px;">post-print</span> '
        f'<strong style="color:{COLORS["amber"]};font-size:14px;margin-left:6px;">'
        f'{n_past}</strong></div>'
        f'<div style="margin-left:auto;"><span style="font-size:9px;'
        f'color:{COLORS["label"]};text-transform:uppercase;letter-spacing:1.4px;">'
        f'cash</span> '
        f'<strong style="color:{COLORS["text"]};font-size:14px;margin-left:6px;">'
        f'${cash:,.0f}</strong></div>'
        f'</div>',
    )

    # ── Per-group row ────────────────────────────────────────────────
    for d in decorated:
        _render_er_group_row(db, d)


def _is_earnings_group(group) -> bool:
    """A group is ER-tagged if any leg's notes contain 'Earnings Hub ·'."""
    for leg in group.legs:
        notes = str(leg.get("notes") or "")
        if "Earnings Hub" in notes:
            return True
    return False


def _extract_er_date(group) -> Optional[date]:
    """Pull the ER date out of the notes string format
    'Earnings Hub · TICKER ER YYYY-MM-DD'."""
    for leg in group.legs:
        notes = str(leg.get("notes") or "")
        if "Earnings Hub" not in notes:
            continue
        # Find an ISO date pattern in the notes
        import re
        m = re.search(r"(\d{4}-\d{2}-\d{2})", notes)
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                continue
    return None


def _render_er_group_row(db, decorated: dict) -> None:
    g = decorated["group"]
    er_date = decorated["er_date"]
    days = decorated["days_to_er"]
    ticker = g.ticker
    template = g.strategy_template

    # Current MTM via re-pricing all legs at today's spot+IV
    from volscope.analytics.black_scholes import bs_price
    try:
        latest = db.get_ticker_history(ticker).iloc[-1]
        spot_now = float(latest.get("spot_price") or 0)
        iv_now = float(latest.get("iv_30d") or 25)
    except Exception:
        spot_now = None
        iv_now = None

    pnl = 0.0
    if spot_now is not None and spot_now > 0:
        for leg in g.legs:
            sign = +1 if str(leg.get("action") or "buy") == "buy" else -1
            entry = float(leg.get("entry_premium") or 0)
            strike = float(leg.get("strike") or 0)
            expiry = leg.get("expiry")
            ctrs = int(leg.get("contracts") or 1)
            opt_type = str(leg.get("option_type") or "call")
            try:
                exp_d = pd.to_datetime(expiry).date()
                dte = max(1, (exp_d - date.today()).days)
            except Exception:
                dte = 30
            T = dte / 365.0
            if strike <= 0:
                cur = spot_now    # stock leg
            else:
                cur = bs_price(spot_now, strike, T, 0.04, iv_now / 100, 0.0,
                                option_type=opt_type)
            pnl += sign * (cur - entry) * ctrs * 100

    # Countdown color + label
    if days is None:
        countdown = "ER date unknown"
        cd_color = COLORS["muted"]
    elif days < 0:
        countdown = f"post-print · {abs(days)}d ago"
        cd_color = COLORS["amber"]
    elif days == 0:
        countdown = "TODAY"
        cd_color = COLORS["warn"]
    elif days <= 2:
        countdown = f"in {days}d"
        cd_color = COLORS["warn"]
    elif days <= 7:
        countdown = f"in {days}d"
        cd_color = COLORS["amber"]
    else:
        countdown = f"in {days}d"
        cd_color = COLORS["accent2"]

    pnl_color = COLORS["accent"] if pnl >= 0 else COLORS["warn"]
    sign = "+" if pnl >= 0 else "−"

    render_html(
        st,
        f'<div style="display:flex;align-items:center;gap:14px;'
        f'background:{COLORS["card"]};border-left:3px solid {cd_color};'
        f'border:1px solid {COLORS["border"]};border-radius:6px;'
        f'padding:10px 14px;margin-bottom:6px;'
        f'font-family:JetBrains Mono,monospace;">'
        f'<div style="flex:0 0 80px;"><strong style="color:{COLORS["text"]};'
        f'font-size:13px;">{escape(ticker)}</strong></div>'
        f'<div style="flex:0 0 160px;color:{COLORS["text"]};font-size:11px;">'
        f'{escape(template)}</div>'
        f'<div style="flex:0 0 130px;color:{cd_color};font-size:11px;'
        f'font-weight:600;">{countdown}</div>'
        f'<div style="flex:0 0 100px;color:{COLORS["muted"]};font-size:10px;">'
        f'ER {er_date.isoformat() if er_date else "—"}</div>'
        f'<div style="flex:0 0 70px;color:{COLORS["muted"]};font-size:10px;'
        f'text-align:right;">{len(g.legs)} legs</div>'
        f'<div style="flex:0 0 100px;color:{pnl_color};font-size:13px;'
        f'font-weight:700;text-align:right;">'
        f'{sign}${abs(pnl):,.0f}</div>'
        f'</div>',
    )

    # Inline close-button when post-print
    if days is not None and days < 0:
        c1, _ = st.columns([1, 4])
        with c1:
            if st.button(f"✕ close · {ticker}",
                         key=f"er_close_{g.strategy_group_id}"):
                pl, cash_after = paper_close_strategy(db, g.strategy_group_id)
                st.success(
                    f"Closed · realised P/L ${pl:+,.0f} · cash ${cash_after:,.0f}"
                )
                st.rerun()
