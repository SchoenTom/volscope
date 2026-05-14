"""
Signals dashboard — bidirectional IV mean-reversion scanner UI.

Renders two columns:

    LONG VOL (buy premium)  |  SHORT VOL (sell premium)

Each card carries the headline reason, recommended strategy, and a
"→ Open in Options Lab" button that pre-fills session_state so the
trader can drill into P&L / Greeks / Scenario matrix without retyping
ticker + strikes.

Earnings-filtered short-vol setups remain visible in a faded state
with an "⚠ ER blocked" pill, so the trader can see *why* a candidate
didn't surface (transparency > silent filtering).
"""
from __future__ import annotations

from html import escape
from typing import Optional

import streamlit as st

from volscope.analytics.signal_backtest import (
    SignalBacktest, backtest_signal, edge_string as bt_edge_string,
)
from volscope.analytics.signals import (
    Signal,
    generate_signals,
    persist_signals,
    summarize,
)
from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
from volscope.ui.components.html_utils import render_html
from volscope.ui.components.sparkline import sparkline_svg
from volscope.ui.styles.theme import COLORS, seq_color


_FILTER_OPTIONS = ("All", "Long Vol", "Short Vol", "Earnings-Filtered")


# ── Public entry point ───────────────────────────────────────────────

def render_signals_page(db, settings: Optional[dict] = None) -> None:
    """Mounted from `_PAGE_REGISTRY` as 'Signals'."""
    st.markdown("## ⚡ IV Trading Signals")
    st.caption(
        "Bidirectional scanner — cheap IV → buy premium, rich IV → sell "
        "premium. 65 % of US tickers show mean-reverting IV (MDPI 2024). "
        "Short-vol setups are auto-filtered when earnings are within 14 days."
    )
    render_data_freshness_bar(db, compact=True)

    # ── Run scan ────────────────────────────────────────────────────
    with st.spinner("Scanning universe …"):
        signals = generate_signals(db, include_filtered_shortvol=True)
    stats = summarize(signals)

    # ── Filter strip — direction quadrant + watchlist toggle ────────
    cols = st.columns(4)
    for col, label in zip(cols, _FILTER_OPTIONS):
        with col:
            is_active = st.session_state.get("sig_filter", "All") == label
            if st.button(
                ("▸ " if is_active else "  ") + label,
                key=f"sig_f_{label}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state["sig_filter"] = label
                st.rerun()
    active_filter = st.session_state.get("sig_filter", "All")

    # Secondary row — watchlist-only toggle, sector multiselect, persist button
    sc1, sc2, sc3 = st.columns([1, 2, 1])
    with sc1:
        watchlist_only = st.toggle(
            "Watchlist only",
            value=st.session_state.get("sig_watchlist_only", False),
            key="sig_watchlist_only",
            help="Show only signals for tickers I have active positions in.",
        )
    with sc2:
        # Build the sector multiselect dynamically from observed signals
        all_sectors = sorted({s.sector for s in signals if s.sector})
        sector_filter = st.multiselect(
            "Sectors",
            options=all_sectors,
            default=[],
            key="sig_sectors",
            label_visibility="collapsed",
            placeholder="Filter by sector(s) — empty = all",
        )
    with sc3:
        if st.button("📥 capture", key="sig_persist", use_container_width=True,
                     help=("Write today's signals into signal_log for "
                           "historical analysis. Idempotent.")):
            try:
                n = persist_signals(db, signals)
                st.toast(f"Captured {n} signals into signal_log", icon="✓")
            except Exception as exc:
                st.error(f"Capture failed: {exc}")

    visible = _apply_filter(signals, active_filter)
    if watchlist_only:
        try:
            positions = db.get_positions(active_only=True)
            held = set(str(t).upper() for t in positions["ticker"].dropna().tolist()) \
                   if positions is not None and not positions.empty else set()
        except Exception:
            held = set()
        visible = [s for s in visible if s.ticker.upper() in held]
    if sector_filter:
        visible = [s for s in visible if s.sector in sector_filter]
    if not visible:
        render_html(
            st,
            f'<div class="volscope-empty-state" style="margin-top:18px;">'
            f'<div class="volscope-empty-headline">No signals fire today.</div>'
            f'<div class="volscope-empty-body">'
            f'The universe is in equilibrium — no ticker breached the '
            f'mean-reversion thresholds. Re-scan after the next scrape.'
            f'</div></div>',
        )
        return

    # ── Two-column body ─────────────────────────────────────────────
    long_signals = [s for s in visible if s.direction == "LONG_VOL"]
    short_signals = [s for s in visible if s.direction == "SHORT_VOL"]

    if active_filter in ("All", "Long Vol", "Earnings-Filtered"):
        if long_signals:
            _render_section_header(
                "💎 LONG VOL · BUY PREMIUM",
                COLORS["accent"],
                f"{len(long_signals)} candidates · IV cheap vs realised + own history",
            )
            for s in long_signals:
                _render_signal_card(s, db=db)

    if active_filter in ("All", "Short Vol", "Earnings-Filtered"):
        if short_signals:
            _render_section_header(
                "🔥 SHORT VOL · SELL PREMIUM",
                COLORS["warn"],
                f"{len(short_signals)} candidates · IV rich + no earnings window",
            )
            for s in short_signals:
                _render_signal_card(s, db=db)

    # ── Stats footer ────────────────────────────────────────────────
    _render_stats_footer(stats, len(signals))


# ── Filter ───────────────────────────────────────────────────────────

def _apply_filter(signals: list[Signal], mode: str) -> list[Signal]:
    if mode == "Long Vol":
        return [s for s in signals if s.direction == "LONG_VOL"]
    if mode == "Short Vol":
        return [s for s in signals
                if s.direction == "SHORT_VOL" and not s.earnings_warning]
    if mode == "Earnings-Filtered":
        return [s for s in signals if s.earnings_warning]
    return signals


# ── Sections ─────────────────────────────────────────────────────────

def _render_section_header(label: str, color: str, sub: str) -> None:
    render_html(
        st,
        f'<div style="display:flex;align-items:baseline;gap:14px;'
        f'border-bottom:1px solid {COLORS["border"]};padding-bottom:6px;'
        f'margin:18px 0 8px 0;font-family:DM Sans,sans-serif;">'
        f'<span style="font-size:14px;font-weight:700;letter-spacing:1.4px;'
        f'color:{color};">{escape(label)}</span>'
        f'<span style="font-size:10px;color:{COLORS["muted"]};">'
        f'{escape(sub)}</span></div>',
    )


# ── Signal card ──────────────────────────────────────────────────────

def _render_signal_card(s: Signal, db=None) -> None:
    is_long = s.direction == "LONG_VOL"
    base_color = COLORS["accent"] if is_long else COLORS["warn"]
    icon = "💎" if is_long else "🔥"
    conf_color = seq_color(min(s.confidence, 100), 0, 100)

    # ── Inline sparkline: last 30d IV-30d trajectory ────────────────
    spark_html = ""
    if db is not None:
        try:
            hist = db.get_ticker_history(s.ticker)
            if hist is not None and not hist.empty and "iv_30d" in hist.columns:
                ivs = hist["iv_30d"].dropna().tail(30).tolist()
                if len(ivs) >= 2:
                    spark_html = sparkline_svg(ivs, width=80, height=18,
                                                color=base_color)
        except Exception:
            pass

    # ── Historical backtest edge for this signal type ───────────────
    edge_html = ""
    if db is not None and not s.earnings_warning:
        try:
            bt = backtest_signal(db, s.ticker, s.signal_type, s.strategy,
                                  max_events=12)
            if bt.n_events > 0:
                edge_color = (
                    COLORS["accent"] if bt.hit_rate >= 0.6 and bt.mean_pl_pct > 0
                    else COLORS["amber"] if bt.hit_rate >= 0.45
                    else COLORS["warn"]
                )
                edge_html = (
                    f'<div style="font-size:10px;color:{edge_color};'
                    f'background:{edge_color}1a;border-left:2px solid {edge_color};'
                    f'padding:5px 9px;margin-top:6px;border-radius:3px;'
                    f'font-family:JetBrains Mono,monospace;">'
                    f'{escape(bt_edge_string(bt))}'
                    f'</div>'
                )
        except Exception:
            pass

    # Earnings warning state
    er_pill = ""
    card_opacity = "1.0"
    if s.earnings_warning:
        er_pill = (
            f'<span style="color:{COLORS["amber"]};background:{COLORS["amber"]}1a;'
            f'border:1px solid {COLORS["amber"]}55;padding:2px 8px;border-radius:4px;'
            f'font-size:10px;font-weight:700;letter-spacing:0.5px;'
            f'margin-left:8px;">'
            f'⚠ ER in {s.days_to_earnings}d · BLOCKED</span>'
        )
        card_opacity = "0.55"

    sector_pill = (
        f'<span style="color:{COLORS["label"]};font-size:9px;letter-spacing:1.2px;'
        f'text-transform:uppercase;margin-left:8px;font-family:DM Sans,sans-serif;">'
        f'{escape(s.sector)}</span>'
        if s.sector else ""
    )

    # Strategy parameter detail (text under the strategy label)
    strat_detail = _format_strategy_detail(s)

    card_html = f'''
<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};
            border-left:3px solid {base_color};border-radius:6px;
            padding:12px 16px;margin-bottom:8px;
            font-family:JetBrains Mono,monospace;opacity:{card_opacity};">
  <div style="display:flex;align-items:center;justify-content:space-between;
              gap:14px;flex-wrap:wrap;margin-bottom:6px;">
    <div style="display:flex;align-items:baseline;gap:8px;">
      <span style="font-size:14px;">{icon}</span>
      <span style="font-size:14px;font-weight:700;color:{COLORS["text"]};">
        {escape(s.ticker)}
      </span>
      {spark_html}
      {sector_pill}
      {er_pill}
    </div>
    <div style="text-align:right;">
      <div style="font-size:9px;letter-spacing:1.2px;color:{COLORS["label"]};
                   text-transform:uppercase;">confidence</div>
      <div style="font-size:18px;font-weight:700;color:{conf_color};
                   line-height:1;">{s.confidence:.0f}</div>
    </div>
  </div>
  <div style="font-size:9px;letter-spacing:1.4px;color:{base_color};
              text-transform:uppercase;font-weight:600;margin-bottom:4px;">
    {escape(s.signal_type)}
  </div>
  <div style="font-size:11px;color:{COLORS["muted"]};margin-bottom:8px;
              line-height:1.5;">{escape(s.reason)}</div>
  <div style="background:{COLORS["bg"]};border-left:2px solid {base_color};
              padding:8px 12px;border-radius:4px;margin-top:6px;">
    <div style="font-size:9px;letter-spacing:1.2px;color:{COLORS["label"]};
                 text-transform:uppercase;font-weight:600;">
      → recommended structure
    </div>
    <div style="font-size:12px;color:{COLORS["text"]};font-weight:700;
                 margin-top:2px;">{escape(s.strategy)}</div>
    <div style="font-size:10px;color:{COLORS["muted"]};margin-top:4px;
                 line-height:1.6;">{strat_detail}</div>
    {edge_html}
  </div>
</div>'''
    render_html(st, card_html)

    # CTA button — only when not earnings-blocked
    if not s.earnings_warning:
        if st.button(
            f"▶ Open in Options Lab · {s.ticker}",
            key=f"sig_open_{s.ticker}_{s.signal_type}",
            type="primary",
            help=(f"Pre-fills Options Lab with {s.strategy} for {s.ticker}; "
                  f"P&L diagram + Greeks + scenario matrix render on switch."),
        ):
            _prefill_lab(s)


def _format_strategy_detail(s: Signal) -> str:
    """Build a one-line parameter summary for the strategy block."""
    p = s.params or {}
    if s.direction == "SHORT_VOL":
        sc = p.get("short_call")
        sp = p.get("short_put")
        cr = p.get("estimated_credit")
        ml = p.get("max_loss")
        pop = p.get("pop")
        dte = p.get("dte")
        if sc and sp and cr is not None:
            return (
                f"strikes ${sp:.0f}P / ${sc:.0f}C · {dte} DTE · "
                f"credit ~${cr:.2f} · max loss ${ml:.2f} · POP {pop}%"
            )
        if sp and cr is not None:
            return (
                f"short put ${sp:.0f} / long ${p.get('long_put', '?'):.0f} · "
                f"{dte} DTE · credit ~${cr:.2f} · POP {pop}%"
            )
    # Long-vol: pick the primary suggestion
    if s.direction == "LONG_VOL":
        a = p.get("strategy_a") or {}
        if a:
            return f"{a.get('name', 'Long Call')} · strike ${a.get('strike', '?'):.0f}"
    return ""


# ── Options Lab prefill ──────────────────────────────────────────────

# Map signal-engine strategy labels to TEMPLATES keys used by Options Lab
_STRATEGY_TO_TEMPLATE = {
    "Long Call (LEAPS)":  "Long Call",
    "Bull Call Spread":   "Bull Call Spread",
    "Long Call":          "Long Call",
    "Iron Condor":        "Short Iron Condor",
    # Bugfix 2026-05-14: previously routed to "Bear Put Spread" which is a
    # DEBIT (long-vol) structure — semantically wrong for a SHORT_VOL signal.
    # The new "Short Put Spread" template is a credit (short-vol) structure.
    "Short Put Spread":   "Short Put Spread",
}


def _prefill_lab(s: Signal) -> None:
    """Write session-state keys consumed by Options Lab + navigate."""
    template_key = _STRATEGY_TO_TEMPLATE.get(s.strategy, "Long Call")
    st.session_state["ol_ticker"] = s.ticker
    st.session_state["selected_ticker"] = s.ticker
    st.session_state["ol_template"] = template_key

    # Pick a strike + DTE override from params when single-leg
    p = s.params or {}
    if s.direction == "LONG_VOL":
        a = p.get("strategy_a") or {}
        if a.get("strike"):
            st.session_state["ol_override_strike"] = float(a["strike"])
        if a.get("dte"):
            st.session_state["ol_dte"] = int(a["dte"])
    elif s.direction == "SHORT_VOL" and template_key == "Short Iron Condor":
        # IC is multi-leg — Options Lab materialiser builds its own strikes
        # from spot + IV. We still hand it the DTE.
        if p.get("dte"):
            st.session_state["ol_dte"] = int(p["dte"])

    st.session_state["active_page"] = "Options Lab"
    st.toast(f"Prefilled Options Lab for {s.ticker} · {template_key}", icon="⚡")
    st.rerun()


# ── Stats footer ─────────────────────────────────────────────────────

def _render_stats_footer(stats: dict, n_universe: int) -> None:
    render_html(
        st,
        f'<div class="volscope-section-rule" style="margin-top:24px;">'
        f'<span class="volscope-section-rule-label">STATISTICS</span>'
        f'<span class="volscope-section-rule-sub">'
        f'{n_universe} tickers scanned · {stats["n_long"]} long-vol · '
        f'{stats["n_short"]} short-vol · {stats["n_filtered_er"]} '
        f'filtered by earnings</span></div>',
    )
    render_html(
        st,
        f'<div style="font-family:JetBrains Mono,monospace;font-size:10px;'
        f'color:{COLORS["muted"]};line-height:1.7;">'
        f'avg Long-Vol confidence  '
        f'<strong style="color:{COLORS["text"]};">{stats["avg_long_conf"]:.0f}</strong>'
        f' · avg Short-Vol confidence  '
        f'<strong style="color:{COLORS["text"]};">{stats["avg_short_conf"]:.0f}</strong>'
        f'<br>academic basis: 65 % of US tickers mean-revert (MDPI 2024); '
        f'85 % of time IV ≥ realised vol (Bali 2008); 16-Δ IC managed @50 % '
        f'→ 78-83 % win rate'
        f'</div>',
    )
