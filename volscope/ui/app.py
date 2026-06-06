"""VolScope Streamlit app entry point.

Run with: streamlit run volscope/ui/app.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Anaconda-Python compatibility shim (MUST RUN BEFORE pandas) ──
# Anaconda's Python 3.13 produces a `sys.version` string with two
# `| ... |` segments that CPython's `platform._sys_version` regex
# can't parse, raising ValueError at pandas import. Streamlit
# imports pandas indirectly during its own startup, BEFORE this
# app.py runs `from volscope...`, so the shim in volscope/__init__.py
# fires too late. Normalising here fixes it for the whole process.
# Operator 2026-05-19: '.venv/bin/python3 → /opt/anaconda3/bin/python3'
# triggered this — every Streamlit page rendered an InvalidInput
# exception.
if "Anaconda" in sys.version and sys.version.count("|") >= 2:
    _parts = sys.version.split("|")
    if len(_parts) >= 3:
        try:
            sys.version = _parts[0].strip() + " " + " ".join(
                p.strip() for p in _parts[2:]
            )
        except Exception:  # noqa: BLE001
            pass

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import importlib  # noqa: E402
import logging  # noqa: E402

import streamlit as st  # noqa: E402

from volscope.config import DB_PATH, DEFAULT_TICKER  # noqa: E402
from volscope.data.database import VolScopeDB  # noqa: E402
from volscope.ui.components.keyboard_shortcuts import inject_keyboard_shortcuts  # noqa: E402
from volscope.ui.components.sidebar import render_sidebar  # noqa: E402
from volscope.ui.components.html_utils import render_html  # noqa: E402
from volscope.ui.styles.theme import COLORS, inject_theme  # noqa: E402
from volscope.utils.timing import instrument  # noqa: E402

log = logging.getLogger(__name__)


# Page registry — lazy imports. The page module is loaded only when the
# user navigates to that page. This prevents one slow / broken page from
# blocking the whole app at startup (iCloud sync, missing optional dep,
# transient import timeout).
_PAGE_REGISTRY: dict[str, tuple[str, str]] = {
    "Onboarding": ("volscope.ui.views.onboarding_page",     "render_onboarding_page"),
    "Command":    ("volscope.ui.views.command_center_page", "render_command_center_page"),
    "Watchlist":  ("volscope.ui.views.watchlist_page",      "render_watchlist_page"),
    "Mega-Scan":  ("volscope.ui.views.megascan_page",       "render_megascan_page"),
    "Discover":   ("volscope.ui.views.discover_page",       "render_discover_page"),
    "Alerts":     ("volscope.ui.views.alerts_page",         "render_alerts_page"),
    "Earnings Hub":("volscope.ui.views.earnings_hub_page",  "render_earnings_hub_page"),
    "Scope":      ("volscope.ui.views.scope_page",          "render_scope_page"),
    "Scanner":    ("volscope.ui.views.scan_page",           "render_scan_page"),
    "Heatmap":    ("volscope.ui.views.heatmap_page",        "render_heatmap_page"),
    "Rotation":   ("volscope.ui.views.rotation_page",       "render_rotation_page"),
    "Flow":       ("volscope.ui.views.flow_page",           "render_flow_page"),
    "Options Lab":("volscope.ui.views.options_lab_page",    "render_options_lab_page"),
    "Vol Insights":("volscope.ui.views.vol_insights_page",  "render_vol_insights_page"),
    # v0.9.0 — Research page: 4-test statistical gauntlet.
    "Research":   ("volscope.ui.views.research_page",       "render_research_page"),
    "Help":       ("volscope.ui.views.help_page",           "render_help_page"),
}


def _load_renderer(page: str):
    """Lazy-import the page renderer; cached at module level after first call."""
    cache = _load_renderer.__dict__.setdefault("_cache", {})
    if page in cache:
        return cache[page]
    module_name, fn_name = _PAGE_REGISTRY[page]
    module = importlib.import_module(module_name)
    fn = getattr(module, fn_name)
    cache[page] = fn
    return fn


def _render_page_safely(page: str, db: "VolScopeDB", settings: dict) -> None:
    """Render a page with error isolation.

    Three failure modes are handled with friendly UX rather than crashes:
      1. Import-time failure (slow filesystem, iCloud sync, missing dep)
      2. Render-time exception
      3. Unknown page (defensive default)
    """
    try:
        renderer = _load_renderer(page)
    except Exception as exc:  # noqa: BLE001
        log.exception("page %s import failed", page)
        _render_import_error(page, exc)
        return

    # Page-specific signature handling: Scope takes ticker, others take db+settings.
    # Wrap with instrumentation so dev panel can show per-page timings.
    perf_name = f"page.{page.lower().replace('-', '_').replace(' ', '_')}"
    try:
        with instrument(perf_name, {"page": page}):
            if page == "Scope":
                renderer(db, st.session_state.get("selected_ticker", DEFAULT_TICKER), settings)
            else:
                renderer(db, settings)
    except Exception as exc:  # noqa: BLE001
        log.exception("page %s render failed", page)
        _render_runtime_error(page, exc)


def _render_import_error(page: str, exc: Exception) -> None:
    err_class = exc.__class__.__name__
    msg = str(exc) or "no message"
    render_html(
        st,
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["warn"]};'
        f'border-left:4px solid {COLORS["warn"]};border-radius:8px;padding:18px 22px;'
        f'margin-top:12px;font-family:JetBrains Mono,monospace;">'
        f'<div style="color:{COLORS["warn"]};font-weight:600;font-size:13px;'
        f'margin-bottom:8px;">⚠ {page} unavailable — import failed</div>'
        f'<div style="color:{COLORS["muted"]};font-size:11px;line-height:1.6;">'
        f'<strong>{err_class}</strong>: {msg}<br><br>'
        f'Other pages are still functional. If the failure was a transient '
        f'iCloud / filesystem timeout, reload the page. If it persists, '
        f'check the terminal log.'
        f'</div></div>',
    )


def _render_runtime_error(page: str, exc: Exception) -> None:
    err_class = exc.__class__.__name__
    msg = str(exc) or "no message"
    render_html(
        st,
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["warn"]};'
        f'border-left:4px solid {COLORS["warn"]};border-radius:8px;padding:18px 22px;'
        f'margin-top:12px;font-family:JetBrains Mono,monospace;">'
        f'<div style="color:{COLORS["warn"]};font-weight:600;font-size:13px;'
        f'margin-bottom:8px;">⚠ {page} render failed</div>'
        f'<div style="color:{COLORS["muted"]};font-size:11px;line-height:1.6;">'
        f'<strong>{err_class}</strong>: {msg}<br><br>'
        f'The page raised an exception during render. Other pages remain '
        f'usable. Reload after the underlying issue is fixed.'
        f'</div></div>',
    )


def _detect_db_writer() -> tuple[bool, str]:
    """Return (writer_active, pid_or_msg) — lightweight lock probe.

    Used by get_db() to decide whether to attempt a writable open or
    immediately go read-only. Avoids the 5-retry × 0.3s backoff loop
    when a long-running scrape clearly holds the lock.
    """
    import subprocess
    from volscope.config import DB_PATH as _DB_PATH
    try:
        rc = subprocess.run(
            ["lsof", "-Fp", str(_DB_PATH)],
            capture_output=True, text=True, timeout=2,
        )
    except Exception:
        return False, ""
    pids = [line[1:] for line in rc.stdout.splitlines()
              if line.startswith("p") and line[1:].isdigit()]
    own_pid = str(os.getpid())
    others = [p for p in pids if p != own_pid]
    return (bool(others), others[0] if others else "")


@st.cache_resource
def get_db() -> "VolScopeDB":
    """Open the VolScope DB, tolerating writer-contention.

    Policy (v0.9.13, hardened after operator hit the "make scrape
    locks Streamlit out" sequence on 2026-05-19):

      1. Probe for a foreign writer via lsof. If one is detected,
         open READ-ONLY immediately and tell the rest of the app
         via st.session_state['vs_db_readonly_reason'].
      2. No foreign writer → try writable (5 attempts × 0.3s).
      3. Writable open fails persistently → fall back to read-only.

    Write paths consult ``vs_db_readonly_reason`` and degrade
    gracefully instead of raising InvalidInputException.
    """
    import time, os
    from pathlib import Path

    from volscope.config import DB_PATH

    writer_active, writer_pid = _detect_db_writer()
    if writer_active:
        st.session_state["vs_db_readonly_reason"] = (
            f"Another VolScope process (PID {writer_pid}) is writing — "
            f"reads work, writes paused until it finishes."
        )
        try:
            return VolScopeDB(read_only=True)
        except Exception:
            pass  # fall through to writable retry

    db_exists = Path(DB_PATH).exists()
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            db = VolScopeDB()
            st.session_state.pop("vs_db_readonly_reason", None)
            return db
        except Exception as exc:
            last_exc = exc
            time.sleep(0.3 * (attempt + 1))

    if db_exists:
        try:
            st.session_state["vs_db_readonly_reason"] = (
                "Database is held by another writer — reads work, "
                "writes paused until the writer finishes."
            )
            return VolScopeDB(read_only=True)
        except Exception as exc2:
            last_exc = exc2
    raise last_exc  # type: ignore[misc]


def main() -> None:
    # v0.9.8 — SSOT state hydration from URL on FIRST boot only.
    # Lets the operator share links like /?ticker=SNOW&page=Scope.
    # Idempotent across reruns so user clicks aren't overridden.
    try:
        from volscope.ui.state import hydrate_from_url
        hydrate_from_url()
    except Exception:                                              # noqa: BLE001
        pass  # hydration is best-effort; legacy keys still work

    # Dynamic page title — picks up the active ticker on rerun so the
    # browser tab reads "VolScope · PYPL" instead of just "VolScope".
    # On first load the session state is empty → fall back to default.
    _active = st.session_state.get("selected_ticker", DEFAULT_TICKER)
    _title = f"VolScope · {_active}" if _active else "VolScope"
    st.set_page_config(
        page_title=_title,
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_theme()
    inject_keyboard_shortcuts()

    if "selected_ticker" not in st.session_state:
        st.session_state["selected_ticker"] = DEFAULT_TICKER

    try:
        db = get_db()
    except Exception as exc:
        log.warning("get_db failed (likely a refresh holding the lock): %s", exc)
        # Calm, user-facing message — no raw exception class or filesystem
        # path. The only realistic cause for an end user is a data refresh
        # briefly holding the database; it clears in seconds.
        render_html(
            st,
            f"""
            <div style="background:{COLORS['card']};border:1px solid {COLORS['amber']};border-left:4px solid {COLORS['amber']};border-radius:8px;padding:20px 24px;margin-top:24px;max-width:560px;">
              <div style="color:{COLORS['amber']};font-weight:700;font-size:15px;margin-bottom:8px;font-family:'DM Sans',sans-serif;">
                VolScope is refreshing its data
              </div>
              <div style="color:{COLORS['text']};font-size:13px;font-family:'DM Sans',sans-serif;line-height:1.6;">
                The market database is busy updating right now — this only
                takes a few seconds. Give it a moment and reload.
              </div>
            </div>
            """,
        )
        if st.button("↻ Reload", type="primary"):
            st.rerun()
        return

    # v0.9.13 — readonly-mode banner. When a foreign writer (the most
    # common: a `make scrape` spawned from our own button) holds the
    # exclusive DB lock, get_db() returns a read-only connection
    # rather than crashing. Surface this state up-front so the
    # operator understands why writes (paper-buy, watchlist add,
    # reset cash, …) fail silently while the scrape runs.
    _ro_reason = st.session_state.get("vs_db_readonly_reason")
    if _ro_reason:
        render_html(
            st,
            f'<div style="background:{COLORS["card"]};border:1px solid '
            f'{COLORS["amber"]};border-left:4px solid {COLORS["amber"]};'
            f'border-radius:6px;padding:10px 14px;margin:8px 0;'
            f'font-family:JetBrains Mono,monospace;font-size:11px;">'
            f'<span style="color:{COLORS["amber"]};font-weight:700;">'
            f'⚑ READ-ONLY MODE</span>'
            f'<span style="color:{COLORS["muted"]};margin-left:10px;">'
            f'{_ro_reason} Reload the page after the scrape '
            f'finishes to resume writes.</span></div>',
        )

    # Onboarding wizard intercept — fresh DB or never-completed flag.
    try:
        from volscope.ui.views.onboarding_page import should_show_onboarding
        in_onboarding_flow = (
            st.session_state.get("onboarding_step") is not None
            and not st.session_state.get("onboarding_complete")
        )
        if in_onboarding_flow or should_show_onboarding(db):
            st.session_state["active_page"] = "Onboarding"
            st.session_state.setdefault("onboarding_step", 1)
    except Exception:
        pass

    # Default landing — Discover is the research entry point. (Was Command
    # Center; switched while Command is being stripped of position tracking
    # in the refocus to IV-research-only.)
    if "active_page" not in st.session_state:
        st.session_state["active_page"] = "Discover"

    with st.sidebar:
        ticker, page, settings = render_sidebar(
            db,
            st.session_state["selected_ticker"],
            st.session_state["active_page"],
        )
    st.session_state["selected_ticker"] = ticker
    st.session_state["active_page"] = page

    # Lazy + isolated: any single page failure no longer kills the app.
    target = page if page in _PAGE_REGISTRY else "Discover"
    _render_page_safely(target, db, settings)

    # Footer — version + commit SHA. Bottom-right, low-emphasis. Lets the
    # operator confirm at a glance which build is running.
    _render_footer()


def _render_footer() -> None:
    """Render the fixed bottom-right version + commit-SHA badge."""
    from volscope import __commit__, __version__
    from volscope.ui.components.html_utils import render_html
    from volscope.ui.styles.theme import COLORS

    html = (
        f'<div style="position:fixed;bottom:6px;right:10px;'
        f'font-family:\'JetBrains Mono\', monospace;font-size:9px;'
        f'color:{COLORS.get("label", "#424666")};opacity:0.55;'
        f'pointer-events:none;z-index:9999;">'
        f'VolScope v{__version__} · {__commit__}'
        f'</div>'
    )
    render_html(st, html)


if __name__ == "__main__":
    main()
