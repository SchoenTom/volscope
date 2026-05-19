"""
Page Watchlist — single-tab home for all watchlist management.

WHY this page exists: operator feedback 2026-05-17 — "ich möchte einen
einzigen Watchlist-Reiter, wenn man darauf klickt kommt einfach
Ticker hinzufügen und alle die gerade drauf sind und dann da evtl
noch ne Alert-Abteilung". The sidebar widget was a sprawling mess
with inline alarm pickers + add forms that pushed nav off-screen.

WHEN to use it: any time you want to view / edit / add to a
watchlist, or configure which alarm types should ping you for the
tickers in a list.

WHAT it depends on:
  - volscope.persistence.watchlists (create, list, add, remove,
    ensure_tables, ALARM_TYPES)
  - volscope.data.database (latest spot + 1d change per ticker)
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS


_ALARM_ICONS: dict[str, str] = {
    "regime_change":     "≈",
    "iv_pct_high":       "⬆",
    "iv_pct_low":        "⬇",
    "iv_rank_high":      "▲",
    "iv_rank_low":       "▼",
    "earnings_imminent": "📅",
    "price_move_1d":     "⚡",
}


def _ticker_snapshot(db, ticker: str) -> tuple[str, str, str]:
    """Return (price_str, change_str, change_color) for a ticker row."""
    try:
        r = db.con.execute(
            "SELECT spot_price FROM daily_vol WHERE ticker = ? "
            "ORDER BY date DESC LIMIT 2",
            [ticker],
        ).fetchall()
        if not r or r[0][0] is None:
            return ("—", "", COLORS["muted"])
        today = float(r[0][0])
        prev = float(r[1][0]) if len(r) > 1 and r[1][0] is not None else None
        price = f"${today:,.2f}" if today < 1000 else f"${today:,.0f}"
        if prev is None or prev <= 0:
            return (price, "", COLORS["muted"])
        chg_pct = (today - prev) / prev * 100.0
        sign = "+" if chg_pct >= 0 else ""
        color = COLORS["accent"] if chg_pct >= 0 else COLORS["warn"]
        return (price, f"{sign}{chg_pct:.2f}%", color)
    except Exception:
        return ("—", "", COLORS["muted"])


def _render_create_new(db) -> None:
    """+ Create new watchlist + 📥 Import-from-CSV."""
    from volscope.persistence.watchlists import (
        add_ticker_to_watchlist, create_watchlist,
    )

    c1, c2 = st.columns(2)
    with c1:
        with st.popover("+ Create new watchlist", use_container_width=True):
            with st.form("wlpage_create", border=False):
                name = st.text_input(
                    "Name",
                    placeholder="e.g. Earnings Plays",
                    key="wlpage_create_name",
                )
                submitted = st.form_submit_button(
                    "Create", type="primary", width='stretch',
                )
                if submitted:
                    clean = (name or "").strip()
                    if not clean:
                        st.error("Pick a name.")
                    else:
                        try:
                            create_watchlist(db, clean)
                            st.toast(f"✓ Created «{clean}»", icon="📌")
                            st.session_state["wlpage_selected"] = clean
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Create failed: {exc}")

    with c2:
        with st.popover("📥 Import from TradingView / CSV",
                          use_container_width=True):
            with st.form("wlpage_import", border=False):
                imp_name = st.text_input(
                    "Watchlist name",
                    placeholder="e.g. TV-Tech",
                    key="wlpage_imp_name",
                )
                imp_text = st.text_area(
                    "Paste tickers (comma-, newline-, or space-separated)",
                    placeholder="AAPL, MSFT, NVDA\nGOOGL META\nPLTR",
                    height=100,
                    key="wlpage_imp_text",
                )
                imp_submitted = st.form_submit_button(
                    "Import", type="primary", width='stretch',
                )
                if imp_submitted:
                    import re
                    clean = (imp_name or "").strip()
                    raw = imp_text or ""
                    parts = [
                        re.sub(r"[^\w\^\.\-]", "", p).upper()
                        for p in re.split(r"[,\n;\s]+", raw)
                    ]
                    tickers = [p for p in parts if p and 1 <= len(p) <= 12]
                    if not clean:
                        st.error("Pick a watchlist name.")
                    elif not tickers:
                        st.error("No valid tickers found.")
                    else:
                        try:
                            create_watchlist(db, clean)
                            n_added = 0
                            for t in tickers:
                                try:
                                    add_ticker_to_watchlist(db, clean, t)
                                    n_added += 1
                                except Exception:
                                    pass
                            st.toast(
                                f"✓ Imported {n_added}/{len(tickers)} into «{clean}»",
                                icon="📥",
                            )
                            st.session_state["wlpage_selected"] = clean
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Import failed: {exc}")


def _render_tickers_panel(db, wl) -> None:
    """Left column: ticker rows with spot + 1d%Δ + remove. Add form below."""
    from volscope.persistence.watchlists import (
        add_ticker_to_watchlist, remove_ticker_from_watchlist,
    )

    render_html(
        st,
        f'<div style="font-family:DM Sans,sans-serif;font-size:12px;'
        f'color:{COLORS["muted"]};letter-spacing:0.04em;'
        f'text-transform:uppercase;margin-bottom:8px;">Tickers · {len(wl.tickers)}</div>',
    )
    if not wl.tickers:
        st.caption("(empty — use the form below to add tickers)")
    else:
        for t in wl.tickers:
            price, chg, color = _ticker_snapshot(db, t)
            c1, c2, c3 = st.columns([3, 4, 1])
            with c1:
                if st.button(
                    t, key=f"wlpage_open_{wl.name}_{t}",
                    width='stretch',
                    help=f"Open {t} on Scope",
                ):
                    try:
                        from volscope.ui.components.navigation import (
                            NavIntent, nav_to,
                        )
                        nav_to(NavIntent(
                            page="Scope", ticker=t, source="Watchlist",
                        ))
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Nav failed: {exc}")
            with c2:
                render_html(
                    st,
                    f'<div style="font-family:JetBrains Mono,monospace;'
                    f'font-size:13px;line-height:34px;text-align:right;">'
                    f'<span style="color:{COLORS["text"]};font-weight:600;">{price}</span>'
                    f'<span style="color:{color};margin-left:10px;">{chg}</span>'
                    f'</div>',
                )
            with c3:
                if st.button(
                    "✕", key=f"wlpage_rm_{wl.name}_{t}",
                    help=f"Remove {t}",
                ):
                    try:
                        remove_ticker_from_watchlist(db, wl.name, t)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Remove failed: {exc}")

    st.markdown("---")
    with st.form(f"wlpage_add_{wl.name}", border=False):
        col_in, col_btn = st.columns([4, 1])
        with col_in:
            new_t = st.text_input(
                "Add ticker",
                placeholder="e.g. PYPL, ^VIX, BRK.B",
                key=f"wlpage_addin_{wl.name}",
                label_visibility="collapsed",
            )
        with col_btn:
            submitted = st.form_submit_button(
                "+ Add", width='stretch', type="primary",
            )
        if submitted:
            clean = (new_t or "").strip().upper()
            if clean:
                try:
                    add_ticker_to_watchlist(db, wl.name, clean)
                    st.toast(f"✓ Added {clean} to «{wl.name}»", icon="📌")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Add failed: {exc}")


def _render_alerts_panel(db, wl) -> None:
    """Right column: alarm-type picker. Save with thresholds."""
    from volscope.persistence.watchlists import ALARM_TYPES, create_watchlist

    render_html(
        st,
        f'<div style="font-family:DM Sans,sans-serif;font-size:12px;'
        f'color:{COLORS["muted"]};letter-spacing:0.04em;'
        f'text-transform:uppercase;margin-bottom:8px;">'
        f'🔔 Alerts · {len(wl.alarm_types or [])} active</div>',
    )
    st.caption(
        "Pick which signals should ping you via Telegram + macOS "
        "for tickers in this watchlist. Nothing fires unless you tick a box."
    )

    with st.form(f"wlpage_alarms_{wl.name}", border=False, clear_on_submit=False):
        new_types: list[str] = []
        new_thresholds: dict = dict(wl.alarm_thresholds or {})

        for key, meta in ALARM_TYPES.items():
            icon = _ALARM_ICONS.get(key, "•")
            checked = key in (wl.alarm_types or [])
            col_toggle, col_threshold = st.columns([3, 2])
            with col_toggle:
                is_on = st.checkbox(
                    f"{icon}  {meta['label']}",
                    value=checked,
                    key=f"wlpage_alarm_{wl.name}_{key}",
                    help=meta["help"],
                )
            with col_threshold:
                tkey = meta.get("threshold_key")
                if is_on and tkey is not None:
                    default_val = wl.alarm_thresholds.get(tkey, meta["default"])
                    try:
                        d = float(default_val)
                    except Exception:
                        d = float(meta["default"])
                    is_days = "days" in tkey
                    val = st.number_input(
                        "Threshold",
                        min_value=0.0,
                        max_value=365.0 if is_days else 200.0,
                        value=d,
                        step=1.0 if is_days else 0.5,
                        key=f"wlpage_thr_{wl.name}_{key}",
                        label_visibility="collapsed",
                        help=f"Threshold for {meta['label']}",
                    )
                    new_thresholds[tkey] = int(val) if is_days else float(val)
            if is_on:
                new_types.append(key)

        saved = st.form_submit_button(
            "✓ Save alerts" if new_types else "Save (no alerts on)",
            width='stretch',
            type="primary" if new_types else "secondary",
        )
        if saved:
            try:
                create_watchlist(
                    db, wl.name,
                    regime_alarms="regime_change" in new_types,
                    alarm_types=new_types,
                    alarm_thresholds=new_thresholds,
                )
                st.toast(
                    f"✓ {wl.name}: {len(new_types)} alert(s) saved",
                    icon="🔔",
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Save failed: {exc}")


def _render_delete_zone(db, wl) -> None:
    """Bottom-of-page danger button."""
    with st.expander("⚠ Delete this watchlist", expanded=False):
        st.warning(
            f"Deleting «{wl.name}» removes all {len(wl.tickers)} ticker(s) "
            f"and disables its alert configuration. This cannot be undone."
        )
        confirm = st.text_input(
            f"Type the watchlist name to confirm",
            key=f"wlpage_del_confirm_{wl.name}",
            placeholder=wl.name,
        )
        if st.button(
            f"⚠ Delete «{wl.name}» permanently",
            key=f"wlpage_del_{wl.name}",
            type="primary",
            disabled=(confirm != wl.name),
        ):
            try:
                db.con.execute(
                    "DELETE FROM watchlist_items WHERE watchlist_name = ?",
                    [wl.name],
                )
                db.con.execute(
                    "DELETE FROM watchlists WHERE name = ?", [wl.name],
                )
                st.toast(f"✓ Deleted «{wl.name}»", icon="🗑")
                # Clear the session selection so we land on the first
                # remaining watchlist on rerun.
                st.session_state.pop("wlpage_selected", None)
                st.rerun()
            except Exception as exc:
                st.error(f"Delete failed: {exc}")


def render_watchlist_page(db, settings: dict | None = None) -> None:
    """Top-level page entry."""
    from volscope.persistence.watchlists import (
        ensure_watchlist_tables, list_watchlists,
    )
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name="Watchlist")

    st.markdown("## ⚑ Watchlists")
    st.caption(
        "Group tickers, track prices, configure per-list alerts. "
        "Everything in one place — no sidebar clutter."
    )

    # v0.9.11 — operator feedback 2026-05-19: "wie erhalte ich die
    # Benachrichtigungen? steht dann beim Alert auch was für einer?
    # bleibt meine watchlist immer erhalten? erhalte ich auch
    # benachrichtigungen wenn volscope aus ist?"
    with st.expander("ℹ How alerts work · Wie funktionieren die Benachrichtigungen", expanded=False):
        st.markdown(
            """
