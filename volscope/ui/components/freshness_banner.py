"""
Drop-in freshness banner.

Single-function helper that any page can call at the top of its
render path to surface a colour-coded data-freshness warning. Reads
from :mod:`volscope.data.freshness` so the assessment is consistent
across every page that adopts it.

Why this is separate from ``data_freshness_bar.py``: the existing
bar shows freshness *and* a "Refresh data" button. This helper is
the minimal banner — pure presentation, no controls — for pages
where the operator should know about staleness without offering
a button (because the button-driven refresh is heavyweight and
not desirable on every page).
"""
from __future__ import annotations

from typing import Any

from volscope.data.freshness import (
    FreshnessLevel,
    FreshnessReport,
    assess_freshness,
)


_COLOR_MAP = {
    "green": ("#00d4aa", "rgba(0, 212, 170, 0.06)"),
    "amber": ("#ff9f43", "rgba(255, 159, 67, 0.08)"),
    "red":   ("#ff4466", "rgba(255, 68, 102, 0.10)"),
    "grey":  ("#9aa0b3", "rgba(154, 160, 179, 0.05)"),
}


def _build_banner_html(report: FreshnessReport) -> str:
    border_color, bg_color = _COLOR_MAP.get(
        report.color_hint, _COLOR_MAP["grey"],
    )
    # Icon hints — chosen so they read as semantic at a glance
    # without leaning on Material-Symbol fonts.
    icon = {
        FreshnessLevel.FRESH:      "●",
        FreshnessLevel.RECENT:     "●",
        FreshnessLevel.STALE:      "⚠",
        FreshnessLevel.VERY_STALE: "⚠",
        FreshnessLevel.MISSING:    "○",
    }.get(report.level, "○")

    next_str = ""
    if report.expected_next_update is not None:
        next_str = (
            f' &middot; <span style="color:#9aa0b3;">next scrape due '
            f'{report.expected_next_update.isoformat()}</span>'
        )

    return (
        f'<div style="background:{bg_color};border:1px solid {border_color}55;'
        f'border-left:3px solid {border_color};border-radius:5px;'
        f'padding:6px 12px;margin:4px 0 10px 0;'
        f'font-family:\'DM Sans\',sans-serif;font-size:11px;color:#e0e4ef;">'
        f'<span style="color:{border_color};font-weight:600;'
        f'letter-spacing:0.02em;font-family:JetBrains Mono,monospace;">'
        f'{icon} {report.level.value}</span>'
        f' &nbsp; <span style="color:#c8ccd9;">{report.warning_message}</span>'
        f'{next_str}'
        f'</div>'
    )


def render_freshness_banner(db: Any, *, hide_when_fresh: bool = True) -> None:
    """Render the colour-coded banner for the latest scrape date.

    Parameters
    ----------
    db
        VolScopeDB instance. Read once via ``get_last_scrape_date``.
    hide_when_fresh
        If True (default), don't render anything when the data is
        FRESH — the operator only sees the banner when there's
        something to know about. Pages that want the banner to act
        as a "yes, your data is current" signal can pass False.
    """
    try:
        import streamlit as st
        from volscope.ui.components.html_utils import render_html
    except Exception:                                          # noqa: BLE001
        return

    last_scrape = None
    try:
        last_scrape = db.get_last_scrape_date()
    except Exception:                                          # noqa: BLE001
        last_scrape = None
    report = assess_freshness(last_scrape)

    if hide_when_fresh and report.level == FreshnessLevel.FRESH:
        return

    render_html(st, _build_banner_html(report))
