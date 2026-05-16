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
        f'STEP {step} OF 5'
        f'</div>'
        f'</div>',
    )

    if step == 1:
        _render_welcome(st)
    elif step == 2:
        _render_pack_picker(st)
    elif step == 3:
        _render_loading(st, db)
    elif step == 4:
        _render_first_ticker_preview(st, db)
    else:
        _render_first_watchlist(st, db)


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
                             type="primary", width='stretch'):
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
                             width='stretch'):
            st_module.session_state["onboarding_step"] = 1
            st_module.rerun()
    with cols[2]:
        if st_module.button("Load pack →", key="ob_step2_next",
                             type="primary", width='stretch'):
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
        "Continue → preview your first ticker",
        key="ob_step3_continue",
        type="primary",
        width='stretch',
    ):
        st_module.session_state["onboarding_step"] = 4
        st_module.rerun()


# ── Step 4: First-ticker preview ───────────────────────────────────────

def _render_first_ticker_preview(st_module, db: VolScopeDB) -> None:
    """Live IV-Rank / Vol Regime card for a ticker the user picks.

    Master plan §3 Stream E: bridge from "data is loaded" to "I know
    what to do with it". The newbie picks one ticker → sees IV-Rank,
    IV-Percentile, current regime, and a one-sentence read of what
    that regime means for short-vol vs long-vol trades.
    """
    render_html(
        st_module,
        f'<div style="max-width:720px;margin:0 auto;font-family:{_MONO};'
        f'color:{COLORS["text"]};">'
        f'<div style="color:{COLORS["accent"]};font-size:13px;font-weight:700;'
        f'letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px;">'
        f'YOUR FIRST TICKER'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};font-size:12px;margin-bottom:18px;'
        f'line-height:1.6;">'
        f'Pick any ticker from your starter pack. We will show its current '
        f'IV-Rank (where today\'s implied vol sits in the last 52 weeks) '
        f'and Vol Regime — the two numbers you check before any trade.'
        f'</div></div>',
    )

    try:
        available = db.get_available_tickers() or []
    except Exception:
        available = []
    if not available:
        st_module.warning("No tickers loaded yet. Go back to step 3.")
        if st_module.button("← Back to load", key="ob_step4_back"):
            st_module.session_state["onboarding_step"] = 3
            st_module.rerun()
        return

    default_idx = 0
    for try_default in ("SPY", "AAPL", "NVDA"):
        if try_default in available:
            default_idx = available.index(try_default)
            break

    pick = st_module.selectbox(
        "Ticker", available, index=default_idx, key="ob_step4_ticker",
        label_visibility="collapsed",
    )

    # Show live KPI snapshot
    try:
        hist = db.get_ticker_history(pick)
        if hist is not None and not hist.empty:
            latest = hist.iloc[-1]
            iv_rank = latest.get("iv_rank")
            iv_pct = latest.get("iv_percentile")
            regime = latest.get("vol_regime") or "—"
            spot = latest.get("spot_price")

            def _band_color(v):
                if v is None:
                    return COLORS["muted"]
                try:
                    v = float(v)
                except Exception:
                    return COLORS["muted"]
                if v < 30: return COLORS["accent"]
                if v > 70: return COLORS["warn"]
                return COLORS["amber"]

            ivr_color = _band_color(iv_rank)
            ivp_color = _band_color(iv_pct)
            regime_read = {
                "CRUSHED":  "Vol is crushed. Long-premium setups have edge.",
                "CHEAP":    "Vol is cheap. Long calendars / long straddles favoured.",
                "FAIR":     "Vol is fair. No edge from vol alone — pick the direction.",
                "RICH":     "Vol is rich. Short-premium setups (credit spreads) favoured.",
                "EXTREME":  "Vol is extreme. Iron condors / short strangles — high reward but watch for crisis.",
                "CRISIS":   "Vol is in crisis mode. Sit out OR small-size long puts.",
            }.get(str(regime).upper(), "Pick a ticker with at least 30 days of history for a regime read.")

            render_html(
                st_module,
                f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
                f'border-left:3px solid {ivr_color};border-radius:8px;padding:16px 20px;'
                f'margin:14px 0;font-family:{_MONO};">'
                f'<div style="font-size:16px;font-weight:700;color:{COLORS["text"]};margin-bottom:10px;">'
                f'{pick} {f"· ${spot:.2f}" if spot else ""}</div>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;font-size:13px;">'
                f'<div><span style="color:{COLORS["muted"]};font-size:11px;">IV Rank</span><br>'
                f'<b style="color:{ivr_color};font-size:18px;">{iv_rank:.0f}</b></div>'
                f'<div><span style="color:{COLORS["muted"]};font-size:11px;">IV Percentile</span><br>'
                f'<b style="color:{ivp_color};font-size:18px;">{iv_pct:.0f}</b></div>'
                f'<div><span style="color:{COLORS["muted"]};font-size:11px;">Vol Regime</span><br>'
                f'<b style="color:{ivr_color};font-size:14px;">{regime}</b></div>'
                f'</div>'
                f'<div style="font-size:11px;color:{COLORS["muted"]};margin-top:14px;line-height:1.5;">'
                f'{regime_read}'
                f'</div></div>',
            )
        else:
            st_module.info(f"No history for {pick} yet. Pick another or rerun step 3.")
    except Exception as exc:
        st_module.warning(f"Could not load {pick}: {exc}")

    cols = st_module.columns([1, 2, 1])
    with cols[0]:
        if st_module.button("← Back", key="ob_step4_back2", width='stretch'):
            st_module.session_state["onboarding_step"] = 3
            st_module.rerun()
    with cols[2]:
        if st_module.button("Continue →", key="ob_step4_next",
                             type="primary", width='stretch'):
            st_module.session_state["onboarding_step"] = 5
            # Pre-populate the watchlist starter with this ticker
            st_module.session_state["onboarding_first_ticker"] = pick
            st_module.rerun()


