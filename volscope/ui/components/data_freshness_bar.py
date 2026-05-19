"""
Data-freshness bar — prominent, always-visible indicator of how stale
the displayed numbers are, plus a one-click refresh.

Renders as a single horizontal row meant to sit DIRECTLY UNDER each
page's title. Three zones:

    [● fresh · 0d ago · 289 tickers]    [↻ refresh]     last scrape 2026-05-13

Colours encode age:
    ≤ 1 day  → green
    ≤ 7 day  → amber
    > 7 day  → red

The refresh button spawns ``make scrape`` in the background (the same
subprocess pattern already used in ``sidebar.py``), so the page stays
responsive. Subsequent reloads pick up the new data.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import subprocess
from html import escape
from typing import Optional

from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

log = logging.getLogger(__name__)


def _latest_scrape_info(db) -> tuple[Optional[_dt.date], int, int]:
    """Return ``(last_date, n_tickers, n_rows)`` from a single query."""
    try:
        last_date, n_tickers, n_rows = db.con.execute("""
            SELECT MAX(date), COUNT(DISTINCT ticker), COUNT(*) FROM daily_vol
        """).fetchone()
    except Exception as exc:
        log.debug("freshness query failed: %s", exc)
        return None, 0, 0
    if hasattr(last_date, "date") and not isinstance(last_date, _dt.date):
        try:
            last_date = last_date.date()
        except Exception:
            last_date = None
    return last_date, int(n_tickers or 0), int(n_rows or 0)


def _age_color(age_days: Optional[int]) -> tuple[str, str, str]:
    """Pick (label, hex_color, semantic_word) for an age in days."""
    if age_days is None:
        return ("no data", COLORS["warn"], "no scrape on record")
    if age_days <= 1:
        return (f"FRESH · {age_days}d", COLORS["accent"], "data current")
    if age_days <= 7:
        return (f"OK · {age_days}d", COLORS["amber"], "data slightly stale")
    return (f"STALE · {age_days}d", COLORS["warn"], "data is stale — rescrape")


def _start_background_scrape() -> tuple[bool, str]:
    """Kick off ``make scrape`` in a detached process, return (ok, log_path).

    Was hardcoded to /Users/tomschoen/Desktop/VolScope — broken
    since the 2026-05-15 migration to ~/dev/VolScope. Delegates to
    the shared ``make_runner.spawn_make`` helper which derives the
    repo root from __file__.
    """
    from volscope.ui.components.make_runner import spawn_make
    return spawn_make("scrape")


def render_data_freshness_bar(db, *, compact: bool = False) -> None:
    """Render the freshness pill + refresh button row.

    ``compact=True`` collapses to a single-line strip (used on
    secondary pages where vertical real-estate is precious).
    """
    import streamlit as st

    last_date, n_tickers, n_rows = _latest_scrape_info(db)
    today = _dt.date.today()
    age = (today - last_date).days if last_date else None
    label, color, hint = _age_color(age)

    last_iso = last_date.isoformat() if last_date else "—"

    # Two compact layouts. The full one uses 3-col grid; compact uses
    # one-line inline pill.
    if compact:
        html = f"""
<div class="vs-fresh-strip">
  <span class="vs-fresh-pill" style="background:{color}1a;border:1px solid {color}55;color:{color};">
    ● {escape(label)}
  </span>
  <span class="vs-fresh-meta">
    {n_tickers} tickers · last {last_iso}
  </span>
</div>"""
        render_html(st, html)
        return

    # Full layout — three cells.
    col_pill, col_btn, col_meta = st.columns([2, 1, 4])
    with col_pill:
        render_html(
            st,
            f'<span class="vs-fresh-pill" '
            f'style="background:{color}1a;border:1px solid {color}55;color:{color};">'
            f'● {escape(label)}</span>',
        )
    with col_btn:
        # The button can't carry its own spinner-icon easily — when
        # clicked we fire a background scrape and surface a toast.
        if st.button(
            "↻ Refresh data",
            key="vs_fresh_refresh",
            help=(f"Run `make scrape` in the background (~{max(2, n_tickers * 0.025):.0f}-{max(5, n_tickers * 0.06):.0f} min). "
                  "Reload this page when the toast says complete."),
            width='stretch',
        ):
            ok, info = _start_background_scrape()
            if ok:
                # Streamlit ≥1.32 rejects icon characters whose Unicode
                # ``Emoji_Presentation`` property is "No" (e.g. ``✓``).
                # ``✅`` (U+2705) is unambiguously emoji-presentation.
                st.toast(
                    f"Scrape started · {n_tickers} tickers · log {os.path.basename(info)}",
                    icon="✅",
                )
            else:
                st.error(f"Couldn't start scrape: {info}")
    with col_meta:
        render_html(
            st,
            f'<div class="vs-fresh-meta-full">'
            f'<span class="vs-fresh-meta-k">last scrape</span>'
            f'<span class="vs-fresh-meta-v">{last_iso}</span>'
            f'<span class="vs-fresh-sep">·</span>'
            f'<span class="vs-fresh-meta-k">tickers</span>'
            f'<span class="vs-fresh-meta-v">{n_tickers}</span>'
            f'<span class="vs-fresh-sep">·</span>'
            f'<span class="vs-fresh-meta-k">rows</span>'
            f'<span class="vs-fresh-meta-v">{n_rows:,}</span>'
            f'<span class="vs-fresh-sep">·</span>'
            f'<span class="vs-fresh-hint">{escape(hint)}</span>'
            f'</div>',
        )


__all__ = ["render_data_freshness_bar"]
