"""Single Source of Truth for VolScope's cross-page UI state.

This module is an **additive wrapper** around `st.session_state`. It
does NOT replace the existing per-page session_state usage — every
key the legacy pages read/write continues to work. The store exposes
a typed accessor API for NEW code paths and centralises the
contract for `selected_ticker`, `active_page`, navigation history,
and URL deep-linking.

Hard rule (master plan §13.2): every write performed by this module
also lands in the same `st.session_state[<key>]` slot that legacy
pages already read. Old code paths continue to see the new value.

Why additive: 16 pages reference `st.session_state["selected_ticker"]`
directly. A full migration would have a 16-file blast radius and
high regression risk; an additive wrapper has zero. The wrapper
gives new code path autocomplete + typed access without forcing a
migration.

Usage::

    from volscope.ui.state import get_state, set_ticker
    state = get_state()
    print(state.selected_ticker)            # reads st.session_state
    set_ticker("PYPL", source="Discover")   # writes both legacy + history
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

import streamlit as st

log = logging.getLogger(__name__)

# Max page-history entries kept in session_state to bound memory.
_MAX_HISTORY: int = 20

# Ticker validation — Yahoo allows letters, digits, dot, caret, dash.
# Length cap protects against pathological URL-param injection.
_TICKER_RE = re.compile(r"^[A-Z0-9.\^\-]{1,16}$")

# Known page names (subset of app._PAGE_REGISTRY) — used for URL
# param validation. Avoids hard-importing _PAGE_REGISTRY to keep this
# module dependency-light.
_KNOWN_PAGE_PREFIXES = (
    "Discover", "Heatmap", "Scope", "Vol Insights", "Pre-Trade",
    "Options Lab", "LEAPS Lab", "Bot", "Portfolio", "Alerts",
    "Command", "Backtest", "Research", "Earnings Hub",
    "Earnings Trades", "Scanner", "Mega-Scan", "Signals", "Rotation",
    "Flow", "Builder", "Dossier", "Help", "Onboarding",
)


@dataclass
class AppState:
    """Typed view over the cross-page slice of st.session_state."""
    selected_ticker:   Optional[str]  = None
    active_page:       str            = "Discover"
    last_nav_source:   Optional[str]  = None
    page_history:      list[dict]     = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _read_session_key(key: str, default):
    try:
        return st.session_state.get(key, default)
    except Exception:                                              # noqa: BLE001
        return default


def get_state() -> AppState:
    """Return a typed snapshot of the cross-page state.

    Reads ARE always live — the AppState mirrors session_state at
    call time. Writes via set_ticker / push_history update both this
    typed view AND the underlying session_state.
    """
    return AppState(
        selected_ticker=_read_session_key("selected_ticker", None),
        active_page=_read_session_key("active_page", "Discover"),
        last_nav_source=_read_session_key("nav_source", None),
        page_history=_read_session_key("page_history", []) or [],
    )


def _validate_ticker(raw: object) -> Optional[str]:
    """Return uppercased ticker if it matches _TICKER_RE; else None."""
    if not raw:
        return None
    s = str(raw).strip().upper()
    if not s:
        return None
    if not _TICKER_RE.match(s):
        return None
    return s


def _validate_page(raw: object) -> Optional[str]:
    """Return page name if it's a known registry entry; else None."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if any(s.startswith(p) for p in _KNOWN_PAGE_PREFIXES):
        return s
    return None


def set_ticker(ticker: str, source: Optional[str] = None) -> Optional[str]:
    """Set the canonical selected_ticker and log a history entry.

    Validates the ticker (regex + length). Returns the value that
    was set (uppercased, validated) or None if validation failed.

    Hard rule: ALWAYS writes the legacy `st.session_state["selected_ticker"]`
    key so old pages immediately see the new value on next rerun.
    """
    valid = _validate_ticker(ticker)
    if valid is None:
        return None
    try:
        st.session_state["selected_ticker"] = valid
        if source:
            st.session_state["nav_source"] = source
    except Exception as exc:                                       # noqa: BLE001
        log.warning("set_ticker(%s) failed: %s", valid, exc)
        return None
    push_history(
        page=_read_session_key("active_page", "Discover"),
        ticker=valid,
        source=source,
    )
    return valid


def push_history(
    *, page: Optional[str] = None, ticker: Optional[str] = None,
    source: Optional[str] = None,
) -> None:
    """Append an entry to the page-history ring buffer."""
    if not page and not ticker:
        return
    try:
        hist = list(_read_session_key("page_history", []) or [])
        hist.append({
            "page":   page,
            "ticker": ticker,
            "source": source,
            "ts":     _now_iso(),
        })
        if len(hist) > _MAX_HISTORY:
            hist = hist[-_MAX_HISTORY:]
        st.session_state["page_history"] = hist
    except Exception as exc:                                       # noqa: BLE001
        log.debug("push_history failed: %s", exc)


def hydrate_from_url() -> None:
    """Re-apply URL query params whenever they CHANGE.

    Earlier this was one-shot per session — a deep-link like
    /?page=Scope&ticker=PYPL was ignored on every subsequent visit
    because the guard flag stayed True. That broke shareable links
    (the operator pastes a Scope URL but lands on Command) and made
    Playwright audits unable to deep-link.

    New policy: hydrate when (page, ticker) in URL differs from what
    we last hydrated. User interactions write through
    ``sync_to_url`` so this stays consistent with click-driven nav.
    """
    try:
        params = st.query_params
        url_page = params.get("page") if "page" in params else None
        url_ticker = params.get("ticker") if "ticker" in params else None
        url_source = params.get("source") if "source" in params else None

        last = st.session_state.get("_appstate_last_url", (None, None))
        if (url_page, url_ticker) == last and st.session_state.get("_appstate_hydrated"):
            return

        if url_ticker:
            t = _validate_ticker(url_ticker)
            if t:
                st.session_state["selected_ticker"] = t
        if url_page:
            p = _validate_page(url_page)
            if p:
                st.session_state["active_page"] = p
        if url_source:
            st.session_state["nav_source"] = str(url_source)[:32]

        st.session_state["_appstate_last_url"] = (url_page, url_ticker)
        st.session_state["_appstate_hydrated"] = True
    except Exception as exc:                                       # noqa: BLE001
        log.debug("hydrate_from_url failed: %s", exc)


def sync_to_url() -> None:
    """Write current selected_ticker + active_page back to URL params.

    Called by `nav_to()` after navigation so the URL bar reflects
    the new view. Idempotent + best-effort: failures don't raise.
    """
    try:
        state = get_state()
        params: dict[str, str] = {}
        if state.selected_ticker:
            params["ticker"] = state.selected_ticker
        if state.active_page:
            params["page"] = state.active_page
        if state.last_nav_source:
            params["source"] = state.last_nav_source[:32]
        if params:
            st.query_params.update(params)
    except Exception as exc:                                       # noqa: BLE001
        log.debug("sync_to_url failed: %s", exc)
