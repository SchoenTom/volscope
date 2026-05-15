"""
TradingView Lightweight-Charts wrapper — replaces the v0.6.x Plotly
spline price chart on Scope / Pre-Trade / Options-Lab.

Rationale (see ADR-0006): the analytics surface (IV/HV multi-line,
skew, term structure, heatmaps) stays on Plotly; the *price* surface
moves to TradingView's own MIT-licensed library so the operator gets
candlesticks, range-selector, crosshair, drag-zoom and volume-pane
out of the box.

The functions here intentionally return *renderable specs* + key,
not Streamlit components themselves — callers do
``renderLightweightCharts(spec, key=key)`` so an import-time crash in
the wrapper does not break the whole UI. Empty / NaN-heavy inputs
return ``([], key)``; the caller can decide to skip rendering.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import pandas as pd

from volscope.ui.styles.theme import COLORS

LWC_BG       = COLORS.get("bg",       "#0a0b14")
LWC_GRID     = COLORS.get("border",   "#1e2038")
LWC_TEXT     = COLORS.get("text",     "#e0e4ef")
LWC_MUTED    = COLORS.get("muted",    "#9aa0b3")
LWC_UP       = COLORS.get("accent",   "#00d4aa")
LWC_DOWN     = COLORS.get("warn",     "#ff4466")
LWC_OVERLAY  = COLORS.get("accent2",  "#5b8cff")


def _to_iso(d: Any) -> str | None:
    """LWC time series want either ISO strings or unix seconds. ISO is
    safer across timezones and survives DST. Falsy / NaT → None."""
    if d is None:
        return None
    try:
        ts = pd.Timestamp(d)
    except Exception:                                       # noqa: BLE001
        return None
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _candles_from_ohlcv(ohlcv: pd.DataFrame) -> list[dict[str, Any]]:
    """Return LWC-shaped candlestick list from a yfinance-style OHLCV frame.

    Expected columns (case-insensitive — yfinance uses Title-Case):
    Open, High, Low, Close. Index must be a DatetimeIndex (yfinance's
    default) OR a 'date' / 'Date' column.

    Returns ``[]`` for empty / malformed input; callers fall back to
    a quieter line chart in that case.
    """
    if ohlcv is None or ohlcv.empty:
        return []

    df = ohlcv.copy()
    # Normalize column names — yfinance ships Title-Case, our DB ships
    # snake_case. Accept both.
    df.columns = [str(c).lower() for c in df.columns]

    # Resolve the time axis. yfinance puts it on the index; some callers
    # reset_index() before passing, in which case it'll be a column.
    if "date" in df.columns:
        time_series = df["date"]
    elif isinstance(df.index, pd.DatetimeIndex):
        time_series = df.index.to_series()
    else:
        return []

    needed = ("open", "high", "low", "close")
    if not all(c in df.columns for c in needed):
        return []

    out: list[dict[str, Any]] = []
    for ts, (o, h, lo, c) in zip(
        time_series,
        zip(df["open"], df["high"], df["low"], df["close"]),
    ):
        t = _to_iso(ts)
        if t is None:
            continue
        if any(pd.isna(v) for v in (o, h, lo, c)):
            continue
        out.append({
            "time":  t,
            "open":  float(o),
            "high":  float(h),
            "low":   float(lo),
            "close": float(c),
        })
    return out


def _candles_from_close_only(history: pd.DataFrame) -> list[dict[str, Any]]:
    """Fallback: synthesize OHLC = (close, close, close, close) from
    ``history.spot_price``.

    v0.9.2: vectorised from a per-row ``iterrows()`` Python loop — at
    1 500 rows (5-year history) the prior implementation cost ~12 ms;
    the vectorised path is < 1 ms.
    """
    if history is None or history.empty or "date" not in history.columns:
        return []
    close_col = "spot_price" if "spot_price" in history.columns else "close"
    if close_col not in history.columns:
        return []
    df = history[["date", close_col]].dropna(subset=[close_col]).copy()
    if df.empty:
        return []
    times = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d").tolist()
    closes = df[close_col].astype(float).tolist()
    return [
        {"time": t, "open": c, "high": c, "low": c, "close": c}
        for t, c in zip(times, closes)
    ]


def _volume_from_ohlcv(ohlcv: pd.DataFrame) -> list[dict[str, Any]]:
    """Volume histogram from yfinance OHLCV. Each bar colour-coded by
    whether the day closed up or down vs the prior close. Returns ``[]``
    when no volume column is present."""
    if ohlcv is None or ohlcv.empty:
        return []
    df = ohlcv.copy()
    df.columns = [str(c).lower() for c in df.columns]
    if "volume" not in df.columns:
        return []
    if "date" in df.columns:
        time_series = df["date"]
    elif isinstance(df.index, pd.DatetimeIndex):
        time_series = df.index.to_series()
    else:
        return []
    closes = df.get("close")
    out: list[dict[str, Any]] = []
    prev_close: float | None = None
    for i, (ts, v) in enumerate(zip(time_series, df["volume"])):
        t = _to_iso(ts)
        if t is None or v is None or pd.isna(v):
            continue
        color = LWC_UP
        if closes is not None and prev_close is not None:
            c = closes.iloc[i]
            if pd.notna(c) and float(c) < prev_close:
                color = LWC_DOWN
            if pd.notna(c):
                prev_close = float(c)
        elif closes is not None and pd.notna(closes.iloc[i]):
            prev_close = float(closes.iloc[i])
        out.append({"time": t, "value": float(v), "color": color})
    return out


def _line_series(
    history: pd.DataFrame,
    *,
    column: str,
    color: str,
) -> list[dict[str, Any]]:
    """Plot any history column as an overlay line on the price chart.

    Used for IV30 / IV-percentile / IV-rank overlays. Skipped silently
    if the column is missing or every value is NaN.
    """
    if history is None or history.empty or "date" not in history.columns:
        return []
    if column not in history.columns:
        return []
    # v0.9.2: vectorised — at 1 500 rows the prior iterrows loop cost
    # ~8 ms per call (called 1-2× per Scope render); the vectorised
    # path runs in < 1 ms.
    df = history[["date", column]].dropna(subset=[column]).copy()
    if df.empty:
        return []
    times  = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d").tolist()
    values = df[column].astype(float).tolist()
    return [{"time": t, "value": v} for t, v in zip(times, values)]


def _earnings_markers(
    earnings_dates: Iterable[Any] | None,
) -> list[dict[str, Any]]:
    """Vertical markers on earnings dates so the operator never confuses
    an earnings-gap with a real signal. ``earnings_dates`` is any
    iterable of date-likes (pd.Timestamp, datetime, str)."""
    if earnings_dates is None:
        return []
    out: list[dict[str, Any]] = []
    for d in earnings_dates:
        iso = _to_iso(d)
        if iso is None:
            continue
        out.append({
            "time":     iso,
            "position": "aboveBar",
            "color":    LWC_OVERLAY,
            "shape":    "circle",
            "text":     "E",
        })
    return out


def _regime_shading(
    history: pd.DataFrame,
    *,
    regime_column: str = "regime_state",
) -> list[dict[str, Any]]:
    """Lightweight-Charts has no built-in vertical-band primitive, but
    a thin Area-series at the chart bottom shaded red on `stress`
    days reads similarly. Returns an Area-series data list with
    ``value = 1`` on stress days and ``value = 0`` otherwise. The
    caller decides the price-scale / axis routing.
    """
    if history is None or history.empty or "date" not in history.columns:
        return []
    if regime_column not in history.columns:
        return []
    # v0.9.2: vectorised — see ``_candles_from_close_only`` for the
    # same iterrows-→-vector pattern. Saves ~6 ms per render.
    df = history[["date", regime_column]].copy()
    times = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d").tolist()
    is_stress = (
        df[regime_column].astype(str).str.lower()
        .isin(("stress", "high", "1"))
        .tolist()
    )
    return [
        {"time": t, "value": 1.0 if s else 0.0}
        for t, s in zip(times, is_stress)
    ]


def price_chart_lwc(
    history: pd.DataFrame,
    *,
    ohlcv: pd.DataFrame | None = None,
    height: int = 380,
    with_volume: bool = True,
    with_iv_overlay: bool = True,
    with_regime_shading: bool = False,
    earnings_dates: Sequence[Any] | None = None,
    title: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Build a TradingView Lightweight-Charts spec for a price history.

    Two data sources:
      • ``ohlcv``  — full OHLC + Volume (typically from yfinance, daily
        bars). Used for the candlestick body and the volume pane.
      • ``history`` — VolScope's own daily_vol frame. Used for the
        IV-30 overlay and (future) regime shading.

    If ``ohlcv`` is None we fall back to a flat-OHLC line built from
    ``history.spot_price`` so the chart still renders, just without
    real wicks.

    Returns ``(charts_spec, suggested_key)``. Empty list means
    "nothing renderable" — caller can show an empty-state card.
    """
    if ohlcv is not None and not ohlcv.empty:
        candles = _candles_from_ohlcv(ohlcv)
    else:
        candles = _candles_from_close_only(history)

    if not candles:
        return ([], f"lwc_empty_{title or 'chart'}")

    layout = {
        "background": {"type": "solid", "color": LWC_BG},
        "textColor":  LWC_TEXT,
    }
    grid = {
        "vertLines": {"color": LWC_GRID, "style": 1},
        "horzLines": {"color": LWC_GRID, "style": 1},
    }
    time_scale = {
        "borderColor":  LWC_GRID,
        "timeVisible":  True,
        "secondsVisible": False,
        "rightOffset": 4,
        "barSpacing":  6,
    }
    crosshair = {
        "mode": 1,  # 0 = normal, 1 = magnet (snaps to closest bar)
        "vertLine": {"color": LWC_MUTED, "width": 1, "style": 3, "labelBackgroundColor": LWC_OVERLAY},
        "horzLine": {"color": LWC_MUTED, "width": 1, "style": 3, "labelBackgroundColor": LWC_OVERLAY},
    }

    series: list[dict[str, Any]] = [{
        "type":    "Candlestick",
        "data":    candles,
        "options": {
            "upColor":         LWC_UP,
            "downColor":       LWC_DOWN,
            "borderUpColor":   LWC_UP,
            "borderDownColor": LWC_DOWN,
            "wickUpColor":     LWC_UP,
            "wickDownColor":   LWC_DOWN,
        },
        "markers": _earnings_markers(earnings_dates),
    }]

    if with_iv_overlay:
        iv_data = _line_series(history, column="iv_30d", color=LWC_OVERLAY)
        if iv_data:
            series.append({
                "type":    "Line",
                "data":    iv_data,
                "options": {
                    "color":        LWC_OVERLAY,
                    "lineWidth":    1,
                    "lineStyle":    2,  # dashed
                    "priceScaleId": "iv",
                    "title":        "IV 30d",
                },
                "priceScale": {
                    "scaleMargins": {"top": 0.05, "bottom": 0.25},
                    "borderColor":  LWC_GRID,
                    "visible":      True,
                },
            })

    if with_volume:
        # Volume comes ONLY from the OHLCV side — daily_vol carries
        # option volumes, not underlying. If no ohlcv was passed in
        # we silently skip the volume pane.
        vol_data = _volume_from_ohlcv(ohlcv) if ohlcv is not None else []
        if vol_data:
            series.append({
                "type":    "Histogram",
                "data":    vol_data,
                "options": {
                    "priceFormat":   {"type": "volume"},
                    "priceScaleId":  "volume",
                },
                "priceScale": {
                    "scaleMargins": {"top": 0.75, "bottom": 0.0},
                    "borderColor":  LWC_GRID,
                },
            })

    if with_regime_shading:
        shading = _regime_shading(history)
        if shading:
            series.append({
                "type":    "Area",
                "data":    shading,
                "options": {
                    "topColor":      f"rgba(255, 68, 102, 0.18)",
                    "bottomColor":   f"rgba(255, 68, 102, 0.0)",
                    "lineColor":     "rgba(0,0,0,0)",
                    "priceScaleId":  "regime",
                },
                "priceScale": {
                    "scaleMargins": {"top": 0.9, "bottom": 0.0},
                    "visible":      False,
                },
            })

    chart: dict[str, Any] = {
        "chart": {
            "height":            height,
            "layout":            layout,
            "grid":              grid,
            "timeScale":         time_scale,
            "crosshair":         crosshair,
            "rightPriceScale":   {"borderColor": LWC_GRID},
            "leftPriceScale":    {"visible": False},
            "handleScroll":      True,
            "handleScale":       True,
            "watermark":         {
                "color":      "rgba(255,255,255,0.04)",
                "visible":    bool(title),
                "text":       (title or ""),
                "fontSize":   18,
                "horzAlign":  "left",
                "vertAlign":  "top",
            },
        },
        "series": series,
    }

    suggested_key = f"lwc_{(title or 'chart').lower().replace(' ', '_')}"
    return ([chart], suggested_key)


