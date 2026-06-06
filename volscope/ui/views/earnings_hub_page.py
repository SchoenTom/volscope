"""
Earnings Hub — VolScope's vol-trader earnings calendar.

Layout (top → bottom):

    Title + freshness bar
    Week-nav strip + filter bar
    Weekly grid (5 columns × BMO/AMC bands × ticker tiles)
    Sector implied-move heatmap (footer)

Each tile carries the 4 numbers that decide the trade: implied move,
direction skew, crowded score (vs ticker's pre-ER history), expected
post-print crush. Click → drawer expansion with detail charts and the
strategy recommendation for the print.

Why this matters: a vol trader's morning ritual is "what earnings
events am I trading this week" and "what is the market mispricing".
Every other earnings calendar answers neither question — they show
consensus EPS, which doesn't move IV. This page answers BOTH.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from html import escape
from typing import Optional

import pandas as pd
import streamlit as st

from volscope.analytics.crowded_pre_er import compute_pre_er_crowded
from volscope.analytics.earnings_backtest import (
    backtest_earnings_strategy, edge_string,
)
from volscope.analytics.earnings_crush import compute_crush_estimate
from volscope.analytics.earnings_expected_move import (
    calibrate_implied_vs_realised,
    compute_implied_move,
)
from volscope.analytics.earnings_strategy import recommend_for_earnings
from volscope.analytics.earnings_thesis import auto_thesis
from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
from volscope.ui.components.earnings_diagnostics import (
    compute_anomaly_score,
    render_anomaly_badge,
    render_calibration_bar,
    render_pre_er_drift,
)
from volscope.ui.components.html_utils import (
    kpi_grid_html,
    page_banner_html,
    render_html,
)
from volscope.ui.styles.theme import COLORS, seq_color

log = logging.getLogger(__name__)


_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri")
_BAND_ORDER = ("bmo", "during", "amc", "unknown")
_BAND_LABEL = {
    "bmo":    "BEFORE OPEN",
    "during": "INTRA-DAY",
    "amc":    "AFTER CLOSE",
    "unknown": "TIME TBD",
}


# ── Macro calendar (static — v1) ─────────────────────────────────────
# Hand-curated for now; replace with a real economic calendar API in
# a follow-up. Tuples of (date, label, level). Level drives the colour
# weight: "high" = Fed-class, "med" = CPI/NFP-class.
_MACRO_EVENTS_2026: tuple[tuple[date, str, str], ...] = (
    (date(2026, 5, 14), "CPI April", "med"),
    (date(2026, 6, 11), "CPI May",   "med"),
    (date(2026, 6, 17), "FOMC June", "high"),
    (date(2026, 6,  5), "NFP May",   "med"),
    (date(2026, 7,  2), "NFP June",  "med"),
    (date(2026, 7, 15), "CPI June",  "med"),
    (date(2026, 7, 29), "FOMC July", "high"),
)


# ── Top-level entry point ────────────────────────────────────────────

def render_earnings_hub_page(db, settings: dict | None = None) -> None:
    # v0.9.7 — 4-phase orientation strip (master plan §2)
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name='Earnings Hub', ticker=st.session_state.get('selected_ticker'))
    """Sidebar entry from `_PAGE_REGISTRY`."""
    st.markdown("## ◈ Earnings Hub")
    render_html(
        st,
        page_banner_html(
            title="Earnings Hub",
            what="weekly grid: implied moves, skew, crowded names",
            when="Sunday review for the week",
        ),
    )
    st.caption(
        "Vol-trader earnings calendar — implied move, direction skew, "
        "crowdedness, expected post-print crush. The four numbers that "
        "decide whether you trade the print."
    )
    render_data_freshness_bar(db)

    # Week navigation + filter strip
    week_start, sort_mode, sector_filter, watchlist_only, watchlist_filter = _render_controls(db)
    week_end = week_start + timedelta(days=6)

    # Pull events for the week
    events = _events_for_week(db, week_start, week_end)

    # Morning briefing — only when there are events today
    today = date.today()
    today_events = [e for e in events if (
        (e["earnings_date"].date()
         if hasattr(e["earnings_date"], "date")
         else e["earnings_date"]) == today
    )]
    if today_events:
        _render_morning_briefing(db, today_events)

    # Macro overlay
    _render_macro_overlay(week_start, week_end)

    if not events:
        render_html(
            st,
            f'<div class="volscope-empty-state">'
            f'<div class="volscope-empty-headline">No earnings this week.</div>'
            f'<div class="volscope-empty-body">'
            f'No tracked ticker reports between {week_start.isoformat()} '
            f'and {week_end.isoformat()}. Pick another week, or run '
            f'<code>python -m scripts.scrape_earnings_meta</code> to refresh '
            f'the calendar from yfinance.</div></div>',
        )
        return

    # Optional filters
    events = _apply_filters(events, sector_filter, watchlist_only, db, watchlist_filter)
    if not events:
        st.info("No events match the current filter combination.")
        return

    # Enrich each event with analytics (cached per-tile)
    enriched = [
        _enrich(db, ev) for ev in events
    ]
    # Sort within each (date, band) bucket using interestingness or
    # user-selected mode.
    enriched.sort(key=_sort_key_factory(sort_mode))

    # ── Render the 5-column × bands grid ─────────────────────────────
    _render_week_grid(db, week_start, enriched)

    # ── Sector heatmap footer ────────────────────────────────────────
    _render_sector_heatmap(enriched)

    # (Removed in the IV-research refocus: the embedded "My Earnings Trades"
    # position tracker depended on the paper-trade book, which was cut.
    # Earnings Hub is now a pure event/expected-move research view.)

    # v0.9.7 — cross-page weave footer (master plan §4)
    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(st, page='Earnings Hub', ticker=st.session_state.get('selected_ticker'))


# ── Controls strip ───────────────────────────────────────────────────

def _render_morning_briefing(db, today_events: list[dict]) -> None:
    """Auto-generated 1-paragraph card with today's actionable events."""
    if not today_events:
        return
    # Enrich each with implied move
    lines = []
    try:
        positions = db.get_positions(active_only=True)
        held = set(str(t).upper() for t in positions["ticker"].dropna().tolist()) \
               if positions is not None and not positions.empty else set()
    except Exception:
        held = set()
    for ev in today_events[:6]:
        ticker = str(ev["ticker"])
        band = str(ev.get("time_of_day") or "—").upper()
        try:
            impl = compute_implied_move(db, ticker,
                pd.to_datetime(ev["earnings_date"]).date()
                if not isinstance(ev["earnings_date"], date)
                else ev["earnings_date"])
            move_str = f"±{impl.move_pct:.1f}%" if impl else "± —"
        except Exception:
            move_str = "± —"
        watchlist_pill = (
            f' <span style="background:{COLORS["accent"]}33;'
            f'color:{COLORS["accent"]};padding:1px 5px;border-radius:3px;'
            f'font-size:9px;font-weight:600;">▣ portfolio</span>'
            if ticker.upper() in held else ""
        )
        lines.append(
            f'<span style="color:{COLORS["text"]};font-weight:700;">{escape(ticker)}</span> '
            f'<span style="color:{COLORS["label"]};font-size:9px;">{band}</span> '
            f'<span style="color:{COLORS["accent"]};">{move_str}</span>'
            f'{watchlist_pill}'
        )

    lines_html = "<br>".join(lines)
    n = len(today_events)
    render_html(
        st,
        f'<div style="background:linear-gradient(135deg,{COLORS["card"]} 0%,'
        f'{COLORS["card_elevated"]} 100%);border:1px solid {COLORS["border"]};'
        f'border-left:3px solid {COLORS["accent2"]};border-radius:6px;'
        f'padding:10px 14px;margin:6px 0 12px 0;'
        f'font-family:JetBrains Mono,monospace;font-size:11px;line-height:1.7;">'
        f'<div style="font-size:9px;color:{COLORS["label"]};text-transform:uppercase;'
        f'letter-spacing:1.4px;margin-bottom:4px;">'
        f'☼ today · {n} earnings event{"s" if n != 1 else ""}'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};">{lines_html}</div>'
        f'</div>',
    )


