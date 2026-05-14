"""
Portfolio page — replicate your real Optionsscheine portfolio in VolScope.

The page lets the trader log a warrant by its **economic characteristics**
(underlying, strike, expiry, type) — no WKN/ISIN required, since warrants
on the same parameters from different issuers behave nearly identically.

For each logged position the assistant shows:
  - Retrospective entry quality (was the IV cheap when you bought?)
  - Forward Greek trajectory (what happens to delta if spot moves ±5/10%?)
  - Knockout distance + barrier alerts
  - Earnings + theta-decay warnings
  - Suggested actions (roll, close, take profits)

Aggregates across all positions: portfolio Greeks, concentration, alerts.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import streamlit as st

log = logging.getLogger(__name__)

from volscope.analytics.data_quality import composite_quality, quality_badge_html
from volscope.analytics.earnings_watch import alert_card_html, scan_portfolio_earnings
from volscope.ui.components.navigation import consume_prefill, render_breadcrumb
from volscope.analytics.optionsschein_lookup import (
    INSTRUMENT_TYPES,
    OptionsscheinSpec,
    bsm_iv_proxy_from_history,
    compute_entry_iv_percentile,
    historical_iv_at,
)
from volscope.analytics.portfolio_assistant import (
    aggregate_portfolio,
    build_position_insight,
)
from volscope.analytics.portfolio_risk import (
    PortfolioLeg,
    concentration_by_ticker,
    monte_carlo_var,
    portfolio_greeks,
)
from volscope.analytics.scenario_analyzer import (
    PREBAKED_SCENARIOS,
    build_custom_scenario,
    run_all_prebaked,
    run_scenario,
)
from volscope.data.database import VolScopeDB
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"

_SEVERITY_COLOR = {
    "alert": COLORS["warn"],
    "warn":  COLORS["amber"],
    "watch": COLORS["accent2"],
    "info":  COLORS["muted"],
}


def render_portfolio_page(db: VolScopeDB, settings: dict) -> None:
    """Render the Portfolio assistant view."""
    render_html(
        st,
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid {COLORS["border"]};">'
        f'<div style="font-family:{_MONO};font-size:20px;font-weight:700;color:{COLORS["text"]};">'
        f'<span style="color:{COLORS["accent"]};">◇</span> PORTFOLIO ASSISTANT'
        f'</div>'
        f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};">'
        f'Optionsscheine modelled by characteristics · Greeks · risk commentary'
        f'</div>'
        f'</div>',
    )

    # Breadcrumb (only renders source when nav_to set one)
    render_breadcrumb(st, "Portfolio")

    # v3 (2026-05-13): data-freshness so MTM numbers are explicitly dated
    from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
    render_data_freshness_bar(db, compact=True)

    # Consume any prefill from another page (e.g. Pre-Trade → Save here).
    # The presence of a payload toggles the add form open and pre-fills.
    prefill = consume_prefill("Portfolio") or {}

    # Pull active positions
    df_positions = db.get_positions(active_only=True)

    # ── Add-position form (auto-open if there's a prefill or DB empty) ────
    with st.expander(
        "➕ Log new Optionsschein",
        expanded=bool(prefill) or df_positions.empty,
    ):
        _render_add_form(db, prefill=prefill)

    if df_positions.empty:
        st.info(
            "No active positions yet. Use the form above to log your first "
            "Optionsschein. WKN is optional — VolScope identifies warrants "
            "by underlying/strike/expiry, not issuer code."
        )
        return

    # ── Build PositionInsight for each position ──────────────────────
    insights = []
    insight_ids: list[int] = []   # parallel list of DB row ids for delete/close
    legs_for_var = []
    for _, row in df_positions.iterrows():
        spec, current_spot, current_iv, iv_pct_now, entry_iv_pctl = _materialise_position(
            db, row,
        )
        if spec is None:
            continue
        insight = build_position_insight(
            spec=spec,
            current_spot=current_spot,
            current_iv=current_iv,
            iv_pct_now=iv_pct_now,
            entry_iv_pctl=entry_iv_pctl,
            spot_at_entry=row.get("spot_at_entry") or None,
        )
        insights.append(insight)
        insight_ids.append(int(row.get("id")) if row.get("id") is not None else -1)
        # Map to PortfolioLeg for VaR (only when IV/spot known)
        if current_iv is not None and current_spot > 0 and spec.contracts:
            legs_for_var.append(PortfolioLeg(
                ticker=spec.underlying,
                spot=current_spot,
                strike=spec.strike,
                days_to_expiry=insight.days_to_expiry,
                iv=current_iv,
                option_type=spec.option_type,
                quantity=int(spec.contracts),
            ))

    # ── Cash & buying-power strip (broker-style) ────────────────────
    _render_cash_strip(st, db)

    # ── Strategy groups: multi-leg trades rendered as one row ───────
    _render_strategy_groups(st, db, df_positions)

    # ── Portfolio-level summary ──────────────────────────────────────
    agg = aggregate_portfolio(insights)
    _render_portfolio_strip(st, agg)

    # ── Performance — equity curve, P&L chart, contributions ────────
    _render_performance_section(st, db, df_positions)

    # ── Trade journal (audit log) ───────────────────────────────────
    _render_trade_journal(st, db)

    # ── Earnings Watch — proactive event alerts on tracked positions ──
    portfolio_tickers = sorted({ins.spec.underlying for ins in insights})
    if portfolio_tickers:
        try:
            er_alerts = scan_portfolio_earnings(db, portfolio_tickers)
            if er_alerts:
                st.markdown("### 📅 Earnings watch")
                st.caption(
                    "Forward-looking alerts for tracked positions. Severity escalates "
                    "as ER approaches; rich IV bumps it further. Expected move = "
                    "consensus of ATM-straddle + 1σ-from-IV when both available."
                )
                for alert in er_alerts:
                    render_html(st, alert_card_html(alert))
        except Exception as exc:
            log.debug("earnings watch failed: %s", exc)

    # ── Aggregated Greeks + VaR ──────────────────────────────────────
    if legs_for_var:
        st.markdown("### Portfolio Greeks + Monte Carlo VaR")
        _render_greeks_var(st, legs_for_var)

    # ── Per-position cards ───────────────────────────────────────────
    st.markdown("### Position commentary")
    # Pre-compute data-quality per ticker so cards can show stale/partial
    # warnings — Tom should never see Greeks based on 30-day-old data
    # without knowing it.
    quality_by_ticker: dict[str, str] = {}
    for insight in insights:
        try:
            tk = insight.spec.underlying
            if tk in quality_by_ticker:
                continue
            hist = db.get_ticker_history(tk)
            if hist is not None and not hist.empty:
                cq = composite_quality(hist.sort_values("date").iloc[-1], history=hist)
                quality_by_ticker[tk] = quality_badge_html(cq) if cq.overall_level != "OK" else ""
        except Exception:
            quality_by_ticker[insight.spec.underlying] = ""

    # Default-collapsed cards — at 10+ positions the page becomes scrollable
    # otherwise. Headline shows ticker · option_type · strike · summary so
    # the user can scan without expanding. Cards with WARN/ALERT severity
    # auto-expand so urgent attention bubbles up.
    for insight, pos_id in zip(insights, insight_ids):
        n_alerts = sum(1 for w in insight.warnings if w.severity == "alert")
        n_warns  = sum(1 for w in insight.warnings if w.severity == "warn")
        # Headline label — kept short so it fits on one line in narrow viewport
        sev_glyph = "⚠" if n_alerts else ("●" if n_warns else "○")
        headline = (
            f"{sev_glyph} {insight.spec.underlying} "
            f"{insight.spec.option_type.upper()} "
            f"K={insight.spec.strike} · "
            f"{insight.days_to_expiry}d to expiry"
        )
        # Cards with ALERT severity (KO breached, ER today, etc) default-open
        with st.expander(headline, expanded=(n_alerts > 0)):
            _render_position_card(
                st, insight,
                quality_html=quality_by_ticker.get(insight.spec.underlying, ""),
            )
            # Inline action row — close (preserves journal history) or delete
            # (removes the row, used when the entry was logged by mistake).
            if pos_id > 0:
                cols = st.columns([1, 1, 1, 5])
                if cols[0].button(
                    "Close",
                    key=f"close_pos_{pos_id}",
                    help="Mark position closed (kept in journal for retrospection).",
                ):
                    db.close_position(pos_id)
                    st.rerun()
                confirm_key = f"confirm_delete_{pos_id}"
                if cols[1].button(
                    "Delete" if not st.session_state.get(confirm_key) else "Confirm?",
                    key=f"delete_pos_{pos_id}",
                    help="Permanently remove this position from the DB.",
                    type="secondary",
                ):
                    if st.session_state.get(confirm_key):
                        db.delete_position(pos_id)
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                    else:
                        st.session_state[confirm_key] = True
                        st.rerun()
                # Pillar 3 deep-links from the position card
                if cols[2].button(
                    "▷ Pre-Trade",
                    key=f"port_pretrade_{pos_id}",
                    help="Open Pre-Trade card for this underlying",
                ):
                    from volscope.ui.components.navigation import NavIntent, nav_to
                    nav_to(NavIntent(
                        page="Pre-Trade",
                        ticker=insight.spec.underlying,
                        source="Portfolio",
                    ))
                    st.rerun()

    # ── Concentration table ──────────────────────────────────────────
    if legs_for_var:
        with st.expander("Concentration by ticker", expanded=False):
            conc = concentration_by_ticker(legs_for_var)
            st.dataframe(conc, use_container_width=True, hide_index=True)

    # ── Scenario Analyzer ────────────────────────────────────────────
    if legs_for_var:
        with st.expander("📊 Scenario Analyzer — what-if stress tests", expanded=True):
            _render_scenario_analyzer(st, legs_for_var)


# ── Add form ─────────────────────────────────────────────────────────────

def _render_add_form(db: VolScopeDB, prefill: Optional[dict] = None) -> None:
    """Streamlit form to log a new Optionsschein.

    ``prefill`` is the payload from another page's ``nav_to(... payload=...)``
    call (e.g. Pre-Trade → Save to Portfolio). When present, fields are
    pre-populated; the user reviews and confirms.
    """
    p = prefill or {}

    def _date_or_default(key, default):
        v = p.get(key)
        if not v:
            return default
        try:
            from datetime import date as _date
            return _date.fromisoformat(str(v)) if isinstance(v, str) else v
        except Exception:
            return default

    with st.form("add_optionsschein_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        underlying = col1.text_input(
            "Underlying ticker",
            value=str(p.get("underlying", "")),
            placeholder="^GDAXI, MSTR, 1810.HK",
            help="Yahoo-style ticker. Must already exist in VolScope DB.",
        )
        _types = list(INSTRUMENT_TYPES)
        _type_idx = _types.index(p.get("instrument_type", "vanilla")) if p.get("instrument_type") in _types else 0
        instrument_type = col2.selectbox(
            "Type", _types, index=_type_idx,
            help="vanilla = plain call/put · knockout = with barrier · "
                 "inline = range certificate · discount = capped certificate",
        )
        _dir_idx = 1 if str(p.get("option_type", "call")).lower() == "put" else 0
        option_type = col3.selectbox("Direction", ["call", "put"], index=_dir_idx)

        col4, col5, col6 = st.columns(3)
        strike = col4.number_input(
            "Strike", min_value=0.0,
            value=float(p.get("strike", 400.0)), step=1.0,
        )
        expiry = col5.date_input(
            "Expiry",
            value=_date_or_default("expiry", date.today() + timedelta(days=180)),
            help="For open-end knockouts, pick a far date (e.g. 2099-12-31).",
        )
        contracts = col6.number_input(
            "Contracts", min_value=1,
            value=int(p.get("contracts", 1)), step=1,
        )

        col7, col8 = st.columns(2)
        barrier = col7.number_input(
            "KO barrier (only for knockouts)",
            min_value=0.0, value=float(p.get("barrier", 0.0)), step=1.0,
            help="Leave 0 for vanilla. Knock-out is breached when spot crosses this.",
        )
        entry_premium = col8.number_input(
            "Entry premium (per warrant)",
            min_value=0.0, value=float(p.get("entry_premium", 0.0)), step=0.01,
            help="Optional — used for P&L mark.",
        )

        col9, col10 = st.columns(2)
        entry_date = col9.date_input(
            "Entry date",
            value=_date_or_default("entry_date", date.today()),
        )
        wkn = col10.text_input(
            "WKN (informational only)",
            value=str(p.get("wkn", "")),
            placeholder="DJ7N5W",
        )

        notes = st.text_area(
            "Notes",
            value=str(p.get("notes", "")),
            placeholder="thesis, hedge purpose, …",
        )

        submitted = st.form_submit_button("Log position", use_container_width=True)
        if not submitted:
            return

        if not underlying.strip():
            st.error("Underlying ticker required.")
            return

        sym = underlying.strip().upper()
        # Pull history to backfill entry IV + percentile
        history = db.get_ticker_history(sym)
        target_dte = max(1, (expiry - entry_date).days)
        entry_iv = historical_iv_at(history, target_dt=entry_date, target_dte=target_dte)
        entry_iv_pctl = (
            compute_entry_iv_percentile(history, entry_iv, entry_date)
            if entry_iv is not None else None
        )

        # Pull current spot for spot_at_entry approximation if entry_date == today
        current_spot = None
        if not history.empty and "spot_price" in history.columns:
            df_at = history.copy()
            df_at["date"] = pd.to_datetime(df_at["date"]).dt.date
            df_at = df_at[df_at["date"] <= entry_date]
            if not df_at.empty:
                current_spot = float(df_at.sort_values("date").iloc[-1].get("spot_price") or 0)

        db.add_position(
            ticker=sym,
            entry_date=entry_date,
            entry_iv_30d=entry_iv,
            entry_iv_percentile=entry_iv_pctl,
            notes=notes,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            instrument_type=instrument_type,
            barrier=(barrier if barrier > 0 else None),
            contracts=int(contracts),
            entry_premium=(entry_premium if entry_premium > 0 else None),
            spot_at_entry=current_spot,
            wkn=wkn,
        )
        if entry_iv is not None:
            st.success(
                f"Logged {sym} {option_type.upper()} K={strike} expiry {expiry} · "
                f"entry IV ≈ {entry_iv:.1f}% (percentile ≈ {entry_iv_pctl:.0f})"
            )
        else:
            st.success(f"Logged {sym} — entry IV unavailable (no history)")
        st.rerun()


# ── Materialise (DB row → spec + current state) ─────────────────────────

def _materialise_position(
    db:   VolScopeDB,
    row:  pd.Series,
):
    """From a DB row, build OptionsscheinSpec + look up current spot/IV.

    Returns a tuple (spec, current_spot, current_iv, iv_pct_now, entry_iv_pctl).
    Returns (None, ...) when ticker has no history.
    """
    ticker = row.get("ticker")
    history = db.get_ticker_history(ticker)
    if history is None or history.empty:
        return None, 0.0, None, None, None

    latest = history.sort_values("date").iloc[-1]
    current_spot = float(latest.get("spot_price") or 0)
    current_iv = (
        float(latest.get("iv_30d"))
        if latest.get("iv_30d") is not None and not pd.isna(latest.get("iv_30d"))
        else None
    )
    iv_pct_now = (
        float(latest.get("iv_percentile"))
        if latest.get("iv_percentile") is not None
        and not pd.isna(latest.get("iv_percentile"))
        else None
    )

    def _coerce_date(v, fallback=None):
        """DuckDB hands back Timestamps; OptionsscheinSpec expects datetime.date.

        Mixing the two crashes downstream (`spec.expiry - date.today()`),
        so normalise at construction time. ``fallback`` is returned when
        the input is missing or unparseable.
        """
        if v is None:
            return fallback
        try:
            if pd.isna(v):
                return fallback
        except (TypeError, ValueError):
            pass
        if isinstance(v, date) and not isinstance(v, pd.Timestamp):
            return v
        try:
            return pd.to_datetime(v).date()
        except Exception:
            return fallback

    expiry = _coerce_date(row.get("expiry"), fallback=date.today() + timedelta(days=60))
    entry_date = _coerce_date(row.get("entry_date"), fallback=None)

    spec = OptionsscheinSpec(
        underlying=ticker,
        option_type=row.get("option_type") or "call",
        strike=float(row.get("strike") or 0.0),
        expiry=expiry,
        instrument_type=row.get("instrument_type") or "vanilla",
        barrier=(float(row["barrier"]) if pd.notna(row.get("barrier")) else None),
        contracts=int(row.get("contracts") or 1),
        entry_date=entry_date,
        entry_premium=(float(row["entry_premium"]) if pd.notna(row.get("entry_premium")) else None),
        entry_iv=(float(row["entry_iv_30d"]) if pd.notna(row.get("entry_iv_30d")) else None),
        wkn=row.get("wkn") or "",
        issuer=row.get("issuer") or "",
    )

    entry_iv_pctl = (
        float(row["entry_iv_percentile"])
        if pd.notna(row.get("entry_iv_percentile"))
        else None
    )

    return spec, current_spot, current_iv, iv_pct_now, entry_iv_pctl


# ── Renderers ────────────────────────────────────────────────────────────

def _render_cash_strip(st_module, db: VolScopeDB) -> None:
    """Broker-style cash strip — current balance, initial deposit, %.

    A reset control lives in a small popover so an accidental click
    doesn't wipe the journal.
    """
    from volscope.data.paper_trader import (
        DEFAULT_CASH, get_cash_balance, get_cash_initial, reset_cash,
    )
    from volscope.ui.components.metric_components import _ibkr_cell

    cash = get_cash_balance(db)
    initial = get_cash_initial(db)
    delta = cash - initial
    pct = (delta / initial * 100) if initial > 0 else 0.0
    pct_color = "fg-cheap" if delta >= 0 else "fg-rich"

    cells = [
        _ibkr_cell("CASH",        f"${cash:,.0f}"),
        _ibkr_cell("INITIAL",     f"${initial:,.0f}"),
        _ibkr_cell("Δ CASH",      f"${delta:+,.0f}", value_class=pct_color),
        _ibkr_cell("RETURN",      f"{pct:+.1f}%",   value_class=pct_color),
    ]
    render_html(
        st_module,
        '<div class="volscope-ibkr-row" style="margin-top:6px;">'
        + "".join(cells) + "</div>",
    )

    with st_module.expander("Reset paper cash", expanded=False):
        col1, col2 = st_module.columns([1, 1])
        with col1:
            new_initial = st_module.number_input(
                "New initial deposit",
                min_value=100.0, max_value=10_000_000.0,
                value=float(DEFAULT_CASH), step=500.0,
                key="pf_reset_amt",
            )
        with col2:
            if st_module.button("Reset", key="pf_reset_btn", type="primary",
                                use_container_width=True):
                reset_cash(db, initial=float(new_initial))
                st_module.success(f"Cash reset to ${new_initial:,.0f}")
                st_module.rerun()
        render_html(
            st_module,
            f'<div style="font-family:{_MONO};font-size:9px;color:{COLORS["muted"]};'
            f'margin-top:6px;">'
            f'Cash reset only changes the balance — open positions remain. '
            f'Close them first if you want a clean slate.'
            f'</div>',
        )


def _render_strategy_groups(
    st_module, db: VolScopeDB, positions_df: pd.DataFrame,
) -> None:
    """Multi-leg trades rendered as one row per strategy.

    Each group: header (template + ticker + net debit/credit), nested
    leg list, single "close strategy" button that closes every leg
    atomically and journals the realised P&L.
    """
    from volscope.data.paper_trader import (
        list_strategy_groups, paper_close_strategy,
    )
    groups = list_strategy_groups(db)
    # Only render groups with > 1 leg OR explicit strategy_template tag.
    # Pure-legacy 1-leg vanillas continue to render via the existing
    # per-position card path below.
    multi_groups = [g for g in groups if g.n_legs > 1 or g.strategy_template != "Vanilla"]
    if not multi_groups:
        return

    render_html(
        st_module,
        f'<div class="volscope-section-rule" style="margin-top:14px;">'
        f'<span class="volscope-section-rule-label">▣ open strategies</span>'
        f'<span class="volscope-section-rule-sub">'
        f'{len(multi_groups)} group{"s" if len(multi_groups) != 1 else ""}'
        f'</span></div>',
    )

    for g in multi_groups:
        debit_label = "DEBIT" if g.net_entry_debit >= 0 else "CREDIT"
        debit_color = COLORS["warn"] if g.net_entry_debit >= 0 else COLORS["accent"]

        leg_rows = ""
        for leg in g.legs:
            action = str(leg.get("action") or "buy")
            sign = "+" if action == "buy" else "−"
            action_color = COLORS["accent"] if action == "buy" else COLORS["warn"]
            opt = (leg.get("option_type") or "?").upper()
            strike = leg.get("strike") or 0
            ctrs = int(leg.get("contracts") or 1)
            premium = float(leg.get("entry_premium") or 0)
            expiry = leg.get("expiry")
            try:
                exp_str = pd.to_datetime(expiry).date().isoformat() if expiry is not None else "—"
            except Exception:
                exp_str = "—"
            leg_rows += (
                f'<div style="display:flex;justify-content:space-between;'
                f'padding:3px 0;font-size:11px;border-bottom:1px solid {COLORS["border"]};">'
                f'<span style="color:{action_color};font-weight:600;">'
                f'{sign}{ctrs} {opt} {strike:g}</span>'
                f'<span style="color:{COLORS["muted"]};">exp {exp_str}</span>'
                f'<span style="color:{COLORS["text"]};font-weight:600;">${premium:.2f}</span>'
                f'</div>'
            )

        entry_iso = g.entry_date.isoformat() if g.entry_date else "—"
        render_html(
            st_module,
            f'''
<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};
            border-left:3px solid {debit_color};border-radius:8px;
            padding:12px 16px;margin-bottom:8px;font-family:{_MONO};">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              padding-bottom:6px;margin-bottom:6px;border-bottom:1px solid {COLORS["border"]};">
    <div>
      <div style="font-size:9px;letter-spacing:1.2px;color:{COLORS["label"]};
                   text-transform:uppercase;font-weight:600;">
        {g.strategy_template} · {g.ticker}
      </div>
      <div style="font-size:11px;color:{COLORS["muted"]};margin-top:2px;">
        opened {entry_iso} · group {g.strategy_group_id[-8:]}
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:9px;letter-spacing:1.2px;color:{COLORS["label"]};
                   text-transform:uppercase;font-weight:600;">{debit_label}</div>
      <div style="font-size:14px;font-weight:700;color:{debit_color};">
        ${abs(g.net_entry_debit):,.0f}
      </div>
    </div>
  </div>
  <div>{leg_rows}</div>
</div>''',
        )
        c1, c2 = st_module.columns([1, 4])
        with c1:
            if st_module.button(
                f"✕ close strategy",
                key=f"pf_close_{g.strategy_group_id}",
                help="Close all legs at the current BSM mark. Realised P&L credited to cash.",
            ):
                try:
                    pl, cash_after = paper_close_strategy(db, g.strategy_group_id)
                    st_module.success(
                        f"Closed · realised P&L ${pl:+,.0f} · cash ${cash_after:,.0f}"
                    )
                    st_module.rerun()
                except Exception as exc:
                    st_module.error(f"Close failed: {exc}")
        with c2:
            render_html(
                st_module,
                f'<div style="font-family:{_MONO};font-size:9px;color:{COLORS["muted"]};'
                f'padding:8px 4px;">'
                f'closes all {g.n_legs} legs · MTM at BSM mark · journals to trade history'
                f'</div>',
            )


def _render_trade_journal(st_module, db: VolScopeDB) -> None:
    """Trade-history audit log — collapsed by default."""
    from volscope.data.paper_trader import get_trade_journal

    df = get_trade_journal(db, limit=30)
    if df.empty:
        return
    with st_module.expander(f"▣ Trade history · {len(df)} events", expanded=False):
        show = df.copy()
        # Pretty-format for the table
        show["event_ts"] = pd.to_datetime(show["event_ts"]).dt.strftime("%Y-%m-%d %H:%M")
        show["net_cash"] = show["net_cash"].map(lambda v: f"${v:+,.0f}" if pd.notna(v) else "—")
        show["realized_pl"] = show["realized_pl"].map(
            lambda v: f"${v:+,.0f}" if pd.notna(v) else "—"
        )
        show["cash_after"] = show["cash_after"].map(
            lambda v: f"${v:,.0f}" if pd.notna(v) else "—"
        )
        show = show[[
            "event_ts", "event_type", "ticker", "strategy_template",
            "net_cash", "realized_pl", "cash_after",
        ]]
        show.columns = ["When", "Event", "Ticker", "Template", "Cash flow", "P&L", "Cash after"]
        st_module.dataframe(show, use_container_width=True, hide_index=True, height=240)


def _render_performance_section(st_module, db: VolScopeDB, positions_df: pd.DataFrame) -> None:
    """
    Performance — daily MTM equity curve + per-position contribution.

    Reads each position's underlying history once, replays the BSM
    premium for each daily snapshot, and aggregates into a portfolio
    equity curve. Pure-derived: no separate equity-curve table needed.
    """
    from volscope.analytics.portfolio_performance import compute_portfolio_performance
    import plotly.graph_objects as go
    from volscope.ui.styles.theme import rgba

    # Bulk-fetch history per ticker
    tickers = sorted({str(t) for t in positions_df.get("ticker", []) if pd.notna(t)})
    history_by_ticker: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            history_by_ticker[t] = db.get_ticker_history(t)
        except Exception:
            history_by_ticker[t] = pd.DataFrame()

    perf = compute_portfolio_performance(positions_df, history_by_ticker)
    if perf.equity_curve.empty:
        render_html(
            st_module,
            f'<div style="margin-top:14px;padding:12px 16px;background:{COLORS["surface"]};'
            f'border-left:3px solid {COLORS["amber"]};border-radius:6px;'
            f'font-family:{_MONO};font-size:11px;color:{COLORS["text"]};">'
            f'⚠ Performance unavailable — none of the active positions has '
            f'sufficient price history (need entry_date + spot/IV history).'
            f'</div>',
        )
        return

    render_html(
        st_module,
        f'<div class="volscope-section-rule">'
        f'<span class="volscope-section-rule-label">▣ Performance</span>'
        f'<span class="volscope-section-rule-sub">'
        f'mark-to-market via BSM · {perf.n_positions} positions · '
        f'inception {perf.inception.isoformat() if perf.inception else "—"}'
        f'</span></div>',
    )

    # ── Headline KPIs (custom IBKR row, never truncates) ────────────
    from volscope.ui.components.metric_components import _ibkr_cell
    pl_color = "fg-cheap" if perf.total_pl >= 0 else "fg-rich"
    pl_cell  = "is-cheap" if perf.total_pl >= 0 else "is-rich"
    sharpe_str = (
        f"{perf.sharpe_252d:+.2f}" if perf.sharpe_252d is not None else "—"
    )
    sharpe_cls = ""
    if perf.sharpe_252d is not None:
        sharpe_cls = "fg-cheap" if perf.sharpe_252d > 0 else "fg-rich"
    dd_str = (
        f"{perf.max_drawdown_pct:.1f}%" if perf.max_drawdown_pct is not None else "—"
    )
    cells = [
        _ibkr_cell("INVESTED",   f"${perf.total_invested:,.0f}"),
        _ibkr_cell("VALUE",      f"${perf.total_value:,.0f}"),
        _ibkr_cell("P&L $",      f"${perf.total_pl:+,.0f}", value_class=pl_color, cell_class=pl_cell),
        _ibkr_cell("P&L %",      f"{perf.total_pl_pct:+.1f}%", value_class=pl_color),
        _ibkr_cell("SHARPE",     sharpe_str, value_class=sharpe_cls),
        _ibkr_cell("MAX DD",     dd_str, value_class="fg-rich"),
    ]
    render_html(
        st_module,
        '<div class="volscope-ibkr-row">' + "".join(cells) + "</div>",
    )

    # ── Equity curve chart ──────────────────────────────────────────
    eq = perf.equity_curve.copy()
    eq["date"] = pd.to_datetime(eq["date"])
    line_color = COLORS["accent"] if perf.total_pl >= 0 else COLORS["warn"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=eq["date"], y=eq["total_value"],
        mode="lines",
        name="Portfolio value",
        line=dict(color=line_color, width=2.0, shape="spline"),
        fill="tozeroy",
        fillcolor=rgba(line_color, 0.06),
        hovertemplate="$%{y:,.0f}<extra></extra>",
    ))
    fig.add_hline(
        y=perf.total_invested,
        line=dict(color=COLORS["muted"], width=1, dash="dot"),
        annotation_text=f"invested ${perf.total_invested:,.0f}",
        annotation_position="top right",
        annotation_font=dict(family=_MONO, color=COLORS["muted"], size=9),
    )
    fig.update_layout(
        title=dict(
            text="EQUITY CURVE — DAILY MTM",
            font=dict(color=COLORS["label"], size=11, family="DM Sans"),
            x=0.0, xanchor="left", y=0.97,
        ),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        height=240,
        margin=dict(l=12, r=44, t=28, b=28),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(13,14,20,0.95)",
            bordercolor=COLORS["border"],
            font=dict(family=_MONO, size=11, color=COLORS["text"]),
        ),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.03)",
            tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.03)",
            tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
            side="right",
            tickformat="$,.0f",
        ),
        showlegend=False,
    )
    st_module.plotly_chart(fig, use_container_width=True)

    # ── Position contribution waterfall ─────────────────────────────
    if perf.contributions:
        contrib = perf.contributions[:10]  # top 10 by absolute P&L

        cfig = go.Figure()
        cfig.add_trace(go.Bar(
            x=[c.label for c in contrib],
            y=[c.pl_total for c in contrib],
            marker_color=[
                COLORS["accent"] if c.pl_total >= 0 else COLORS["warn"]
                for c in contrib
            ],
            marker_line_width=0,
            text=[f"{c.pl_pct:+.0f}%" for c in contrib],
            textposition="outside",
            textfont=dict(family=_MONO, size=9, color=COLORS["text"]),
            hovertemplate=(
                "%{x}<br>P&L $%{y:+,.0f}<extra></extra>"
            ),
        ))
        cfig.update_layout(
            title=dict(
                text="P&L CONTRIBUTION BY POSITION",
                font=dict(color=COLORS["label"], size=11, family="DM Sans"),
                x=0.0, xanchor="left", y=0.97,
            ),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family=_MONO, color=COLORS["text"], size=10),
            height=260,
            margin=dict(l=12, r=24, t=28, b=80),
            xaxis=dict(
                gridcolor="rgba(255,255,255,0.03)",
                tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
                tickangle=-30,
            ),
            yaxis=dict(
                gridcolor="rgba(255,255,255,0.03)",
                tickfont=dict(family=_MONO, size=9, color=COLORS["label"]),
                side="right",
                tickprefix="$",
            ),
            showlegend=False,
        )
        st_module.plotly_chart(cfig, use_container_width=True)


def _render_portfolio_strip(st_module, agg) -> None:
    """Top-level portfolio summary strip."""
    color = (
        COLORS["warn"]   if agg.n_warnings_alert > 0 else
        COLORS["amber"]  if agg.n_warnings_watch > 0 else
        COLORS["accent"]
    )
    div_html = ""
    if agg.diversification_warnings:
        div_lines = "".join(
            f'<div style="color:{COLORS["amber"]};font-size:11px;">⚠ {w}</div>'
            for w in agg.diversification_warnings
        )
        div_html = f'<div style="margin-top:6px;">{div_lines}</div>'

    render_html(
        st_module,
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-left:4px solid {color};padding:14px 18px;border-radius:8px;'
        f'margin-bottom:16px;font-family:{_MONO};">'
        f'<div style="color:{color};font-weight:700;font-size:13px;">{agg.headline}</div>'
        f'<div style="color:{COLORS["muted"]};font-size:11px;margin-top:4px;">'
        f'{agg.n_positions} active · {agg.n_warnings_alert} alerts · '
        f'{agg.n_warnings_watch} watch · {agg.n_dead} dead'
        f'</div>'
        f'{div_html}'
        f'</div>',
    )


def _render_greeks_var(st_module, legs) -> None:
    """Aggregated Greeks + Monte Carlo VaR."""
    g = portfolio_greeks(legs)
    cols = st_module.columns(5)
    _kpi(cols[0], "Δ Delta",   f"{g.delta:+.0f}",   "Net share-equiv delta")
    _kpi(cols[1], "Γ Gamma",   f"{g.gamma:.4f}")
    _kpi(cols[2], "ν Vega",    f"${g.vega:+.0f}",   "$ P&L per +1% IV")
    _kpi(cols[3], "Θ Theta",   f"${g.theta:+.0f}",  "$ P&L per day")
    _kpi(cols[4], "Notional",  f"${g.notional:,.0f}")

    horizon_days = st_module.slider(
        "VaR horizon (calendar days)",
        min_value=1, max_value=21, value=5, step=1,
        help="Monte Carlo VaR over this look-ahead window.",
    )
    var = monte_carlo_var(legs, horizon_days=horizon_days, n_paths=500, seed=42)
    cols = st_module.columns(4)
    _kpi(cols[0], f"95% VaR ({horizon_days}d)", f"${var.var_95:,.0f}",
         f"Loss not exceeded with 95% prob over {horizon_days}d")
    _kpi(cols[1], "CVaR (95%)", f"${var.cvar_95:,.0f}",
         "Mean loss in worst-5% scenarios")
    _kpi(cols[2], "Expected P&L", f"${var.expected_pnl:+,.0f}")
    _kpi(cols[3], "Worst path", f"${var.worst_loss:,.0f}")


def _render_position_card(st_module, insight, quality_html: str = "") -> None:
    """One position card with full commentary block.

    quality_html: optional inline data-quality badge (rendered below the
    summary) so the trader knows if the Greeks rest on stale data.
    """
    color = (
        COLORS["warn"]   if any(w.severity == "alert" for w in insight.warnings) else
        COLORS["amber"]  if any(w.severity == "warn"  for w in insight.warnings) else
        COLORS["accent2"] if any(w.severity == "watch" for w in insight.warnings) else
        COLORS["accent"]
    )
    spec = insight.spec
    eq = insight.entry_quality
    eq_html = ""
    if eq is not None:
        eq_color = {
            "EXCELLENT": COLORS["accent"],
            "GOOD":      COLORS["accent"],
            "FAIR":      COLORS["muted"],
            "POOR":      COLORS["amber"],
            "BAD":       COLORS["warn"],
        }.get(eq.quality_label, COLORS["muted"])
        ivch = (
            f"Δ IV {eq.iv_change_since_entry_pp:+.1f}pt"
            if eq.iv_change_since_entry_pp is not None else ""
        )
        eq_html = (
            f'<div style="margin-top:6px;font-size:11px;color:{COLORS["muted"]};">'
            f'entry: <span style="color:{eq_color};font-weight:700;">'
            f'{eq.quality_label}</span>'
            f'{f" · pctl {eq.entry_iv_percentile:.0f}" if eq.entry_iv_percentile is not None else ""}'
            f'{f" · {ivch}" if ivch else ""}'
            f'</div>'
        )

    g = insight.greeks
    greeks_html = (
        f'<div style="margin-top:6px;display:grid;grid-template-columns:repeat(4,1fr);'
        f'gap:6px;font-size:11px;font-family:{_MONO};">'
        f'<div><span style="color:{COLORS["label"]};">Δ</span> {g.delta_now:+.3f}</div>'
        f'<div><span style="color:{COLORS["label"]};">Γ</span> {g.gamma_now:.4f}</div>'
        f'<div><span style="color:{COLORS["label"]};">ν</span> {g.vega_now:+.3f}</div>'
        f'<div><span style="color:{COLORS["label"]};">Θ</span> {g.theta_now:+.3f}</div>'
        f'</div>'
        f'<div style="margin-top:4px;font-size:10px;color:{COLORS["muted"]};">'
        f'delta @ ±5%: {g.delta_at_minus_5pct:+.3f} → {g.delta_at_plus_5pct:+.3f} · '
        f'@ ±10%: {g.delta_at_minus_10pct:+.3f} → {g.delta_at_plus_10pct:+.3f}'
        f'</div>'
    )

    warns_html = ""
    if insight.warnings:
        warn_lines = []
        for w in insight.warnings:
            wc = _SEVERITY_COLOR.get(w.severity, COLORS["muted"])
            warn_lines.append(
                f'<div style="color:{wc};font-size:11px;margin-top:3px;">'
                f'<span style="background:{wc}22;padding:1px 5px;border-radius:3px;'
                f'font-size:9px;font-weight:700;">{w.severity.upper()}</span> '
                f'{w.message}</div>'
            )
        warns_html = (
            '<div style="margin-top:8px;border-top:1px solid '
            + COLORS['border'] + ';padding-top:6px;">'
            + "".join(warn_lines) + "</div>"
        )

    actions_html = ""
    if insight.suggested_actions:
        action_lines = "".join(
            f'<div style="color:{COLORS["text"]};font-size:11px;margin-top:3px;">→ {a}</div>'
            for a in insight.suggested_actions
        )
        actions_html = (
            f'<div style="margin-top:6px;border-top:1px dashed {COLORS["border"]};'
            f'padding-top:6px;">'
            f'<div style="color:{COLORS["accent"]};font-size:10px;font-weight:700;'
            f'letter-spacing:1px;text-transform:uppercase;">suggested</div>'
            f'{action_lines}</div>'
        )

    render_html(
        st_module,
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-left:4px solid {color};padding:14px 18px;border-radius:8px;'
        f'margin-bottom:12px;font-family:{_MONO};">'
        f'<div style="color:{COLORS["text"]};font-weight:700;font-size:12px;">'
        f'{insight.summary}'
        f'</div>'
        f'{("<div style=\"margin-top:4px;\">" + quality_html + "</div>") if quality_html else ""}'
        f'{eq_html}'
        f'{greeks_html}'
        f'{warns_html}'
        f'{actions_html}'
        f'</div>',
    )


def _render_scenario_analyzer(st_module, legs) -> None:
    """Pre-baked + custom what-if stress tests on the portfolio."""
    st_module.markdown(
        "**Pre-baked scenarios** — full-portfolio P&L under canonical stress tests. "
        "Each row repricing every leg via BSM under the spot+IV shock pair."
    )

    results = run_all_prebaked(legs)
    rows = []
    for r in results:
        scen = next(s for s in PREBAKED_SCENARIOS if s.name == r.scenario_name)
        # Pull representative wildcard shock (or "QQQ" if none)
        shock = scen.shocks.get("*") or list(scen.shocks.values())[0]
        rows.append({
            "scenario":      r.scenario_name,
            "spot_shock_%":  shock.spot_shock_pct * 100,
            "iv_shock_pp":   shock.iv_shock_pp,
            "P&L_usd":       r.total_pnl,
            "pre_value":     r.total_pre_value,
            "post_value":    r.total_post_value,
            "pnl_pct":       (r.total_pnl / r.total_pre_value * 100)
                              if r.total_pre_value > 0 else 0.0,
        })

    df_scen = pd.DataFrame(rows)

    st_module.dataframe(
        df_scen,
        use_container_width=True,
        hide_index=True,
        column_config={
            "scenario":     st_module.column_config.TextColumn("Scenario", width="medium"),
            "spot_shock_%": st_module.column_config.NumberColumn("Spot Δ%", format="%+.1f%%"),
            "iv_shock_pp":  st_module.column_config.NumberColumn("IV Δpp",  format="%+.1f"),
            "P&L_usd":      st_module.column_config.NumberColumn("P&L $", format="$%+,.0f"),
            "pre_value":    st_module.column_config.NumberColumn("Pre $",  format="$%,.0f"),
            "post_value":   st_module.column_config.NumberColumn("Post $", format="$%,.0f"),
            "pnl_pct":      st_module.column_config.NumberColumn("P&L %",  format="%+.1f%%"),
        },
    )

    st_module.markdown("---")
    st_module.markdown("**Custom scenario** — pick your own combined shock.")
    cols = st_module.columns(2)
    spot_shock = cols[0].slider(
        "Spot shock %", min_value=-50, max_value=50, value=-10, step=1,
        help="Percentage change in spot, applied to every ticker.",
    )
    iv_shock = cols[1].slider(
        "IV shock (pp)", min_value=-30, max_value=50, value=+10, step=1,
        help="Absolute change in IV in percentage-points.",
    )
    custom = build_custom_scenario(
        name=f"Custom ({spot_shock:+}% / {iv_shock:+}pp)",
        spot_shock_pct={"*": spot_shock / 100.0},
        iv_shock_pp={"*": float(iv_shock)},
        description="User-defined combined shock.",
    )
    cust_result = run_scenario(legs, custom)

    cols = st_module.columns(3)
    pnl_color = (
        COLORS["accent"] if cust_result.total_pnl >= 0 else COLORS["warn"]
    )
    _kpi(cols[0], "Custom P&L",
         f"${cust_result.total_pnl:+,.0f}",
         f"({cust_result.total_pnl / cust_result.total_pre_value * 100:+.1f}%)"
         if cust_result.total_pre_value > 0 else "")
    _kpi(cols[1], "Worst leg",
         f"{cust_result.worst_leg.ticker} ${cust_result.worst_leg.pnl_dollar:+,.0f}"
         if cust_result.worst_leg else "—")
    _kpi(cols[2], "Best leg",
         f"{cust_result.best_leg.ticker} ${cust_result.best_leg.pnl_dollar:+,.0f}"
         if cust_result.best_leg else "—")


def _kpi(col, label: str, value: str, help_text: str = "") -> None:
    """Render one KPI tile."""
    render_html(
        col,
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:6px;padding:10px 12px;height:100%;">'
        f'<div style="color:{COLORS["label"]};font-size:9px;text-transform:uppercase;'
        f'letter-spacing:1px;font-family:{_MONO};">{label}</div>'
        f'<div style="font-family:{_MONO};font-size:16px;font-weight:700;'
        f'color:{COLORS["text"]};margin-top:2px;">{value}</div>'
        f'{f"<div style=\"color:{COLORS["muted"]};font-size:9px;margin-top:2px;\">{help_text}</div>" if help_text else ""}'
        f'</div>',
    )
