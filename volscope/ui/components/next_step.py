"""Next-step footer — the cross-page weave.

Every page renders ONE call to ``render_next_step_footer`` at the
bottom of its main content. The footer shows 2-3 right-aligned
buttons that pre-populate the target page's ticker context (re-uses
the existing ``NavIntent`` mechanism — see
``volscope.ui.components.navigation``).

Mapping per page is declared once in ``NEXT_STEPS`` below. The
mapping IS the cross-page navigation graph from master plan §4.

Strict rules (master plan §13.2 + §13.6):
  - Re-uses NavIntent verbatim — no parallel routing
  - Never renders the user's CURRENT page in its own footer
  - Skips destinations that require a ticker if no ticker is set
  - Silent fallback: unknown page → no footer (page still works)

Usage::

    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(st, page="Scope", ticker=ticker)
"""
from __future__ import annotations

import logging
from typing import Optional

from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

log = logging.getLogger(__name__)


# ── Next-step graph ────────────────────────────────────────────────
# Each entry: (target_page, label_template, ticker_required)
# label_template may contain {ticker} which is substituted at render
# time. ticker_required=True means the entry is hidden when no
# ticker is selected.

# Every (source -> target) target MUST be a page in app._PAGE_REGISTRY
# (enforced by tests/test_next_step.py). Trimmed in the IV-research
# refocus: all trade-execution / bot / backtest destinations were removed.
NEXT_STEPS: dict[str, list[tuple[str, str, bool]]] = {
    # ① SCAN — find candidates
    "Discover": [
        ("Scope",        "Deep-dive {ticker}",                  True),
        ("Mega-Scan",    "Deeper multi-strategy scan",          False),
        ("Vol Insights", "Asymmetric EM + OI map",              True),
    ],
    "Heatmap": [
        ("Scope",        "Deep-dive selected ticker",           True),
        ("Discover",     "Filter by sector / IV rank",          False),
        ("Rotation",     "Rotate sectors by vol regime",        False),
    ],
    "Rotation": [
        ("Flow",         "Today's sector flow",                 False),
        ("Scope",        "Drill into the leading ticker",       True),
    ],
    "Flow": [
        ("Rotation",     "Sector trajectory over time",         False),
        ("Scope",        "Drill into the leading ticker",       True),
    ],
    "Mega-Scan": [
        ("Scope",        "Deep-dive a hit",                     True),
        ("Discover",     "Back to the main scan",               False),
    ],
    "Earnings Hub": [
        ("Vol Insights", "Event-premium decomposition",         True),
        ("Scope",        "Deep-dive the name",                  True),
    ],
    "Scanner": [
        ("Scope",        "Deep-dive a hit",                     True),
        ("Heatmap",      "Visualise the universe",              False),
    ],

    # ② INVESTIGATE — understand the candidate
    "Scope": [
        ("Vol Insights", "Skew + OI for {ticker}",              True),
        ("Options Lab",  "Price a trade on {ticker}",           True),
        ("Heatmap",      "See it against the universe",         False),
    ],
    "Vol Insights": [
        ("Options Lab",  "Price the EM ladder",                 True),
        ("Scope",        "Back to single-ticker view",          True),
        ("Earnings Hub", "Event-premium context",               False),
    ],
    "Research": [
        ("Scope",        "Re-test on another ticker",           True),
        ("Discover",     "Find new candidates",                 False),
    ],

    # ③ STRUCTURE — price the trade (no execution)
    "Options Lab": [
        ("Scope",        "Back to the IV verdict",              True),
        ("Vol Insights", "Skew + expected move",                True),
    ],

    # ④ MANAGE
    "Alerts": [
        ("Command",      "Alerts management",                   False),
        ("Scope",        "Deep-dive a ticker",                  True),
    ],
    "Command": [
        ("Alerts",       "Alert rules",                         False),
        ("Scope",        "Deep-dive a ticker",                  True),
    ],
    "Watchlist": [
        ("Scope",        "Deep-dive {ticker}",                  True),
        ("Discover",     "Find new candidates",                 False),
    ],
}


def render_next_step_footer(
    st, *, page: str, ticker: Optional[str] = None,
) -> None:
    """Render the bottom-of-page next-step footer. Always safe."""
    try:
        from volscope.ui.components.navigation import NavIntent, nav_to
    except Exception:                                              # noqa: BLE001
        log.debug("navigation module unavailable — skipping footer")
        return

    options = NEXT_STEPS.get(page, [])
    if not options:
        return

    # Filter destinations that need a ticker we don't have
    filtered: list[tuple[str, str, bool]] = []
    for target, label, needs_t in options:
        if needs_t and not ticker:
            continue
        # Never link to the current page
        if target == page:
            continue
        filtered.append((target, label, needs_t))
    if not filtered:
        return

    render_html(
        st,
        f'<div style="margin:24px 0 8px 0;padding-top:14px;'
        f'border-top:1px solid {COLORS["border"]};">'
        f'<div style="font-family:\'DM Sans\',sans-serif;font-size:11px;'
        f'color:{COLORS["muted"]};letter-spacing:0.04em;'
        f'text-transform:uppercase;margin-bottom:8px;">→ Next step</div>'
        f'</div>',
    )

    cols = st.columns(min(len(filtered), 3))
    for i, (target, label_tpl, _needs_t) in enumerate(filtered[:3]):
        with cols[i]:
            label = label_tpl.format(ticker=ticker) if ticker else label_tpl
            if st.button(
                f"→ {target}",
                key=f"next_step_{page}_{target}",
                width='stretch',
                help=label,
            ):
                nav_to(NavIntent(page=target, ticker=ticker, source=page))
                st.rerun()
