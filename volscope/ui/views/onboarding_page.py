"""
Onboarding wizard — first-run experience.

Three steps:
  1. Welcome — orient the trader to the four core questions VolScope
     answers ("buy or wait", "where is vol cheapest", "what's the trade",
     "how big should it be").
  2. Pick starter pack — 8 / 50 / full universe.
  3. Loading — live progress feed via universe_loader; auto-routes to
     Command Center on completion.

Triggered automatically by ``app.py`` when:
  - DB has no daily_vol rows OR
  - user_settings["onboarding_complete"] is missing/False

Once complete, the flag is persisted to ``user_settings`` so the wizard
never reappears for that user.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from volscope.data.database import VolScopeDB
from volscope.data.ticker_universe import all_tickers
from volscope.data.universe_loader import (
    TickerOutcome,
    load_universe,
    persist_report,
)
from volscope.ui.components.html_utils import render_html
from volscope.ui.components.navigation import NavIntent, nav_to
from volscope.ui.styles.theme import COLORS

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"

# Starter packs — sized for a useful Command Center within ~30s vs ~10min.
_STARTER_PACKS: dict[str, list[str]] = {
    "Quick start (8 tickers)": [
        "SPY", "QQQ", "AAPL", "NVDA", "TSLA", "META", "GLD", "TLT",
    ],
    "Hedge-fund book (50 tickers)": None,   # populated dynamically
    "Full universe (568 tickers)": None,
}


def render_onboarding_page(db: VolScopeDB, settings: dict) -> None:
    """Top-level onboarding wizard."""
    step = st.session_state.setdefault("onboarding_step", 1)

    render_html(
        st,
        f'<div style="text-align:center;margin-top:30px;margin-bottom:30px;">'
        f'<div style="font-family:{_MONO};font-size:32px;font-weight:700;'
        f'color:{COLORS["accent"]};letter-spacing:0.05em;">'
        f'◈ VolScope'
        f'</div>'
        f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};'
        f'margin-top:6px;letter-spacing:0.5px;">'
        f'volatility intelligence for serious option traders'
        f'</div>'
        f'<div style="font-family:{_MONO};font-size:9px;color:{COLORS["label"]};'
        f'margin-top:14px;letter-spacing:1.5px;">'
        f'STEP {step} OF 3'
        f'</div>'
        f'</div>',
    )

    if step == 1:
        _render_welcome(st)
    elif step == 2:
        _render_pack_picker(st)
    else:
        _render_loading(st, db)


# ── Step 1: Welcome ───────────────────────────────────────────────────

def _render_welcome(st_module) -> None:
    """Orient the trader to the four core questions VolScope answers."""
    render_html(
        st_module,
        f'<div style="max-width:720px;margin:0 auto;background:{COLORS["card"]};'
        f'border:1px solid {COLORS["border"]};border-radius:12px;padding:28px 32px;'
        f'font-family:{_MONO};color:{COLORS["text"]};line-height:1.7;">'
        f'<div style="color:{COLORS["accent"]};font-size:13px;font-weight:700;'
        f'letter-spacing:1.5px;text-transform:uppercase;margin-bottom:16px;">'
        f'WELCOME'
        f'</div>'
        f'<div style="font-size:13px;margin-bottom:16px;">'
        f'VolScope answers four questions a serious vol trader has every morning:'
        f'</div>'
        f'<div style="font-size:12px;color:{COLORS["muted"]};margin-left:8px;">'
        f'<div style="margin-bottom:8px;">'
        f'<span style="color:{COLORS["accent"]};">1</span>. '
        f'<span style="color:{COLORS["text"]};font-weight:600;">'
        f'Where is vol cheap right now?</span>'
        f'</div>'
        f'<div style="margin-bottom:8px;">'
        f'<span style="color:{COLORS["accent"]};">2</span>. '
        f'<span style="color:{COLORS["text"]};font-weight:600;">'
        f'Should I buy or wait?</span> (Edge Score · ML signal · IV percentile)'
        f'</div>'
        f'<div style="margin-bottom:8px;">'
        f'<span style="color:{COLORS["accent"]};">3</span>. '
        f'<span style="color:{COLORS["text"]};font-weight:600;">'
        f'What\'s the optimal structure?</span> (Strategy Recommender + backtest hit-rates)'
        f'</div>'
        f'<div style="margin-bottom:0;">'
        f'<span style="color:{COLORS["accent"]};">4</span>. '
        f'<span style="color:{COLORS["text"]};font-weight:600;">'
        f'How big should I size it?</span> (Kelly fractional · vega P&amp;L)'
        f'</div>'
        f'</div>'
        f'<div style="font-size:11px;color:{COLORS["muted"]};margin-top:20px;">'
        f'You\'ll start with a curated ticker universe; you can extend it later '
        f'via the sidebar. All data comes from yfinance + FRED — free, daily.'
        f'</div>'
        f'</div>',
    )

    cols = st_module.columns([3, 1, 1])
    with cols[2]:
        if st_module.button("Continue →", key="ob_step1_next",
                             type="primary", use_container_width=True):
            st_module.session_state["onboarding_step"] = 2
            st_module.rerun()


# ── Step 2: Pack picker ───────────────────────────────────────────────

def _render_pack_picker(st_module) -> None:
    """Pick starter pack."""
    universe = all_tickers()
    # Build the 50-ticker pack from the curated list (first 50 alphabetically
    # after deduping the quick-start 8 to keep it well-rounded).
    quick = set(_STARTER_PACKS["Quick start (8 tickers)"])
    fifty = sorted(set(universe) - quick)[:50]
    _STARTER_PACKS["Hedge-fund book (50 tickers)"] = fifty
    _STARTER_PACKS["Full universe (568 tickers)"] = universe

    render_html(
        st_module,
        f'<div style="max-width:720px;margin:0 auto;font-family:{_MONO};'
        f'color:{COLORS["text"]};">'
        f'<div style="color:{COLORS["accent"]};font-size:13px;font-weight:700;'
        f'letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px;">'
        f'CHOOSE YOUR STARTER PACK'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};font-size:12px;margin-bottom:18px;'
        f'line-height:1.6;">'
        f'Smaller packs load faster (~30 seconds for 8 tickers, ~5 minutes '
        f'for 50, ~30+ minutes for the full universe). You can always extend '
        f'later from the sidebar.'
        f'</div>'
        f'</div>',
    )

    pack = st_module.radio(
        "Pack",
        list(_STARTER_PACKS.keys()),
        index=0,
        label_visibility="collapsed",
    )
    st_module.session_state["onboarding_pack"] = pack

    cols = st_module.columns([1, 2, 1])
    with cols[0]:
        if st_module.button("← Back", key="ob_step2_back",
                             use_container_width=True):
            st_module.session_state["onboarding_step"] = 1
            st_module.rerun()
    with cols[2]:
        if st_module.button("Load pack →", key="ob_step2_next",
                             type="primary", use_container_width=True):
            st_module.session_state["onboarding_step"] = 3
            st_module.rerun()


# ── Step 3: Loading ────────────────────────────────────────────────────

def _render_loading(st_module, db: VolScopeDB) -> None:
    """Stream the loader output, then auto-finish."""
    pack = st_module.session_state.get("onboarding_pack", "Quick start (8 tickers)")
    target_tickers = _STARTER_PACKS.get(pack) or _STARTER_PACKS["Quick start (8 tickers)"]

    render_html(
        st_module,
        f'<div style="max-width:720px;margin:0 auto;font-family:{_MONO};'
        f'color:{COLORS["text"]};">'
        f'<div style="color:{COLORS["accent"]};font-size:13px;font-weight:700;'
        f'letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px;">'
        f'LOADING — {pack}'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};font-size:11px;margin-bottom:14px;">'
        f'Fetching 2y of OHLCV per ticker. Failures are logged and you can '
        f'resume them later via <code>make load-universe-resume</code>.'
        f'</div>'
        f'</div>',
    )

    # Already-loaded short-circuit: if onboarding_completed flag exists, skip
    if st_module.session_state.get("onboarding_loading_done"):
        st_module.success("Loading complete!")
        if st_module.button("Open Command Center →", key="ob_step3_finish",
                             type="primary"):
            try:
                db.set_user_setting("onboarding_complete", "true")
            except Exception:
                pass
            st_module.session_state["onboarding_complete"] = True
            nav_to(NavIntent(page="Command", source="Onboarding"))
            st_module.rerun()
        return

    progress = st_module.progress(0.0, text="Starting…")
    counters = {"loaded": 0, "skipped": 0, "failed": 0}

    def _cb(outcome: TickerOutcome, idx: int, total: int) -> None:
        if outcome.status in ("loaded", "retried"):
            counters["loaded"] += 1
        elif outcome.status == "skipped":
            counters["skipped"] += 1
        else:
            counters["failed"] += 1
        progress.progress(
            idx / max(1, total),
            text=(f"{outcome.status:<8} {outcome.ticker:<12} ({idx}/{total}) — "
                  f"loaded={counters['loaded']} · failed={counters['failed']}"),
        )

    report = load_universe(db, tickers=target_tickers, progress_callback=_cb)
    persist_report(report)
    progress.empty()

    if report.n_failed == 0:
        st_module.success(
            f"✓ Loaded {report.n_loaded} tickers · "
            f"coverage {report.coverage_pct():.0f}% · "
            f"elapsed {report.elapsed_s:.0f}s"
        )
    else:
        st_module.warning(
            f"Loaded {report.n_loaded} · failed {report.n_failed}. "
            f"Run `make load-universe-resume` to retry — failures logged "
            f"to data/load/."
        )

    st_module.session_state["onboarding_loading_done"] = True
    if st_module.button(
        "Open Command Center →",
        key="ob_step3_open",
        type="primary",
        use_container_width=True,
    ):
        try:
            db.set_user_setting("onboarding_complete", "true")
        except Exception:
            pass
        st_module.session_state["onboarding_complete"] = True
        nav_to(NavIntent(page="Command", source="Onboarding"))
        st_module.rerun()


# ── Route gate (called by app.py) ──────────────────────────────────────

def should_show_onboarding(db: VolScopeDB) -> bool:
    """Return True when the wizard should intercept normal nav."""
    # Already explicitly completed?
    try:
        if db.get_user_setting("onboarding_complete") == "true":
            return False
    except Exception:
        pass
    # Or DB simply has data already (returning user)
    try:
        if db.get_available_tickers():
            return False
    except Exception:
        pass
    return True
