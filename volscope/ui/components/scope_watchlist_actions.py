"""Scope-page action bar — add current ticker to a watchlist + jump
to the watchlist's alarm picker.

Operator feedback 2026-05-16: "im Scope Menü brauche ich eine
Funktion zum zur Watchlist hinzufügen, Watchlist Alerts hinzufügen".

Two buttons rendered side-by-side under the Scope status bar:
  ① "+ Watchlist"   — popover to pick existing watchlist or create new
  ② "🔔 Alarms"     — set up alarm types for the current ticker's
                      watchlists (deep-links to sidebar picker)
"""
from __future__ import annotations


def render_scope_watchlist_actions(st, db, ticker: str) -> None:
    """Render the two action buttons. Best-effort — if the watchlist
    schema fails (read-only DB, missing tables) we render nothing
    rather than crashing the Scope page."""
    try:
        from volscope.persistence.watchlists import (
            add_ticker_to_watchlist, create_watchlist,
            ensure_watchlist_tables, list_watchlists,
        )
        ensure_watchlist_tables(db)
        wls = list_watchlists(db)
    except Exception:
        return  # Read-only or missing schema — silent skip

    col_a, col_b, _spacer = st.columns([3, 3, 6])

    with col_a:
        with st.popover(f"+ Add {ticker} to watchlist", use_container_width=True):
            existing_names = [w.name for w in wls]
            if existing_names:
                pick = st.selectbox(
                    "Add to existing",
                    ["(pick a watchlist)"] + existing_names,
                    key=f"scope_wl_pick_{ticker}",
                    label_visibility="visible",
                )
                # An empty-string first option rendered as an invisible
                # black bar (operator screenshot 2026-05-16). Use a
                # human-readable placeholder and treat it as "no pick".
                if pick == "(pick a watchlist)":
                    pick = ""
                if pick and st.button(
                    f"✓ Add {ticker} to «{pick}»",
                    key=f"scope_wl_add_existing_{ticker}",
                    width="stretch", type="primary",
                ):
                    try:
                        add_ticker_to_watchlist(db, pick, ticker)
                        st.toast(f"✓ {ticker} → {pick}", icon="📌")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Add failed: {exc}")
                st.divider()
            new_name = st.text_input(
                "Or create new watchlist",
                placeholder="e.g. Earnings Plays",
                key=f"scope_wl_new_{ticker}",
            )
            if new_name and st.button(
                f"+ Create «{new_name}» with {ticker}",
                key=f"scope_wl_create_{ticker}",
                width="stretch", type="primary",
            ):
                try:
                    create_watchlist(db, new_name.strip())
                    add_ticker_to_watchlist(db, new_name.strip(), ticker)
                    st.toast(f"✓ Created «{new_name}» with {ticker}", icon="📌")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Create failed: {exc}")

    with col_b:
        # Find watchlists that already contain this ticker — alarms
        # are configured per-watchlist, so jump to the first one that
        # carries the ticker. If none do, prompt to add first.
        containing = [w for w in wls if ticker in w.tickers]
        with st.popover(
            f"🔔 Alarms ({sum(len(w.alarm_types) for w in containing)})",
            use_container_width=True,
        ):
            if not containing:
                st.caption(
                    f"{ticker} isn't in any watchlist yet. Add it first "
                    f"(button on the left) — alarms are configured per "
                    f"watchlist."
                )
            else:
                st.caption(
                    f"{ticker} is in {len(containing)} watchlist(s). "
                    f"Configure alarms in the sidebar's «My watchlists» "
                    f"expander. Quick-jump:"
                )
                for w in containing:
                    if st.button(
                        f"↪ Open «{w.name}»  ·  {len(w.alarm_types)} alarm(s)",
                        key=f"scope_alarms_jump_{ticker}_{w.name}",
                        width="stretch",
                    ):
                        # Sidebar expanders aren't directly addressable
                        # by key — best we can do is leave a session-
                        # state hint that the sidebar reads to
                        # auto-expand the right watchlist.
                        st.session_state["sidebar_watchlist_open"] = w.name
                        st.toast(
                            f"Watchlist «{w.name}» opened in sidebar",
                            icon="🔔",
                        )
                        st.rerun()
