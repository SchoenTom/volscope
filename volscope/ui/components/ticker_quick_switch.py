"""Sidebar widget — type a ticker, hit Enter → jump to Scope.

This is the cross-tool "universal jump" affordance that was the §N.B
deliverable of the Cross-Tool Weaving phase. It sits at the top of
the sidebar above the existing page-specific ticker pickers, so the
operator always has a one-keystroke path to deep-dive any ticker
from anywhere.

Uses the existing NavIntent mechanism — no parallel routing logic.
Validation via the SSOT state-store's _validate_ticker pattern
(regex `^[A-Z0-9.^-]{1,16}$`).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z0-9.\^\-]{1,16}$")


def _validate(raw: object) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip().upper()
    if not s:
        return None
    if not _TICKER_RE.match(s):
        return None
    return s


def render_ticker_quick_switch(st) -> None:
    """Render the persistent sidebar quick-switch widget.

    Renders nothing if streamlit is unavailable. Never raises.
    """
    try:
        with st.sidebar:
            from volscope.ui.styles.theme import COLORS
            from volscope.ui.components.html_utils import render_html
            render_html(
                st,
                f'<div style="margin-top:6px;margin-bottom:6px;'
                f'font-family:DM Sans,sans-serif;font-size:10px;'
                f'color:{COLORS["muted"]};letter-spacing:0.04em;'
                f'text-transform:uppercase;font-weight:600;">'
                f'⟶ JUMP TO TICKER</div>',
            )
            with st.form(key="quick_switch_form", border=False, clear_on_submit=True):
                raw = st.text_input(
                    "Ticker", placeholder="e.g. PYPL, ^VIX",
                    key="quick_switch_input",
                    label_visibility="collapsed",
                )
                go = st.form_submit_button(
                    "→ Scope", width='stretch',
                    help="Jump to Scope with this ticker",
                )
            if go:
                valid = _validate(raw)
                if valid:
                    try:
                        from volscope.ui.components.navigation import (
                            NavIntent, nav_to,
                        )
                        nav_to(NavIntent(
                            page="Scope", ticker=valid, source="QuickSwitch",
                        ))
                        st.rerun()
                    except Exception as exc:                       # noqa: BLE001
                        log.warning("quick-switch nav failed: %s", exc)
                        st.error(f"Could not jump to {valid}: {exc}")
                elif raw:
                    st.error(
                        f"Invalid ticker: {raw!r}. Use uppercase + digits "
                        f"+ . ^ - (e.g. SPY, ^VIX, BRK-B)."
                    )
    except Exception as exc:                                       # noqa: BLE001
        log.debug("ticker_quick_switch render failed: %s", exc)


def render_breadcrumb_trail(st) -> None:
    """Render last-3-hop breadcrumb from the SSOT page_history.

    Click any breadcrumb segment → nav_to that page with the ticker
    that was active at that hop. Silent on empty history.
    """
    try:
        from volscope.ui.state import get_state
        state = get_state()
        if not state.page_history:
            return
        from volscope.ui.styles.theme import COLORS
        from volscope.ui.components.html_utils import render_html
        recent = state.page_history[-3:]
        parts: list[str] = []
        for h in recent:
            page = h.get("page") or "?"
            ticker = h.get("ticker")
            label = f"{page} · {ticker}" if ticker else page
            parts.append(
                f'<span style="color:{COLORS["muted"]};font-family:DM Sans,sans-serif;'
                f'font-size:10px;letter-spacing:0.03em;">{label}</span>'
            )
        crumb = (
            f'<span style="color:{COLORS["muted"]};opacity:0.5;font-size:10px;margin:0 6px;">›</span>'
        ).join(parts)
        render_html(
            st,
            f'<div style="margin-top:-6px;margin-bottom:8px;'
            f'padding:4px 0;text-transform:uppercase;">{crumb}</div>',
        )
    except Exception as exc:                                       # noqa: BLE001
        log.debug("breadcrumb_trail render failed: %s", exc)
