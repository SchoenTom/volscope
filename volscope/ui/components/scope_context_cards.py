"""Cross-tool awareness cards for Scope.

Three thin cards rendered between Scope's header and the verdict
block. Each card pulls from a cached DB query and reads from the
SSOT page_history; each renders nothing on empty result. Together
they answer the question:

    "What ELSE exists in VolScope for this ticker, beyond raw vol stats?"

  1. 📌 Positions card  — open positions in Portfolio for this ticker
  2. 📅 Earnings card   — next upcoming earnings + implied move hint
  3. ⚡ History card    — was this ticker seen on Discover recently?

Each card has a click-through to the relevant page.

Master plan §13.2: this component is PURELY additive; it does NOT
modify Scope's existing render logic. Master plan §13.4 failure
modes: every DB query in its own try/except → silent log on failure.
Master plan §13.7 saubere Arbeit: one helper per card; cards
render NOTHING when there's no data to surface (no empty-state
cruft).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

log = logging.getLogger(__name__)


def _query_open_positions_for(db, ticker: str):
    """Return open positions DataFrame or None."""
    try:
        df = db.get_positions(ticker=ticker, active_only=True)
        if df is None or df.empty:
            return None
        return df
    except Exception as exc:                                       # noqa: BLE001
        log.debug("get_positions(%s) failed: %s", ticker, exc)
        return None


def _query_upcoming_earnings(db, ticker: str, asof: date):
    """Return next earnings date or None."""
    try:
        df = db.get_upcoming_earnings(ticker, asof)
        if df is None or df.empty:
            return None
        df = df[df["earnings_date"] >= asof].sort_values("earnings_date")
        if df.empty:
            return None
        return df.iloc[0]["earnings_date"]
    except Exception as exc:                                       # noqa: BLE001
        log.debug("get_upcoming_earnings(%s) failed: %s", ticker, exc)
        return None


def _query_discover_history(ticker: str):
    """Look in SSOT page_history for the most recent Discover visit
    of this ticker. Returns (timestamp_iso, hops_ago) or None."""
    try:
        from volscope.ui.state import get_state
        hist = get_state().page_history
        if not hist:
            return None
        ticker_up = ticker.upper()
        # Search from newest to oldest for a Discover hop
        for i, entry in enumerate(reversed(hist)):
            if entry.get("page") == "Discover" and (entry.get("ticker") or "").upper() == ticker_up:
                return (entry.get("ts"), i)
        return None
    except Exception as exc:                                       # noqa: BLE001
        log.debug("discover_history(%s) failed: %s", ticker, exc)
        return None


def _humanise_days_until(target: date, asof: date) -> str:
    delta = (target - asof).days
    if delta < 0:
        return f"{-delta} d ago"
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return f"in {delta} d"


def render_scope_context_cards(st, db, ticker: str) -> None:
    """Top-level entry — render zero or more of the three cards."""
    if not ticker:
        return
    asof = date.today()

    positions = _query_open_positions_for(db, ticker)
    next_earn = _query_upcoming_earnings(db, ticker, asof)
    disc_hist = _query_discover_history(ticker)

    if positions is None and next_earn is None and disc_hist is None:
        return  # no zero-state cruft

    # ── Position card ──
    if positions is not None and not positions.empty:
        n = len(positions)
        # Pick the largest position by contracts for the summary line
        try:
            top = positions.sort_values("contracts", ascending=False).iloc[0]
            label_parts = []
            otype = str(top.get("option_type") or "").lower()
            strike = top.get("strike")
            expiry = top.get("expiry")
            contracts = top.get("contracts")
            if otype and strike is not None:
                label_parts.append(
                    f"{otype.title()} ${strike:.0f}"
                )
            if expiry:
                label_parts.append(str(expiry))
            if contracts:
                label_parts.append(f"× {int(contracts)} ctr")
            top_line = " · ".join(label_parts) if label_parts else "see Portfolio"
        except Exception:                                          # noqa: BLE001
            top_line = "see Portfolio"

        title = (
            f"📌 You have {n} open position{'s' if n != 1 else ''} on {ticker}"
        )
        render_html(
            st,
            f'<div style="background:{COLORS["surface"]};border:1px solid {COLORS["border"]};'
            f'border-left:3px solid {COLORS["accent"]};border-radius:6px;'
            f'padding:10px 14px;margin:8px 0;font-family:DM Sans,sans-serif;font-size:12px;">'
            f'<span style="color:{COLORS["accent"]};font-weight:700;">{title}</span> · '
            f'<span style="color:{COLORS["muted"]};">{top_line}</span>'
            f'</div>',
        )
        # Click-through button to Portfolio
        if st.button(
            "Open in Portfolio →",
            key=f"scope_ctx_portfolio_{ticker}",
            help="See full position details + P/L",
        ):
            try:
                from volscope.ui.components.navigation import NavIntent, nav_to
                nav_to(NavIntent(page="Portfolio", ticker=ticker, source="Scope"))
                st.rerun()
            except Exception as exc:                               # noqa: BLE001
                log.warning("nav to Portfolio failed: %s", exc)

    # ── Earnings card ──
    if next_earn is not None:
        when = _humanise_days_until(next_earn, asof)
        accent = (
            COLORS["warn"] if (next_earn - asof).days <= 7 else
            COLORS["amber"] if (next_earn - asof).days <= 30 else
            COLORS["accent2"]
        )
        title = f"📅 Earnings {when} ({next_earn})"
        render_html(
            st,
            f'<div style="background:{COLORS["surface"]};border:1px solid {COLORS["border"]};'
            f'border-left:3px solid {accent};border-radius:6px;'
            f'padding:10px 14px;margin:8px 0;font-family:DM Sans,sans-serif;font-size:12px;">'
            f'<span style="color:{accent};font-weight:700;">{title}</span> · '
            f'<span style="color:{COLORS["muted"]};">'
            f'Pre-earnings IV is typically elevated — front/back-IV decomposition '
            f'on Vol Insights shows the isolated event premium.'
            f'</span></div>',
        )
        if st.button(
            "Open Earnings Hub →",
            key=f"scope_ctx_earnings_{ticker}",
            help="See implied move, post-print history, crush estimate",
        ):
            try:
                from volscope.ui.components.navigation import NavIntent, nav_to
                nav_to(NavIntent(page="Earnings Hub", ticker=ticker, source="Scope"))
                st.rerun()
            except Exception as exc:                               # noqa: BLE001
                log.warning("nav to Earnings Hub failed: %s", exc)

    # ── Discover history card ──
    if disc_hist is not None:
        ts_str, hops_ago = disc_hist
        when_str = ""
        try:
            if ts_str:
                t = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                delta_days = (datetime.now(t.tzinfo) - t).days
                when_str = "earlier today" if delta_days == 0 else f"{delta_days} d ago"
        except Exception:                                          # noqa: BLE001
            when_str = f"{hops_ago + 1} nav-hops ago"
        title = f"⚡ Last seen on Discover {when_str or 'recently'}"
        render_html(
            st,
            f'<div style="background:{COLORS["surface"]};border:1px solid {COLORS["border"]};'
            f'border-left:3px solid {COLORS["accent2"]};border-radius:6px;'
            f'padding:10px 14px;margin:8px 0;font-family:DM Sans,sans-serif;font-size:12px;">'
            f'<span style="color:{COLORS["accent2"]};font-weight:700;">{title}</span> · '
            f'<span style="color:{COLORS["muted"]};">'
            f'Re-rank against today\'s universe to see if the signal still holds.'
            f'</span></div>',
        )
        if st.button(
            "Re-rank on Discover →",
            key=f"scope_ctx_discover_{ticker}",
            help="Compare today's signal vs your last visit",
        ):
            try:
                from volscope.ui.components.navigation import NavIntent, nav_to
                nav_to(NavIntent(page="Discover", ticker=ticker, source="Scope"))
                st.rerun()
            except Exception as exc:                               # noqa: BLE001
                log.warning("nav to Discover failed: %s", exc)