**Persistence — ja, deine Watchlists bleiben erhalten.**
Die Watchlists liegen in der lokalen DuckDB (`watchlists` +
`watchlist_items` Tabellen). Sie überleben Streamlit-Neustarts,
App-Close, Mac-Reboot. Einzig manuelles Löschen der DB oder ein
Restore eines älteren Backups (`make restore-drill`) wischt sie.

**Benachrichtigungskanäle** (`.env` konfigurierbar):
1. **Telegram** — setze `TELEGRAM__BOT_TOKEN` und
   `TELEGRAM__CHAT_ID` in `.env`; Alarme erscheinen als Chat-
   Nachricht.
2. **macOS Desktop Notification** — keine Konfiguration nötig
   (`osascript`-basiert, immer an).
3. **Log line** — jeder Alarm wird zusätzlich ins App-Log
   geschrieben.

**Wann feuern Alarme?**
Ein eigener Cron-Job (`scripts/ops/check_alarms.py`) läuft
**unabhängig vom UI** — du brauchst weder Streamlit offen noch
Auto-Refresh aktiv. Setup:

```bash
make schedule-alerts     # registriert einen launchd-Job, der den
                         # Cron alle 30 min während NYSE-Stunden
                         # (09-21 NY-Zeit, Werktage) laufen lässt
```

