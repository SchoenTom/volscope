"""
Sidebar — brand, ticker picker, nav, page-aware context, live screener, data status.

Design principles:
  - No unicode gear emoji in widget labels (some fonts render it as '⚙' which
    can get garbled next to Streamlit's native expander chevron).
  - Vertical radio nav — horizontal in a narrow sidebar wraps and overlaps.
  - Page-aware context block: different quick stats for Discover / Scope / Scanner.
  - Live screener: "Load universe" button bulk-adds every ticker from
    `TICKER_UNIVERSE` in one batch — the user gets 280+ tickers in one click.
"""
from __future__ import annotations

import pandas as pd

from volscope.data.ticker_resolver import resolve_and_ingest
from volscope.data.ticker_universe import TICKER_UNIVERSE, all_tickers
from volscope.ui.components.html_utils import render_html
from volscope.ui.components.metric_components import freshness_badge


def _render_user_watchlists(st, db) -> None:
    """Sidebar widget: list/create/manage TradingView-style watchlists.

    Compact UI:
      - One expander per watchlist (collapsed by default)
      - Click ticker → set selected_ticker + nav to Scope
      - Delete-button per ticker (single-click; no confirm because
        the persistence layer can recreate from the add-form)
      - Bottom: "New watchlist" inline form + add-ticker form
      - Regime-alarm toggle stored per watchlist
    """
    from volscope.persistence.watchlists import (
        add_ticker_to_watchlist,
        create_watchlist,
        ensure_watchlist_tables,
        list_watchlists,
        remove_ticker_from_watchlist,
    )

    # Best-effort: ensure tables exist. DB is read_only in UI context,
    # so first-time creation can fail. We catch and fall back to "no
    # watchlists yet" rendering.
    try:
        ensure_watchlist_tables(db)
    except Exception:
        # Read-only DB: writing here is forbidden. The bot/scrape
        # process creates the tables on next write-open; until then
        # we just render an info card.
        render_html(
            st,
            f'<div style="margin-top:8px;color:#8a8f9e;font-family:DM Sans,sans-serif;'
            f'font-size:11px;padding:8px 10px;background:#1a1d2e;border-radius:4px;">'
            f'⚑ Watchlists initialise on first scrape — run <code>make scrape</code> '
            f'or wait for the next cron job to enable this widget.</div>',
        )
        return

    lists = list_watchlists(db)

    render_html(
        st,
        f'<div style="margin-top:14px;margin-bottom:4px;'
        f'font-family:DM Sans,sans-serif;font-size:11px;'
        f'color:#5b8cff;letter-spacing:0.04em;font-weight:600;'
        f'text-transform:uppercase;">⚑ My watchlists</div>',
    )

    if not lists:
        st.caption("No watchlists yet. Create one below ↓")
    else:
        for wl in lists:
            label = f"{wl.name} · {len(wl.tickers)}"
            if wl.regime_alarms_enabled:
                label += " 🔔"
            with st.expander(label, expanded=False):
                if not wl.tickers:
                    st.caption("(empty — add tickers below)")
                else:
                    for t in wl.tickers:
                        c1, c2 = st.columns([5, 1])
                        with c1:
                            if st.button(
                                t, key=f"wl_pick_{wl.name}_{t}",
                                width='stretch',
                                help=f"Jump to Scope · {t}",
                            ):
                                from volscope.ui.components.navigation import (
                                    NavIntent, nav_to,
                                )
                                nav_to(NavIntent(
                                    page="Scope", ticker=t, source="Watchlist",
                                ))
                                st.rerun()
                        with c2:
                            if st.button(
                                "✕", key=f"wl_rm_{wl.name}_{t}",
                                help=f"Remove {t} from {wl.name}",
                            ):
                                try:
                                    remove_ticker_from_watchlist(db, wl.name, t)
                                    st.rerun()
                                except Exception as exc:
                                    st.error(f"Remove failed: {exc}")

                # Inline add-ticker form, scoped per watchlist
                with st.form(key=f"wl_add_{wl.name}", border=False):
                    new_t = st.text_input(
                        "Add ticker",
                        placeholder="e.g. PYPL",
                        key=f"wl_add_input_{wl.name}",
                        label_visibility="collapsed",
                    )
                    if st.form_submit_button(
                        "+ Add", width='stretch', help="Append to this watchlist",
                    ):
                        clean = (new_t or "").strip().upper()
                        if clean:
                            try:
                                add_ticker_to_watchlist(db, wl.name, clean)
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Add failed: {exc}")

    # Create-new-watchlist form (compact)
    with st.form(key="wl_create_new", border=False):
        c1, c2 = st.columns([4, 1])
        with c1:
            new_name = st.text_input(
                "New watchlist name",
                placeholder="e.g. Earnings Plays",
                key="wl_new_name",
                label_visibility="collapsed",
            )
        with c2:
            alarms = st.checkbox(
                "🔔", value=False,
                key="wl_new_alarms",
                help="Enable vol-regime alarms (CHEAP/RICH boundary + regime shift)",
            )
        if st.form_submit_button(
            "+ Watchlist", width='stretch', help="Create a new empty watchlist",
        ):
            clean_name = (new_name or "").strip()
            if clean_name:
                try:
                    create_watchlist(db, clean_name, regime_alarms=alarms)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Create failed: {exc}")


