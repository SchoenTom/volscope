"""
Page Vol Insights — Skew-adjusted Expected Move, Front/Back IV
decomposition, and OI Heatmap.

WHY this page exists: differentiating features (asymmetric EM,
event-premium extraction, max-pain OI map) that no free retail
platform packages cleanly. The conversation captured by the
operator on 2026-05-15 identified these four cards as the
"echter Differenzierungs-Feature" stack.

WHEN to use it: pre-earnings sizing, event-week long-vol vs
short-vol selection, identifying max-pain pull strikes for
weekly short-premium spreads.

WHAT it depends on:
  - volscope.analytics.expected_move_skew
  - volscope.analytics.front_back_iv
  - volscope.analytics.oi_heatmap
  - volscope.data.chain_scraper.fetch_chain (live yfinance chain)
"""
from __future__ import annotations

from datetime import date as _date
from typing import Optional

import pandas as pd
import streamlit as st

from volscope.ui.components.html_utils import render_html
from volscope.ui.components.pretrade_skew_em import (
    render_front_back_block, render_oi_heatmap_block, render_skew_em_block,
)
from volscope.ui.styles.theme import COLORS


@st.cache_data(ttl=300, show_spinner=False)
def _cached_chain_fetch(ticker: str, max_expiries: int = 6) -> pd.DataFrame:
    """5-minute-cached live chain fetch via yfinance.

    Wraps volscope.data.chain_scraper.fetch_chain — bounded to
    ``max_expiries`` to keep first-paint under ~10s. Returns an
    empty DataFrame on failure (network / 429 / delisted).
    """
    try:
        from volscope.data.chain_scraper import fetch_chain
        rows = fetch_chain(ticker, max_expiries=max_expiries)
        if not rows:
            return pd.DataFrame()
        records = []
        for r in rows:
            records.append({
                "ticker":         r.ticker,
                "expiry":         r.expiry,
                "strike":         r.strike,
                "option_right":   r.option_right,
                "iv":             r.iv,
                "delta":          getattr(r, "delta", None),
                "open_interest":  getattr(r, "open_interest", None) or 0,
                "bid":            getattr(r, "bid", None),
                "ask":            getattr(r, "ask", None),
                "mid":            getattr(r, "mid", None),
            })
        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()


def render_vol_insights_page(db, settings: dict | None = None) -> None:
    """Top-level page entry."""
    st.markdown("## ⚡ Vol Insights")
    st.caption(
        "Skew-adjusted Expected Move · Front/Back IV decomposition · "
        "OI Heatmap. Differentiating analytics not packaged by free retail "
        "platforms. Live chain via yfinance — first paint after fetch ~5-10s."
    )

    # Ticker + DTE controls
    ticker_default = st.session_state.get("selected_ticker", "SPY")
    col1, col2, col3, _ = st.columns([2, 2, 2, 4])
    with col1:
        ticker = st.text_input(
            "Ticker", value=ticker_default, key="vol_insights_ticker",
        ).strip().upper()
    with col2:
        dte_target = st.number_input(
            "Target DTE", min_value=1, max_value=365, value=30, step=1,
            key="vol_insights_dte",
        )
    with col3:
        max_expiries = st.number_input(
            "Expiries to scan", min_value=3, max_value=20, value=6, step=1,
            key="vol_insights_max_expiries",
            help="Front + back + a few middle for term-structure work. More = slower.",
        )

    if not ticker:
        st.info("Enter a ticker to fetch its chain.")
        return

    with st.spinner(f"Fetching {ticker} chain (≤ {max_expiries} expiries)…", show_time=False):
        chain = _cached_chain_fetch(ticker, max_expiries=int(max_expiries))

    if chain.empty:
        render_html(
            st,
            f'<div style="background:{COLORS["surface"]};border:1px solid {COLORS["warn"]};'
            f'border-left:3px solid {COLORS["warn"]};border-radius:6px;padding:12px 16px;'
            f'margin:12px 0;color:{COLORS["muted"]};font-family:DM Sans,sans-serif;font-size:12px;">'
            f'No chain data for <b>{ticker}</b>. Yahoo returned empty — ticker may '
            f'have no listed options, be delisted, or yfinance is rate-limited. '
            f'Try again in 60s or pick a more liquid US name.'
            f'</div>',
        )
        return

    # Snapshot spot from underlying history (DB)
    try:
        hist = db.get_ticker_history(ticker)
        spot = float(hist["spot_price"].dropna().iloc[-1]) if not hist.empty else None
    except Exception:
        spot = None
    if not spot or spot <= 0:
        # Try chain mid as proxy — calls + puts cross at spot
        from volscope.analytics.expected_move import compute_max_pain
        spot_est = chain.loc[chain["strike"].sub(chain["strike"].mean()).abs().idxmin(), "strike"]
        spot = float(spot_est)

    # Pick front expiry (closest DTE ≥ 1) and back expiry (≥ 60 days)
    today = _date.today()
    chain["expiry"] = pd.to_datetime(chain["expiry"]).dt.date
    chain["dte"] = chain["expiry"].apply(lambda d: (d - today).days)
    chain = chain[chain["dte"] >= 1]
    if chain.empty:
        st.info("No future expiries in scrape window.")
        return

    front_exp = chain.loc[chain["dte"].idxmin(), "expiry"]
    front_dte = int(chain.loc[chain["dte"].idxmin(), "dte"])
    far_mask = chain["dte"] >= 60
    if far_mask.any():
        back_idx = chain.loc[far_mask, "dte"].idxmin()
        back_exp = chain.loc[back_idx, "expiry"]
        back_dte = int(chain.loc[back_idx, "dte"])
    else:
        back_idx = chain["dte"].idxmax()
        back_exp = chain.loc[back_idx, "expiry"]
        back_dte = int(chain.loc[back_idx, "dte"])

    # Target-DTE expiry — for the asymmetric EM card
    chain["dte_gap"] = (chain["dte"] - int(dte_target)).abs()
    target_idx = chain["dte_gap"].idxmin()
    target_exp = chain.loc[target_idx, "expiry"]
    target_dte = int(chain.loc[target_idx, "dte"])
    target_chain = chain[chain["expiry"] == target_exp].copy()

    # ── 1. Skew-adjusted Expected Move ───────────────────────────────
    render_skew_em_block(st, ticker, target_chain, spot=spot, dte_days=target_dte)

    # ── 2. Front/Back IV decomposition ──────────────────────────────
    def _atm_iv(slice_df: pd.DataFrame) -> Optional[float]:
        slice_df = slice_df.copy()
        slice_df["dist"] = (slice_df["strike"] - spot).abs()
        atm = slice_df.sort_values("dist").head(4)["iv"].dropna()
        atm = atm[atm > 0]
        return float(atm.mean()) if not atm.empty else None

    front_chain = chain[chain["expiry"] == front_exp]
    back_chain  = chain[chain["expiry"] == back_exp]
    front_atm = _atm_iv(front_chain)
    back_atm  = _atm_iv(back_chain)
    render_front_back_block(
        st, ticker,
        front_iv=front_atm, front_dte=front_dte,
        back_iv=back_atm, back_dte=back_dte,
    )

    # ── 3. OI Heatmap (target expiry) ───────────────────────────────
    render_oi_heatmap_block(st, ticker, target_chain, spot=spot)
