"""Yahoo options chain scraper with self-computed ATM IV (30-day)."""
from __future__ import annotations

import logging
import math
from datetime import date, datetime
from typing import Optional

import pandas as pd

from volscope.analytics.black_scholes import bs_delta, implied_volatility
from volscope.data.fundamentals import fetch_ttm_dividend_yield
from volscope.data.risk_free import get_rate
from volscope.utils.retry import retry
from volscope.utils.safe import safe_num

log = logging.getLogger(__name__)


def _import_yf():
    try:
        import yfinance as yf

        return yf
    except Exception as exc:  # pragma: no cover
        log.error("yfinance import failed: %s", exc)
        return None


def _days_between(today: date, target: date) -> int:
    return (target - today).days


def _parse_expiry(expiry_str: str) -> Optional[date]:
    try:
        return datetime.strptime(expiry_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _filter_for_iv(df: pd.DataFrame) -> pd.DataFrame:
    """Strict liquidity filter for IV computation: real bid/ask and some interest."""
    if df is None or df.empty:
        return pd.DataFrame()
    needed = {"strike", "bid", "ask", "volume", "openInterest"}
    if not needed.issubset(df.columns):
        return pd.DataFrame()
    return df[
        (df["bid"] > 0)
        & (df["ask"] > 0)
        & (df["ask"] >= df["bid"])
        & ((df["volume"].fillna(0) > 0) | (df["openInterest"].fillna(0) > 10))
    ].copy()


def _filter_for_aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Loose filter for OI / volume aggregation — keeps tail strikes (bid=0 OK)."""
    if df is None or df.empty:
        return pd.DataFrame()
    needed = {"strike", "openInterest"}
    if not needed.issubset(df.columns):
        return pd.DataFrame()
    return df.copy()


def _atm_iv_interpolated(
    chain: pd.DataFrame,
    spot: float,
    T: float,
    r: float,
    q: float,
    option_type: str,
) -> tuple[Optional[float], float]:
    """
    Compute ATM IV via linear interpolation in strike between the two strikes
    that bracket spot, falling back to the nearest strike on one side.

    Returns (iv_fraction, liquidity_weight). Liquidity weight is the sum of
    (volume + openInterest) for the strikes used — handy for downstream
    weighting between call and put estimates.
    """
    if chain.empty or T <= 0 or spot <= 0:
        return None, 0.0

    df = chain.copy()
    df["mid"] = (df["bid"] + df["ask"]) / 2.0
    # Reject quotes with absurd spreads (>50% of mid) — usually stale.
    df["spread_frac"] = (df["ask"] - df["bid"]) / df["mid"].replace(0, math.nan)
    df = df[df["spread_frac"].fillna(1.0) <= 0.5]
    if df.empty:
        return None, 0.0

    df = df.sort_values("strike").reset_index(drop=True)
    below = df[df["strike"] <= spot]
    above = df[df["strike"] > spot]

    used_rows: list[pd.Series] = []
    iv_frac: Optional[float] = None

    if not below.empty and not above.empty:
        lo = below.iloc[-1]
        hi = above.iloc[0]
        iv_lo = implied_volatility(
            float(lo["mid"]), spot, float(lo["strike"]), T, r, q=q, option_type=option_type
        )
        iv_hi = implied_volatility(
            float(hi["mid"]), spot, float(hi["strike"]), T, r, q=q, option_type=option_type
        )
        if iv_lo is not None and iv_hi is not None and 0.01 < iv_lo < 5.0 and 0.01 < iv_hi < 5.0:
            k_lo, k_hi = float(lo["strike"]), float(hi["strike"])
            if k_hi == k_lo:
                iv_frac = 0.5 * (iv_lo + iv_hi)
            else:
                w = (spot - k_lo) / (k_hi - k_lo)
                iv_frac = iv_lo + w * (iv_hi - iv_lo)
            used_rows.extend([lo, hi])

    if iv_frac is None:
        # Fallback: nearest single strike
        df["dist"] = (df["strike"] - spot).abs()
        nearest = df.nsmallest(1, "dist")
        if not nearest.empty:
            row = nearest.iloc[0]
            iv = implied_volatility(
                float(row["mid"]), spot, float(row["strike"]), T, r, q=q, option_type=option_type
            )
            if iv is not None and 0.01 < iv < 5.0:
                iv_frac = iv
                used_rows.append(row)

    if iv_frac is None:
        return None, 0.0

    weight = 0.0
    for row in used_rows:
        from volscope.utils.safe import safe_num
        weight += safe_num(row.get("volume")) + safe_num(row.get("openInterest"))
    return iv_frac, weight


def _expiry_iv_from_chain(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    T: float,
    r: float,
    q: float,
) -> Optional[float]:
    """
    Compute a single ATM IV estimate (in percent) for an expiry by combining
    call and put IVs, weighted by their respective liquidity. Returns None if
    neither side produces a usable estimate.
    """
    call_iv, call_w = _atm_iv_interpolated(
        _filter_for_iv(calls), spot, T, r, q, "call"
    )
    put_iv, put_w = _atm_iv_interpolated(
        _filter_for_iv(puts), spot, T, r, q, "put"
    )

    pieces: list[tuple[float, float]] = []
    if call_iv is not None:
        pieces.append((call_iv, max(call_w, 1.0)))
    if put_iv is not None:
        pieces.append((put_iv, max(put_w, 1.0)))
    if not pieces:
        return None

    total_w = sum(w for _, w in pieces)
    weighted = sum(v * w for v, w in pieces) / total_w
    return weighted * 100.0


@retry(attempts=3, base_delay=1.5, factor=2.0)
def _fetch_chain(yf_ticker, expiry_str: str):
    return yf_ticker.option_chain(expiry_str)


@retry(attempts=3, base_delay=1.5, factor=2.0)
def _fetch_expiries(yf_ticker) -> tuple:
    return yf_ticker.options


@retry(attempts=3, base_delay=1.0, factor=2.0)
def _fetch_history(yf_ticker, period: str = "5d"):
    return yf_ticker.history(period=period)


def _fetch_intraday_spot(yf_ticker) -> Optional[float]:
    """Try fast_info for a real intraday quote; fall back to last close."""
    try:
        fi = yf_ticker.fast_info
        for key in ("last_price", "lastPrice", "regular_market_price", "regularMarketPrice"):
            try:
                val = fi.get(key) if hasattr(fi, "get") else getattr(fi, key, None)
            except Exception:
                val = None
            if val is not None:
                try:
                    v = float(val)
                    if v > 0:
                        return v
                except (TypeError, ValueError):
                    continue
    except Exception:
        pass
    try:
        hist = _fetch_history(yf_ticker, "5d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        log.warning("Failed to fetch spot: %s", exc)
    return None


def scrape_options_chain(ticker: str) -> Optional[dict]:
    """
    Scrape Yahoo options for `ticker` and return a summary dict with
    self-computed 30-day ATM IV plus volume/OI aggregates. Returns None on
    failure. Never uses Yahoo's impliedVolatility column.
    """
    yf = _import_yf()
    if yf is None:
        return None

    try:
        yf_t = yf.Ticker(ticker)
        expiries = _fetch_expiries(yf_t)
    except Exception as exc:
        log.warning("Failed to list expiries for %s: %s", ticker, exc)
        return None

    if not expiries:
        return None

    spot = _fetch_intraday_spot(yf_t)
    if spot is None or spot <= 0:
        return None

    q = fetch_ttm_dividend_yield(yf_t, spot)

    today = date.today()
    parsed: list[tuple[str, int]] = []
    for e in expiries:
        d = _parse_expiry(e)
        if d is None:
            continue
        days = _days_between(today, d)
        if days > 0:
            parsed.append((e, days))
    if not parsed:
        return None

    # IV candidates: for each term-structure target (30/60/90/180d) pick the
    # expiry closest to that target.  This is crucial for tickers with weekly
    # options (QQQ, SPY, MSTR…): a naïve [:8] would grab only 1-12 day
    # expiries and extrapolate from ultra-short-dated gamma, producing a flat
    # or wrong term structure.
    _IV_TARGETS = [30, 60, 90, 180]
    _MAX_DIST = 35  # days — how far from target an expiry can be and still count
    _selected: dict[str, int] = {}  # {expiry_str: days}
    for _target in _IV_TARGETS:
        # Prefer expiries within ±35d of the target; fall back to nearest ≥ 10d.
        _bucket = [(e, d) for e, d in parsed if abs(d - _target) <= _MAX_DIST]
        if not _bucket:
            _bucket = [(e, d) for e, d in parsed if d >= 10]
        if _bucket:
            _best = min(_bucket, key=lambda x: abs(x[1] - _target))
            _selected[_best[0]] = _best[1]
    iv_candidates = sorted(_selected.items(), key=lambda x: x[1])

    # Volume/OI candidates: 4 nearest to 30d (near-term sentiment signal).
    vol_candidates_set = {
        e for e, _ in sorted(parsed, key=lambda x: abs(x[1] - 30))[:4]
    }

    iv_points: list[tuple[int, float]] = []
    near_term_call_volume = 0
    near_term_put_volume = 0
    near_term_oi = 0

    for exp_str, days in iv_candidates:
        try:
            chain = _fetch_chain(yf_t, exp_str)
        except Exception as exc:
            log.warning("option_chain(%s) failed for %s: %s", exp_str, ticker, exc)
            continue

        T = days / 365.0
        r_t = get_rate(days)
        # Skip chains that are too thin to produce a reliable IV estimate.
        # A chain with < 3 usable strikes on both sides combined is almost
        # always a thinly-traded European/ETF instrument where the mid-price
        # has a >50% spread — our ATM interpolation will fail or return a
        # noise value.  Return None rather than a misleading number.
        n_calls = len(_filter_for_iv(chain.calls))
        n_puts = len(_filter_for_iv(chain.puts))
        if n_calls + n_puts < 3:
            log.debug(
                "Skipping thin chain %s %s: only %d call + %d put strikes pass filter",
                ticker, exp_str, n_calls, n_puts,
            )
            continue
        iv = _expiry_iv_from_chain(chain.calls, chain.puts, spot, T, r_t, q)
        if iv is not None:
            iv_points.append((days, iv))

        if exp_str in vol_candidates_set:
            try:
                calls_agg = _filter_for_aggregate(chain.calls)
                puts_agg = _filter_for_aggregate(chain.puts)
                near_term_call_volume += int(calls_agg.get("volume", pd.Series(dtype=float)).fillna(0).sum())
                near_term_put_volume += int(puts_agg.get("volume", pd.Series(dtype=float)).fillna(0).sum())
                near_term_oi += int(calls_agg.get("openInterest", pd.Series(dtype=float)).fillna(0).sum())
                near_term_oi += int(puts_agg.get("openInterest", pd.Series(dtype=float)).fillna(0).sum())
            except Exception:
                pass

    if not iv_points:
        return None

    iv_30d = _interpolate_iv(iv_points, target_days=30)
    iv_60d = _interpolate_iv(iv_points, target_days=60)
    iv_90d = _interpolate_iv(iv_points, target_days=90)
    iv_180d = _interpolate_iv(iv_points, target_days=180)

    # 25-delta skew from the expiry closest to 30 days
    iv_skew_25d: Optional[float] = None
    if iv_candidates:
        nearest_exp, nearest_days = min(iv_candidates, key=lambda x: abs(x[1] - 30))
        try:
            skew_chain = _fetch_chain(yf_t, nearest_exp)
            T_skew = nearest_days / 365.0
            r_skew = get_rate(nearest_days)
            iv_skew_25d = _compute_skew_25d(
                skew_chain.calls, skew_chain.puts, spot, T_skew, r_skew, q
            )
        except Exception as exc:
            log.debug("Skew computation failed for %s: %s", ticker, exc)

    pc_ratio = (
        near_term_put_volume / near_term_call_volume if near_term_call_volume > 0 else None
    )

    return {
        "iv_30d": iv_30d,
        "iv_60d": iv_60d,
        "iv_90d": iv_90d,
        "iv_180d": iv_180d,
        "iv_skew_25d": iv_skew_25d,
        "total_call_volume": near_term_call_volume,
        "total_put_volume": near_term_put_volume,
        "put_call_ratio": pc_ratio,
        "total_open_interest": near_term_oi,
        "spot_price": spot,
        "dividend_yield": q,
    }


def _compute_skew_25d(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    spot: float,
    T: float,
    r: float,
    q: float,
) -> Optional[float]:
    """
    Compute 25-delta skew: put_IV(25Δ) − call_IV(25Δ).

    For each side:
    1. Compute IV at each strike (filtered chain).
    2. Compute BSM delta at that IV.
    3. Interpolate IV at the target delta (0.25 for calls, -0.25 for puts).

    Returns skew in percentage points (positive = puts more expensive than calls).
    """
    if T <= 0 or spot <= 0:
        return None

    def _iv_delta_pairs(chain: pd.DataFrame, option_type: str) -> list[tuple[float, float]]:
        """Return (delta, iv_pct) pairs sorted by ascending delta."""
        filt = _filter_for_iv(chain)
        if filt.empty:
            return []
        filt = filt.copy()
        filt["mid"] = (filt["bid"] + filt["ask"]) / 2.0
        pairs: list[tuple[float, float]] = []
        for _, row in filt.iterrows():
            k = float(row["strike"])
            mid = float(row["mid"])
            iv = implied_volatility(mid, spot, k, T, r, q=q, option_type=option_type)
            if iv is None or not (0.01 < iv < 5.0):
                continue
            delta = bs_delta(spot, k, T, r, iv, q=q, option_type=option_type)
            if delta is None:
                continue
            pairs.append((float(delta), iv * 100.0))
        return sorted(pairs, key=lambda x: x[0])

    def _iv_at_delta(pairs: list[tuple[float, float]], target: float) -> Optional[float]:
        if len(pairs) < 2:
            return None
        for i in range(len(pairs) - 1):
            d0, iv0 = pairs[i]
            d1, iv1 = pairs[i + 1]
            if d0 <= target <= d1:
                if d1 == d0:
                    return iv0
                w = (target - d0) / (d1 - d0)
                return iv0 + w * (iv1 - iv0)
        return None

    call_pairs = _iv_delta_pairs(calls, "call")
    put_pairs  = _iv_delta_pairs(puts,  "put")

    # Call 25Δ: delta ≈ 0.25 (OTM call)
    iv_call_25d = _iv_at_delta(call_pairs, 0.25)
    # Put 25Δ: delta ≈ -0.25 (OTM put)
    iv_put_25d  = _iv_at_delta(put_pairs, -0.25)

    if iv_call_25d is None or iv_put_25d is None:
        return None
    return round(iv_put_25d - iv_call_25d, 2)


def _interpolate_iv(points: list[tuple[int, float]], target_days: int) -> Optional[float]:
    """
    Interpolate IV across maturities linearly in TOTAL VARIANCE (σ²·T) — the
    no-arbitrage convention for the IV term structure. Falls back to the
    nearest point for extrapolation.

    Inputs and outputs are IV in percent; conversion to fraction happens
    internally.
    """
    if not points:
        return None
    if len(points) == 1:
        return points[0][1]

    pts = sorted(points, key=lambda x: x[0])
    target_T = target_days / 365.0

    for i in range(len(pts) - 1):
        d0, iv0 = pts[i]
        d1, iv1 = pts[i + 1]
        if d0 <= target_days <= d1:
            T0 = d0 / 365.0
            T1 = d1 / 365.0
            if T1 == T0:
                return iv0
            var0 = (iv0 / 100.0) ** 2 * T0
            var1 = (iv1 / 100.0) ** 2 * T1
            w = (target_T - T0) / (T1 - T0)
            var_target = var0 + w * (var1 - var0)
            if var_target <= 0 or target_T <= 0:
                return iv0
            return float(math.sqrt(var_target / target_T) * 100.0)

    nearest = min(pts, key=lambda x: abs(x[0] - target_days))
    return float(nearest[1])