def _cached_available_tickers(db) -> list[str]:
    """Short-cache wrapper for db.get_available_tickers().

    The sidebar calls get_available_tickers in 4 places per render
    (ticker-picker, bulk-load button enable, brand-counter,
    add-ticker form). Pre-v0.9.6 those were each a fresh DuckDB
    query — ~80ms × 4 = 320ms per sidebar render on a warm cache
    miss. Routing through the existing 60s cached helper drops it
    to one query per minute.
    """
    from volscope.ui.components.cached_data import (
        get_available_tickers_cached, make_cache_key,
    )
    try:
        return get_available_tickers_cached(make_cache_key(db), db)
    except Exception:
        # Fallback to direct query if cache fails for any reason
        return db.con.execute(
            "SELECT DISTINCT ticker FROM daily_vol ORDER BY ticker"
        ).fetchdf()["ticker"].tolist() if not _is_db_empty(db) else []


def _is_db_empty(db) -> bool:
    try:
        r = db.con.execute("SELECT COUNT(*) FROM daily_vol LIMIT 1").fetchone()
        return (r[0] if r else 0) == 0
    except Exception:
        return True


def _freshness(last_scrape):
    """Thin wrapper producing the sidebar-cased version of the badge."""
    label, color = freshness_badge(last_scrape)
    return label.lower(), color


def _regime_label(latest: pd.DataFrame) -> tuple[str, str]:
    """Single-line market regime summary for the sidebar pulse block."""
    if latest is None or latest.empty or "iv_percentile" not in latest.columns:
        return ("—", "#8a8f9e")
    series = latest["iv_percentile"].dropna()
    if len(series) < 5:
        return ("warming up", "#8a8f9e")
    median = float(series.median())
    if median < 25:
        return (f"risk on — {median:.0f}", "#00d4aa")
    if median > 75:
        return (f"risk off — {median:.0f}", "#ff4466")
    if median > 55:
        return (f"elevated — {median:.0f}", "#ff9f43")
    return (f"normal — {median:.0f}", "#5b8cff")


def _top_movers_snippet(db, latest: pd.DataFrame, n: int = 3) -> list[tuple[str, float]]:
    """Return up to `n` (ticker, abs_iv_change) tuples for the biggest movers.

    v0.9.2 fix: the previous implementation called
    ``db.get_ticker_history(t)`` once per ticker — at 842 tickers
    in the universe that's 842 separate DuckDB queries on every
    sidebar rerun. Now uses the existing ``get_recent_for_tickers``
    bulk-fetch with ``lookback_days=2`` → a single query that
    returns all the rows we need. ~50× faster on the production
    universe.
    """
    if latest is None or latest.empty or "ticker" not in latest.columns:
        return []
    tickers = [str(t) for t in latest["ticker"].dropna().tolist()]
    if not tickers:
        return []
    try:
        bulk = db.get_recent_for_tickers(tickers, lookback_days=2)
    except Exception:                                          # noqa: BLE001
        return []
    out: list[tuple[str, float]] = []
    for t, hist in bulk.items():
        if hist is None or hist.shape[0] < 2 or "iv_30d" not in hist.columns:
            continue
        iv_now  = hist["iv_30d"].iloc[-1]
        iv_prev = hist["iv_30d"].iloc[-2]
        if pd.isna(iv_now) or pd.isna(iv_prev):
            continue
        out.append((t, float(iv_now) - float(iv_prev)))
    out.sort(key=lambda p: abs(p[1]), reverse=True)
    return out[:n]


