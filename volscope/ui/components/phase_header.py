"""4-phase orientation strip — "where you are in the workflow".

Every page renders a single 24px strip near the top that visualises
the user's position in VolScope's four-phase workflow:

    ① SCAN  →  ② INVESTIGATE  →  ③ STRUCTURE  →  ④ EXECUTE

The current phase is highlighted; clicking another phase navigates
to that phase's default page. Optionally shows the selected ticker.

Strict additive: never replaces existing page chrome. If the helper
fails (registry miss, navigation broken) it logs and renders
nothing — pages keep working.

Wired in by calling:
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name="Scope", ticker=ticker)
"""
from __future__ import annotations

import logging
from typing import Optional

from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

log = logging.getLogger(__name__)

# ── Phase model ────────────────────────────────────────────────────
# Each phase has a numeric label, an icon, a human title, and a
# default landing page. The mapping from page → phase is authoritative
# here; consumers should never hard-code it elsewhere.

PHASES: list[dict] = [
    {"num": "①", "key": "SCAN",        "title": "Scan",        "default_page": "Discover"},
    {"num": "②", "key": "INVESTIGATE", "title": "Investigate", "default_page": "Scope"},
    {"num": "③", "key": "STRUCTURE",   "title": "Structure",   "default_page": "Pre-Trade"},
    {"num": "④", "key": "EXECUTE",     "title": "Execute",     "default_page": "Options Lab"},
]

# Page → phase mapping. Every sidebar entry in app._PAGE_REGISTRY
# should appear in EXACTLY one bucket. Pages not listed get no
# phase highlight (degrade gracefully).
PAGE_TO_PHASE: dict[str, str] = {
    # ① SCAN — find candidates
    "Discover":         "SCAN",
    "Heatmap":          "SCAN",
    "Rotation":         "SCAN",
    "Flow":             "SCAN",
    "Mega-Scan":        "SCAN",
    "Earnings Hub":     "SCAN",
    "Earnings Trades":  "SCAN",
    "Scanner":          "SCAN",
    "Signals":          "SCAN",

    # ② INVESTIGATE — understand the candidate
    "Scope":            "INVESTIGATE",
    "Vol Insights":     "INVESTIGATE",
    "Research":         "INVESTIGATE",

    # ③ STRUCTURE — build the trade
    "Pre-Trade":        "STRUCTURE",
    "Builder":          "STRUCTURE",
    "Options Lab":      "STRUCTURE",

    # ④ EXECUTE — ship + monitor
    "LEAPS Lab":        "EXECUTE",
    "Dossier":          "EXECUTE",
    "Backtest":         "EXECUTE",
    "Bot":              "EXECUTE",
    "Portfolio":        "EXECUTE",
    "Alerts":           "EXECUTE",
    "Command":          "EXECUTE",

    # Reference / meta (no phase)
    "Help":             "",
    "Onboarding":       "",
}


def render_phase_header(
    st, *, page_name: str, ticker: Optional[str] = None,
) -> None:
    """Render the 4-phase strip at the top of a page. Always safe.

    Parameters
    ----------
    st : streamlit module
    page_name : the page key as registered in ``app._PAGE_REGISTRY``
    ticker : optional ticker to show as a context badge
    """
    try:
        active_phase = PAGE_TO_PHASE.get(page_name, "")
    except Exception:
        active_phase = ""

    # Build the row HTML. Each phase = small pill; active = brighter
    # background; inactive = muted with hover-accent. Separator "→"
    # between phases. Ticker badge right-aligned if provided.

    pill_html_parts: list[str] = []
    for i, p in enumerate(PHASES):
        is_active = (p["key"] == active_phase)
        bg = rgba_inline(COLORS["accent"], 0.18) if is_active else "transparent"
        bd = COLORS["accent"] if is_active else COLORS["border"]
        col = COLORS["accent"] if is_active else COLORS["muted"]
        weight = "700" if is_active else "500"
        pill_html_parts.append(
            f'<a href="?phase_jump={p["default_page"]}" '
            f'style="text-decoration:none;display:inline-flex;align-items:center;'
            f'gap:6px;background:{bg};border:1px solid {bd};border-radius:14px;'
            f'padding:4px 12px;font-family:\'DM Sans\',sans-serif;font-size:11px;'
            f'color:{col};font-weight:{weight};letter-spacing:0.03em;'
            f'cursor:pointer;transition:all 0.15s;">'
            f'<span>{p["num"]}</span><span>{p["title"]}</span></a>'
        )
        if i < len(PHASES) - 1:
            pill_html_parts.append(
                f'<span style="color:{COLORS["muted"]};opacity:0.4;'
                f'font-size:11px;margin:0 4px;">→</span>'
            )

    pills = "".join(pill_html_parts)

    ticker_badge = ""
    if ticker:
        ticker_badge = (
            f'<span style="margin-left:auto;background:{COLORS["surface"]};'
            f'border:1px solid {COLORS["border"]};border-radius:4px;padding:3px 10px;'
            f'font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:600;'
            f'color:{COLORS["text"]};letter-spacing:0.04em;'
            f'font-variant-numeric:tabular-nums;">'
            f'● {ticker}</span>'
        )

    render_html(
        st,
        f'<div style="display:flex;align-items:center;gap:0;margin:0 0 12px 0;'
        f'padding:6px 0;border-bottom:1px solid {COLORS["border"]};">'
        f'{pills}'
        f'{ticker_badge}'
        f'</div>',
    )


def rgba_inline(hex_or_rgba: str, alpha: float) -> str:
    """Inline rgba() to avoid importing from theme.py for one call.

    Accepts a 6-char hex (#RRGGBB) or any valid CSS color string.
    For non-hex strings, returns them unchanged (CSS-valid passthrough).
    """
    s = (hex_or_rgba or "").strip()
    if s.startswith("#") and len(s) == 7:
        try:
            r = int(s[1:3], 16)
            g = int(s[3:5], 16)
            b = int(s[5:7], 16)
            return f"rgba({r},{g},{b},{alpha})"
        except ValueError:
            return s
    return s
