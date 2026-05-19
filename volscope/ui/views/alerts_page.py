"""
Alerts page — universe-wide live scanner.

Reads ``scan_alerts(db)`` (analytics layer), renders a filterable
chronological feed with category chips, ticker quick-jump, and a tiny
"how this was computed" footer per alert.
"""
from __future__ import annotations

from html import escape

import streamlit as st

from volscope.analytics.alerts_scanner import (
    ANOMALY,
    CATEGORY_COLORS,
    CATEGORY_LABELS,
    EARNINGS,
    FLOW,
    REGIME,
    Alert,
    count_by_category,
    scan_alerts,
)
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS


_CATEGORIES_IN_ORDER = (ANOMALY, FLOW, REGIME, EARNINGS)


def _render_filter_strip(st, counts: dict[str, int], total: int) -> str:
    """Render the [All N] [Anomaly N] [Flow N] … selector strip.

    Click-state lives in ``st.session_state['alerts_filter']``.
    """
    if "alerts_filter" not in st.session_state:
        st.session_state["alerts_filter"] = "all"

    active = st.session_state["alerts_filter"]

    # Use Streamlit native buttons so click handling works. CSS in
    # theme.py already gives them the compact TWS-style look.
    cols = st.columns(5)
    labels = [
        ("all",   f"ALL · {total}"),
        (ANOMALY, f"ANOMALY · {counts.get(ANOMALY, 0)}"),
        (FLOW,    f"FLOW · {counts.get(FLOW, 0)}"),
        (REGIME,  f"REGIME · {counts.get(REGIME, 0)}"),
        (EARNINGS,f"EARNINGS · {counts.get(EARNINGS, 0)}"),
    ]
    for col, (key, label) in zip(cols, labels):
        with col:
            is_on = (key == active)
            if st.button(
                ("▸ " if is_on else "  ") + label,
                key=f"alerts_filter_{key}",
                width='stretch',
                type="primary" if is_on else "secondary",
            ):
                st.session_state["alerts_filter"] = key
                st.rerun()
    return st.session_state["alerts_filter"]


def _alert_row_html(alert: Alert) -> str:
    """Render one alert as a dense, clickable row."""
    color = CATEGORY_COLORS.get(alert.type, COLORS["muted"])
    cat_label = CATEGORY_LABELS.get(alert.type, alert.type.upper())
    ts = alert.timestamp.isoformat() if alert.timestamp else ""
    return f"""
<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;
            background:rgba(255,255,255,0.012);
            border:1px solid rgba(255,255,255,0.04);
            border-left:3px solid {color};border-radius:6px;
            margin-bottom:4px;
            font-family:JetBrains Mono,monospace;font-size:11px;
            transition:background 150ms ease,transform 150ms ease;"
     onmouseover="this.style.background='rgba(255,255,255,0.03)';this.style.transform='translateX(2px)';"
     onmouseout="this.style.background='rgba(255,255,255,0.012)';this.style.transform='translateX(0)';">
  <span style="color:{color};font-size:11px;">●</span>
  <span style="color:{color};font-weight:600;font-size:9px;letter-spacing:1.2px;
               text-transform:uppercase;min-width:62px;">{escape(cat_label)}</span>
  <span style="color:{COLORS['text']};font-weight:700;min-width:64px;">
    ◈ {escape(alert.ticker)}
  </span>
  <span style="flex:1;color:{COLORS['muted']};">{escape(alert.message)}</span>
  <span style="color:{COLORS['label']};font-size:10px;">{escape(ts)}</span>
</div>"""