def _render_ticker_picker(st, db) -> str:
    """Search-style ticker picker + 'add any symbol' inline action.

    Visual structure (post-v0.7.0):
      ┌── TICKER ────────────────────────────────────┐
      │ [ AAPL ▾ ]                                   │
      │                                              │
      │ add symbol                                   │
      │ [ z.B. PLTR oder ^VIX        ] [ + ADD ]     │
      └──────────────────────────────────────────────┘

    Single shared container, one label scale (11px DM Sans,
    color :muted), single placeholder, single visual rhythm. Prior
    layout used a Mono 9px caps label at #424666 which was
    sub-WCAG (~1.8:1 contrast) — unreadable on dark theme.
    """
    available = _cached_available_tickers(db) or all_tickers()
    current = st.session_state.get("selected_ticker", "SPY")
    if current not in available:
        current = available[0] if available else "SPY"

    render_html(
        st,
        '<div style="font-family:\'DM Sans\',sans-serif;font-size:11px;'
        'color:#9aa0b3;margin:6px 0 4px 0;font-weight:500;'
        'letter-spacing:0.02em;">Ticker</div>',
    )
    ticker = st.selectbox(
        "Ticker",
        available,
        index=available.index(current),
        help="Type to filter your loaded tickers.",
        label_visibility="collapsed",
    )

    render_html(
        st,
        '<div style="font-family:\'DM Sans\',sans-serif;font-size:11px;'
        'color:#9aa0b3;margin:12px 0 4px 0;font-weight:500;'
        'letter-spacing:0.02em;">Add symbol</div>',
    )
    with st.form("add_ticker_form", clear_on_submit=True):
        # Stacked layout — input on top at full width, button below
        # at full width. Prior side-by-side split (st.columns([3, 1]))
        # crammed the placeholder against the button in a ~200px
        # sidebar; vertical stacking gives both elements room to
        # breathe and reads cleanly on narrow viewports.
        raw = st.text_input(
            "Symbol",
            placeholder="z.B. PLTR oder ^VIX",
            label_visibility="collapsed",
            help=(
                "Single symbol per add. Digit-only codes auto-resolve to "
                "HK / TW / Shanghai. Alpha codes that fail bare also try "
                "London / XETRA / Paris."
            ),
        )
        submitted = st.form_submit_button("+ ADD", width='stretch')
        if submitted and raw:
            with st.spinner(f"Resolving {raw.strip().upper()}..."):
                result = resolve_and_ingest(db, raw)
            if result.ok:
                st.success(result.message)
                st.session_state["selected_ticker"] = result.ticker
                st.rerun()
            else:
                st.error(result.message)

    return ticker


def _render_live_screener(st, db) -> None:
    """
    Inline bulk-load entry point — replaces the previous expander pattern.

    Why no expander: the expander chevron leaked Material-Symbol literal
    text on slow font loads, plus its chrome was disproportionate to the
    payload (1 link + 1 button). New pattern: a single status pill that
    expands into a load button via session-state toggle on click.
    """
    universe_size = len(all_tickers())
    already = len(_cached_available_tickers(db) or [])
    missing = universe_size - already
    coverage_pct = int(round(already / max(1, universe_size) * 100))

    # All-loaded state — quiet success pill, no action.
    if missing == 0:
        render_html(
            st,
            """
<div style="font-family:'DM Sans',sans-serif;font-size:11px;
            color:#00d4aa;padding:6px 10px;margin-top:6px;
            background:rgba(0,212,170,0.06);border-radius:5px;
            border:1px solid rgba(0,212,170,0.18);">
  ● Universe complete
</div>""",
        )
        return

    # Compact status row + "load" toggle. Click flips a session flag that
    # reveals the actual load button. Two clicks to start a 7-min job —
    # protects against stray clicks.
    eta_min = max(1, round(missing * 1.5 / 60))
    show_loader = st.session_state.get("vs_show_bulk_loader", False)

    render_html(
        st,
        f"""
<div style="display:flex;justify-content:space-between;align-items:center;
            font-family:'DM Sans',sans-serif;font-size:11px;
            color:#9aa0b3;margin-top:6px;padding:4px 0;">
  <span>Universe</span>
  <span><span style="color:#e0e4ef;font-weight:600;">{already}</span>
        <span style="color:#6c7286;">/{universe_size}</span>
        <span style="color:#6c7286;">· {coverage_pct}%</span></span>
</div>""",
    )

    if not show_loader:
        if st.button(
            f"+ load {missing} missing",
            key="sb_bulk_show",
            help=f"Reveal the bulk-load button. Estimated duration ~{eta_min} min.",
            width='stretch',
        ):
            st.session_state["vs_show_bulk_loader"] = True
            st.rerun()
        return

    # Confirmation revealed
    render_html(
        st,
        f"""
<div style="font-family:'DM Sans',sans-serif;font-size:11px;
            color:#c8ccd9;padding:8px 10px;margin-top:4px;
            background:rgba(255,159,67,0.06);border-radius:5px;
            border-left:2px solid #ff9f43;">
  <div style="color:#ff9f43;font-weight:600;letter-spacing:0.02em;">Long-running job</div>
  <div style="margin-top:3px;color:#9aa0b3;">{missing} tickers · ~{eta_min} min · idempotent · safe to interrupt</div>
</div>""",
    )

    c1, c2 = st.columns([3, 1])
    with c1:
        run_now = st.button(
            "▶ run loader",
            key="sb_bulk_run",
            type="primary",
            width='stretch',
        )
    with c2:
        if st.button("✕", key="sb_bulk_cancel", help="Cancel"):
            st.session_state["vs_show_bulk_loader"] = False
            st.rerun()

    if run_now:
        from volscope.data.universe_loader import load_universe, persist_report
        progress = st.progress(0.0, text="Starting bulk load...")
        counters = {"loaded": 0, "skipped": 0, "failed": 0}

        def _on_progress(outcome, idx, total):
            if outcome.status in ("loaded", "retried"):
                counters["loaded"] += 1
            elif outcome.status == "skipped":
                counters["skipped"] += 1
            else:
                counters["failed"] += 1
            progress.progress(
                idx / max(1, total),
                text=(f"{outcome.status:<8} {outcome.ticker:<12} "
                      f"({idx}/{total}) — ✓{counters['loaded']} ✗{counters['failed']}"),
            )

        report = load_universe(db, progress_callback=_on_progress)
        persist_report(report)
        progress.empty()
        st.session_state["vs_show_bulk_loader"] = False
        if report.n_failed == 0:
            st.success(
                f"Loaded {report.n_loaded} · skipped {report.n_skipped} "
                f"· coverage {report.coverage_pct():.1f}%"
            )
        else:
            st.warning(
                f"Loaded {report.n_loaded} · failed {report.n_failed}. "
                f"Run `make load-universe-resume` to retry."
            )
        st.rerun()


