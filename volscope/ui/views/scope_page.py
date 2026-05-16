"""Scope page — per-ticker IV/HV analysis, the hero page for a single name."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from volscope.analytics.backtest import (
    bootstrap_ci,
    build_calibration_table,
    naive_baseline_hit_rate,
    rolling_hit_rate,
    run_backtest,
)
from volscope.analytics.earnings_crush import compute_crush_estimate, crush_badge_html
from volscope.ui.components.chart_builders import (
    create_backtest_distribution_chart,
    create_backtest_hit_rate_chart,
    create_intraday_price_chart,
    create_iv_hv_chart,
    create_iv_range_bar,
    create_percentile_chart,
    create_skew_chart,
    create_spread_chart,
    create_term_structure_chart,
)
from volscope.ui.components.error_boundary import error_boundary
from volscope.ui.components.html_utils import page_banner_html, render_html
from volscope.ui.components.metric_components import (
    freshness_badge,
    render_iv_range_bar,
    render_iv_verdict_hero,
    render_kpi_row,
    render_ticker_header,
    render_warning_card,
)
from volscope.ui.components.status_bar import render_status_bar
from volscope.ui.styles.theme import COLORS
from volscope.utils.safe import is_missing, safe_str


def _render_header(st, db, ticker: str, latest: dict, history: pd.DataFrame) -> None:
    """IBKR-style header: symbol + price + day-change (left) | sector + freshness (right)."""
    try:
        name = db.get_company_name(ticker)
    except Exception:
        name = None
    if is_missing(name):
        name = safe_str(latest.get("company_name"))
    sector = safe_str(latest.get("sector"))

    # Day-over-day spot change — computed from the last two history rows
    # so we don't need an extra DB call. Returns None when only one row
    # exists (e.g. just-resolved ticker on first scrape).
    change = change_pct = None
    spot_now = latest.get("spot_price")
    try:
        if len(history) >= 2 and "spot_price" in history.columns:
            prev = history["spot_price"].iloc[-2]
            now = float(spot_now) if spot_now is not None else None
            if now is not None and prev is not None and not pd.isna(prev) and float(prev) != 0:
                change = now - float(prev)
                change_pct = (change / float(prev)) * 100.0
    except (TypeError, ValueError):
        pass

    fresh_label, fresh_color = freshness_badge(latest.get("date"))

    render_ticker_header(
        symbol=escape(ticker),
        name=escape(str(name)) if name else None,
        spot=spot_now,
        sector=escape(str(sector)) if sector else None,
        freshness_label=fresh_label,
        freshness_color=fresh_color,
        change=change,
        change_pct=change_pct,
    )


def _render_skew_metric(st, latest: dict) -> None:
    """Render the 25-delta skew metric if available."""
    skew = latest.get("iv_skew_25d")
    if skew is None:
        return
    try:
        skew_f = float(skew)
    except (TypeError, ValueError):
        return
    import math
    if math.isnan(skew_f):
        return

    mono = "JetBrains Mono, SF Mono, Menlo, monospace"
    if skew_f > 5.0:
        label, color = "RICH PUT SKEW — protection is expensive", COLORS["warn"]
    elif skew_f > 2.0:
        label, color = "elevated put skew", COLORS["amber"]
    elif skew_f < -2.0:
        label, color = "call skew — unusual for equities", COLORS["accent2"]
    else:
        label, color = "neutral skew", COLORS["muted"]

    sign = "+" if skew_f > 0 else ""
    # Demoted from 12 px hero to a 10 px secondary footnote — the 52-week
    # verdict above carries the headline.
    render_html(
        st,
        f'<div style="margin:2px 0 10px 0;font-family:{mono};font-size:10px;'
        f'color:{COLORS["label"]};">'
        f'25Δ skew · '
        f'<span style="color:{color};font-weight:600;">{sign}{skew_f:.1f}pt</span>'
        f'<span style="color:{COLORS["muted"]};margin-left:6px;">{label}</span>'
        f'</div>',
    )


def _earnings_list(db, ticker: str) -> list:
    try:
        df = db.get_upcoming_earnings(ticker, pd.Timestamp("1970-01-01").date())
    except Exception:
        return []
    if df is None or df.empty:
        return []
    try:
        return [pd.Timestamp(d).to_pydatetime() for d in df["earnings_date"]]
    except Exception:
        return []


_INTRADAY_CONFIG = {
    "1D":  {"period": "1d",  "interval": "5m",  "ttl": 60},
    "5D":  {"period": "5d",  "interval": "30m", "ttl": 300},
    "1M":  {"period": "1mo", "interval": "1d",  "ttl": 3600},
}


def _fetch_intraday_bars(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """Fetch OHLCV bars from yfinance. Returns empty DataFrame on failure."""
    try:
        import yfinance as yf
        bars = yf.Ticker(ticker).history(period=period, interval=interval)
        return bars if bars is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# Module-level cached wrappers — one per TTL so each timeframe has the correct
# refresh interval. Defined here (not inside _render_intraday_section) because
# @st.cache_data creates a new function object on every call if placed inside a
# function body, making the cache miss every time.
@st.cache_data(ttl=60, show_spinner=False)
def _bars_ttl60(ticker: str, period: str, interval: str) -> pd.DataFrame:
    return _fetch_intraday_bars(ticker, period, interval)


@st.cache_data(ttl=300, show_spinner=False)
def _bars_ttl300(ticker: str, period: str, interval: str) -> pd.DataFrame:
    return _fetch_intraday_bars(ticker, period, interval)


@st.cache_data(ttl=3600, show_spinner=False)
def _bars_ttl3600(ticker: str, period: str, interval: str) -> pd.DataFrame:
    return _fetch_intraday_bars(ticker, period, interval)


_CACHE_FN_BY_TTL: dict[int, object] = {
    60: _bars_ttl60,
    300: _bars_ttl300,
    3600: _bars_ttl3600,
}


def _render_intraday_section(st, ticker: str) -> None:
    """Show 1D / 5D / 1M price chart with volume bars below.

    Engine choice:
      • > 1D timeframes → TradingView Lightweight-Charts (candles +
        volume pane + crosshair) via ``lwc_chart.price_chart_lwc``.
      • 1D intraday → Plotly fallback (LWC handles daily bars; the
        intraday-minute series shape doesn't suit it).
    """
    render_html(
        st,
        f'<div style="margin-top:16px;margin-bottom:4px;'
        f'font-family:\'DM Sans\',sans-serif;font-size:11px;'
        f'color:{COLORS["muted"]};letter-spacing:0.02em;font-weight:500;">'
        f'INTRADAY · 1D / 5D / 1M</div>',
    )

    tf = st.radio(
        "Timeframe",
        list(_INTRADAY_CONFIG.keys()),
        index=0,
        horizontal=True,
        key=f"scope_tf_{ticker}",
        label_visibility="collapsed",
    )

    cfg = _INTRADAY_CONFIG[tf]
    cached_fn = _CACHE_FN_BY_TTL[cfg["ttl"]]
    bars = cached_fn(ticker, cfg["period"], cfg["interval"])  # type: ignore[operator]

    with error_boundary(st, f"Intraday price chart [{tf}]"):
        fig = create_intraday_price_chart(bars, ticker, timeframe=tf)
        st.plotly_chart(fig, width='stretch')


def _render_history_price_lwc(
    st,
    ticker: str,
    history,
    earnings_dates: list | None = None,
) -> None:
    """TradingView-feel daily candlestick chart on top of the page.

    Renders the full available history as candles + a volume sub-pane
    + a dashed IV-30 overlay on a second price scale + earnings
    markers (passed in from ``_earnings_list``, not re-derived).

    Why this exists separately from ``_render_intraday_section``:
        • Daily history (multi-year) → Lightweight-Charts: candles,
          range navigation, crosshair, drag-to-zoom.
        • Intraday minute bars (1D / 5D / 1M) → Plotly stays;
          Lightweight-Charts is built around daily / business-day
          spacing and minute-granularity needs special handling we
          don't ship in v0.7.0.
    """
    from volscope.ui.components.lwc_chart import (
        fetch_daily_ohlcv, price_chart_lwc, render_lwc_safe,
    )

    # Empty / one-row history is a no-op — caller renders an
    # IBKR-style "No data" card upstream.
    if history is None or history.empty:
        return

    # Range selector — default 5y for cycle context; max gives the
    # full yfinance-available history (typically 20+ years for the
    # big-cap names). yfinance caches each (ticker, period) pair so
    # toggling is cheap after first fetch.
    _range_opts = ["1y", "2y", "5y", "10y", "max"]
    _range_pick = st.radio(
        "History range",
        _range_opts,
        index=2,
        horizontal=True,
        key=f"scope_hist_range_{ticker}",
        label_visibility="collapsed",
    )

    # daily_vol carries only the close (spot_price). Real candles +
    # volume require a separate OHLCV source — pulled from yfinance
    # via a 1-hour-cached helper. On failure the fallback inside
    # ``price_chart_lwc`` synthesises a flat-OHLC line from history.
    ohlcv = fetch_daily_ohlcv(ticker, period=_range_pick)

    spec, key = price_chart_lwc(
        history,
        ohlcv=ohlcv,
        height=380,
        with_volume=True,
        with_iv_overlay=True,
        with_regime_shading=False,
        earnings_dates=earnings_dates or [],
        title=f"{ticker} · {_range_pick.upper()}",
    )
    if not spec:
        return

    render_html(
        st,
        f'<div style="margin-top:18px;margin-bottom:6px;'
        f'font-family:\'DM Sans\',sans-serif;font-size:11px;'
        f'color:{COLORS["muted"]};letter-spacing:0.02em;font-weight:500;">'
        f'DAILY · CANDLES · VOLUME · IV30 OVERLAY</div>',
    )
    with error_boundary(st, "TradingView price chart"):
        ok = render_lwc_safe(spec, key=f"{key}_{ticker}")
        if not ok:
            render_html(
                st,
                f'<div style="color:{COLORS["muted"]};font-size:11px;'
                f'font-family:\'DM Sans\',sans-serif;">'
                f'TradingView candles unavailable — the intraday '
                f'view below still renders.</div>',
            )


def render_scope_page(db, ticker: str, settings: dict | None = None) -> None:
    import streamlit as st

    # v0.9.0 — persistent vol-regime header strip.
    from volscope.ui.components.regime_header import render_regime_header
    render_regime_header(db)
    # v0.9.7 — phase strip (master plan §2)
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name="Scope", ticker=ticker)

    render_html(
        st,
        page_banner_html(
            title="Scope",
            what="single-ticker deep dive: IV/HV + skew + 52w range",
            when="after Discover surfaces a name",
        ),
    )

    history = db.get_ticker_history(ticker)
    if history.empty:
        render_warning_card(
            st,
            title=f"No data for {escape(ticker)}",
            body=(
                "Use the <strong>Add ticker</strong> box in the sidebar, "
                "or run <code>make seed</code> / <code>make scrape</code> to "
                "populate the database."
            ),
        )
        return

    latest = history.iloc[-1].to_dict()
    # v3 (2026-05-13): data-freshness bar shown before the status bar so
    # the trader knows immediately whether the numbers below are current.
    from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
    render_data_freshness_bar(db, compact=True)

    # v3: pinned status bar — IBKR-style symbol/price/IV/HV/Rank/Perc strip
    try:
        company_name = db.get_company_name(ticker)
    except Exception:
        company_name = None
    sector = latest.get("sector")
    # Days to earnings — try the existing earnings table
    days_to_er = None
    try:
        df_er = db.get_upcoming_earnings(ticker, pd.Timestamp("1970-01-01").date())
        if df_er is not None and not df_er.empty:
            future = df_er[pd.to_datetime(df_er["earnings_date"]) >= pd.Timestamp.today().normalize()]
            if not future.empty:
                days_to_er = int((pd.to_datetime(future["earnings_date"].iloc[0])
                                   - pd.Timestamp.today().normalize()).days)
    except Exception:
        pass
    render_status_bar(
        ticker=ticker,
        history=history,
        company_name=company_name if company_name else None,
        sector=sector if sector and not pd.isna(sector) else None,
        days_to_earnings=days_to_er,
    )

    # v0.9.8 Phase D — cross-tool awareness cards. Renders zero or
    # more of: open positions / upcoming earnings / discover history
    # for this ticker. Renders nothing if none of the three apply.
    try:
        from volscope.ui.components.scope_context_cards import (
            render_scope_context_cards,
        )
        render_scope_context_cards(st, db, ticker)
    except Exception as _ctx_exc:                                  # noqa: BLE001
        import logging as _lg
        _lg.getLogger("volscope.ui.scope").debug(
            "context-cards failed: %s", _ctx_exc,
        )

    # Phase-4 — VOL_INDEX / VOL_PRODUCT gating. Vol indices are derived
    # data (not directly tradable) so the CHEAP/RICH verdict makes no
    # sense for them. Vol products (VXX/UVXY/SVXY/VIXY) carry structural
    # contango drag — long holds bleed regardless of spot vol move, so
    # the operator gets an amber warning before any sizing decision.
    from volscope.data.symbol_types import is_vol_index, is_vol_product
    _is_vol_idx = is_vol_index(ticker)
    _is_vol_prod = is_vol_product(ticker)
    if _is_vol_idx:
        render_html(
            st,
            f'<div style="background:{COLORS["surface"]};border:1px solid {COLORS["border"]};'
            f'border-left:3px solid {COLORS["accent"]};border-radius:6px;padding:12px 16px;'
            f'margin:8px 0 12px;font-family:DM Sans,sans-serif;font-size:12px;">'
            f'<span style="color:{COLORS["accent"]};font-weight:700;letter-spacing:0.5px;">'
            f'VOLATILITY INDEX</span>'
            f'<span style="color:{COLORS["muted"]};margin-left:12px;">'
            f'Derived data — not directly tradable. CHEAP/RICH verdicts do '
            f'not apply; use the term-structure + history below for context, '
            f'or trade exposure via the matching vol product (e.g. VXX for '
            f'^VIX, UVXY for leveraged term-structure plays).'
            f'</span></div>',
        )
    if _is_vol_prod:
        render_html(
            st,
            f'<div style="background:{COLORS["surface"]};border:1px solid {COLORS["border"]};'
            f'border-left:3px solid {COLORS["amber"]};border-radius:6px;padding:12px 16px;'
            f'margin:8px 0 12px;font-family:DM Sans,sans-serif;font-size:12px;">'
            f'<span style="color:{COLORS["amber"]};font-weight:700;letter-spacing:0.5px;">'
            f'⚠ STRUCTURAL CONTANGO DRAG</span>'
            f'<span style="color:{COLORS["muted"]};margin-left:12px;">'
            f'Long {escape(ticker)} loses value to roll-cost during normal '
            f'contango regimes regardless of spot-vol direction. Hold horizons '
            f'beyond ~5 trading days carry a measurable bleed — size and time '
            f'entries accordingly. Inverse products (SVXY) reverse the sign.'
            f'</span></div>',
        )

    _render_header(st, db, ticker, latest, history)
    # v0.6.1 — IV quality warning banner (FISV-class single-spike
    # contamination). Renders ABOVE the headline KPIs so the operator
    # sees the verdict before any IVR / IVP / "CHEAP" claim below it.
    from volscope.ui.components.iv_quality_banner import (
        render_iv_quality_banner,
    )
    if not _is_vol_idx:
        render_iv_quality_banner(st, latest)
    # 52-week IV verdict — the single most actionable read on this page.
    # Sits directly under the header so the user knows in 1 second whether
    # to even keep scrolling. Suppressed for vol indices (derived data).
    if not _is_vol_idx:
        render_iv_verdict_hero(history)
    render_kpi_row(latest)
    _render_skew_metric(st, latest)

    # Legacy-flat-spread detection + banner is gone — the auto-migration
    # in VolScopeDB.__init__ silently recomputes any legacy rows on every
    # DB open, so the user never sees the broken state.

    earnings = _earnings_list(db, ticker)

    # Earnings crush estimate — shown below header when upcoming ER exists
    try:
        crush_est = compute_crush_estimate(db, ticker)
        badge = crush_badge_html(crush_est)
        if badge:
            crush_detail = ""
            if crush_est.avg_crush_pct is not None and crush_est.n_events > 0:
                sign = "+" if crush_est.avg_crush_pct > 0 else ""
                crush_detail = (
                    f'  <span style="color:{COLORS["muted"]};font-size:10px;font-family:'
                    f'JetBrains Mono,monospace;">'
                    f'Historical crush: avg {sign}{crush_est.avg_crush_pct:.0f}%'
                    f', range {crush_est.min_crush_pct:.0f}% to {crush_est.max_crush_pct:.0f}%'
                    f' ({crush_est.n_events} events)'
                    f'</span>'
                )
            render_html(st, f'<div style="margin-bottom:10px;">{badge}{crush_detail}</div>')
    except Exception:
        pass

    # Determine which optional data is available so we only show populated charts.
    latest_row = history.iloc[-1]
    _term_pts = [(d, latest_row.get(c)) for d, c in
                 ((30, "iv_30d"), (60, "iv_60d"), (90, "iv_90d"), (180, "iv_180d"))]
    has_term_structure = sum(1 for _, v in _term_pts if v is not None and v == v) >= 2
    has_skew = (
        "iv_skew_25d" in history.columns
        and history["iv_skew_25d"].notna().any()
    )

    # Tabbed layout — vol / price / backtest. Reduces vertical scroll
    # from 6 stacked charts to 3 grouped views. Default tab = Vol View
    # because that's the workhorse view for vol traders.
    tab_vol, tab_price, tab_backtest = st.tabs([
        "📈 Vol View",
        "💲 Price View",
        "▣ Backtest",
    ])

    with tab_vol:
        # Compact HTML 52-week range bar — full-width above whatever follows.
        with error_boundary(st, "52-Week IV Range"):
            render_iv_range_bar(history)

        if has_term_structure:
            with error_boundary(st, "IV Term Structure"):
                st.plotly_chart(
                    create_term_structure_chart(history), width='stretch'
                )
        else:
            render_html(
                st,
                f'<div style="background:{COLORS["surface"]};border:1px solid {COLORS["border"]};'
                f'border-left:3px solid {COLORS["amber"]};border-radius:6px;padding:10px 14px;'
                f'margin-bottom:12px;font-family:JetBrains Mono,monospace;font-size:11px;">'
                f'<span style="color:{COLORS["amber"]};font-weight:600;">⚠ Seed-only data</span>'
                f'<span style="color:{COLORS["muted"]};margin-left:10px;">'
                f'IV 60d / 90d / 180d not yet scraped — run '
                f'<code style="background:{COLORS["border"]};padding:1px 5px;border-radius:3px;">'
                f'make scrape</code> to populate the full term structure'
                f'</span></div>',
            )
        with error_boundary(st, "IV vs HV chart"):
            st.plotly_chart(
                create_iv_hv_chart(history, ticker, earnings_dates=earnings),
                width='stretch',
            )
        with error_boundary(st, "IV-HV Spread chart"):
            st.plotly_chart(
                create_spread_chart(history, earnings_dates=earnings),
                width='stretch',
            )
        with error_boundary(st, "IV Percentile chart"):
            st.plotly_chart(
                create_percentile_chart(history, earnings_dates=earnings),
                width='stretch',
            )

    with tab_price:
        _render_history_price_lwc(st, ticker, history, earnings_dates=earnings)
        _render_intraday_section(st, ticker)
        if has_skew:
            with error_boundary(st, "25Δ Skew chart"):
                st.plotly_chart(create_skew_chart(history), width='stretch')
        # Inline action: open Pre-Trade for this ticker
        if st.button(
            f"▷ Open Pre-Trade for {ticker}",
            key=f"scope_pretrade_{ticker}",
            help="Build a strategy + Greeks for this ticker.",
        ):
            from volscope.ui.components.navigation import NavIntent, nav_to
            nav_to(NavIntent(page="Pre-Trade", ticker=ticker, source="Scope"))
            st.rerun()

    with tab_backtest:
        _render_backtest_section(st, history, ticker)

    # v0.9.7 — cross-page weave footer
    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(st, page="Scope", ticker=ticker)


def _render_backtest_section(st, history: pd.DataFrame, ticker: str) -> None:
    """
    Production-grade backtest panel.

    Headline KPIs above tabs:
      • BUY signal hit-rate vs. naive long-vol baseline (with Δ)
      • Bootstrap 95 % CI on the BUY-signal mean IV change
      • Verdict pill — BEATS BASELINE / IN LINE / WEAK
    """
    # Hold-period selector — preset buttons mean the user can probe the
    # signal at multiple horizons without typing.
    hold_options = [5, 10, 21, 42, 63]
    hold = st.radio(
        "Hold period (trading days)",
        hold_options,
        index=1,
        horizontal=True,
        key=f"scope_backtest_hold_{ticker}",
        label_visibility="collapsed",
    )

    result = run_backtest(history, ticker=ticker, hold_days=int(hold))
    if result is None:
        render_html(
            st,
            f'<div style="color:{COLORS["muted"]};font-family:JetBrains Mono,monospace;'
            f'font-size:12px;padding:8px 0;">'
            f'Not enough history to backtest (need ≥30 rows). '
            f'Run <code>make scrape</code> to accumulate daily data.</div>',
        )
        return

    # ── Headline KPIs ───────────────────────────────────────────────
    sig_df = result.signals_df
    buy_df = sig_df[sig_df["signal_cat"].isin(["buy", "lean_buy"])]
    buy_hit = result.hit_rates.get("buy", float("nan"))
    naive = naive_baseline_hit_rate(sig_df)
    n_buy = result.n_signals.get("buy", 0) + result.n_signals.get("lean_buy", 0)

    point, lo, hi = (float("nan"), float("nan"), float("nan"))
    if not buy_df.empty and "iv_change_pct" in buy_df.columns:
        point, lo, hi = bootstrap_ci(buy_df["iv_change_pct"].dropna().tolist())

    # Verdict — BUY signal must hit at least 5pp above the naive baseline
    # AND the 95 % CI on its mean must exclude zero in the *long-vol*
    # direction (negative IV change = win).
    import math
    if (
        not math.isnan(buy_hit)
        and not math.isnan(naive)
        and buy_hit >= naive + 0.05
        and not math.isnan(hi)
        and hi < 0
    ):
        verdict_label, verdict_class = "BEATS BASELINE", "fg-cheap"
        verdict_cell = "is-cheap"
    elif not math.isnan(buy_hit) and not math.isnan(naive) and buy_hit >= naive - 0.05:
        verdict_label, verdict_class = "IN LINE", "fg-warn"
        verdict_cell = "is-warning"
    else:
        verdict_label, verdict_class = "WEAK", "fg-rich"
        verdict_cell = "is-rich"

    def _pct(x: float) -> str:
        return f"{x*100:.0f}%" if not math.isnan(x) else "—"

    def _delta(x: float) -> str:
        return f"{x:+.1f}%" if not math.isnan(x) else "—"

    delta_vs_naive = (
        f"{(buy_hit - naive) * 100:+.0f}pp"
        if not (math.isnan(buy_hit) or math.isnan(naive)) else "—"
    )
    ci_str = f"[{lo:+.1f}%, {hi:+.1f}%]" if not math.isnan(lo) else "—"

    from volscope.ui.components.metric_components import _ibkr_cell
    cells = [
        _ibkr_cell("HOLD",          f"{result.hold_days}d"),
        _ibkr_cell("N TOTAL",       f"{result.n_total}"),
        _ibkr_cell("BUY SIGNALS",   f"{n_buy}"),
        _ibkr_cell("BUY HIT",       _pct(buy_hit), value_class="fg-cheap"),
        _ibkr_cell("NAIVE BASE",    _pct(naive)),
        _ibkr_cell("Δ VS BASE",     delta_vs_naive,
                   value_class=("fg-cheap" if "+" in delta_vs_naive else "fg-rich")),
        _ibkr_cell("VERDICT",       verdict_label,
                   value_class=verdict_class, cell_class=verdict_cell),
    ]
    render_html(
        st,
        '<div class="volscope-ibkr-row">' + "".join(cells) + "</div>",
    )

    # ── Bootstrap CI explainer ──────────────────────────────────────
    if not math.isnan(point):
        ci_color = COLORS["accent"] if hi < 0 else COLORS["warn"] if lo > 0 else COLORS["amber"]
        render_html(
            st,
            f'<div style="font-family:JetBrains Mono,monospace;font-size:11px;'
            f'color:{COLORS["muted"]};margin:4px 0 10px 0;">'
            f'Mean BUY-signal IV change over {result.hold_days}d: '
            f'<strong style="color:{COLORS["text"]};">{_delta(point)}</strong> '
            f'· 95 %&nbsp;CI <span style="color:{ci_color};">{ci_str}</span> '
            f'<span style="color:{COLORS["label"]};">'
            f'(negative = vol fell as predicted)'
            f'</span>'
            f'</div>',
        )

    # ── Calibration table ───────────────────────────────────────────
    cal = build_calibration_table(result)
    if not cal.empty:
        st.dataframe(cal, width='stretch', hide_index=True)

    # ── Charts ──────────────────────────────────────────────────────
    rhr = rolling_hit_rate(result.signals_df)
    with error_boundary(st, "Rolling hit rate chart"):
        st.plotly_chart(
            create_backtest_hit_rate_chart(rhr), width='stretch'
        )
    with error_boundary(st, "IV change distribution chart"):
        st.plotly_chart(
            create_backtest_distribution_chart(result.signals_df),
            width='stretch',
        )
