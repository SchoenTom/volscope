"""
Per-chart error boundary for the VolScope UI.

Streamlit renders top-down. Without a boundary, a single exception — a bad
DataFrame shape, a DuckDB hiccup, a rogue NaN — blanks the entire page and
leaves the user staring at an empty cockpit. This helper catches the error,
surfaces it in a gentle card, and lets the rest of the page continue rendering.

Usage:

    with error_boundary(st, "IV vs HV chart"):
        st.plotly_chart(create_iv_hv_chart(history, ticker))
"""
from __future__ import annotations

import logging
import traceback
from contextlib import contextmanager
from typing import Any

from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

log = logging.getLogger(__name__)


@contextmanager
def error_boundary(st: Any, label: str, show_traceback: bool = False):
    """Catch any exception inside the block and render a fallback card."""
    try:
        yield
    except Exception as exc:
        log.exception("error_boundary(%s) caught exception", label)
        cls = exc.__class__.__name__
        msg = str(exc) or "no message"
        render_html(
            st,
            f"""
            <div style="background:{COLORS['card']};border:1px solid {COLORS['warn']};border-left:4px solid {COLORS['warn']};border-radius:8px;padding:14px 16px;margin:10px 0;">
              <div style="color:{COLORS['warn']};font-weight:600;font-size:12px;letter-spacing:0.5px;margin-bottom:4px;font-family:'JetBrains Mono',monospace;">
                ⚠ {label} failed
              </div>
              <div style="color:{COLORS['muted']};font-size:11px;font-family:'JetBrains Mono',monospace;">
                {cls}: {msg}
              </div>
            </div>
            """,
        )
        if show_traceback:
            st.code(traceback.format_exc())