def _render_page_context(
    st, page: str, current_ticker: str, db, latest: pd.DataFrame
) -> None:
    """Different quick-stats panel depending on the active page."""
    if page == "Command":
        # No extra panel needed — the Command Center page is self-contained.
        return
    if page == "Discover":
        regime, color = _regime_label(latest)
        movers = _top_movers_snippet(db, latest, n=3)
        movers_html = ""
        if movers:
            rows = "".join(
                f'<div style="display:flex;justify-content:space-between;padding:3px 0;">'
                f'<span style="color:#e0e4ef;font-weight:500;">{t}</span>'
                f'<span style="color:{"#ff4466" if c > 0 else "#00d4aa"};">'
                f'{"▲" if c > 0 else "▼"} {abs(c):.1f}</span>'
                f'</div>'
                for t, c in movers
            )
            movers_html = (
                f'<div style="margin-top:10px;font-family:\'DM Sans\',sans-serif;'
                f'font-size:11px;color:#c8ccd9;">'
                f'<div style="color:#9aa0b3;font-size:11px;'
                f'margin-bottom:4px;font-weight:500;">Top movers</div>'
                f'{rows}</div>'
            )

        render_html(
            st,
            f"""
            <div style="background:#12131a;border:1px solid #1e2038;border-radius:6px;padding:10px 12px;margin-top:8px;">
              <div style="color:#9aa0b3;font-family:'DM Sans',sans-serif;font-size:11px;font-weight:500;margin-bottom:4px;">Market pulse</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:13px;color:{color};font-weight:600;">● {regime}</div>
              {movers_html}
            </div>
            """,
        )
    elif page == "Scope":
        # Show KPI snapshot for the current ticker.
        try:
            history = db.get_ticker_history(current_ticker)
        except Exception:
            history = pd.DataFrame()
        if history.empty:
            return
        row = history.iloc[-1]
        iv = row.get("iv_30d")
        hv = row.get("hv_20d")
        perc = row.get("iv_percentile")
        spread = (float(iv) - float(hv)) if pd.notna(iv) and pd.notna(hv) else None
        iv_str = f"{float(iv):.1f}%" if pd.notna(iv) else "—"
        hv_str = f"{float(hv):.1f}%" if pd.notna(hv) else "—"
        perc_str = f"{float(perc):.0f}" if pd.notna(perc) else "—"
        spread_str = f"{spread:+.1f}" if spread is not None else "—"
        spread_color = "#ff4466" if (spread or 0) > 0 else "#00d4aa"
        iv_color = "#00d4aa"
        hv_color = "#5b8cff"

        render_html(
            st,
            f"""
            <div class="volscope-snap">
              <div class="volscope-snap-head">{current_ticker} snapshot</div>
              <div class="volscope-snap-row"><span class="k">IV</span><span class="v" style="color:{iv_color};">{iv_str}</span></div>
              <div class="volscope-snap-row"><span class="k">HV 20d</span><span class="v" style="color:{hv_color};">{hv_str}</span></div>
              <div class="volscope-snap-row"><span class="k">Percentile</span><span class="v">{perc_str}</span></div>
              <div class="volscope-snap-row"><span class="k">Spread</span><span class="v" style="color:{spread_color};">{spread_str}</span></div>
            </div>
            """,
        )
    elif page == "Scanner":
        # Show universe breakdown by sector.
        if latest is None or latest.empty or "sector" not in latest.columns:
            return
        counts = latest["sector"].dropna().value_counts().head(6)
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;font-size:11px;color:#8a8f9e;padding:2px 0;">'
            f'<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:140px;">{sec}</span>'
            f'<span style="color:#e0e4ef;">{n}</span></div>'
            for sec, n in counts.items()
        )
        render_html(
            st,
            f"""
            <div style="background:#12131a;border:1px solid #1e2038;border-radius:6px;padding:10px 12px;margin-top:8px;">
              <div style="color:#9aa0b3;font-family:'DM Sans',sans-serif;font-size:11px;font-weight:500;margin-bottom:6px;">Universe by sector</div>
              {rows}
            </div>
            """,
        )


