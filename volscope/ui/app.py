"""VolScope Streamlit app entry point.

Run with: streamlit run volscope/ui/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

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
    "Portfolio":  ("volscope.ui.views.portfolio_page",      "render_portfolio_page"),
    "Mega-Scan":  ("volscope.ui.views.megascan_page",       "render_megascan_page"),
    "Discover":   ("volscope.ui.views.discover_page",       "render_discover_page"),
    "Alerts":     ("volscope.ui.views.alerts_page",         "render_alerts_page"),
    "Signals":    ("volscope.ui.views.signals_page",        "render_signals_page"),
    "Bot":        ("volscope.ui.views.bot_dashboard_page",  "render_bot_dashboard_page"),
    "Earnings Hub":("volscope.ui.views.earnings_hub_page",  "render_earnings_hub_page"),
    "Earnings Trades":("volscope.ui.views.earnings_positions_page", "render_earnings_positions_page"),
    "Scope":      ("volscope.ui.views.scope_page",          "render_scope_page"),
    "Scanner":    ("volscope.ui.views.scan_page",           "render_scan_page"),
    "Heatmap":    ("volscope.ui.views.heatmap_page",        "render_heatmap_page"),
    "Rotation":   ("volscope.ui.views.rotation_page",       "render_rotation_page"),
    "Flow":       ("volscope.ui.views.flow_page",           "render_flow_page"),
    "Pre-Trade":  ("volscope.ui.views.pretrade_page",       "render_pretrade_page"),
    "Builder":    ("volscope.ui.views.strategy_builder_page","render_strategy_builder_page"),
    "Options Lab":("volscope.ui.views.options_lab_page",    "render_options_lab_page"),
    "Vol Insights":("volscope.ui.views.vol_insights_page",  "render_vol_insights_page"),
    "LEAPS Lab":  ("volscope.ui.views.leaps_page",          "render_leaps_page"),
    "Dossier":    ("volscope.ui.views.leaps_dossier_page",  "render_leaps_dossier_page"),
    "Backtest":   ("volscope.ui.views.backtest_page",       "render_backtest_page"),
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


@st.cache_resource
def get_db() -> VolScopeDB:
    """
    Open the VolScope DB, tolerating transient lock collisions.

    v0.9.8 — prefer WRITABLE (was read-only). The earlier
    read-only-first policy made paper-trader, watchlist, and
    personal-cash writes all crash with InvalidInputException —
    the operator hit "Paper-buy failed", "Portfolio render
    failed", and "watchlist section missing" in the same session
    (2026-05-16). Fall back to read-only only if writable open
    fails persistently (e.g. live bot scheduler holds the
    exclusive lock).
    """
    import time
    from pathlib import Path

    from volscope.config import DB_PATH

    db_exists = Path(DB_PATH).exists()
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            return VolScopeDB()
        except Exception as exc:  # duckdb.IOException subclasses Exception
            last_exc = exc
            time.sleep(0.3 * (attempt + 1))

    # All writable attempts failed → bot scheduler likely holds the
    # lock. Fall back to read-only so the UI at least renders. Personal
    # writes will fail with a friendly error from the affected feature.
    if db_exists:
        try:
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
        render_html(
            st,
            f"""
            <div style="background:{COLORS['card']};border:1px solid {COLORS['warn']};border-left:4px solid {COLORS['warn']};border-radius:8px;padding:18px 22px;margin-top:12px;">
              <div style="color:{COLORS['warn']};font-weight:600;font-size:13px;letter-spacing:0.5px;margin-bottom:8px;font-family:'JetBrains Mono',monospace;">
                ⚠ Database unavailable
              </div>
              <div style="color:{COLORS['muted']};font-size:12px;font-family:'JetBrains Mono',monospace;line-height:1.6;">
                <strong>{exc.__class__.__name__}</strong>: {str(exc) or 'no message'}<br><br>
                <span style="color:{COLORS['text']};">Path:</span> {DB_PATH}<br><br>
                Most common cause: another VolScope process (a running
                <code>make scrape</code> or a second Streamlit tab) is
                holding a write lock. Stop it and reload this page.
              </div>
            </div>
            """,
        )
        return

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

    # Default landing — Command Center if data exists, else Discover.
    if "active_page" not in st.session_state:
        try:
            empty_db = db.get_all_latest().empty
        except Exception:
            empty_db = False
        st.session_state["active_page"] = "Discover" if empty_db else "Command"

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
