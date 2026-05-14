"""
Opt-in per-page auto-refresh.

Streamlit doesn't support push streaming for our data sources (Yahoo
doesn't push), but we can still give the user a one-click "keep this
fresh" toggle that periodically reruns the page. The trader can pin a
page open during market hours and watch metrics update without
clicking around.

Design choices:
  - **Opt-in only.** Default is OFF. Auto-refresh costs CPU (and Yahoo
    rate-limit budget) so we never enable it by default.
  - **Per-page state.** Each page has its own session_state key, so
    enabling auto-refresh on Discover does NOT also enable it on Scope.
    Useful when one page is fine to leave stale (Backtest) and another
    must stay fresh (Command Center).
  - **Sane intervals.** 30s / 60s / 5min options. No 5s — Yahoo will
    rate-limit and the cache TTLs (60s/5min) wouldn't see benefit.
  - **Honest UX.** Shows the next-tick countdown so the user knows
    when the rerun will happen. No surprise reloads mid-edit.

Usage from any page::

    from volscope.ui.components.auto_refresh import auto_refresh_toggle
    auto_refresh_toggle(page_key="discover")

The single call places the toggle + countdown + actual rerun trigger.
Place it near the top of the page, AFTER the breadcrumb but BEFORE any
expensive rendering — that way the rerun happens before the user sees
stale state for long.
"""
from __future__ import annotations

import time
from typing import Final

import streamlit as st

# (label_shown_to_user, seconds)
INTERVAL_OPTIONS: Final[tuple[tuple[str, int], ...]] = (
    ("Off",   0),
    ("30s",   30),
    ("60s",   60),
    ("5min",  300),
)


def _state_keys(page_key: str) -> tuple[str, str]:
    """Return (interval_key, last_tick_key) for the given page."""
    safe = page_key.lower().replace(" ", "_").replace("-", "_")
    return f"_autorefresh_interval_{safe}", f"_autorefresh_last_{safe}"


def auto_refresh_toggle(page_key: str) -> None:
    """Render the opt-in auto-refresh control for the calling page.

    The control:
      - shows a small selectbox (Off / 30s / 60s / 5min)
      - tracks the next-tick wall-clock time in session_state
      - triggers ``st.rerun()`` once the interval has elapsed

    Auto-refresh is per-page, off by default, and persists for the
    duration of the session.
    """
    interval_key, last_tick_key = _state_keys(page_key)
    interval_seconds = st.session_state.get(interval_key, 0)

    cols = st.columns([1, 4])
    with cols[0]:
        labels = [label for label, _ in INTERVAL_OPTIONS]
        seconds_lookup = {label: secs for label, secs in INTERVAL_OPTIONS}
        current_label = next(
            (label for label, secs in INTERVAL_OPTIONS if secs == interval_seconds),
            "Off",
        )
        chosen = st.selectbox(
            "Auto-refresh",
            options=labels,
            index=labels.index(current_label),
            key=f"_autorefresh_select_{page_key}",
            help=(
                "Periodically refresh this page. Off by default. "
                "Choose a longer interval if the page renders slowly."
            ),
        )
        chosen_seconds = seconds_lookup[chosen]
        if chosen_seconds != interval_seconds:
            st.session_state[interval_key] = chosen_seconds
            st.session_state[last_tick_key] = time.time()
            interval_seconds = chosen_seconds

    if interval_seconds <= 0:
        return

    last_tick = st.session_state.get(last_tick_key, time.time())
    now = time.time()
    elapsed = now - last_tick
    remaining = max(0, int(interval_seconds - elapsed))

    with cols[1]:
        st.caption(f"Next refresh in {remaining}s")

    if elapsed >= interval_seconds:
        st.session_state[last_tick_key] = now
        st.rerun()