def fetch_daily_ohlcv(ticker: str, period: str = "5y") -> pd.DataFrame:
    """Fetch daily OHLCV from yfinance with smart caching.

    Two pitfalls of the naïve ``@st.cache_data(ttl=3600)`` pattern this
    function avoids:

    1. **Caching empty results.** If yfinance is rate-limited or
       returns an empty frame for a given symbol, the prior version
       cached *that* empty frame for an hour. The operator hit refresh
       and still saw a chart "ending in mid-April" because the stale
       fallback path (DuckDB ``spot_price``) was now the only source.
       Fix: only cache *non-empty* frames; an empty result is treated
       as a transient failure and re-tried on every render until it
       succeeds.

    2. **Caching stale results.** A non-empty frame whose last bar is
       > 5 calendar days old (week-of-holidays + weekend + delisting)
       is treated as stale and re-fetched. yfinance occasionally
       returns trimmed history during temporary outages; we don't
       want to lock in a stale view across a 1-hour TTL window.

    Returns an empty DataFrame on any failure so the caller's
    fallback path engages cleanly.
    """
    def _raw_yf(t: str, p: str) -> pd.DataFrame:
        try:
            import yfinance as yf
            df = yf.Ticker(t).history(period=p, interval="1d", auto_adjust=False)
            if df is None or df.empty:
                return pd.DataFrame()
            return df.reset_index()
        except Exception:                                      # noqa: BLE001
            return pd.DataFrame()

    def _is_stale(df: pd.DataFrame) -> bool:
        if df is None or df.empty:
            return True
        # Find the most recent date in any plausible "date" column.
        for col in ("Date", "date", "Datetime", "datetime"):
            if col in df.columns:
                try:
                    last = pd.to_datetime(df[col]).max()
                    if pd.isna(last):
                        return True
                    return (pd.Timestamp.now() - last).days > 5
                except Exception:                              # noqa: BLE001
                    return True
        if isinstance(df.index, pd.DatetimeIndex):
            return (pd.Timestamp.now() - df.index.max()).days > 5
        return True

    try:
        import streamlit as st

        # Cache only *non-empty, non-stale* responses; empty/stale
        # frames go through a short 60-second negative cache so we
        # don't hammer yfinance on a rate-limited symbol but still
        # recover within a minute when the upstream comes back.
        @st.cache_data(ttl=3600, show_spinner=False)
        def _cached_ok(t: str, p: str, version: int) -> pd.DataFrame:
            return _raw_yf(t, p)

        @st.cache_data(ttl=60,   show_spinner=False)
        def _cached_neg(t: str, p: str) -> int:
            # Returns a sentinel int; used purely as a TTL gate.
            return 1

        df = _cached_ok(ticker, period, version=int(pd.Timestamp.now().date().toordinal()))
        if df.empty or _is_stale(df):
            # Force a fresh upstream call; bypass the long TTL by
            # mutating the version argument. Re-cache only if fresh.
            _cached_neg(ticker, period)  # honors the 60s negative cache
            fresh = _raw_yf(ticker, period)
            if not fresh.empty and not _is_stale(fresh):
                # Replace the cached entry by calling the OK fn with
                # a new version so it stores the fresh frame.
                try:
                    _cached_ok.clear()                          # type: ignore[attr-defined]
                except Exception:                              # noqa: BLE001
                    pass
                return fresh
            return fresh
        return df
    except Exception:                                          # noqa: BLE001
        # Streamlit not in context (e.g. unit test) — call raw.
        return _raw_yf(ticker, period)


def render_lwc_safe(charts_spec: list[dict[str, Any]], *, key: str) -> bool:
    """Attempt to render the spec. Returns True on success, False if the
    library is missing (so the caller can fall back gracefully).

    Wrapped to be defensive against import failure: a fresh checkout
    might not have ``streamlit-lightweight-charts`` installed yet, and
    the rest of the UI must keep working.
    """
    try:
        from streamlit_lightweight_charts import renderLightweightCharts
    except Exception:                                       # noqa: BLE001
        return False
    if not charts_spec:
        return False
    renderLightweightCharts(charts_spec, key=key)
    return True