def render_alerts_page(db, settings: dict | None = None) -> None:
    # v0.9.7 — 4-phase orientation strip (master plan §2)
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name='Alerts')
    st.markdown("## ◈ Alerts")

    # v0.9.11 — operator feedback 2026-05-19: "bei alerts sollte
    # alles gelöscht sein und nur das aus einer Watchlist kommen,
    # also nur Watchlist alerts". Default to watchlist-scope so the
    # signal isn't drowned by 200+ universe-wide threshold trips.
    scope = st.radio(
        "Scope",
        ["My watchlists", "Full universe"],
        index=0,
        horizontal=True,
        key="alerts_scope",
        label_visibility="collapsed",
        help=(
            "My watchlists (default): only alerts for tickers in at "
            "least one of your watchlists.  Full universe: every "
            "tracked ticker in the DB."
        ),
    )

    allow_tickers: "set[str] | None" = None
    if scope == "My watchlists":
        try:
            from volscope.persistence.watchlists import list_watchlists
            wls = list_watchlists(db)
            allow_tickers = set()
            for wl in wls:
                for t in wl.tickers:
                    allow_tickers.add(str(t).upper())
        except Exception:
            allow_tickers = set()

    st.caption(
        f"{'Watchlist-scoped' if scope == 'My watchlists' else 'Universe-wide'} "
        f"scanner — anomaly, flow, regime, and earnings "
        f"conditions that just tripped a threshold."
        + (f"  ·  {len(allow_tickers)} watchlist ticker(s) in scope."
            if allow_tickers is not None else "")
    )

    with st.spinner("Scanning..."):
        alerts = scan_alerts(db, allow_tickers=allow_tickers)

    if not alerts:
        empty_body = (
            "None of your watchlist tickers currently hit a threshold. "
            "Switch to <strong>Full universe</strong> above to scan all "
            "tracked tickers, or add tickers via the Watchlist page."
            if scope == "My watchlists"
            else "No ticker in the universe is currently hitting an "
                  "anomaly, flow, regime, or earnings threshold. Run a "
                  "fresh scrape to re-evaluate."
        )
        render_html(
            st,
            f'<div class="volscope-empty-state">'
            f'<div class="volscope-empty-headline">No active alerts.</div>'
            f'<div class="volscope-empty-body">{empty_body}</div></div>',
        )
        if scope != "My watchlists":
            from volscope.ui.components.make_runner import run_make_button
            run_make_button(
                st, target="scrape", label="↻ Run make scrape",
                key="alerts_empty_scrape",
                help_text="Spawns make scrape in the background.",
                use_width_stretch=False,
            )
        return

    counts = count_by_category(alerts)
    total = len(alerts)

    active_filter = _render_filter_strip(st, counts, total)

    # ── Sort selector ──────────────────────────────────────────────
    SORT_OPTIONS = {
        "severity":  "Most important first",
        "newest":    "Newest first",
        "oldest":    "Oldest first",
        "ticker":    "Ticker A → Z",
        "metric":    "Metric value (extreme first)",
    }
    sort_col1, _ = st.columns([2, 5])
    with sort_col1:
        sort_key = st.selectbox(
            "Sort",
            list(SORT_OPTIONS.keys()),
            format_func=lambda k: SORT_OPTIONS[k],
            label_visibility="collapsed",
            key="alerts_sort",
        )

    visible = alerts if active_filter == "all" else [a for a in alerts if a.type == active_filter]

    # ── Apply sort order ───────────────────────────────────────────
    def _sort(items):
        if sort_key == "severity":
            return sorted(items, key=lambda a: (-a.severity, a.ticker))
        if sort_key == "newest":
            return sorted(items, key=lambda a: (a.timestamp, -a.severity), reverse=True)
        if sort_key == "oldest":
            return sorted(items, key=lambda a: (a.timestamp, -a.severity))
        if sort_key == "ticker":
            return sorted(items, key=lambda a: (a.ticker, -a.severity))
        if sort_key == "metric":
            # Extremity = absolute distance from "neutral" 50, with NaN sinking last.
            def _extremity(a):
                v = a.metric_value
                if v is None:
                    return -1.0
                return abs(float(v))
            return sorted(items, key=_extremity, reverse=True)
        return items

    visible = _sort(visible)
    if not visible:
        render_html(
            st,
            f'<div style="color:{COLORS["muted"]};font-family:JetBrains Mono,monospace;'
            f'font-size:11px;padding:14px 0;">No alerts in the selected category.</div>',
        )
        return

    # ── Quick-jump from any alert into Scope/Dossier ────────────────
    # We render the HTML feed first (read-only), then expose a single
    # selectbox + button for navigating, so the visual list stays tight.
    rows = "".join(_alert_row_html(a) for a in visible)
    render_html(st, f'<div style="margin-top:8px;">{rows}</div>')

    # v0.9.8 Phase C — clickable ticker jump from the visible feed.
    # Picks the alert at the top and offers a button; uses NavIntent
    # for SSOT history + toast feedback.
    if visible:
        unique_tickers = []
        seen = set()
        for a in visible[:20]:
            if a.ticker and a.ticker not in seen:
                unique_tickers.append(a.ticker)
                seen.add(a.ticker)
        if unique_tickers:
            c1, c2 = st.columns([3, 1])
            with c1:
                jump_t = st.selectbox(
                    "Open ticker in Scope",
                    unique_tickers,
                    key="alerts_quickjump_select",
                )
            with c2:
                if st.button(
                    "→ Scope",
                    key="alerts_quickjump_btn",
                    width='stretch',
                    help="Deep-dive the selected ticker on Scope",
                ):
                    try:
                        from volscope.ui.components.navigation import (
                            NavIntent, nav_to,
                        )
                        nav_to(NavIntent(
                            page="Scope", ticker=jump_t, source="Alerts",
                        ))
                        st.rerun()
                    except Exception as exc:                       # noqa: BLE001
                        st.error(f"Nav failed: {exc}")

    # Footer: rule glossary so the user can audit what fired.
    with st.expander("Rule thresholds (audit)", expanded=False):
        st.markdown(
            """
| Category | Rule | Fires when |
|---|---|---|
| ANOMALY | IV Perc low | `iv_percentile` < 5 |
| ANOMALY | IV Perc high | `iv_percentile` > 95 |
| ANOMALY | IV/HV cheap | `iv_30d / hv_20d` < 0.65 |
| ANOMALY | IV/HV rich | `iv_30d / hv_20d` > 1.50 |
| ANOMALY | Convergence | `convergence_score` > 80 |
| FLOW    | PCR put-heavy | `put_call_ratio` > 2.0 |
| FLOW    | PCR call-heavy | `put_call_ratio` < 0.3 |
| FLOW    | Volume spike | today total options vol > 3× 20d-avg |
| REGIME  | IV expansion | `iv_rank` crossed from < 20 to > 50 within 5d |
| REGIME  | IV crush | `iv_rank` crossed from > 80 to < 50 within 5d |
| REGIME  | Spread sign-flip | `iv_30d − hv_20d` flipped sign vs yesterday |
| EARNINGS | Imminent | Next earnings in 0–7 days |
| EARNINGS | Just passed | Earnings yesterday or today |

All thresholds live in `volscope/analytics/alerts_scanner.py` — tune them
without touching the UI. Rules are pure functions: `rule_xxx(row, …) → Alert | None`.
"""
        )

    # v0.9.7 — cross-page weave footer (master plan §4)
    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(st, page='Alerts')
