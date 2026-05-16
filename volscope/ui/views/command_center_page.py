"""
Command Center — the single-page trading decision hub.

Designed around a specific workflow: you buy DAX Puts, Nasdaq Puts (long
maturities), and knock-out certificates on Xiaomi / SNOW / MSTR.  Before
any of those trades the one question is: "Is vol cheap or expensive right
now, and where is it cheapest across my markets?"

This page answers that on open, without clicking.

Sections
--------
1. YOUR MARKETS  — compact cards for your tracked positions
   · IV 30d, HV 20d, VRP ratio, IV Rank/Perc pill, term-spread label

2. VOL PULSE     — cross-asset vol-index strip
   · VIX · VDAX-New · VXFXI · BVOL-BTC (Deribit)
   · Each: current level, 52w rank, 1w change, regime badge

3. CHARTS        — two-panel row
   · Left:  multi-ticker term structure (contango / backwardation per position)
   · Right: IV/RV ratio bar chart per position (VRP, reference at 1.0)
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st

from volscope.alerts.alert_engine import (
    AlertRule,
    alert_fired_html,
    alert_rule_html,
    dispatch_alert,
    evaluate_rules,
)
from volscope.analytics.earnings_crush import CrushEstimate, compute_crush_estimate, crush_badge_html
from volscope.analytics.edge_score import EdgeScore, compute_edge_table
from volscope.analytics.ml_signal import MLPrediction, ml_badge_html, predict_buy_prob
from volscope.analytics.position_sizing import SizingResult, compute_sizing, sizing_summary_html
from volscope.analytics.signal import VolSignal, compute_signal, market_summary
from volscope.data.database import VolScopeDB
from volscope.data.ticker_resolver import resolve_and_ingest
from volscope.data.vol_index_fetcher import bvol_snapshot, vol_index_snapshot
from volscope.ui.components.chart_builders import (
    create_command_term_structure,
    create_vrp_bar,
)
from volscope.ui.components.html_utils import page_banner_html, render_html
from volscope.ui.components.metric_components import (
    freshness_badge,
    render_percentile_pill,
    render_warning_card,
    vol_signal_badge_html,
)
from volscope.ui.styles.theme import COLORS

log = logging.getLogger(__name__)

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"

# Default tracked positions — the user's actual markets.
DEFAULT_COMMAND_TICKERS: list[str] = ["QQQ", "MSTR", "SNOW", "1810.HK"]

# Vol-pulse index sources: (display_name, yf_symbol_or_list_or_None_for_deribit)
_VOL_PULSE_SOURCES: list[tuple[str, object]] = [
    ("VIX",      "^VIX"),
    ("VDAX-New", ["^VDAX", "VDAX-NEW.DE"]),
    ("VXFXI",    "^VXFXI"),
    ("BVOL-BTC", None),   # fetched from Deribit, symbol is irrelevant
]


# ---------------------------------------------------------------------------
# Cached data loaders — module-level so Streamlit's TTL cache is stable
# across reruns.
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def _prepare_command_data_cached(
    cache_key:       str,
    command_tickers: tuple[str, ...],
    _db,
) -> dict:
    """Bundle all heavy per-ticker analytics into one cached call.

    cache_key is the last-scrape-date so the cache invalidates on
    fresh data. command_tickers is hashable (tuple of strings).
    _db is excluded from the hash via the underscore-prefix convention.
    """
    history_map = _db.get_recent_for_tickers(list(command_tickers), lookback_days=730)
    latest_rows: dict[str, Optional[pd.Series]] = {}
    for t in command_tickers:
        hist = history_map.get(t)
        latest_rows[t] = hist.iloc[-1] if hist is not None and not hist.empty else None

    signals: dict[str, VolSignal] = {}
    for t, row in latest_rows.items():
        if row is not None:
            signals[t] = compute_signal(
                row.get("iv_percentile"),
                row.get("iv_30d"),
                row.get("hv_20d"),
            )
        else:
            signals[t] = compute_signal(None, None, None)

    crush_ests: dict[str, Optional[CrushEstimate]] = {}
    for t in command_tickers:
        try:
            crush_ests[t] = compute_crush_estimate(_db, t)
        except Exception:
            crush_ests[t] = None

    ml_preds: dict[str, Optional[MLPrediction]] = {}
    for t in command_tickers:
        try:
            hist = history_map.get(t)
            ml_preds[t] = predict_buy_prob(t, hist) if hist is not None else None
        except Exception:
            ml_preds[t] = None

    return {
        "history_map": history_map,
        "latest_rows": latest_rows,
        "signals":     signals,
        "crush_ests":  crush_ests,
        "ml_preds":    ml_preds,
    }


@st.cache_data(ttl=300, show_spinner=False)
def _load_vol_pulse() -> list[dict]:
    """Fetch all four vol-index snapshots.  Cached for 5 minutes."""
    snaps: list[dict] = []
    for name, sym in _VOL_PULSE_SOURCES:
        if sym is None:
            snaps.append(bvol_snapshot())
        else:
            snaps.append(vol_index_snapshot(name, sym))  # type: ignore[arg-type]
    return snaps


# ---------------------------------------------------------------------------
# HTML builders — pure functions, no st.* calls, easy to unit-test
# ---------------------------------------------------------------------------

def _edge_score_color(score: float) -> str:
    """Map a 0–100 Edge Score to the cheap/neutral/rich color ramp."""
    if score >= 70:
        return COLORS["accent"]   # green — strong edge
    if score >= 55:
        return COLORS["accent2"]  # blue/cyan — lean edge
    if score >= 40:
        return COLORS["muted"]    # neutral
    return COLORS["warn"]         # rich / no edge


def _edge_row_html(rank: int, edge: EdgeScore) -> str:
    """One ranked row in the Top Edges strip."""
    color = _edge_score_color(edge.score)
    bar_w = max(2, int(edge.score))  # clip to 2% min so the bar is visible

    illiquid_badge = ""
    if edge.illiquid:
        illiquid_badge = (
            f'<span style="background:{COLORS["warn"]}22;color:{COLORS["warn"]};'
            f'padding:1px 6px;border-radius:3px;font-size:9px;margin-left:6px;">illiquid</span>'
        )

    confidence_pct = int(round(edge.confidence * 100))

    return (
        f'<div style="display:grid;grid-template-columns:24px 80px 60px 1fr 80px;'
        f'align-items:center;gap:10px;padding:8px 12px;'
        f'border-bottom:1px solid {COLORS["border"]};font-family:{_MONO};font-size:12px;">'
        # rank
        f'<div style="color:{COLORS["muted"]};font-size:10px;">#{rank}</div>'
        # ticker
        f'<div style="color:{COLORS["text"]};font-weight:700;">{edge.ticker}{illiquid_badge}</div>'
        # score number
        f'<div style="color:{color};font-weight:700;font-size:14px;">{edge.score:.0f}</div>'
        # bar + one-liner
        f'<div>'
        f'<div style="height:6px;background:{COLORS["border"]};border-radius:3px;overflow:hidden;">'
        f'<div style="width:{bar_w}%;height:100%;background:{color};"></div>'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};font-size:10px;margin-top:3px;">{edge.one_liner}</div>'
        f'</div>'
        # confidence
        f'<div style="color:{COLORS["label"]};font-size:9px;text-align:right;">'
        f'conf {confidence_pct}%</div>'
        f'</div>'
    )


def _edges_strip_html(edges: list[EdgeScore], max_rows: int = 5) -> str:
    """Compact ranked strip — top long-vol entry edges across tracked tickers."""
    if not edges:
        return ""

    rows_html = "".join(
        _edge_row_html(i + 1, e) for i, e in enumerate(edges[:max_rows])
    )

    return (
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:8px;padding:0;margin-bottom:18px;overflow:hidden;">'
        # Header
        f'<div style="padding:10px 14px;display:flex;align-items:center;'
        f'justify-content:space-between;border-bottom:1px solid {COLORS["border"]};">'
        f'<div style="font-family:{_MONO};font-size:12px;font-weight:700;'
        f'color:{COLORS["text"]};letter-spacing:1px;">'
        f'<span style="color:{COLORS["accent"]};">◎</span> '
        f'TOP EDGES TODAY · LONG VOL'
        f'</div>'
        f'<div style="font-family:{_MONO};font-size:10px;color:{COLORS["muted"]};">'
        f'composite of perc · VRP · rank · ML'
        f'</div>'
        f'</div>'
        # Rows
        f'{rows_html}'
        f'</div>'
    )


def _market_card_html(
    ticker: str,
    row: Optional[pd.Series],
    signal: Optional[VolSignal] = None,
    crush_est: Optional[CrushEstimate] = None,
    ml_pred: Optional[MLPrediction] = None,
    edge: Optional[EdgeScore] = None,
) -> str:
    """Return the HTML string for one 'Your Markets' card.

    Parameters
    ----------
    ticker : str
        Ticker symbol, used as the card heading.
    row : pd.Series | None
        Latest daily_vol row for this ticker.  None = no data in DB.
    signal : VolSignal | None
        Pre-computed buy/wait/rich signal.  If None, computed from row.
    crush_est : CrushEstimate | None
        Pre-computed earnings crush estimate for the ⚠ ER badge.
    ml_pred : MLPrediction | None
        Pre-computed ML mean-reversion prediction.  None = not enough history.
    edge : EdgeScore | None
        Pre-computed composite edge score; rendered as a prominent
        numeric tile in the top-right of the card.
    """
    if row is None or (isinstance(row, pd.Series) and row.empty):
        return (
            f'<div class="volscope-card">'
            f'<div class="volscope-card-ticker">{ticker}</div>'
            f'<div class="volscope-card-context" style="margin-top:8px;color:{COLORS["muted"]};">'
            f'No data — run <code>make scrape</code> or add via sidebar'
            f'</div></div>'
        )

    def _f(v: object, fmt: str = ".1f", suffix: str = "") -> str:
        if v is None:
            return "—"
        try:
            fv = float(v)  # type: ignore[arg-type]
            if fv != fv:   # NaN guard
                return "—"
            return f"{fv:{fmt}}{suffix}"
        except (TypeError, ValueError):
            return "—"

    iv_val  = row.get("iv_30d")
    hv_val  = row.get("hv_20d")
    iv60    = row.get("iv_60d")
    perc    = row.get("iv_percentile")

    iv_str  = _f(iv_val,  ".1f", "%")
    hv_str  = _f(hv_val,  ".1f", "%")

    # Variance Risk Premium ratio
    vrp_str   = "—"
    vrp_color = COLORS["muted"]
    try:
        iv_f  = float(iv_val)   # type: ignore[arg-type]
        hv_f  = float(hv_val)   # type: ignore[arg-type]
        if hv_f > 0 and iv_f == iv_f and hv_f == hv_f:
            vrp = iv_f / hv_f
            vrp_str   = f"{vrp:.2f}×"
            vrp_color = (
                COLORS["accent"] if vrp < 0.9
                else COLORS["warn"] if vrp > 1.1
                else COLORS["muted"]
            )
    except (TypeError, ValueError):
        pass

    # Percentile pill (reuses existing component)
    pill = render_percentile_pill(perc)

    # Term structure slope label
    term_html = ""
    try:
        iv_f2  = float(iv_val)   # type: ignore[arg-type]
        iv60_f = float(iv60)     # type: ignore[arg-type]
        if iv_f2 == iv_f2 and iv60_f == iv60_f:
            slope = iv60_f - iv_f2
            if abs(slope) > 0.1:
                sign = "+" if slope > 0 else ""
                direction = "contango" if slope > 0 else "backwardation"
                col = COLORS["accent2"] if slope > 0 else COLORS["amber"]
            else:
                sign, direction, col = "", "flat curve", COLORS["muted"]
            term_html = (
                f'<div style="margin-top:8px;font-size:11px;font-family:{_MONO};">'
                f'<span style="color:{col};">{sign}{slope:.1f}pt · {direction}</span>'
                f'</div>'
            )
    except (TypeError, ValueError):
        pass

    # Card accent class driven by percentile
    card_cls = "volscope-card"
    try:
        pv = float(perc)  # type: ignore[arg-type]
        if pv == pv:
            if pv < 30:
                card_cls += " volscope-card-cheap"
            elif pv > 70:
                card_cls += " volscope-card-rich"
            else:
                card_cls += " volscope-card-neutral"
    except (TypeError, ValueError):
        pass

    company = row.get("company_name") or ""
    company_html = (
        f'<span class="volscope-card-name">{company}</span>' if company else ""
    )

    # Signal badge — compute if not provided (allows pre-computing for summary)
    if signal is None:
        signal = compute_signal(perc, iv_val, hv_val)
    badge_html = vol_signal_badge_html(signal)

    # ML mean-reversion badge
    ml_html = ml_badge_html(ml_pred)

    # Earnings crush badge (only if ER is upcoming)
    er_badge_html = ""
    if crush_est is not None:
        er_badge_html = crush_badge_html(crush_est, mono_font=_MONO)
        if er_badge_html:
            er_badge_html = f'<div style="margin-top:6px;">{er_badge_html}</div>'

    # Composite Edge Score badge — prominent numeric tile in the top right.
    # The edge is the single most-actionable signal for "should I trade
    # this right now"; surfacing it on every card makes the card useful
    # without expanding into Pre-Trade.
    edge_html = ""
    if edge is not None and edge.score > 0:
        edge_color = (
            COLORS["accent"]  if edge.score >= 70 else
            COLORS["accent2"] if edge.score >= 55 else
            COLORS["muted"]   if edge.score >= 40 else
            COLORS["warn"]
        )
        edge_html = (
            f'<div style="background:{edge_color}22;border-left:2px solid {edge_color};'
            f'border-radius:3px;padding:2px 8px;font-family:{_MONO};font-size:10px;'
            f'color:{edge_color};font-weight:700;letter-spacing:0.4px;">'
            f'EDGE {edge.score:.0f}'
            f'</div>'
        )

    stats = (
        f'<div class="volscope-card-stats" style="margin-top:10px;display:grid;'
        f'grid-template-columns:1fr 1fr 1fr;gap:4px 12px;">'
        f'<div>'
        f'<span style="color:{COLORS["label"]};font-size:9px;text-transform:uppercase;letter-spacing:1px;">IV 30d</span><br>'
        f'<span style="color:{COLORS["accent"]};">{iv_str}</span>'
        f'</div>'
        f'<div>'
        f'<span style="color:{COLORS["label"]};font-size:9px;text-transform:uppercase;letter-spacing:1px;">HV 20d</span><br>'
        f'<span style="color:{COLORS["accent2"]};">{hv_str}</span>'
        f'</div>'
        f'<div>'
        f'<span style="color:{COLORS["label"]};font-size:9px;text-transform:uppercase;letter-spacing:1px;">VRP</span><br>'
        f'<span style="color:{vrp_color};">{vrp_str}</span>'
        f'</div>'
        f'</div>'
    )

    return (
        f'<div class="{card_cls}">'
        # Header: ticker + company + (edge badge | percentile pill)
        f'<div style="display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:6px;margin-bottom:8px;">'
        f'<span class="volscope-card-ticker">{ticker}</span>'
        f'{edge_html}'
        f'{company_html}'
        f'{pill}'
        f'</div>'
        # Signal badge — the most prominent element
        f'{badge_html}'
        f'{ml_html}'
        f'{er_badge_html}'
        # Stats row: IV / HV / VRP
        f'{stats}'
        f'{term_html}'
        f'</div>'
    )


def _vol_pulse_block_html(snap: dict) -> str:
    """Return the HTML block for one vol-index card in the Vol Pulse strip."""
    name     = snap.get("name", "—")
    level    = snap.get("level")
    rank     = snap.get("rank_52w")
    pct      = snap.get("pct_52w")
    change   = snap.get("change_1w")
    regime   = snap.get("regime", "NO DATA")
    source   = snap.get("source", "")

    def _num(v: object, fmt: str = ".1f") -> str:
        if v is None:
            return "—"
        try:
            fv = float(v)  # type: ignore[arg-type]
            return "—" if fv != fv else f"{fv:{fmt}}"
        except (TypeError, ValueError):
            return "—"

    level_str  = _num(level, ".1f")
    rank_str   = (_num(rank, ".0f") + "%") if rank is not None else "—"
    pct_str    = (_num(pct,  ".0f") + "%") if pct  is not None else "—"

    chg_str   = "—"
    chg_color = COLORS["muted"]
    if change is not None:
        try:
            chg_f = float(change)  # type: ignore[arg-type]
            if chg_f == chg_f:
                prefix    = "+" if chg_f > 0 else ""
                chg_str   = f"{prefix}{chg_f:.1f}"
                chg_color = COLORS["warn"] if chg_f > 0 else COLORS["accent"]
        except (TypeError, ValueError):
            pass

    regime_color = {
        "CHEAP":   COLORS["accent"],
        "RICH":    COLORS["warn"],
        "NORMAL":  COLORS["muted"],
        "NO DATA": COLORS["label"],
    }.get(regime, COLORS["muted"])

    # Source badge: only show for proxy/fallback sources (not clean direct symbols)
    source_html = ""
    if source and source not in ("Deribit",) and not source.startswith("^") and not source.endswith(".DE"):
        source_html = (
            f'<div style="margin-top:5px;color:{COLORS["muted"]};font-size:9px;'
            f'font-family:{_MONO};letter-spacing:0.3px;">via {source}</div>'
        )
    elif source and source.startswith("^") or (source and source.endswith(".DE")):
        # Direct official symbol — show dimly for transparency
        source_html = (
            f'<div style="margin-top:5px;color:{COLORS["border"]};font-size:9px;'
            f'font-family:{_MONO};">{source}</div>'
        )

    return (
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:8px;padding:14px 16px;height:100%;">'
        f'<div style="color:{COLORS["label"]};font-size:9px;text-transform:uppercase;'
        f'letter-spacing:1.5px;margin-bottom:6px;font-family:{_MONO};">{name}</div>'
        f'<div style="font-family:{_MONO};font-size:28px;font-weight:700;'
        f'color:{COLORS["text"]};line-height:1;">{level_str}</div>'
        f'{source_html}'
        f'<div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;'
        f'gap:4px;font-family:{_MONO};font-size:11px;">'
        f'<div style="color:{COLORS["muted"]};">52w Rank</div>'
        f'<div style="color:{COLORS["text"]};text-align:right;">{rank_str}</div>'
        f'<div style="color:{COLORS["muted"]};">Percentile</div>'
        f'<div style="color:{COLORS["text"]};text-align:right;">{pct_str}</div>'
        f'<div style="color:{COLORS["muted"]};">1w Δ</div>'
        f'<div style="color:{chg_color};text-align:right;">{chg_str}</div>'
        f'</div>'
        f'<div style="margin-top:10px;">'
        f'<span style="background:{regime_color}22;color:{regime_color};'
        f'padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;'
        f'letter-spacing:0.5px;font-family:{_MONO};">● {regime}</span>'
        f'</div>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Trade journal HTML builders
# ---------------------------------------------------------------------------

def _position_row_html(pos: pd.Series, current_iv: Optional[float]) -> str:
    """Return one table row for a position in the trade journal."""
    entry_date = str(pos.get("entry_date", ""))[:10]
    entry_iv   = pos.get("entry_iv_30d")
    entry_pct  = pos.get("entry_iv_percentile")
    notes      = pos.get("notes") or ""
    pos_id     = pos.get("id")

    def _f(v: object, fmt: str = ".1f", suffix: str = "") -> str:
        if v is None:
            return "—"
        try:
            fv = float(v)   # type: ignore[arg-type]
            return "—" if fv != fv else f"{fv:{fmt}}{suffix}"
        except (TypeError, ValueError):
            return "—"

    entry_iv_str  = _f(entry_iv, ".1f", "%")
    current_iv_str = _f(current_iv, ".1f", "%")
    entry_pct_str  = _f(entry_pct, ".0f", "%")

    # Delta and color
    delta_html = '<td style="text-align:right;">—</td>'
    try:
        if entry_iv is not None and current_iv is not None:
            eiv = float(entry_iv)
            civ = float(current_iv)
            if eiv == eiv and civ == civ:
                delta = civ - eiv
                sign = "+" if delta > 0 else ""
                # IV rose after entry = bad (paid rich). IV fell = good (bought cheap).
                col = COLORS["warn"] if delta > 0.5 else COLORS["accent"] if delta < -0.5 else COLORS["muted"]
                delta_html = (
                    f'<td style="text-align:right;color:{col};font-family:{_MONO};">'
                    f'{sign}{delta:.1f}%</td>'
                )
    except (TypeError, ValueError):
        pass

    # Truncate long notes
    notes_short = (notes[:28] + "…") if len(notes) > 30 else notes

    return (
        f'<tr style="border-bottom:1px solid {COLORS["border"]};">'
        f'<td style="color:{COLORS["muted"]};font-family:{_MONO};">{entry_date}</td>'
        f'<td style="text-align:right;color:{COLORS["accent"]};font-family:{_MONO};">{entry_iv_str}</td>'
        f'<td style="text-align:right;color:{COLORS["text"]};font-family:{_MONO};">{current_iv_str}</td>'
        f'{delta_html}'
        f'<td style="text-align:right;color:{COLORS["muted"]};font-family:{_MONO};">{entry_pct_str}</td>'
        f'<td style="color:{COLORS["muted"]};font-size:10px;">{notes_short}</td>'
        f'</tr>'
    )


def _positions_table_html(
    ticker: str,
    positions_df: pd.DataFrame,
    current_iv: Optional[float],
) -> str:
    """Return an HTML table of the last 3 positions for a ticker."""
    if positions_df.empty:
        return ""

    header = (
        f'<div style="font-family:{_MONO};font-size:10px;color:{COLORS["label"]};'
        f'text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">'
        f'{ticker} — Entry Log</div>'
        f'<table style="width:100%;border-collapse:collapse;font-size:11px;">'
        f'<thead><tr style="color:{COLORS["muted"]};font-family:{_MONO};font-size:9px;'
        f'text-transform:uppercase;letter-spacing:0.8px;">'
        f'<th style="text-align:left;">Date</th>'
        f'<th style="text-align:right;">Entry IV</th>'
        f'<th style="text-align:right;">Now IV</th>'
        f'<th style="text-align:right;">Δ IV</th>'
        f'<th style="text-align:right;">Entry Pct</th>'
        f'<th style="text-align:left;padding-left:8px;">Notes</th>'
        f'</tr></thead><tbody>'
    )

    rows_html = ""
    for _, pos in positions_df.head(3).iterrows():
        rows_html += _position_row_html(pos, current_iv)

    return header + rows_html + "</tbody></table>"


# ---------------------------------------------------------------------------
# Position Sizer section
# ---------------------------------------------------------------------------

def _render_position_sizer(
    command_tickers: list[str],
    latest_rows: dict[str, Optional[pd.Series]],
    signals: dict[str, VolSignal],
    db,
) -> None:
    """
    Render the Position Sizer expander on the Command Center.

    The user sets a single max-allocation-per-position slider (stored in
    session state so it persists across reruns) and sees, for each of their
    tracked tickers:
      - Signal-based size multiplier → suggested allocation in USD
      - If there is a recent trade journal entry for that ticker, shows the
        rough P&L estimate (entry IV vs current IV).

    Parameters
    ----------
    command_tickers : Ordered list of tickers to show.
    latest_rows     : {ticker: latest daily_vol Series | None}
    signals         : {ticker: VolSignal}
    db              : VolScopeDB — used to look up most recent position entry_iv.
    """
    with st.expander("Position Sizer", expanded=False):
        render_html(
            st,
            f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};'
            f'margin-bottom:10px;">'
            f'Signal-based allocation calculator. '
            f'BUY VOL → full size · LEAN BUY → half size · WAIT / RICH → no position. '
            f'P&amp;L estimate uses first-order vega approx for long-dated ATM options.</div>',
        )

        # Max allocation slider — shared across all tickers
        max_alloc = st.slider(
            "Max allocation per position (USD)",
            min_value=500,
            max_value=50_000,
            value=st.session_state.get("sizer_max_alloc", 5_000),
            step=500,
            key="sizer_max_alloc",
            help="Your maximum intended size for a single position in this vol regime.",
        )

        # Build sizing rows
        tickers_with_data = [t for t in command_tickers if latest_rows.get(t) is not None]
        if not tickers_with_data:
            render_html(
                st,
                f'<div style="color:{COLORS["muted"]};font-size:11px;">'
                f'No market data — run <code>make scrape</code>.</div>',
            )
            return

        # Pull most recent position entry_iv per ticker (from trade journal)
        all_positions = db.get_positions()
        entry_ivs: dict[str, Optional[float]] = {}
        for t in tickers_with_data:
            try:
                ticker_pos = all_positions[
                    (all_positions["ticker"] == t) & (all_positions["active"] == True)
                ] if not all_positions.empty else pd.DataFrame()
                if not ticker_pos.empty:
                    # Most recent active entry
                    recent = ticker_pos.sort_values("entry_date", ascending=False).iloc[0]
                    val = recent.get("entry_iv_30d")
                    entry_ivs[t] = float(val) if val is not None and val == val else None
                else:
                    entry_ivs[t] = None
            except Exception:
                entry_ivs[t] = None

        # Render one row per ticker in a table-like layout
        header_html = (
            f'<div style="display:grid;grid-template-columns:80px 1fr 1fr 1fr;'
            f'gap:4px 12px;font-family:{_MONO};font-size:9px;'
            f'color:{COLORS["label"]};text-transform:uppercase;letter-spacing:1px;'
            f'margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid {COLORS["border"]};">'
            f'<div>TICKER</div><div>SIGNAL → SIZE</div>'
            f'<div>SUGGESTED</div><div>EST. P&amp;L (vs entry)</div>'
            f'</div>'
        )
        render_html(st, header_html)

        for t in tickers_with_data:
            row      = latest_rows[t]
            signal   = signals.get(t)
            entry_iv = entry_ivs.get(t)
            current_iv = None
            try:
                val = row.get("iv_30d")  # type: ignore[union-attr]
                if val is not None and val == val:
                    current_iv = float(val)
            except Exception:
                pass

            cat = signal.category if signal else "no_data"
            sizing = compute_sizing(
                cat,
                max_allocation=float(max_alloc),
                entry_iv=entry_iv,
                current_iv=current_iv,
            )

            # Color for ticker column driven by signal
            if cat in ("buy", "lean_buy"):
                tick_color = COLORS["accent"]
            elif cat in ("rich", "lean_rich"):
                tick_color = COLORS["warn"]
            else:
                tick_color = COLORS["muted"]

            # P&L cell
            if sizing.rough_pnl_usd is not None and sizing.rough_pnl_pct is not None:
                pnl_color = COLORS["accent"] if sizing.rough_pnl_usd >= 0 else COLORS["warn"]
                sign      = "+" if sizing.rough_pnl_usd >= 0 else "−"
                abs_pnl   = abs(sizing.rough_pnl_usd)
                pnl_cell  = (
                    f'<span style="color:{pnl_color};">'
                    f'{sign}${abs_pnl:,.0f} ({sizing.rough_pnl_pct:+.1f}%)</span>'
                )
            elif entry_iv is None:
                pnl_cell = f'<span style="color:{COLORS["label"]};">no entry logged</span>'
            else:
                pnl_cell = f'<span style="color:{COLORS["label"]};">—</span>'

            # Suggested allocation cell
            if sizing.suggested_allocation > 0:
                alloc_str = f'${sizing.suggested_allocation:,.0f}'
                alloc_color = tick_color
            else:
                alloc_str = "—"
                alloc_color = COLORS["label"]

            row_html = (
                f'<div style="display:grid;grid-template-columns:80px 1fr 1fr 1fr;'
                f'gap:4px 12px;font-family:{_MONO};font-size:11px;'
                f'padding:6px 0;border-bottom:1px solid {COLORS["border"]};">'
                f'<div style="color:{tick_color};font-weight:700;">{t}</div>'
                f'<div style="color:{COLORS["text"]};">{sizing.size_label}</div>'
                f'<div style="color:{alloc_color};font-weight:600;">{alloc_str}</div>'
                f'<div>{pnl_cell}</div>'
                f'</div>'
            )
            render_html(st, row_html)

        # Footer disclaimer
        render_html(
            st,
            f'<div style="font-family:{_MONO};font-size:9px;color:{COLORS["label"]};'
            f'margin-top:10px;">'
            f'P&amp;L estimate: first-order vega approximation for ATM long-dated options. '
            f'Not financial advice. Log entries in Trade Journal to enable P&amp;L tracking.</div>',
        )


def _render_alerts_expander(
    db: VolScopeDB,
    command_tickers: list[str],
    latest_rows: dict[str, Optional[pd.Series]],
) -> None:
    """Alerts expander: create/delete rules and see last-triggered log."""
    from volscope.alerts.alert_engine import SUPPORTED_METRICS, SUPPORTED_OPERATORS, SUPPORTED_CHANNELS

    rules_df = db.get_alert_rules()
    n_rules  = len(rules_df) if not rules_df.empty else 0
    expander_label = f"Vol Alerts ({n_rules} rule{'s' if n_rules != 1 else ''})"

    with st.expander(expander_label, expanded=False):
        render_html(
            st,
            f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};'
            f'margin-bottom:12px;">Passive threshold alerts — fires when vol crosses '
            f'a level you care about. Runs live in-app and via '
            f'<code>python scripts/backtest/run_alerts.py</code> for cron.</div>',
        )

        # ── Active rules table ─────────────────────────────────────────
        if not rules_df.empty:
            render_html(
                st,
                f'<div style="font-family:{_MONO};font-size:10px;'
                f'color:{COLORS["label"]};text-transform:uppercase;letter-spacing:1px;'
                f'margin-bottom:4px;">ACTIVE RULES</div>',
            )
            for _, rule_row in rules_df.iterrows():
                rule = AlertRule(
                    id=int(rule_row["id"]),
                    ticker=str(rule_row["ticker"]),
                    metric=str(rule_row["metric"]),
                    operator=str(rule_row["operator"]),
                    threshold=float(rule_row["threshold"]),
                    channel=str(rule_row["channel"]),
                    label=str(rule_row["label"]),
                    enabled=bool(rule_row["enabled"]),
                )
                col_rule, col_del = st.columns([6, 1])
                with col_rule:
                    render_html(st, alert_rule_html(rule))
                with col_del:
                    if st.button("✕", key=f"del_rule_{rule.id}",
                                 help=f"Delete rule: {rule.label}"):
                        db.delete_alert_rule(rule.id)
                        st.rerun()
        else:
            render_html(
                st,
                f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};">'
                f'No rules yet — create your first alert below.</div>',
            )

        # ── Live check against current data ───────────────────────────
        if not rules_df.empty:
            valid_rows = {t: r for t, r in latest_rows.items() if r is not None}
            if valid_rows:
                rules = [
                    AlertRule(
                        id=int(r["id"]),
                        ticker=str(r["ticker"]),
                        metric=str(r["metric"]),
                        operator=str(r["operator"]),
                        threshold=float(r["threshold"]),
                        channel=str(r["channel"]),
                        label=str(r["label"]),
                        enabled=bool(r["enabled"]),
                    )
                    for _, r in rules_df.iterrows()
                ]
                fired_now = evaluate_rules(rules, valid_rows)
                if fired_now:
                    render_html(
                        st,
                        f'<div style="font-family:{_MONO};font-size:10px;'
                        f'color:{COLORS["warn"]};margin-top:10px;margin-bottom:4px;">'
                        f'⚡ CURRENTLY TRIGGERING</div>',
                    )
                    for f in fired_now:
                        render_html(st, alert_fired_html(f))
                        # Log to DB + dispatch (desktop/email)
                        try:
                            db.log_alert_fired(
                                rule_id=f.rule_id,
                                fired_at=f.fired_at,
                                ticker=f.ticker,
                                metric=f.metric,
                                metric_value=f.value,
                                message=f.message,
                            )
                            dispatch_alert(f)
                        except Exception as _alert_exc:                # noqa: BLE001
                            # Telegram down, malformed rule, persistence
                            # error — operator must know a real alert
                            # didn't fire. Log loud (warning level), do
                            # NOT crash the page.
                            import logging as _lg
                            _lg.getLogger("volscope.ui.command").warning(
                                "dispatch_alert failed for ticker=%s msg=%s: %s",
                                getattr(f, "ticker", "?"),
                                str(getattr(f, "message", ""))[:80],
                                _alert_exc,
                            )

        st.write("")

        # ── Create rule form ──────────────────────────────────────────
        render_html(
            st,
            f'<div style="font-family:{_MONO};font-size:10px;color:{COLORS["label"]};'
            f'text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">'
            f'CREATE ALERT RULE</div>',
        )
        with st.form("create_alert_rule", clear_on_submit=True):
            col_t, col_m, col_op, col_thr, col_ch = st.columns([2, 2, 1.2, 1.5, 1.5])
            ticker_opts = ["*"] + command_tickers
            alert_ticker = col_t.selectbox(
                "Ticker", ticker_opts, index=0,
                help='"*" watches all your tracked tickers',
            )
            alert_metric = col_m.selectbox("Metric", list(SUPPORTED_METRICS))
            alert_op     = col_op.selectbox("Operator", list(SUPPORTED_OPERATORS))
            alert_thr    = col_thr.number_input(
                "Threshold", value=20.0, step=0.5, format="%.2f"
            )
            alert_ch     = col_ch.selectbox("Channel", list(SUPPORTED_CHANNELS))
            alert_label  = st.text_input(
                "Label (optional)",
                placeholder="e.g. QQQ BUY vol alert",
            )
            alert_submit = st.form_submit_button("Add rule", width='stretch')

        if alert_submit:
            label = alert_label.strip() or (
                f"{alert_ticker} {alert_metric} {alert_op} {alert_thr:.2f}"
            )
            db.add_alert_rule(
                ticker=alert_ticker,
                metric=alert_metric,
                operator=alert_op,
                threshold=float(alert_thr),
                channel=alert_ch,
                label=label,
            )
            st.success(f"Rule added: {label}")
            st.rerun()

        # ── Alert log ─────────────────────────────────────────────────
        log_df = db.get_alert_log(limit=20)
        if not log_df.empty:
            st.write("")
            render_html(
                st,
                f'<div style="font-family:{_MONO};font-size:10px;color:{COLORS["label"]};'
                f'text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">'
                f'RECENT ALERTS</div>',
            )
            for _, lr in log_df.iterrows():
                render_html(
                    st,
                    f'<div style="font-family:{_MONO};font-size:10px;'
                    f'color:{COLORS["muted"]};padding:2px 0;">'
                    f'[{str(lr.get("fired_at", ""))[:19]}] '
                    f'{lr.get("ticker","?")} — {lr.get("message","")}</div>',
                )


# ---------------------------------------------------------------------------
# Main render entry point
# ---------------------------------------------------------------------------

def render_command_center_page(db: VolScopeDB, settings: dict) -> None:
    # v0.9.7 — 4-phase orientation strip (master plan §2)
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name='Command', ticker=st.session_state.get('selected_ticker'))
    """Render the Command Center page."""

    # v0.9.0 — persistent vol-regime header strip.
    from volscope.ui.components.regime_header import render_regime_header
    render_regime_header(db)

    render_html(
        st,
        page_banner_html(
            title="Command Center",
            what="today's most important signals in one screen",
            when="first thing each morning",
        ),
    )

    # ── Session state: command tickers ──────────────────────────────────
    if "command_tickers" not in st.session_state:
        st.session_state["command_tickers"] = list(DEFAULT_COMMAND_TICKERS)
    command_tickers: list[str] = list(st.session_state["command_tickers"])

    # ── Header strip ────────────────────────────────────────────────────
    last_scrape         = db.get_last_scrape_date()
    badge_label, badge_color = freshness_badge(last_scrape)
    last_str            = last_scrape.isoformat() if last_scrape else "—"

    render_html(
        st,
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid {COLORS["border"]};">'
        f'<div style="font-family:{_MONO};font-size:22px;font-weight:700;color:{COLORS["text"]};">'
        f'<span style="color:{COLORS["accent"]};">⚡</span> COMMAND CENTER'
        f'</div>'
        f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};">'
        f'last scrape: <span style="color:{COLORS["text"]};">{last_str}</span>'
        f'&nbsp;&nbsp;'
        f'<span style="background:{badge_color}22;color:{badge_color};'
        f'padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;">'
        f'● {badge_label}</span>'
        f'</div>'
        f'</div>',
    )

    from volscope.ui.components.auto_refresh import auto_refresh_toggle
    auto_refresh_toggle("command")

    # Cached aggregate data prep — runs the heavy ML + crush + edge work
    # ONCE per (snapshot, ticker-tuple) for 5 minutes. Subsequent reruns
    # (sidebar interactions, modal opens) hit the cache and render instantly.
    from volscope.ui.components.cached_data import make_cache_key as _cache_key
    cmd_data = _prepare_command_data_cached(
        _cache_key(db),
        tuple(command_tickers),
        db,
    )
    history_map  = cmd_data["history_map"]
    latest_rows  = cmd_data["latest_rows"]
    signals      = cmd_data["signals"]
    crush_ests   = cmd_data["crush_ests"]
    ml_preds     = cmd_data["ml_preds"]

    # ── Earnings calendar — next 14d on tracked tickers ────────────────
    try:
        from volscope.analytics.earnings_calendar import severity_for_dte, upcoming_earnings
        events = upcoming_earnings(db, command_tickers, horizon_days=14)
        if events:
            sev_color = {
                "alert": COLORS["warn"],
                "warn":  COLORS["amber"],
                "watch": COLORS["accent2"],
                "info":  COLORS["muted"],
            }
            chips = []
            for ev in events:
                sev = severity_for_dte(ev.days_to_earnings)
                color = sev_color[sev]
                dte_label = "TODAY" if ev.days_to_earnings == 0 else f"in {ev.days_to_earnings}d"
                chips.append(
                    f'<div style="background:{color}22;border-left:2px solid {color};'
                    f'border-radius:4px;padding:5px 10px;font-family:{_MONO};'
                    f'font-size:11px;display:flex;justify-content:space-between;'
                    f'align-items:center;gap:8px;">'
                    f'<span style="color:{COLORS["text"]};font-weight:700;">{ev.ticker}</span>'
                    f'<span style="color:{color};font-weight:600;">{dte_label}</span>'
                    f'<span style="color:{COLORS["muted"]};font-size:9px;">'
                    f'{ev.earnings_date.isoformat()}</span>'
                    f'</div>'
                )
            render_html(
                st,
                f'<div style="margin-bottom:14px;">'
                f'<div style="font-family:{_MONO};font-size:9px;letter-spacing:1.4px;'
                f'color:{COLORS["label"]};text-transform:uppercase;font-weight:600;'
                f'margin-bottom:6px;">📅 earnings calendar — next 14 days</div>'
                f'<div style="display:grid;grid-template-columns:repeat(auto-fit,'
                f'minmax(220px,1fr));gap:6px;">'
                + "".join(chips) +
                f'</div></div>',
            )
    except Exception as exc:
        log.debug("Earnings calendar strip failed: %s", exc)

    # ── What changed today — overnight delta strip ─────────────────────
    # Top 5 biggest IV moves across tracked positions vs yesterday.
    try:
        from volscope.analytics.daily_delta import rank_daily_deltas
        deltas = rank_daily_deltas(history_map, n=5)
        if deltas:
            chips_html = []
            for d in deltas:
                chips_html.append(
                    f'<div style="background:{d.color}22;border-left:3px solid {d.color};'
                    f'border-radius:4px;padding:6px 10px;font-family:{_MONO};'
                    f'font-size:11px;display:flex;flex-direction:column;min-width:0;">'
                    f'<div style="color:{d.color};font-weight:700;">{d.ticker}</div>'
                    f'<div style="color:{COLORS["muted"]};font-size:10px;'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                    f'{d.headline}</div>'
                    f'</div>'
                )
            render_html(
                st,
                f'<div style="margin-bottom:14px;">'
                f'<div style="font-family:{_MONO};font-size:9px;letter-spacing:1.4px;'
                f'color:{COLORS["label"]};text-transform:uppercase;font-weight:600;'
                f'margin-bottom:6px;">overnight Δ — biggest IV moves vs yesterday</div>'
                f'<div style="display:grid;grid-template-columns:repeat(auto-fit,'
                f'minmax(180px,1fr));gap:8px;">'
                + "".join(chips_html) +
                f'</div></div>',
            )
    except Exception as exc:
        log.debug("Daily-delta strip failed: %s", exc)

    # ── Vol Pulse promoted up — answers "where is vol RIGHT NOW" first ──
    pulse_header_left, pulse_header_right = st.columns([3, 1])
    with pulse_header_left:
        render_html(st, "<h3>VOL PULSE — CROSS-ASSET INDICES</h3>")
    with pulse_header_right:
        if st.button("↻ Refresh", key="vol_pulse_refresh", help="Re-fetch vol indices now"):
            _load_vol_pulse.clear()
            st.rerun()

    pulse_snaps = _load_vol_pulse()
    pulse_cols  = st.columns(4)
    for i, snap in enumerate(pulse_snaps):
        with pulse_cols[i]:
            render_html(st, _vol_pulse_block_html(snap))

    st.divider()

    # ── Top Edges (composite Edge Score) ─────────────────────────────────
    # Single ranked answer to "where's the best long-vol entry right now?"
    edges_by_ticker: dict[str, EdgeScore] = {}
    try:
        edges = compute_edge_table(
            command_tickers,
            latest_rows,
            ml_preds=ml_preds,
        )
        edges_by_ticker = {e.ticker: e for e in edges}
        edges_html = _edges_strip_html(edges, max_rows=min(len(command_tickers), 5))
        if edges_html:
            render_html(st, edges_html)
    except Exception as exc:
        log.debug("Edge Score block failed: %s", exc)

    # ── Your Markets ─────────────────────────────────────────────────────
    render_html(st, "<h3>YOUR MARKETS</h3>")

    # Summary line — universe-wide signal distribution above the cards.
    summary_text = market_summary(list(signals.values()))
    if summary_text:
        # Pick color based on whether the majority is cheap or rich.
        buy_count  = sum(1 for s in signals.values() if s.category in ("buy", "lean_buy"))
        rich_count = sum(1 for s in signals.values() if s.category in ("rich", "lean_rich"))
        if buy_count > rich_count:
            summary_color = COLORS["accent"]
            summary_icon  = "⚡"
        elif rich_count > buy_count:
            summary_color = COLORS["warn"]
            summary_icon  = "⚠"
        else:
            summary_color = COLORS["muted"]
            summary_icon  = "○"
        render_html(
            st,
            f'<div style="font-family:{_MONO};font-size:12px;color:{summary_color};'
            f'margin-bottom:12px;padding:8px 12px;background:{summary_color}11;'
            f'border-radius:6px;border-left:3px solid {summary_color};">'
            f'{summary_icon} {summary_text}'
            f'</div>',
        )

    # Auto-fit grid: 4 cols on wide screens, fewer on narrow. Inline ▷
    # Pre-Trade button per card so the trader can deep-link to the
    # execution view in one click.
    n = len(command_tickers)
    n_cols = 4 if n >= 8 else 3 if n >= 5 else max(1, min(n, 4))
    cols = st.columns(n_cols)
    for i, ticker in enumerate(command_tickers):
        with cols[i % n_cols]:
            render_html(
                st,
                _market_card_html(
                    ticker,
                    latest_rows.get(ticker),
                    signals.get(ticker),
                    crush_ests.get(ticker),
                    ml_preds.get(ticker),
                    edge=edges_by_ticker.get(ticker),
                ),
            )
            # Inline action row: jump to Pre-Trade or Scope for this ticker
            act_l, act_r = st.columns(2)
            if act_l.button(
                f"▷ Pre-Trade",
                key=f"cmd_pretrade_{ticker}",
                width='stretch',
                help=f"Open Pre-Trade card for {ticker}",
            ):
                from volscope.ui.components.navigation import NavIntent, nav_to
                nav_to(NavIntent(page="Pre-Trade", ticker=ticker, source="Command"))
                st.rerun()
            if act_r.button(
                f"◈ Scope",
                key=f"cmd_scope_{ticker}",
                width='stretch',
                help=f"Open Scope deep-dive for {ticker}",
            ):
                from volscope.ui.components.navigation import NavIntent, nav_to
                nav_to(NavIntent(page="Scope", ticker=ticker, source="Command"))
                st.rerun()

    # Ticker management
    with st.expander("Manage tickers", expanded=False):
        with st.form("cmd_add_ticker", clear_on_submit=True):
            raw = st.text_input(
                "Add Yahoo symbol",
                placeholder="NVDA, ^GDAXI, BTC-USD, 9988.HK",
                help=(
                    "Adds ticker to your Command Center and backfills "
                    "historical vol data if not already in the DB."
                ),
            )
            col_add, col_reset = st.columns([2, 1])
            submitted = col_add.form_submit_button("Add", width='stretch')
            reset     = col_reset.form_submit_button("Reset to defaults", width='stretch')

        if reset:
            st.session_state["command_tickers"] = list(DEFAULT_COMMAND_TICKERS)
            st.rerun()

        if submitted and raw:
            sym = raw.strip().upper()
            if sym in st.session_state["command_tickers"]:
                st.success(f"{sym} already tracked.")
            elif len(st.session_state["command_tickers"]) >= 10:
                st.error("Maximum 10 tickers in Command Center.")
            else:
                with st.spinner(f"Resolving {sym}…"):
                    result = resolve_and_ingest(db, raw)
                if result.ok:
                    st.session_state["command_tickers"].append(result.ticker)
                    st.success(f"Added {result.ticker}")
                    st.rerun()
                else:
                    st.error(result.message)

        # Remove buttons
        if command_tickers:
            st.write("Remove a ticker:")
            remove_cols = st.columns(min(len(command_tickers), 5))
            for i, t in enumerate(command_tickers):
                if remove_cols[i % 5].button(f"✕ {t}", key=f"rm_{t}"):
                    tickers = list(st.session_state["command_tickers"])
                    if t in tickers:
                        tickers.remove(t)
                    st.session_state["command_tickers"] = tickers
                    st.rerun()

    # ── Trade Journal ─────────────────────────────────────────────────────
    all_positions = db.get_positions()
    active_count = len(all_positions[all_positions["active"] == True]) if not all_positions.empty else 0
    journal_label = f"Trade Journal ({active_count} active)" if active_count else "Trade Journal"

    with st.expander(journal_label, expanded=active_count > 0):
        render_html(st,
            f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};'
            f'margin-bottom:12px;">Track your entries — see if vol was cheap when you bought.</div>'
        )

        # Show entry logs per ticker that has positions
        if not all_positions.empty:
            tickers_with_positions = all_positions["ticker"].unique().tolist()
            for t in tickers_with_positions:
                ticker_pos = all_positions[all_positions["ticker"] == t]
                current_iv = None
                row = latest_rows.get(t)
                if row is not None:
                    try:
                        current_iv = float(row.get("iv_30d"))  # type: ignore[arg-type]
                        if current_iv != current_iv:
                            current_iv = None
                    except (TypeError, ValueError):
                        pass
                table_html = _positions_table_html(t, ticker_pos, current_iv)
                if table_html:
                    render_html(st, table_html)
                    st.write("")

                # Close buttons for active positions of this ticker
                active_pos = ticker_pos[ticker_pos["active"] == True]
                if not active_pos.empty:
                    close_cols = st.columns(min(len(active_pos), 4))
                    for j, (_, pos) in enumerate(active_pos.iterrows()):
                        pos_id = int(pos["id"])
                        entry_str = str(pos.get("entry_date", ""))[:10]
                        if close_cols[j % 4].button(
                            f"Close {t} {entry_str}", key=f"close_pos_{pos_id}"
                        ):
                            db.close_position(pos_id)
                            st.rerun()
        else:
            render_html(st,
                f'<div style="color:{COLORS["muted"]};font-family:{_MONO};font-size:11px;">'
                f'No entries yet. Log your first trade below.</div>'
            )

        st.write("")

        # Add position form
        with st.form("add_position_form", clear_on_submit=True):
            render_html(st, f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["label"]};margin-bottom:6px;">LOG NEW ENTRY</div>')
            col_t, col_d, col_iv, col_pct, col_vrp = st.columns([2, 2, 1.5, 1.5, 1.5])
            add_ticker  = col_t.text_input("Ticker", placeholder="QQQ")
            add_date    = col_d.date_input("Entry date", value=date.today())
            add_iv      = col_iv.number_input("Entry IV 30d (%)", min_value=0.0, max_value=200.0, value=0.0, step=0.1)
            add_pct     = col_pct.number_input("Entry IV Pct (%)", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
            add_vrp     = col_vrp.number_input("Entry VRP", min_value=0.0, max_value=10.0, value=0.0, step=0.01)
            add_notes   = st.text_input("Notes (optional)", placeholder="Sep 2027 DAX put, stress event")
            log_submit  = st.form_submit_button("Log entry", width='stretch')

        if log_submit and add_ticker:
            sym = add_ticker.strip().upper()
            db.add_position(
                ticker=sym,
                entry_date=add_date,
                entry_iv_30d=add_iv if add_iv > 0 else None,
                entry_iv_percentile=add_pct if add_pct > 0 else None,
                entry_vrp=add_vrp if add_vrp > 0 else None,
                notes=add_notes.strip(),
            )
            st.success(f"Logged entry for {sym} on {add_date}")
            st.rerun()

    # ── Position Sizer ────────────────────────────────────────────────────
    _render_position_sizer(command_tickers, latest_rows, signals, db)

    # ── Vol Alerts ────────────────────────────────────────────────────────
    _render_alerts_expander(db, command_tickers, latest_rows)

    st.divider()

    # ── Charts row ────────────────────────────────────────────────────────
    chart_data: dict[str, dict] = {
        t: row.to_dict()
        for t, row in latest_rows.items()
        if row is not None
    }

    left, right = st.columns(2)

    with left:
        fig_ts = create_command_term_structure(chart_data)
        st.plotly_chart(fig_ts, width='stretch')

    with right:
        fig_vrp = create_vrp_bar(chart_data)
        st.plotly_chart(fig_vrp, width='stretch')

    # v0.9.7 — cross-page weave footer (master plan §4)
    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(st, page='Command', ticker=st.session_state.get('selected_ticker'))