# ── Step 5: First watchlist ────────────────────────────────────────────

def _render_first_watchlist(st_module, db: VolScopeDB) -> None:
    """Create a watchlist + add 3 tickers. Wires the user into the
    regime-alarm system right at first-touch (master plan §3 Stream E).
    """
    render_html(
        st_module,
        f'<div style="max-width:720px;margin:0 auto;font-family:{_MONO};'
        f'color:{COLORS["text"]};">'
        f'<div style="color:{COLORS["accent"]};font-size:13px;font-weight:700;'
        f'letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px;">'
        f'YOUR FIRST WATCHLIST'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};font-size:12px;margin-bottom:18px;'
        f'line-height:1.6;">'
        f'Watchlists track tickers you care about, and (optionally) ping you '
        f'when their vol regime changes — entering CHEAP for long-vol entries, '
        f'or RICH for short-premium opportunities. Pick 3-5 to start; you can '
        f'always edit from the sidebar.'
        f'</div></div>',
    )

    try:
        available = db.get_available_tickers() or []
    except Exception:
        available = []

    first = st_module.session_state.get("onboarding_first_ticker", "")
    default_picks = [first] if first in available else []
    if len(default_picks) < 3:
        for t in ("SPY", "NVDA", "AAPL", "QQQ", "TSLA"):
            if t in available and t not in default_picks:
                default_picks.append(t)
            if len(default_picks) >= 3:
                break

    picks = st_module.multiselect(
        "Tickers (3-10 recommended)",
        available,
        default=default_picks[:5],
        key="ob_step5_picks",
    )
    name = st_module.text_input(
        "Watchlist name",
        value="My first watchlist",
        key="ob_step5_name",
    )
    alarms_on = st_module.checkbox(
        "🔔 Send Telegram + desktop ping on regime change "
        "(needs TELEGRAM__BOT_TOKEN in .env for Telegram)",
        value=True, key="ob_step5_alarms",
    )

    cols = st_module.columns([1, 2, 1])
    with cols[0]:
        if st_module.button("← Back", key="ob_step5_back", width='stretch'):
            st_module.session_state["onboarding_step"] = 4
            st_module.rerun()
    with cols[2]:
        if st_module.button(
            "Finish & open Command →", key="ob_step5_finish",
            type="primary", width='stretch',
        ):
            try:
                from volscope.persistence.watchlists import (
                    add_ticker_to_watchlist, create_watchlist,
                )
                if name and picks:
                    create_watchlist(db, name, regime_alarms=bool(alarms_on))
                    for t in picks:
                        add_ticker_to_watchlist(db, name, t)
            except Exception as exc:
                st_module.warning(f"Watchlist persist failed (continuing): {exc}")

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
