"""
HTML rendering helper — aggressively defensive against Streamlit's markdown
code-block trap.

Streamlit runs any `st.markdown(body, unsafe_allow_html=True)` body through a
markdown parser FIRST. The parser treats any line with 4+ leading spaces as
an indented code block, which escapes the HTML and shows the tags as literal
monospace source. This is the exact bug that had the Discover page rendering
`<div class="volscope-card ...">` instead of actual cards.

`textwrap.dedent()` alone is NOT enough: it only removes the common minimum
leading whitespace. If a nested template has lines at 8, 10, 12, 14 spaces of
indent, dedent removes 8 and leaves 0, 2, 4, 6 — and the 4-space and 6-space
lines still trip the code-block rule.

This helper guarantees the render by `lstrip`ing *every* line, so no line
ever has leading whitespace regardless of the source template's indentation.
HTML is whitespace-insensitive (outside <pre> blocks), so we lose nothing.
"""
from __future__ import annotations

from typing import Any


def render_html(st: Any, body: str) -> None:
    """Render an HTML body via Streamlit, safe against accidental indentation.

    Every line is left-stripped of whitespace before being joined and passed
    to `st.markdown(..., unsafe_allow_html=True)`. Blank lines are preserved
    for visual separation in the rendered DOM.
    """
    cleaned = "\n".join(line.lstrip() for line in body.splitlines()).strip()
    st.markdown(cleaned, unsafe_allow_html=True)


# ── LEAPS-Lab redesign primitives (2026-05-10) ───────────────────────────
# Reusable HTML snippets for the convergence dial, the KPI grid, the
# score-bar group, and the section rule. Pages compose pages out of these
# rather than re-inventing identical markup. CSS lives in
# ``volscope/ui/styles/theme.py`` (`.volscope-dial`, `.volscope-kpi-*`,
# `.volscope-bar-*`, `.volscope-section-rule`).


def convergence_dial_html(score: float, color: str, caption: str = "CONVERG.") -> str:
    """Render the 72-px conic-gradient dial.

    Score is clamped to 0..100 because conic-gradient with values outside
    that range silently renders garbage. ``color`` is a CSS hex/rgba —
    the dial fill *and* the centre digit get it.
    """
    pct = max(0.0, min(100.0, float(score)))
    return (
        f'<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">'
        f'<div class="volscope-dial" style="--dial-pct:{pct};--dial-color:{color};">'
        f'<div class="volscope-dial-value">{score:.0f}</div>'
        f'</div>'
        f'<div class="volscope-dial-caption">{caption}</div>'
        f'</div>'
    )


def section_rule_html(label: str, sub: str = "") -> str:
    """One-line section divider — replaces the heavier ``_section_header``."""
    sub_html = (
        f'<span class="volscope-section-rule-sub">{sub}</span>'
        if sub else ""
    )
    return (
        f'<div class="volscope-section-rule">'
        f'<span class="volscope-section-rule-label">── {label}</span>'
        f'{sub_html}'
        f'</div>'
    )


def kpi_grid_html(
    items: list[tuple[str, str, str | None]],
    variant: str = "detail",
) -> str:
    """Render a KPI strip in one of two variants.

    Each item is ``(label, value, color_or_none)``. The colour applies to
    the value text only; pass ``None`` to inherit the default text colour.

    Variants:
      "detail" — 5 columns, restrained 22-px values (Greeks, sub-stats).
      "hero"   — 3 columns, 34-px hero values (headline KPIs).
    """
    cls = (
        "volscope-kpi-grid-hero" if variant == "hero"
        else "volscope-kpi-grid-detail"
    )
    cells = []
    for label, value, color in items:
        style = f'style="color:{color};"' if color else ""
        cells.append(
            f'<div class="volscope-kpi-cell">'
            f'<div class="volscope-kpi-label">{label}</div>'
            f'<div class="volscope-kpi-value" {style}>{value}</div>'
            f'</div>'
        )
    return f'<div class="{cls}">{"".join(cells)}</div>'