**Was steht im Alarm?**
Jeder Alert nennt explizit:
- Ticker + Alarm-Typ (z.B. `▲ DAX · IV Rank crosses HIGH`)
- aktueller Wert vs. konfigurierter Schwellwert (`IV Rank 82 crossed
  threshold 80`)
- aktuelle Vol-Regime + Spot-Preis
- Quell-Watchlist
- Deep-Link auf Scope für diesen Ticker

**Steht da auch "DAX IV rank < 20"?** Ja, exakt so — wenn du den
`▼ IV Rank crosses LOW`-Alarm auf deine Watchlist setzt und der
Schwellwert 20 ist, kommt:
> `▼ DAX · IV Rank crosses LOW`
> IV Rank 18 crossed threshold 20
> regime CHEAP · spot $44.61 · from watchlist «Mein DAX»
> → open Scope: /?ticker=DAX&page=Scope&source=alarm
            """,
        )

    try:
        ensure_watchlist_tables(db)
    except Exception as exc:
        st.error(f"Watchlist tables unavailable (DB is read-only?): {exc}")
        return

    wls = list_watchlists(db)

    _render_create_new(db)

    if not wls:
        st.info(
            "No watchlists yet — click **+ Create new watchlist** above, "
            "or paste a list of symbols into **📥 Import from TradingView / CSV**."
        )
        return

    # Selector — which watchlist to view
    names = [w.name for w in wls]
    sel = st.session_state.get("wlpage_selected") or names[0]
    if sel not in names:
        sel = names[0]
    sel = st.selectbox(
        "Watchlist",
        names,
        index=names.index(sel),
        key="wlpage_selector",
        label_visibility="collapsed",
    )
    st.session_state["wlpage_selected"] = sel

    wl = next(w for w in wls if w.name == sel)

    # Two-column layout: tickers left, alerts right
    col_t, col_a = st.columns([3, 2])
    with col_t:
        _render_tickers_panel(db, wl)
    with col_a:
        _render_alerts_panel(db, wl)

    st.markdown("---")
    _render_delete_zone(db, wl)