def _render_macro_overlay(week_start: date, week_end: date) -> None:
    """Show any macro events landing in the visible week."""
    matches = [
        ev for ev in _MACRO_EVENTS_2026
        if week_start <= ev[0] <= week_end
    ]
    if not matches:
        return
    chips = []
    for d, label, level in matches:
        color = COLORS["warn"] if level == "high" else COLORS["amber"]
        day_name = _DAY_NAMES[(d - week_start).days] if 0 <= (d - week_start).days <= 4 else "—"
        chips.append(
            f'<span style="background:{color}1a;color:{color};'
            f'border:1px solid {color}55;padding:2px 8px;border-radius:4px;'
            f'font-size:10px;font-weight:700;letter-spacing:0.5px;'
            f'margin-right:6px;">{day_name} · {escape(label)}</span>'
        )
    render_html(
        st,
        f'<div style="font-family:JetBrains Mono,monospace;font-size:10px;'
        f'margin-bottom:10px;display:flex;align-items:center;gap:10px;'
        f'flex-wrap:wrap;">'
        f'<span style="color:{COLORS["label"]};text-transform:uppercase;'
        f'letter-spacing:1.4px;">macro events</span>'
        f'{"".join(chips)}</div>',
    )


def _render_controls(db) -> tuple[date, str, Optional[str], bool]:
    """Top filter row. Returns (week_start, sort_mode, sector, watchlist_only)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    if "eh_week_offset" not in st.session_state:
        st.session_state["eh_week_offset"] = 0
    week_start = monday + timedelta(days=7 * st.session_state["eh_week_offset"])
    week_end = week_start + timedelta(days=4)

    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 2, 2])
    with c1:
        if st.button("◂ prev", key="eh_prev", width='stretch'):
            st.session_state["eh_week_offset"] -= 1
            st.rerun()
    with c2:
        if st.button("this week", key="eh_today",
                     width='stretch',
                     type=("primary" if st.session_state["eh_week_offset"] == 0
                            else "secondary")):
            st.session_state["eh_week_offset"] = 0
            st.rerun()
    with c3:
        if st.button("next ▸", key="eh_next", width='stretch'):
            st.session_state["eh_week_offset"] += 1
            st.rerun()
    with c4:
        sort_mode = st.selectbox(
            "Sort",
            ["interestingness", "implied move ↓", "crowdedness ↓",
             "market cap ↓", "alphabetical"],
            index=0, key="eh_sort", label_visibility="collapsed",
        )
    with c5:
        # Sector filter built dynamically from latest snapshot
        sectors = ["all"]
        try:
            df = db.con.execute(
                "SELECT DISTINCT sector FROM daily_vol "
                "WHERE sector IS NOT NULL ORDER BY sector"
            ).fetchdf()
            sectors += [s for s in df["sector"].dropna().tolist() if s]
        except Exception:
            pass
        sector = st.selectbox("Sector", sectors, index=0, key="eh_sector",
                               label_visibility="collapsed")
        sector = None if sector == "all" else sector

    tcol1, tcol2 = st.columns(2)
    with tcol1:
        watchlist_only = st.toggle(
            "Only tickers in my portfolio", value=False,
            key="eh_watchlist_only",
            help="Show only tickers you currently hold a position in.",
        )
    with tcol2:
        # v0.9.11 — operator feedback: add "only watchlist tickers"
        # toggle (their daily workflow is watchlist-driven, not
        # portfolio-driven). Both toggles AND together — turn both
        # on to intersect, leave both off to see the full grid.
        watchlist_filter = st.toggle(
            "Only tickers in my watchlists", value=False,
            key="eh_watchlist_filter",
            help="Show only tickers that appear in at least one of your watchlists.",
        )

    render_html(
        st,
        f'<div style="font-family:JetBrains Mono,monospace;font-size:11px;'
        f'color:{COLORS["muted"]};margin:6px 0 12px 0;">'
        f'showing earnings for week of <strong style="color:{COLORS["text"]};">'
        f'{week_start.strftime("%b %d")} → {week_end.strftime("%b %d %Y")}'
        f'</strong></div>',
    )
    return week_start, sort_mode, sector, watchlist_only, watchlist_filter


# ── Event sourcing & enrichment ──────────────────────────────────────

def _events_for_week(db, week_start: date, week_end: date) -> list[dict]:
    try:
        df = db.con.execute(
            """
            SELECT e.ticker, e.earnings_date, e.time_of_day,
                   e.eps_estimate, e.revenue_estimate, e.market_cap,
                   d.sector, d.company_name
            FROM earnings e
            LEFT JOIN (
                SELECT ticker, sector, company_name,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
                FROM daily_vol
            ) d ON d.ticker = e.ticker AND d.rn = 1
            WHERE e.earnings_date BETWEEN ? AND ?
            ORDER BY e.earnings_date, e.ticker
            """,
            [week_start, week_end],
        ).fetchdf()
    except Exception as exc:
        log.exception("earnings query failed: %s", exc)
        return []
    return df.to_dict("records") if not df.empty else []


def _apply_filters(events, sector_filter, watchlist_only, db,
                    watchlist_filter: bool = False) -> list[dict]:
    out = events
    if sector_filter:
        out = [e for e in out if (e.get("sector") or "").lower()
                                  == sector_filter.lower()]
    if watchlist_only:
        try:
            positions = db.get_positions(active_only=True)
            held = set(str(t).upper() for t in positions["ticker"].dropna().tolist()) \
                   if positions is not None and not positions.empty else set()
        except Exception:
            held = set()
        out = [e for e in out if str(e["ticker"]).upper() in held]
    if watchlist_filter:
        try:
            from volscope.persistence.watchlists import list_watchlists
            wls = list_watchlists(db)
            wl_tickers = set()
            for wl in wls:
                for t in wl.tickers:
                    wl_tickers.add(str(t).upper())
        except Exception:
            wl_tickers = set()
        out = [e for e in out if str(e["ticker"]).upper() in wl_tickers]
    return out


@st.cache_data(ttl=300, show_spinner=False, hash_funcs={dict: lambda d: (str(d.get("ticker", "")), str(d.get("earnings_date", "")))})
def _enrich_analytics(cache_key: str, ticker: str, er_date_iso: str, _db) -> dict:
    """v0.9.2: caches the 4 per-event analytics computations.

    Earnings Hub renders ~30 events per week. The previous _enrich
    fired ``compute_implied_move`` + ``compute_pre_er_crowded`` +
    ``compute_crush_estimate`` + ``calibrate_implied_vs_realised`` for
    every event on every page render — each of those internally does
    ``db.get_ticker_history(ticker)`` + further analytics. That's
    ~4 DuckDB reads × 30 events = 120 reads per Earnings-Hub render,
    on every interaction.

    Caching at this level (per ticker × earnings_date × last-scrape)
    is the correct granularity: analytics depend on the freshness of
    the underlying scrape (covered by cache_key) and on the specific
    event, but NOT on which page is currently active.
    """
    from datetime import date as _date
    er_date = _date.fromisoformat(er_date_iso)
    result: dict = {
        "implied":     None,
        "crowded":     None,
        "crush":       None,
        "calibration": None,
    }
    try:
        result["implied"] = compute_implied_move(_db, ticker, er_date)
    except Exception as exc:                                   # noqa: BLE001
        log.debug("implied move %s: %s", ticker, exc)
    try:
        result["crowded"] = compute_pre_er_crowded(_db, ticker)
    except Exception as exc:                                   # noqa: BLE001
        log.debug("crowded pre-er %s: %s", ticker, exc)
    try:
        result["crush"] = compute_crush_estimate(_db, ticker)
    except Exception as exc:                                   # noqa: BLE001
        log.debug("crush %s: %s", ticker, exc)
    try:
        result["calibration"] = calibrate_implied_vs_realised(
            _db, ticker, min_events=3,
        )
    except Exception as exc:                                   # noqa: BLE001
        log.debug("calibration %s: %s", ticker, exc)
    return result


def _enrich(db, ev: dict) -> dict:
    """Compute the 4 headline analytics for one event.

    v0.9.2: analytics are now cached via ``_enrich_analytics`` at
    (cache_key, ticker, earnings_date_iso, _db). ~120× fewer DB
    reads on a 30-event week.

    Note on the date normalisation: ``pd.Timestamp`` is a *subclass*
    of ``datetime.date`` (via ``datetime.datetime``), so a naive
    ``isinstance(x, date)`` check returns True even for Timestamps —
    they then leak into downstream date-arithmetic (``ts - date``
    is unsupported and crashes ``_render_week_grid``). We therefore
    normalise unconditionally via ``pd.Timestamp(...).date()`` which
    accepts every shape (Timestamp, datetime, date, ISO string) and
    always emits a plain ``datetime.date``.
    """
    ticker = str(ev["ticker"])
    er_date = pd.Timestamp(ev["earnings_date"]).date()

    out = dict(ev)
    out["earnings_date"] = er_date
    out["implied"] = None
    out["crowded"] = None
    out["crush"] = None
    out["calibration"] = None
    out["recommendation"] = None
    out["interestingness"] = 0.0

    # v0.9.2 cached path. Reaches all four analytics calls in one
    # cache key, so subsequent renders of the same week hit cache.
    cache_hit = False
    try:
        from volscope.ui.components.cached_data import make_cache_key
        cached = _enrich_analytics(
            make_cache_key(db), ticker, er_date.isoformat(), db,
        )
        out["implied"]     = cached["implied"]
        out["crowded"]     = cached["crowded"]
        out["crush"]       = cached["crush"]
        out["calibration"] = cached["calibration"]
        cache_hit = True
    except Exception as exc:                                    # noqa: BLE001
        # Cache failed for any reason — fall through to the original
        # per-call path below (preserves correctness, just slower).
        log.debug("enrich cache miss %s: %s", ticker, exc)

    if not cache_hit:
        try:
            out["implied"] = compute_implied_move(db, ticker, er_date)
        except Exception as exc:
            log.debug("implied move %s: %s", ticker, exc)
        try:
            out["crowded"] = compute_pre_er_crowded(db, ticker)
        except Exception as exc:
            log.debug("crowded pre-er %s: %s", ticker, exc)
        try:
            out["crush"] = compute_crush_estimate(db, ticker)
        except Exception as exc:
            log.debug("crush %s: %s", ticker, exc)
        try:
            out["calibration"] = calibrate_implied_vs_realised(db, ticker, min_events=3)
        except Exception as exc:
            log.debug("calibration %s: %s", ticker, exc)

    # Recommendation — computed for BOTH the cache-hit and slow paths
    # (previously the cache path returned early and left this None).
    try:
        latest = db.get_ticker_history(ticker).iloc[-1]
        iv_rank = float(latest.get("iv_rank") or 0)
        skew = float(latest.get("iv_skew_25d") or 0)
    except Exception:
        iv_rank = 0
        skew = 0
    out["recommendation"] = recommend_for_earnings(
        implied_move_pct=getattr(out["implied"], "move_pct", None),
        skew_pt=skew,
        crowded_band=getattr(out["crowded"], "band", None),
        iv_rank=iv_rank,
        calibration_ratio=getattr(out["calibration"], "ratio", None),
    )

    # Interestingness score (matches Part 7 of EARNINGS_HUB_PLAN)
    move = getattr(out["implied"], "move_pct", 0.0) or 0.0
    crd = getattr(out["crowded"], "score_today", 0.0) or 0.0
    sk = abs(skew)
    out["interestingness"] = (
        0.40 * min(move, 15) / 15
        + 0.40 * crd / 100
        + 0.20 * min(sk, 5) / 5
    )
    return out


def _sort_key_factory(mode: str):
    def _key(ev: dict):
        if mode == "implied move ↓":
            return -(getattr(ev["implied"], "move_pct", 0.0) or 0)
        if mode == "crowdedness ↓":
            return -(getattr(ev["crowded"], "score_today", 0.0) or 0)
        if mode == "market cap ↓":
            return -float(ev.get("market_cap") or 0)
        if mode == "alphabetical":
            return str(ev["ticker"])
        # default: interestingness
        return -ev["interestingness"]
    return _key


# ── Grid layout ──────────────────────────────────────────────────────

def _render_week_grid(db, week_start: date, events: list[dict]) -> None:
    # Group events: { day_index: { band: [events] } }
    buckets: dict[int, dict[str, list[dict]]] = {
        i: {b: [] for b in _BAND_ORDER} for i in range(5)
    }
    for ev in events:
        # Defensive normalisation: ``earnings_date`` should already be a
        # plain ``date`` after ``_enrich``, but ``pd.Timestamp`` *is* a
        # subclass of ``datetime.date`` and slips through naive isinstance
        # checks. ``Timestamp - date`` raises TypeError, so we coerce here
        # too — cheap and prevents Earnings Hub from crashing on any
        # future code path that bypasses ``_enrich``.
        raw_d = ev["earnings_date"]
        d = pd.Timestamp(raw_d).date() if hasattr(raw_d, "to_pydatetime") else raw_d
        idx = (d - week_start).days
        if idx < 0 or idx > 4:
            continue
        band = str(ev.get("time_of_day") or "unknown").lower()
        if band not in buckets[idx]:
            band = "unknown"
        buckets[idx][band].append(ev)

    # Render columns side-by-side
    cols = st.columns(5)
    for i, col in enumerate(cols):
        day_date = week_start + timedelta(days=i)
        is_today = (day_date == date.today())
        with col:
            header_color = COLORS["accent"] if is_today else COLORS["label"]
            render_html(
                st,
                f'<div style="font-family:JetBrains Mono,monospace;'
                f'font-size:10px;letter-spacing:1.4px;text-transform:uppercase;'
                f'color:{header_color};margin-bottom:4px;font-weight:700;">'
                f'{_DAY_NAMES[i]} · {day_date.strftime("%b %d")}'
                f'{" · TODAY" if is_today else ""}'
                f'</div>',
            )
            n_events = sum(len(buckets[i][b]) for b in _BAND_ORDER)
            if n_events == 0:
                render_html(
                    st,
                    f'<div style="color:{COLORS["label"]};font-family:JetBrains Mono;'
                    f'font-size:10px;padding:8px 0;opacity:0.5;">—</div>',
                )
                continue
            for band in _BAND_ORDER:
                if not buckets[i][band]:
                    continue
                render_html(
                    st,
                    f'<div style="font-family:JetBrains Mono;font-size:8px;'
                    f'letter-spacing:1.3px;color:{COLORS["label"]};'
                    f'margin:8px 0 4px 0;border-top:1px dashed {COLORS["border"]};'
                    f'padding-top:4px;">{_BAND_LABEL[band]}</div>',
                )
                for ev in buckets[i][band]:
                    _render_tile(db, ev)


# ── Tile component ───────────────────────────────────────────────────

def _render_tile(db, ev: dict) -> None:
    ticker = str(ev["ticker"])
    impl = ev["implied"]
    crowd = ev["crowded"]
    crush = ev["crush"]
    rec = ev["recommendation"]
    company = ev.get("company_name")

    # Border-left color = strongest signal among the three
    border_color = COLORS["border"]
    if impl and impl.move_pct >= 8:
        border_color = seq_color(min(impl.move_pct, 15), 0, 15)
    elif crowd and crowd.percentile_today >= 75:
        border_color = seq_color(crowd.percentile_today, 0, 100)
    elif impl and impl.move_pct > 0:
        border_color = seq_color(min(impl.move_pct, 15), 0, 15)

    move_str = (
        f"±{impl.move_pct:.1f}%" if impl is not None else "± —"
    )
    upper_str = f"▲ +{impl.upper_pct:.1f}" if impl is not None else "—"
    lower_str = f"▼ {impl.lower_pct:.1f}" if impl is not None else "—"

    # Skew
    try:
        latest = db.get_ticker_history(ticker).iloc[-1]
        skew = float(latest.get("iv_skew_25d") or 0)
        iv_rank = float(latest.get("iv_rank") or 0)
    except Exception:
        skew = 0
        iv_rank = 0
    skew_color = (COLORS["warn"] if skew > 3
                    else COLORS["amber"] if abs(skew) > 1
                    else COLORS["muted"])
    skew_sign = "+" if skew >= 0 else "−"
    skew_str = f"skew {skew_sign}{abs(skew):.1f}pt"

    # Crowded badge
    crowd_str = "—"
    crowd_color = COLORS["muted"]
    crowd_bg = "transparent"
    if crowd is not None:
        crowd_str = f"crowd {crowd.score_today:.0f}"
        crowd_color = seq_color(crowd.percentile_today, 0, 100)
        if crowd.band == "exceptional":
            crowd_bg = f"{crowd_color}33"
            crowd_str = f"crowd {crowd.score_today:.0f} · top {100 - crowd.percentile_today:.0f}%"

    # Crush
    crush_str = "—"
    if crush is not None and getattr(crush, "n_events", 0) >= 3:
        crush_str = f"crush {crush.avg_crush_pct:+.0f}%"

    # Watchlist badge
    portfolio_badge = ""
    try:
        positions = db.get_positions(active_only=True)
        if positions is not None and not positions.empty:
            held = set(str(t).upper() for t in positions["ticker"].dropna().tolist())
            if ticker.upper() in held:
                portfolio_badge = (
                    f'<span style="background:{COLORS["accent"]}33;'
                    f'color:{COLORS["accent"]};padding:1px 5px;border-radius:3px;'
                    f'font-size:9px;font-weight:600;margin-left:4px;">▣</span>'
                )
    except Exception:
        pass

    # Time-of-day pill
    band = str(ev.get("time_of_day") or "unknown").lower()
    band_pill_color = (
        COLORS["accent2"] if band == "bmo"
        else COLORS["amber"] if band == "amc"
        else COLORS["muted"]
    )
    time_pill = f'<span style="color:{band_pill_color};font-weight:700;font-size:9px;">{band.upper()}</span>' \
                 if band != "unknown" else ""

    spot = impl.spot if impl else None
    spot_str = f"${spot:,.2f}" if spot is not None else "—"

    rec_label = rec.structure if rec is not None else "Wait"
    rec_color = (
        COLORS["accent"] if rec_label in ("Long Straddle", "Long Call")
        else COLORS["warn"] if rec_label in ("Short Iron Condor", "Long Put")
        else COLORS["muted"]
    )

    company_html = (
        f'<span style="font-family:DM Sans;font-size:9px;color:{COLORS["label"]};'
        f'margin-left:6px;">{escape(str(company))[:22]}</span>'
        if company and not pd.isna(company) else ""
    )

    html = f'''
<div class="vs-er-tile" style="border-left:3px solid {border_color};">
  <div class="vs-er-row1">
    <span class="vs-er-ticker">{escape(ticker)}</span>
    {portfolio_badge}
    {company_html}
    <span class="vs-er-spot">{spot_str}</span>
    {time_pill}
  </div>
  <div class="vs-er-row2">
    <span class="vs-er-move">{move_str}</span>
    <span class="vs-er-arrows">
      <span style="color:{COLORS["accent"]};">{upper_str}</span>
      <span style="color:{COLORS["warn"]};">{lower_str}</span>
    </span>
    <span class="vs-er-skew" style="color:{skew_color};">{skew_str}</span>
  </div>
  <div class="vs-er-row3">
    <span style="background:{crowd_bg};color:{crowd_color};padding:1px 5px;
           border-radius:3px;font-weight:600;">{crowd_str}</span>
    <span style="color:{COLORS["label"]};">IVR <strong style="color:{COLORS["text"]};">{iv_rank:.0f}</strong></span>
    <span style="color:{COLORS["amber"]};">{crush_str}</span>
  </div>
  <div class="vs-er-row4">
    <span class="vs-er-rec-label">{escape(rec_label)}</span>
    <span style="color:{rec_color};font-size:9px;">●</span>
  </div>
</div>'''
    render_html(st, html)

    # Click-to-expand via st.expander
    with st.expander(f"▾ details · {ticker}", expanded=False):
        _render_tile_drawer(db, ev)


# ── Detail drawer (E6) ───────────────────────────────────────────────

def _render_tile_drawer(db, ev: dict) -> None:
    """Drawer = 6 sub-cards: anomaly, calibration, drift, crowded,
    crush, recommendation (with backtest edge) + paper-buy CTA."""
    ticker = str(ev["ticker"])
    impl = ev["implied"]
    crowd = ev["crowded"]
    crush = ev["crush"]
    cal = ev["calibration"]
    rec = ev["recommendation"]
    er_date = ev["earnings_date"]

    # Pull ticker history once — reused by drift + anomaly + calibration
    try:
        history = db.get_ticker_history(ticker)
    except Exception:
        history = pd.DataFrame()

    # ── Anomaly badge (top of drawer) ───────────────────────────────
    anomaly = compute_anomaly_score(history, er_date)
    badge_html = render_anomaly_badge(anomaly)
    if badge_html:
        render_html(st, badge_html)

    # ── Auto-thesis (1-2 sentences trader-grade narrative) ──────────
    try:
        latest = history.iloc[-1]
        iv_rank = float(latest.get("iv_rank") or 0)
        skew = float(latest.get("iv_skew_25d") or 0)
    except Exception:
        iv_rank = 0
        skew = 0
    thesis_text = auto_thesis(
        ticker=ticker,
        implied_move_pct=getattr(impl, "move_pct", None),
        skew_pt=skew,
        crowded_band=getattr(crowd, "band", None),
        crowded_pct=getattr(crowd, "percentile_today", None),
        calibration_ratio=getattr(cal, "ratio", None),
        iv_rank=iv_rank,
        crush_avg_pct=getattr(crush, "avg_crush_pct", None),
        n_calibration_events=getattr(cal, "n_events", 0),
    )
    if thesis_text:
        render_html(
            st,
            f'<div style="background:{COLORS["card"]};border-left:3px solid '
            f'{COLORS["accent2"]};border-radius:6px;padding:10px 14px;margin:6px 0;'
            f'font-family:DM Sans,sans-serif;font-size:12px;color:{COLORS["text"]};'
            f'line-height:1.5;font-style:italic;">'
            f'<span style="font-size:9px;color:{COLORS["label"]};letter-spacing:1.3px;'
            f'text-transform:uppercase;font-style:normal;">thesis</span><br>'
            f'{escape(thesis_text)}'
            f'</div>',
        )

    # ── Calibration: implied-vs-realised history bar chart ──────────
    if cal is not None:
        # st.metric is forbidden (truncates) — use the KPI grid helper.
        render_html(
            st,
            kpi_grid_html(
                [
                    ("AVG IMPLIED", f"{cal.avg_implied_pct:.1f}%", None),
                    ("AVG REALISED", f"{cal.avg_realised_pct:.1f}%", None),
                    ("RATIO", f"{cal.ratio:.2f}×", None),
                    ("BAND", cal.band.upper(), None),
                ],
                variant="detail",
            ),
        )

        # Pull the per-event rows for the visual bar stack
        try:
            cal_df = db.con.execute(
                """
                SELECT earnings_date, last_implied_pct, last_reaction_pct
                FROM earnings
                WHERE ticker = ?
                  AND earnings_date < CURRENT_DATE
                  AND last_implied_pct IS NOT NULL
                  AND last_reaction_pct IS NOT NULL
                ORDER BY earnings_date DESC LIMIT 8
                """,
                [ticker],
            ).fetchdf()
            cal_rows = cal_df.to_dict("records") if not cal_df.empty else []
            cal_html = render_calibration_bar(cal_rows)
            if cal_html:
                render_html(st, cal_html)
        except Exception:
            pass
    else:
        st.caption("Calibration: insufficient history "
                    "(< 3 past earnings with both implied + realised)")

    # ── Pre-ER drift sparklines (spot + IV last 10d) ────────────────
    drift_html = render_pre_er_drift(history, er_date, days=10)
    if drift_html:
        render_html(st, drift_html)

    # ── Pre-ER crowded context ──────────────────────────────────────
    if crowd is not None:
        st.caption(
            f"Pre-ER crowded: score {crowd.score_today:.0f}, "
            f"percentile {crowd.percentile_today:.0f} ({crowd.band})  ·  "
            f"history median {crowd.historical_median:.0f}, "
            f"p75 {crowd.historical_p75:.0f}, p90 {crowd.historical_p90:.0f} "
            f"({crowd.historical_n_events} samples)"
        )

    # ── Crush estimate ──────────────────────────────────────────────
    if crush is not None and getattr(crush, "n_events", 0) >= 3:
        st.caption(
            f"Post-ER IV crush (historical avg): "
            f"{getattr(crush, 'avg_crush_pct', 0):.0f}% over "
            f"{getattr(crush, 'n_events', 0)} events"
        )

    # ── Recommendation + backtest edge ──────────────────────────────
    if rec is not None:
        if rec.structure != "Wait":
            badge_color = (
                COLORS["accent"] if rec.direction in ("long_vol", "bullish")
                else COLORS["warn"] if rec.direction in ("short_vol", "bearish")
                else COLORS["muted"]
            )

            # NEW — backtest edge for the recommended strategy
            bt = None
            edge_html_inner = ""
            if rec.template_name is not None:
                try:
                    bt = backtest_earnings_strategy(
                        db, ticker, rec.template_name, max_events=8,
                    )
                    if bt.n_events > 0:
                        edge_color = (
                            COLORS["accent"] if bt.hit_rate >= 0.6 and bt.mean_pl_pct > 0
                            else COLORS["amber"] if bt.hit_rate >= 0.45
                            else COLORS["warn"]
                        )
                        edge_html_inner = (
                            f'<div style="font-size:10px;color:{edge_color};'
                            f'background:{edge_color}1a;border-left:2px solid {edge_color};'
                            f'padding:6px 10px;margin-top:8px;border-radius:4px;'
                            f'font-family:JetBrains Mono,monospace;">'
                            f'{escape(edge_string(bt))}'
                            f'</div>'
                        )
                        # By-IV-rank bucket detail
                        if bt.by_iv_rank_bucket:
                            buckets_html = "  ".join(
                                f'<span style="color:{COLORS["label"]};">{k}</span> '
                                f'<strong style="color:{COLORS["text"]};">{v:+.0f}%</strong>'
                                for k, v in bt.by_iv_rank_bucket.items()
                            )
                            edge_html_inner += (
                                f'<div style="font-size:10px;color:{COLORS["muted"]};'
                                f'margin-top:4px;font-family:JetBrains Mono,monospace;'
                                f'line-height:1.6;">by IV-rank · {buckets_html}</div>'
                            )
                except Exception:
                    pass

            render_html(
                st,
                f'<div style="background:{COLORS["card"]};border:1px solid '
                f'{COLORS["border"]};border-left:3px solid {badge_color};'
                f'border-radius:6px;padding:10px 14px;margin-top:8px;'
                f'font-family:DM Sans,sans-serif;">'
                f'<div style="font-size:9px;letter-spacing:1.4px;'
                f'text-transform:uppercase;color:{COLORS["label"]};">'
                f'recommended structure · confidence {rec.confidence}</div>'
                f'<div style="font-size:14px;font-weight:700;color:{COLORS["text"]};'
                f'margin-top:4px;">{escape(rec.structure)}</div>'
                f'<div style="font-size:11px;color:{COLORS["muted"]};margin-top:6px;'
                f'line-height:1.5;">{escape(rec.thesis)}</div>'
                f'<div style="font-size:11px;color:{COLORS["amber"]};margin-top:6px;">'
                f'<strong>kills the trade:</strong> {escape(rec.kills_the_trade)}'
                f'</div>'
                f'{edge_html_inner}'
                f'</div>',
            )

        # (Paper-buy CTA removed in the IV-research refocus — Earnings Hub
        # is now a pure event/expected-move research view.)


# ── Sector heatmap footer ────────────────────────────────────────────

def _render_sector_heatmap(events: list[dict]) -> None:
    by_sector: dict[str, list[float]] = {}
    for ev in events:
        sec = ev.get("sector")
        move = getattr(ev["implied"], "move_pct", None)
        if not sec or pd.isna(sec) or move is None:
            continue
        by_sector.setdefault(str(sec), []).append(move)
    if not by_sector:
        return

    rows: list[tuple[str, float, int]] = []
    for sec, moves in by_sector.items():
        if len(moves) < 1:
            continue
        rows.append((sec, sum(moves) / len(moves), len(moves)))
    rows.sort(key=lambda r: -r[1])

    render_html(
        st,
        f'<div class="volscope-section-rule">'
        f'<span class="volscope-section-rule-label">SECTOR · MEDIAN IMPLIED MOVE</span>'
        f'<span class="volscope-section-rule-sub">'
        f'{len(rows)} sectors · {sum(r[2] for r in rows)} events</span></div>',
    )

    for sec, avg, n in rows:
        col = seq_color(min(avg, 15), 0, 15)
        bar_pct = min(100, int(avg * 8))
        render_html(
            st,
            f'<div style="display:flex;align-items:center;gap:10px;padding:5px 0;'
            f'border-bottom:1px solid {COLORS["border"]};font-family:JetBrains Mono;">'
            f'<div style="flex:0 0 180px;font-size:12px;color:{COLORS["text"]};">'
            f'{escape(sec)}</div>'
            f'<div style="flex:0 0 36px;color:{COLORS["muted"]};font-size:10px;">n={n}</div>'
            f'<div style="flex:1;background:{COLORS["border"]};height:6px;'
            f'border-radius:3px;"><div style="background:{col};height:6px;'
            f'width:{bar_pct}%;border-radius:3px;"></div></div>'
            f'<div style="flex:0 0 80px;text-align:right;font-size:12px;color:{col};'
            f'font-weight:600;">±{avg:.1f}%</div>'
            f'</div>',
        )
