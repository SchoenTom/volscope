"""
Navigation helper — single canonical cross-page transition primitive.

Before this module, every page implemented its own session_state
mutation pattern for "open this ticker on Pre-Trade". The result was
seven slightly-different patterns and brittle session keys.

This module exposes ONE call:

    nav_to(NavIntent(page="Pre-Trade", ticker="QQQ", source="Discover",
                     payload={"strike": 400}))

…and three thin helpers:

    consume_prefill(page)   — read+clear a page-specific prefill payload
    render_breadcrumb(...)  — render the "◈ {page} · {ticker} ← from {src}"
    is_active(page)         — sugar for st.session_state['active_page'] == page

Design rules
------------
- ``nav_to`` mutates st.session_state and DOES NOT call ``st.rerun()`` —
  callers from inside button handlers trigger rerun implicitly. Avoiding
  rerun here prevents double-rerun pitfalls.
- Prefill payloads are namespaced ``prefill_<page>`` (lowercased,
  spaces→underscores, dashes→underscores). ``consume_prefill`` is the
  read-AND-clear path so payloads never leak to subsequent visits.
- ``render_breadcrumb`` is the only place that surfaces ``nav_source``,
  preventing breadcrumb logic from drifting across pages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class NavIntent:
    """Intent to navigate to a page, optionally with ticker + payload.

    Attributes
    ----------
    page    : Target page name. Must match a key in app.py's _PAGE_REGISTRY.
    ticker  : Optional ticker to set as the new ``selected_ticker``.
    source  : Optional source-page label for the breadcrumb (e.g. "Discover").
    payload : Optional dict written to ``prefill_<page>`` — read-and-cleared
              by the destination page via ``consume_prefill``.
    """
    page:    str
    ticker:  Optional[str] = None
    source:  Optional[str] = None
    payload: Optional[dict] = None


def _prefill_key(page: str) -> str:
    """Canonical session_state key for per-page prefill payloads."""
    return "prefill_" + page.lower().replace(" ", "_").replace("-", "_")


def nav_to(intent: NavIntent) -> None:
    """Mutate session_state to perform the navigation.

    Does NOT call ``st.rerun()`` — the caller is typically inside a
    Streamlit button handler whose return-True path already triggers a
    rerun on the next event loop.

    v0.9.8 — also pushes to the SSOT page_history and (best-effort)
    syncs the URL query params so deep-links / shared URLs reflect
    the new view. Both extensions are silent-fallback safe.
    """
    import streamlit as st

    if intent.ticker is not None:
        st.session_state["selected_ticker"] = intent.ticker
    st.session_state["active_page"] = intent.page
    if intent.source is not None:
        st.session_state["nav_source"] = intent.source
    else:
        # When no source provided, clear stale source so breadcrumb is clean
        st.session_state.pop("nav_source", None)
    if intent.payload is not None:
        st.session_state[_prefill_key(intent.page)] = intent.payload

    # SSOT history + URL sync (best-effort)
    try:
        from volscope.ui.state import push_history, sync_to_url
        push_history(
            page=intent.page,
            ticker=intent.ticker,
            source=intent.source,
        )
        sync_to_url()
    except Exception:                                              # noqa: BLE001
        pass  # nav still works without history; URL bar may be stale

    # Toast feedback so the operator gets a confirmation chip when
    # they cross page boundaries. Streamlit >= 1.27 (we run 1.57).
    if intent.ticker:
        try:
            st.toast(f"→ {intent.page} · {intent.ticker}", icon="🎯")
        except Exception:                                          # noqa: BLE001
            pass  # toast is non-essential, never raise


def consume_prefill(page: str) -> Optional[dict]:
    """Pop and return the prefill payload for a page.

    Returns None when nothing was set. Pages call this once at the top
    of their render to pick up an inbound prefill (e.g. Pre-Trade →
    Portfolio with strike/expiry/option_type pre-populated). After
    this call the payload is gone — no stale prefills on future visits.
    """
    import streamlit as st
    return st.session_state.pop(_prefill_key(page), None)


def is_active(page: str) -> bool:
    """True if the named page is the currently-rendered active page."""
    import streamlit as st
    return st.session_state.get("active_page") == page


def render_breadcrumb(
    st_module,
    page:    str,
    ticker:  Optional[str] = None,
    accent:  Optional[str] = None,
    muted:   Optional[str] = None,
    mono:    str = "JetBrains Mono, SF Mono, Menlo, monospace",
) -> None:
    """Render a small breadcrumb under a page's main header.

    Format::
        ◈ {page} · {ticker} ← from {source}

    The "← from {source}" suffix only appears when ``nav_source`` is
    set in session_state (i.e. the user arrived via ``nav_to`` with a
    source provided). Otherwise the suffix is omitted.

    Colors default to the design-token palette via ``theme.COLORS`` —
    callers should NOT pass hex literals; if they do, the override wins
    (legacy callers, tests).
    """
    import streamlit as st

    from volscope.ui.components.html_utils import render_html
    from volscope.ui.styles.theme import COLORS

    accent = accent or COLORS["accent2"]
    muted  = muted  or COLORS["muted"]
    text   = COLORS["text"]

    parts = [f'<span style="color:{accent};">◈ {page}</span>']
    if ticker:
        parts.append(f'<span style="color:{text};">{ticker}</span>')
    source = st.session_state.get("nav_source")
    if source:
        parts.append(f'<span style="color:{muted};">← from {source}</span>')

    sep = f' <span style="color:{muted};">·</span> '
    render_html(
        st_module,
        f'<div style="font-family:{mono};font-size:10px;letter-spacing:0.5px;'
        f'margin-top:-6px;margin-bottom:10px;">'
        + sep.join(parts) +
        f'</div>',
    )