def render_sidebar(db, current_ticker: str, current_page: str) -> tuple[str, str, dict]:
    import streamlit as st

    # ── Brand strip ────────────────────────────────────────────────
    # Functional row: logo on the left, live ticker count + freshness dot
    # on the right. Replaces the previous stand-alone wordmark which was
    # decorative-only.
    try:
        _n_loaded_brand = len(_cached_available_tickers(db) or [])
    except Exception:
        _n_loaded_brand = 0
    try:
        _last_brand = db.get_last_scrape_date()
    except Exception:
        _last_brand = None
    if _last_brand is None:
        _brand_dot_color = "#424666"
    else:
        from datetime import date as _date
        _age = (_date.today() - _last_brand).days
        _brand_dot_color = "#00d4aa" if _age <= 1 else "#ff9f43" if _age <= 7 else "#ff4466"

    render_html(
        st,
        f"""
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:4px 0 8px 0;border-bottom:1px solid rgba(255,255,255,0.04);
                    margin-bottom:8px;">
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:16px;
                         font-weight:700;letter-spacing:0.04em;line-height:1;
                         background:linear-gradient(135deg,#00d4aa 0%,#5b8cff 100%);
                         -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
              ◈ VolScope
            </div>
            <div style="color:#6c7286;font-size:10px;letter-spacing:0.04em;
                         text-transform:uppercase;margin-top:3px;font-weight:500;
                         font-family:'DM Sans',sans-serif;">
              Vol intelligence
            </div>
          </div>
          <div style="text-align:right;line-height:1.25;">
            <div style="color:#e0e4ef;font-weight:600;font-size:12px;
                         font-family:'JetBrains Mono',monospace;">
              <span style="color:{_brand_dot_color};font-size:9px;">●</span> {_n_loaded_brand}
            </div>
            <div style="color:#9aa0b3;font-size:10px;letter-spacing:0.04em;
                         text-transform:uppercase;font-family:'DM Sans',sans-serif;">tickers</div>
          </div>
        </div>
        """,
    )

    # ── Ticker picker + add form ────────────────────────────────────
    ticker = _render_ticker_picker(st, db)

    # ── Live screener: bulk load ────────────────────────────────────
    _render_live_screener(st, db)

    st.divider()

    # ── Navigation (grouped) ────────────────────────────────────────
    # Three semantic groups — trader scans by purpose, not alphabet.
    # Each page renders as a sidebar button so groups can have their own
    # markdown headers between rows. Active page = green, others = muted.
    NAV_GROUPS: list[tuple[str, list[str]]] = [
        ("◆ DECISIONS",  ["Command", "Discover", "Signals", "Bot", "Alerts", "Earnings Hub", "Portfolio", "Mega-Scan"]),
        ("◇ RESEARCH",   ["Scope", "Scanner", "Heatmap", "Rotation", "Flow", "Vol Insights", "Research"]),
        ("▷ EXECUTION",  ["Pre-Trade", "Builder", "Options Lab", "LEAPS Lab", "Dossier", "Earnings Trades", "Backtest"]),
        ("? REFERENCE",  ["Help"]),
    ]
    pages = [p for _, group in NAV_GROUPS for p in group]
    if current_page not in pages:
        # Defensive: an unknown ``current_page`` typically means a
        # caller used the wrong registry key (e.g. "Bot Dashboard"
        # instead of "Bot", or "Command Center" instead of "Command").
        # Previously this silently reset to "Command", which hid the
        # underlying bug AND surprised operators by jumping them to
        # Command Center after dismissing any page-banner / modal.
        #
        # Heuristic recovery: if the unknown name has a close-prefix
        # match in the registry, snap to that (so "Bot Dashboard"
        # snaps to "Bot", "Command Center" snaps to "Command"). The
        # last-resort fallback is the previously-active page captured
        # in session_state, then "Command" only as a final default.
        snap = next(
            (p for p in pages if current_page.lower().startswith(p.lower())),
            None,
        )
        if snap is not None:
            current_page = snap
        else:
            current_page = st.session_state.get(
                "vs_last_valid_page", "Command",
            )
    # Remember the page on every successful render so the recovery
    # path above has something better than "Command" to fall back to.
    st.session_state["vs_last_valid_page"] = current_page

    # Live alert counter — cached for 60 s so each rerun is cheap.
    # Failures are logged (not silenced) so an operator-visible "0
    # alerts" doesn't mask a broken scanner (DB lock / bad query / etc).
    @st.cache_data(ttl=60, show_spinner=False)
    def _cached_alert_count(_db_marker: str) -> int:
        try:
            from volscope.analytics.alerts_scanner import scan_alerts
            return len(scan_alerts(db))
        except Exception as exc:                                # noqa: BLE001
            import logging as _lg
            _lg.getLogger("volscope.ui.sidebar").warning(
                "scan_alerts failed; alert count rendered as 0: %s", exc,
            )
            return 0

    try:
        _alert_n = _cached_alert_count(str(getattr(db, "path", "default")))
    except Exception as exc:                                    # noqa: BLE001
        import logging as _lg
        _lg.getLogger("volscope.ui.sidebar").warning(
            "alert-count cache call failed: %s", exc,
        )
        _alert_n = 0

    page = current_page
    for group_label, group_pages in NAV_GROUPS:
        render_html(
            st,
            f'<div style="font-family:\'DM Sans\',sans-serif;font-size:11px;'
            f'color:#5b8cff;letter-spacing:0.04em;margin-top:12px;margin-bottom:5px;'
            f'font-weight:600;text-transform:uppercase;">{group_label}</div>',
        )
        for p in group_pages:
            is_active = (p == current_page)
            badge = ""
            if p == "Alerts" and _alert_n > 0:
                badge = f"  ({_alert_n})"
            label = (f"▸ {p}{badge}" if is_active else f"  {p}{badge}")
            if st.button(
                label,
                key=f"nav_btn_{p}",
                width='stretch',
                type="primary" if is_active else "secondary",
            ):
                page = p

    # ── Page-aware context block ────────────────────────────────────
    # v0.9.2 perf: cache via the existing get_all_latest_cached
    # helper so the 842-row snapshot isn't refetched on every nav-
    # button click. 60-second TTL — fresh scrape invalidates via
    # the make_cache_key(db) date string.
    try:
        from volscope.ui.components.cached_data import (
            get_all_latest_cached, make_cache_key,
        )
        latest = get_all_latest_cached(make_cache_key(db), db)
    except Exception:                                          # noqa: BLE001
        latest = pd.DataFrame()
    _render_page_context(st, page, ticker, db, latest)

    st.divider()

    # ── Settings ────────────────────────────────────────────────────
    with st.expander("HV window settings", expanded=False):
        hv_short = st.number_input(
            "Short-window HV (days)",
            min_value=5,
            max_value=120,
            value=20,
            step=1,
            help="Rolling window for short-term historical volatility.",
        )
        hv_long = st.number_input(
            "Long-window HV (days)",
            min_value=10,
            max_value=240,
            value=60,
            step=1,
            help="Rolling window for long-term historical volatility.",
        )

    # ── Theme toggle (Dark / High-Contrast) ─────────────────────────
    with st.expander("Appearance", expanded=False):
        theme_toggle = st.radio(
            "Theme",
            ["Dark", "High-Contrast"],
            horizontal=True,
            index=0 if st.session_state.get("vs_theme", "Dark") == "Dark" else 1,
            help=(
                "Dark = default Bloomberg-cockpit palette. "
                "High-Contrast lifts text and grids for bright-screen readability."
            ),
            key="theme_toggle_radio",
        )
        st.session_state["vs_theme"] = theme_toggle

    settings = {
        "hv_short": hv_short,
        "hv_long":  hv_long,
        "theme":    st.session_state.get("vs_theme", "Dark"),
    }

    # ── Data status (bottom, subtle) ────────────────────────────────
    try:
        n_loaded = len(_cached_available_tickers(db) or [])
    except Exception:
        n_loaded = 0
    try:
        from volscope.data.ticker_universe import all_tickers as _all_t
        n_curated = len(_all_t())
    except Exception:
        n_curated = 0
    try:
        last = db.get_last_scrape_date()
    except Exception:
        last = None
    label, color = _freshness(last)
    last_str = last.isoformat() if last else "—"
    coverage_pct = int(round(n_loaded / max(1, n_curated) * 100)) if n_curated else 0
    render_html(
        st,
        f"""
        <div style="margin-top:18px;padding-top:12px;border-top:1px solid #1e2038;font-family:'DM Sans',sans-serif;font-size:11px;color:#9aa0b3;line-height:1.7;">
          <div><span style="color:#e0e4ef;font-weight:600;">{n_loaded}</span> loaded · <span style="color:#9aa0b3;">{n_curated}</span> curated <span style="color:#9aa0b3;">({coverage_pct}%)</span></div>
          <div>last scrape — <span style="color:#e0e4ef;">{last_str}</span></div>
          <div style="margin-top:6px;"><span style="background:{color}22;color:{color};padding:2px 8px;border-radius:4px;font-weight:500;">● {label}</span></div>
        </div>
        """,
    )

    # ── Data-health badge (Pillar 2) ─────────────────────────────────
    # GREEN: 0 FAIL & ≤ 5 FLAG today
    # AMBER: 1-3 FAIL or 6-20 FLAG
    # RED:   > 3 FAIL → click to drill into validation_log
    try:
        v_summary = db.get_validation_summary()
        if v_summary.empty:
            health_color, health_label, health_detail = (
                "#8a8f9e", "DATA NOT VALIDATED",
                "run scripts/backtest/run_validation.py",
            )
        else:
            n_ok   = int(v_summary[v_summary["overall_level"] == "OK"]["n"].sum())
            n_flag = int(v_summary[v_summary["overall_level"] == "FLAG"]["n"].sum())
            n_fail = int(v_summary[v_summary["overall_level"] == "FAIL"]["n"].sum())
            if n_fail > 3:
                health_color, health_label = "#ff4466", "DATA RED"
            elif n_fail > 0 or n_flag > 20:
                health_color, health_label = "#ff9f43", "DATA AMBER"
            elif n_flag > 5:
                health_color, health_label = "#ff9f43", "DATA AMBER"
            else:
                health_color, health_label = "#00d4aa", "DATA GREEN"
            health_detail = f"{n_ok} OK · {n_flag} FLAG · {n_fail} FAIL"
        render_html(
            st,
            f"""
            <div style="margin-top:10px;font-family:'JetBrains Mono',monospace;font-size:10px;color:#8a8f9e;">
              <span style="background:{health_color}22;color:{health_color};padding:2px 8px;border-radius:4px;font-weight:600;">● {health_label}</span>
              <span style="margin-left:6px;">{health_detail}</span>
            </div>
            """,
        )
    except Exception:
        # Validation is non-critical UI; never break the sidebar
        pass

    # ── Active alerts — alert-rule status at a glance ───────────────
    # Shows up to 5 enabled alert rules with live "would fire now?" status.
    # Click → jumps to Command Center where the trader can manage rules.
    # v0.9.7 rename: was "Watchlist · N rules" — collided with the new
    # user-watchlist widget below. Both render in the sidebar, but
    # "Active alerts" describes WHAT this shows (rule status), while
    # "My watchlists" describes ticker groupings.
    try:
        rules_df = db.get_alert_rules()
        enabled = rules_df[rules_df["enabled"] == True] if not rules_df.empty else rules_df
        if not enabled.empty:
            with st.expander(f"⚠ Active alerts · {len(enabled)} rules", expanded=False):
                # Compact status: ticker · metric · operator threshold · current
                from volscope.alerts.alert_engine import AlertRule, evaluate_rule
                from volscope.ui.components.cached_data import (
                    get_all_latest_cached, make_cache_key,
                )
                # Cached — sidebar re-renders on every page interaction;
                # uncached get_all_latest() was a 100-300ms hit per
                # navigation click on a 800-ticker DB.
                latest_for_eval = get_all_latest_cached(make_cache_key(db), db)
                rows_html: list[str] = []
                for _, r in enabled.head(5).iterrows():
                    try:
                        rule = AlertRule(
                            id=int(r["id"]),
                            ticker=str(r["ticker"]),
                            metric=str(r["metric"]),
                            operator=str(r["operator"]),
                            threshold=float(r["threshold"]),
                            channel=str(r["channel"]),
                            label=str(r["label"]),
                            enabled=True,
                        )
                        target_rows = (
                            latest_for_eval[latest_for_eval["ticker"] == rule.ticker]
                            if rule.ticker != "*"
                            else latest_for_eval
                        )
                        fired = False
                        if not target_rows.empty:
                            fired_obj = evaluate_rule(rule, target_rows.iloc[0])
                            fired = fired_obj is not None
                        glyph = "●" if fired else "○"
                        glyph_color = "#ff4466" if fired else "#8a8f9e"
                        rows_html.append(
                            f'<div style="font-family:\'DM Sans\',sans-serif;'
                            f'font-size:11px;color:#9aa0b3;padding:3px 0;">'
                            f'<span style="color:{glyph_color};">{glyph}</span> '
                            f'<span style="color:#e0e4ef;">{rule.label}</span>'
                            f'</div>'
                        )
                    except Exception:
                        continue
                if rows_html:
                    render_html(st, "".join(rows_html))
                if st.button(
                    "Manage rules →",
                    key="sidebar_watchlist_manage",
                    width='stretch',
                    help="Open Command Center alerts panel",
                ):
                    from volscope.ui.components.navigation import NavIntent, nav_to
                    nav_to(NavIntent(page="Command", source="Sidebar"))
                    st.rerun()
    except Exception as exc:                                        # noqa: BLE001
        import logging as _lg
        _lg.getLogger("volscope.ui.sidebar").warning(
            "Watchlist (alerts) render failed: %s", exc,
        )

    # ── User Watchlists (TradingView-style) ────────────────────────
    # Operator-managed groupings with optional regime-alarm trigger.
    # Persistence in volscope.persistence.watchlists; alarms dispatch
    # via Telegram + macOS desktop. See PRE_LAUNCH_REPORT.md.
    try:
        _render_user_watchlists(st, db)
    except Exception as exc:                                        # noqa: BLE001
        import logging as _lg
        _lg.getLogger("volscope.ui.sidebar").warning(
            "User-watchlist widget render failed: %s", exc,
        )

    # ── Dev panel (only when ?dev=1 in URL) ───────────────────────────
    try:
        if st.query_params.get("dev") == "1":
            with st.expander("⚙ Dev panel — perf", expanded=False):
                from volscope.utils.timing import (
                    list_instrumented_names,
                    n_records_for,
                    percentiles_for,
                )
                names = list_instrumented_names()
                if not names:
                    st.caption("No instrumented calls yet — navigate around to populate.")
                else:
                    rows = []
                    for name in names:
                        pcts = percentiles_for(name)
                        rows.append({
                            "name":  name,
                            "p50":   pcts.get(50),
                            "p95":   pcts.get(95),
                            "n":     n_records_for(name),
                        })
                    df_perf = pd.DataFrame(rows).sort_values("p95", ascending=False, na_position="last")
                    st.dataframe(df_perf, width='stretch', hide_index=True)
    except Exception as exc:
        # Dev panel must never break the sidebar
        pass

    # Refresh-data button: triggers `make scrape` in a detached background
    # process so the UI stays responsive. The scrape itself is long
    # (several minutes) — we just kick it off and let the user keep
    # working. Status surfaces via the next page-reload of "last scrape".
    if st.button(
        "↻ Refresh market data",
        key="sidebar_scrape_btn",
        help="Run `make scrape` in the background (several minutes).",
        width='stretch',
    ):
        import subprocess, os, datetime as _dt
        log_dir = os.path.expanduser("~/.claude/volscope-cron-logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(
            log_dir,
            f"manual-scrape-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.log",
        )
        try:
            with open(log_file, "w") as lf:
                subprocess.Popen(
                    ["make", "scrape"],
                    cwd="/Users/tomschoen/Desktop/VolScope",
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            # Streamlit ≥1.32 rejects ``↻`` as icon — replaced by the
            # emoji-presentation ``🔄`` (U+1F504, counterclockwise arrows).
            st.toast(f"Scrape started — log: {os.path.basename(log_file)}", icon="🔄")
        except Exception as exc:
            st.error(f"Could not start scrape: {exc}")

    return ticker, page, settings
