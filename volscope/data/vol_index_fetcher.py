"""
Vol index fetcher — VIX, VDAX-New, VXFXI, and Deribit DVOL (BVOL).

These indices ARE implied volatility: their price IS the IV level.
We fetch their price history and compute rank / percentile / 1w-change
in-memory, no DB write needed. Results are meant to be cached short-term
(5 min TTL) so the Command Center page stays responsive without hammering
external APIs on every rerun.

Data sources / fallback chain for VDAX-New:
  1. ^VDAX        — CBOE listing (often unavailable on free Yahoo tier)
  2. VDAX-NEW.DE  — Deutsche Börse listing via yfinance
  3. EWG IV proxy — ATM IV of nearest-30d EWG (iShares MSCI Germany ETF)
                    options. EWG tracks German equities and correlates well
                    with VDAX. The proxy level is labelled "(EWG proxy)" so
                    the user knows it is not the official index.
  4. ^GDAXI HV    — 20-day realized vol of the DAX index as absolute last
                    resort. Labelled "(DAX HV)" — realized not implied.

For all other indices (VIX, VXFXI):
  Single symbol via yfinance.

BVOL:
  Deribit REST API, endpoint /api/v2/public/get_volatility_index_data
  No API key required. Near-real-time.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core yfinance helper — returns (series, source_label)
# ---------------------------------------------------------------------------

def fetch_vol_index_history(
    symbol: str | list[str], period: str = "1y"
) -> pd.Series:
    """Return daily closing price series for a vol index via yfinance.

    If *symbol* is a list, each entry is tried in order; first non-empty wins.
    Returns an empty Series on failure.  Use fetch_vol_index_history_with_source
    when you need to know which symbol succeeded.
    """
    series, _ = fetch_vol_index_history_with_source(symbol, period)
    return series


def fetch_vol_index_history_with_source(
    symbol: str | list[str], period: str = "1y"
) -> tuple[pd.Series, str]:
    """Like fetch_vol_index_history but also returns the winning symbol string.

    Returns (series, source_label) where source_label is the symbol that
    produced data, or "" if all failed.
    """
    try:
        import yfinance as yf
    except Exception as exc:
        log.warning("yfinance import failed: %s", exc)
        return pd.Series(dtype=float), ""

    symbols = [symbol] if isinstance(symbol, str) else list(symbol)
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period=period, auto_adjust=True)
            if hist is not None and not hist.empty and "Close" in hist.columns:
                s = hist["Close"].dropna()
                if not s.empty:
                    log.debug("fetch_vol_index_history: %s OK (%d rows)", sym, len(s))
                    return s, sym
        except Exception as exc:
            log.debug("fetch_vol_index_history(%s) failed: %s", sym, exc)
    return pd.Series(dtype=float), ""


# ---------------------------------------------------------------------------
# VDAX proxy via EWG options (ATM 30-day IV)
# ---------------------------------------------------------------------------

def _fetch_vdax_proxy_ewg(period: str = "1y") -> tuple[pd.Series, str]:
    """Compute a VDAX proxy using ATM IV of EWG (iShares MSCI Germany ETF).

    EWG options trade on US exchanges and correlate well with DAX volatility.
    The returned series is the computed ATM IV (annualized %) for the nearest
    30-day expiry, repeated as a constant over the history window so it can be
    used for rank/percentile vs historical EWG ATM IV.

    Returns (series, "EWG proxy") or (empty_series, "") on failure.
    """
    try:
        import yfinance as yf
        from volscope.analytics.black_scholes import implied_volatility
        from volscope.data.risk_free import get_rate
    except Exception as exc:
        log.debug("_fetch_vdax_proxy_ewg: import failed: %s", exc)
        return pd.Series(dtype=float), ""

    try:
        ticker = yf.Ticker("EWG")

        # Current spot
        hist_df = ticker.history(period=period, auto_adjust=True)
        if hist_df is None or hist_df.empty or "Close" not in hist_df.columns:
            return pd.Series(dtype=float), ""
        close_series = hist_df["Close"].dropna()
        if close_series.empty:
            return pd.Series(dtype=float), ""
        spot = float(close_series.iloc[-1])

        # Find expiry closest to 30 calendar days out
        options_list = ticker.options
        if not options_list:
            return pd.Series(dtype=float), ""

        today = date.today()
        best_expiry: Optional[str] = None
        best_diff = 999
        for exp_str in options_list:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                diff = abs((exp_date - today).days - 30)
                if diff < best_diff:
                    best_diff = diff
                    best_expiry = exp_str
            except ValueError:
                continue

        if best_expiry is None:
            return pd.Series(dtype=float), ""

        exp_date = datetime.strptime(best_expiry, "%Y-%m-%d").date()
        T = (exp_date - today).days / 365.0
        if T <= 0:
            return pd.Series(dtype=float), ""

        r = get_rate() / 100.0

        chain = ticker.option_chain(best_expiry)
        calls = chain.calls if chain.calls is not None else pd.DataFrame()
        puts = chain.puts if chain.puts is not None else pd.DataFrame()

        # Find ATM call and put (strike nearest to spot, with real bid/ask)
        iv_samples: list[float] = []
        for df, opt_type in [(calls, "call"), (puts, "put")]:
            if df.empty:
                continue
            needed = {"strike", "bid", "ask"}
            if not needed.issubset(df.columns):
                continue
            liquid = df[(df["bid"] > 0) & (df["ask"] > 0)].copy()
            if liquid.empty:
                continue
            liquid = liquid.assign(_dist=(liquid["strike"] - spot).abs())
            liquid = liquid.nsmallest(3, "_dist")
            for _, row in liquid.iterrows():
                mid = (float(row["bid"]) + float(row["ask"])) / 2.0
                iv = implied_volatility(mid, spot, float(row["strike"]), T, r,
                                        option_type=opt_type)
                if iv is not None and 0.03 < iv < 5.0:
                    iv_samples.append(iv * 100.0)  # to percent

        if not iv_samples:
            return pd.Series(dtype=float), ""

        current_iv = sum(iv_samples) / len(iv_samples)

        # Build a history series of EWG close-to-close realized vol (for rank ctx)
        # Scale so that rank/pct is computed over EWG HV history in same unit
        # Instead, use historical EWG ATM IV proxied from HV * typical VRP ratio
        # Simplest: return close_series as surrogate for regime context, but
        # replace the last value with our computed IV. This gives rank/pct vs
        # EWG's own price history — not ideal but produces a usable regime signal.
        # Better: compute rolling 20d HV of EWG and use that as the history
        # (realized vol tracks implied vol closely over time).
        log_ret = close_series.pct_change().apply(lambda x: math.log(1 + x) if x > -1 else float("nan"))
        hv_series = log_ret.rolling(20).std() * math.sqrt(252) * 100.0
        hv_series = hv_series.dropna()
        if hv_series.empty:
            return pd.Series(dtype=float), ""

        # Replace the last point with our IV-derived estimate
        hv_series.iloc[-1] = current_iv
        return hv_series, "EWG proxy"

    except Exception as exc:
        log.debug("_fetch_vdax_proxy_ewg failed: %s", exc)
        return pd.Series(dtype=float), ""


def _fetch_vdax_proxy_gdaxi_hv(period: str = "1y") -> tuple[pd.Series, str]:
    """Last-resort VDAX proxy: 20-day realized vol of ^GDAXI (DAX index).

    This is historical vol, NOT implied vol. Labelled 'DAX HV' to be clear.
    Returns (series, "DAX HV") or (empty_series, "") on failure.
    """
    try:
        import yfinance as yf
    except Exception as exc:
        log.debug("_fetch_vdax_proxy_gdaxi_hv: yfinance import failed: %s", exc)
        return pd.Series(dtype=float), ""

    try:
        hist = yf.Ticker("^GDAXI").history(period=period, auto_adjust=True)
        if hist is None or hist.empty or "Close" not in hist.columns:
            return pd.Series(dtype=float), ""
        close = hist["Close"].dropna()
        if len(close) < 25:
            return pd.Series(dtype=float), ""
        log_ret = close.pct_change().apply(
            lambda x: math.log(1 + x) if x > -1 else float("nan")
        )
        hv = log_ret.rolling(20).std() * math.sqrt(252) * 100.0
        hv = hv.dropna()
        if hv.empty:
            return pd.Series(dtype=float), ""
        return hv, "DAX HV"
    except Exception as exc:
        log.debug("_fetch_vdax_proxy_gdaxi_hv failed: %s", exc)
        return pd.Series(dtype=float), ""


def _rank_and_pct_52w(
    series: pd.Series, current: float
) -> tuple[Optional[float], Optional[float]]:
    """
    Compute 52-week (252-session) IV rank and IV percentile.

    rank = (current − min) / (max − min) × 100
    pct  = fraction of sessions where index was below current × 100
    """
    window = series.tail(252).dropna()
    if len(window) < 10:
        return None, None
    iv_min = float(window.min())
    iv_max = float(window.max())
    span = iv_max - iv_min
    rank: Optional[float] = (current - iv_min) / span * 100.0 if span > 0 else 50.0
    pct: Optional[float] = float((window < current).sum()) / len(window) * 100.0
    return rank, pct


def vol_index_snapshot(name: str, symbol: str | list[str]) -> dict:
    """Fetch a volatility index and compute its snapshot metrics.

    For VDAX-New the symbol list triggers a 4-step fallback chain:
      1. ^VDAX  2. VDAX-NEW.DE  3. EWG proxy (ATM IV)  4. DAX HV (last resort)

    Returns a dict with keys:
        name        — display label
        level       — current index value (float or None)
        rank_52w    — IV rank 0-100 over last 252 sessions (float or None)
        pct_52w     — IV percentile 0-100 (float or None)
        change_1w   — absolute change vs 5 sessions ago (float or None)
        regime      — 'CHEAP' | 'NORMAL' | 'RICH' | 'NO DATA'
        source      — which data source succeeded (e.g. "^VIX", "EWG proxy")
    """
    is_vdax = name == "VDAX-New"

    series, source = fetch_vol_index_history_with_source(symbol, period="1y")

    # VDAX-specific fallback chain when direct symbols fail
    if series.empty and is_vdax:
        log.info("VDAX direct symbols failed, trying EWG proxy")
        series, source = _fetch_vdax_proxy_ewg(period="1y")

    if series.empty and is_vdax:
        log.info("VDAX EWG proxy failed, falling back to DAX HV")
        series, source = _fetch_vdax_proxy_gdaxi_hv(period="1y")

    if series.empty:
        return {
            "name": name,
            "level": None,
            "rank_52w": None,
            "pct_52w": None,
            "change_1w": None,
            "regime": "NO DATA",
            "source": "",
        }

    log.info("vol_index_snapshot(%s): source=%s, rows=%d", name, source, len(series))

    current = float(series.iloc[-1])
    rank, pct = _rank_and_pct_52w(series, current)

    change_1w: Optional[float] = None
    if len(series) >= 5:
        prev = float(series.iloc[-5])
        change_1w = current - prev

    if pct is None:
        regime = "NO DATA"
    elif pct < 20:
        regime = "CHEAP"
    elif pct > 80:
        regime = "RICH"
    else:
        regime = "NORMAL"

    return {
        "name": name,
        "level": current,
        "rank_52w": rank,
        "pct_52w": pct,
        "change_1w": change_1w,
        "regime": regime,
        "source": source,
    }


def fetch_deribit_dvol(currency: str = "BTC") -> pd.Series:
    """
    Fetch the Deribit DVOL index for a currency (BTC or ETH).

    Deribit exposes a free, unauthenticated REST endpoint:
    GET /api/v2/public/get_volatility_index_data?currency=BTC&resolution=86400&count=365

    Each row in `result.data` is [timestamp_ms, open, high, low, close].
    We take the `close` column as the daily DVOL level (in percent).

    Returns an empty Series on any failure.
    """
    try:
        import requests
    except Exception as exc:
        log.warning("requests import failed: %s", exc)
        return pd.Series(dtype=float)

    url = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    params: dict = {
        "currency": currency.upper(),
        "resolution": "86400",  # daily candles
        "count": 365,
    }
    try:
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Deribit DVOL fetch failed (%s): %s", currency, exc)
        return pd.Series(dtype=float)

    try:
        rows = data["result"]["data"]
        if not rows:
            return pd.Series(dtype=float)
        timestamps = [r[0] for r in rows]
        closes = [float(r[4]) for r in rows]
        idx = pd.to_datetime(timestamps, unit="ms").normalize()
        series = pd.Series(closes, index=idx, dtype=float)
        return series[series > 0].dropna()
    except Exception as exc:
        log.warning("Deribit DVOL parse failed (%s): %s", currency, exc)
        return pd.Series(dtype=float)


def bvol_snapshot() -> dict:
    """Convenience wrapper: Bitcoin DVOL snapshot from Deribit."""
    series = fetch_deribit_dvol("BTC")
    if series.empty:
        return {
            "name": "BVOL-BTC",
            "level": None,
            "rank_52w": None,
            "pct_52w": None,
            "change_1w": None,
            "regime": "NO DATA",
            "source": "",
        }

    current = float(series.iloc[-1])
    rank, pct = _rank_and_pct_52w(series, current)

    change_1w: Optional[float] = None
    if len(series) >= 5:
        change_1w = current - float(series.iloc[-5])

    if pct is None:
        regime = "NO DATA"
    elif pct < 20:
        regime = "CHEAP"
    elif pct > 80:
        regime = "RICH"
    else:
        regime = "NORMAL"

    return {
        "name": "BVOL-BTC",
        "level": current,
        "rank_52w": rank,
        "pct_52w": pct,
        "change_1w": change_1w,
        "regime": regime,
        "source": "Deribit",
    }