def kpi_value_with_est_html(value: str, color: str | None = None) -> str:
    """Format a single value with a quiet ``est`` superscript marker.

    Replaces the heavier per-card amber chip with an Apple-style 11-px
    sup. Use this when the EST scope is *one* number (e.g. a single
    premium cell), not a whole section.
    """
    style = f'style="color:{color};"' if color else ""
    return f'<span {style}>{value}<sup class="volscope-est-sup">est</sup></span>'


def empty_state_html(
    headline: str,
    body: str,
    cta_label: str | None = None,
    cta_id: str | None = None,
) -> str:
    """Apple-style empty state — declarative, not technical.

    The CTA is rendered as a plain anchor; wire the click via Streamlit
    on the page (this helper deliberately stays presentation-only).
    """
    cta_html = ""
    if cta_label and cta_id:
        cta_html = (
            f'<div style="margin-top:24px;"><a href="#{cta_id}" '
            f'class="volscope-cta">{cta_label}</a></div>'
        )
    return (
        f'<div class="volscope-empty-state">'
        f'<div class="volscope-empty-headline">{headline}</div>'
        f'<div class="volscope-empty-body">{body}</div>'
        f'{cta_html}'
        f'</div>'
    )


def score_bar_html(label: str, value: float | None) -> str:
    """One score-bar row — quieter than a coloured pill, groups visually."""
    if value is None:
        return (
            f'<div class="volscope-bar">'
            f'<span class="volscope-bar-key">{label}</span>'
            f'<span class="volscope-bar-value" style="color:#5a5e6e;">—</span>'
            f'<span class="volscope-bar-track"><span class="volscope-bar-fill" '
            f'style="width:0%;"></span></span>'
            f'</div>'
        )
    pct = max(0.0, min(100.0, float(value)))
    fill_class = (
        "volscope-bar-fill-strong" if pct >= 70
        else "volscope-bar-fill-mid" if pct >= 40
        else "volscope-bar-fill-weak"
    )
    return (
        f'<div class="volscope-bar">'
        f'<span class="volscope-bar-key">{label}</span>'
        f'<span class="volscope-bar-value">{pct:.0f}</span>'
        f'<span class="volscope-bar-track">'
        f'<span class="volscope-bar-fill {fill_class}" style="width:{pct:.0f}%;">'
        f'</span></span>'
        f'</div>'
    )


def score_bar_group_html(items: list[tuple[str, float | None]]) -> str:
    bars = "".join(score_bar_html(k, v) for k, v in items)
    return f'<div class="volscope-bar-group">{bars}</div>'


def est_underline_html(text: str = "est · BSM model price") -> str:
    """Single-line dotted-underline est marker — placed under whole sections."""
    return f'<div class="volscope-est-underline">{text}</div>'


def page_banner_html(
    *,
    title: str,
    what: str,
    when: str,
    learn_more: str | None = None,
) -> str:
    """Per-page orientation banner — title + what + when in two lines.

    Mounted at the top of high-traffic pages so a fresh operator
    understands purpose and timing without reading the docs. Kept under
    64 px tall so it doesn't dominate small screens.

    Use sparingly: only on pages where orientation pays for the vertical
    cost (Command Center, Discover, Signals, Bot, Scope, Earnings,
    LEAPS, Pre-Trade).
    """
    from volscope.ui.styles.theme import COLORS

    learn_html = ""
    if learn_more:
        learn_html = (
            f'<span style="color:{COLORS["muted"]};font-size:11px;'
            f'margin-left:8px;">· {learn_more}</span>'
        )
    return (
        f'<div style="background:{COLORS["card"]};'
        f'border:1px solid {COLORS["border"]};'
        f'border-left:3px solid {COLORS["accent"]};'
        f'border-radius:6px;padding:10px 14px;margin-bottom:14px;'
        f'font-family:\'DM Sans\',sans-serif;">'
        f'<div style="color:{COLORS["text"]};font-size:13px;'
        f'font-weight:600;letter-spacing:0.01em;">{title}</div>'
        f'<div style="color:{COLORS["muted"]};font-size:12px;'
        f'margin-top:3px;line-height:1.45;">'
        f'<span>{what}</span>'
        f'<span style="color:{COLORS["border"]};margin:0 6px;">·</span>'
        f'<span>{when}</span>'
        f'{learn_html}'
        f'</div>'
        f'</div>'
    )
