"""
On-demand ticker resolution with international exchange fallback.

Any Yahoo-listed symbol can become a first-class VolScope ticker without
hardcoding. Given a raw user string we:

    1. Normalize and shape-validate it (accepts US symbols, HK digit codes,
       Yahoo-suffixed international forms, indices, crypto pairs).
    2. Try the bare form against Yahoo.
    3. If that fails, try a prioritized list of exchange suffixes driven by
       the shape of the input — pure-digit inputs go to Asia first, alphabetic
       inputs to Europe / Commonwealth markets.
    4. On success, backfill 2y of HV history and cache the company name so the
       Scope header can render "AAPL · Apple Inc.".

The canonical form stored in the DB is always the suffixed one — once we
resolve 1810 → 1810.HK, every subsequent query uses 1810.HK.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from volscope.analytics.historical_vol import (
    hv_close_to_close,
    hv_yang_zhang,
)
from volscope.analytics.vol_metrics import iv_percentile, iv_rank
from volscope.config import (
    DEFAULT_HV_LONG,
    DEFAULT_HV_SHORT,
    DEFAULT_RANK_LOOKBACK,
)
from volscope.data import price_fetcher
from volscope.data.ticker_universe import sector_of

log = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[\^A-Z0-9][A-Z0-9.\-^=]{0,9}$")
_DIGITS_RE = re.compile(r"^\d{3,5}$")
_ALPHA_RE = re.compile(r"^[A-Z]{1,5}$")
# Mixed alphanumeric: starts with digit or letter, contains both, ≤ 6 chars.
# Examples: DB1 (Deutsche Börse), 2FE, ADS2, IFX — almost always European.
_MIXED_ALPHANUM_RE = re.compile(r"^[A-Z0-9]{2,6}$")

# Exchange suffix fallback order.
#
# Digit-only symbols (e.g. "1810" for Xiaomi, "2330" for TSMC) almost always
# belong to an Asian exchange. Hong Kong is the most common retail search so
# it leads; then Taiwan, Shanghai, Shenzhen, Tokyo, Korea.
#
# Alphabetic symbols that fail bare lookup are usually European or
# Commonwealth listings. XETRA (.DE) leads for German users, then London,
# Paris, Amsterdam, Australia, Toronto.
#
# Mixed alphanumeric (DB1, 2FE, IFX) are overwhelmingly German XETRA symbols
# so .DE leads the fallback list for those.
_ASIAN_SUFFIXES: tuple[str, ...] = (".HK", ".TW", ".SS", ".SZ", ".T", ".KS")
_WESTERN_SUFFIXES: tuple[str, ...] = (".DE", ".L", ".PA", ".AS", ".AX", ".TO")
_GERMAN_FIRST_SUFFIXES: tuple[str, ...] = (".DE", ".F", ".L", ".PA", ".AS")


@dataclass
class ResolveResult:
    ok: bool
    ticker: str
    rows_written: int
    message: str


def normalize_ticker(raw: Optional[str]) -> Optional[str]:
    """Trim, uppercase, and shape-validate. Returns None on clearly bogus input.

    Accepts US (AAPL), BRK.B, ^VIX, 1810, 1810.HK, BTC-USD, ES=F.
    """
    if raw is None:
        return None
    candidate = raw.strip().upper()
    if not candidate:
        return None
    if not _TICKER_RE.match(candidate):
        return None
    return candidate


def _suffix_candidates(ticker: str) -> tuple[str, ...]:
    """Return a prioritized list of exchange suffixes to try after a bare lookup fails.

    Pure digits → Asian exchanges (HK leads).
    Pure alpha  → Western exchanges (XETRA leads for German user base).
    Mixed alphanumeric (DB1, 2FE, IFX) → XETRA first, overwhelmingly German.
    Already qualified (.DE, -USD, =F, ^) → no fallback needed.
    """
    if "." in ticker or "-" in ticker or "=" in ticker or "^" in ticker:
        return ()
    if _DIGITS_RE.match(ticker):
        return _ASIAN_SUFFIXES
    if _ALPHA_RE.match(ticker):
        return _WESTERN_SUFFIXES
    # Mixed alphanumeric that is otherwise valid: try German/European suffixes.
    if _MIXED_ALPHANUM_RE.match(ticker):
        return _GERMAN_FIRST_SUFFIXES
    return ()


def _fetch_with_fallback(raw_ticker: str, period: str) -> tuple[Optional[str], pd.DataFrame]:
    """
    Try `raw_ticker` against Yahoo. If it returns empty, try exchange-suffixed
    variants in priority order. Returns (canonical_ticker, dataframe).

    `canonical_ticker` is whichever form produced data, or None if nothing worked.
    """
    df = price_fetcher.fetch_ohlcv(raw_ticker, period=period)
    if not df.empty:
        return raw_ticker, df

    for suffix in _suffix_candidates(raw_ticker):
        candidate = f"{raw_ticker}{suffix}"
        log.info("Ticker %s failed bare; trying %s", raw_ticker, candidate)
        df = price_fetcher.fetch_ohlcv(candidate, period=period)
        if not df.empty:
            return candidate, df
    return None, pd.DataFrame()


def _fetch_company_name(ticker: str) -> Optional[str]:
    """Best-effort company name via yfinance fast_info / info. Never raises."""
    try:
        import yfinance as yf
    except Exception:
        return None

    try:
        yft = yf.Ticker(ticker)
    except Exception:
        return None

    # fast_info is cheap; info is a heavier REST call but richer.
    for attr in ("shortName", "longName"):
        try:
            fi = getattr(yft, "fast_info", None)
            if fi is not None:
                val = fi.get(attr) if hasattr(fi, "get") else getattr(fi, attr, None)
                if val:
                    return str(val).strip()
        except Exception:
            pass
    try:
        info = yft.info or {}
        for key in ("shortName", "longName", "displayName"):
            val = info.get(key)
            if val:
                return str(val).strip()
    except Exception:
        pass
    return None


def _sector_hint(ticker: str) -> Optional[str]:
    """Try curated universe first; daily_scrape will fill sectors for new tickers."""
    return sector_of(ticker)


#: Variance Risk Premium multiplier applied to the HV proxy during seed backfill.
#: Yahoo never exposes historical options data, so seed IV is synthesized from
#: realized vol. Empirically IV trades at a ~10-15% premium over RV across
#: liquid US equities; 1.12 is a conservative mid-estimate. Real `iv_30d` from
#: `daily_scrape.py` OVERWRITES this proxy as soon as the scraper runs.
_SEED_VRP_MULT: float = 1.12


def _backfill_hv_history(
    db, ticker: str, df: pd.DataFrame, company_name: Optional[str]
) -> int:
    """
    Write the HV time-series for `ticker` into daily_vol. Returns rows written.

    Seed architecture note:
      - `hv_20d` uses close-to-close (Parkinson-independent baseline)
      - `iv_30d` (proxy) uses Yang-Zhang × 1.12 — a DIFFERENT estimator scaled
        by the typical variance risk premium. This ensures the IV-HV spread is
        NON-ZERO and varies over time as YZ and CC diverge — without which the
        Scope page's spread chart is a dead flat line at zero.
      - `hv_yz_20d` keeps the raw YZ value for analytics that want it.

    Once `daily_scrape.py` runs it replaces `iv_30d` with real solver output.
    """
    close = df["Close"]
    hv_cc_s = hv_close_to_close(close, DEFAULT_HV_SHORT)
    hv_cc_l = hv_close_to_close(close, DEFAULT_HV_LONG)
    try:
        hv_yz_s = hv_yang_zhang(
            df["Open"], df["High"], df["Low"], df["Close"], DEFAULT_HV_SHORT
        )
    except Exception:
        hv_yz_s = pd.Series(index=df.index, dtype=float)

    # IV proxy: scale YZ by VRP multiplier. Produces a series that visibly
    # differs from the CC baseline, giving the Scope spread chart real signal.
    iv_proxy_series = hv_yz_s * _SEED_VRP_MULT

    sector = _sector_hint(ticker)
    rows = 0
    for i, idx in enumerate(df.index):
        if i < DEFAULT_HV_LONG:
            continue
        d = idx.date() if hasattr(idx, "date") else idx

        hv_val = float(hv_cc_s.iloc[i]) if pd.notna(hv_cc_s.iloc[i]) else None
        iv_val = (
            float(iv_proxy_series.iloc[i])
            if pd.notna(iv_proxy_series.iloc[i])
            else None
        )
        # Fallback: if YZ didn't produce a value (first days / bad OHLC), fall
        # back to scaled CC so we still have a usable IV proxy.
        if iv_val is None and hv_val is not None:
            iv_val = hv_val * _SEED_VRP_MULT

        rank_history = (
            iv_proxy_series.iloc[max(0, i - DEFAULT_RANK_LOOKBACK) : i].dropna()
        )

        spread = None
        if iv_val is not None and hv_val is not None:
            spread = iv_val - hv_val

        db.upsert_daily(
            ticker,
            d,
            spot_price=float(close.iloc[i]),
            iv_30d=iv_val,
            hv_20d=hv_val,
            hv_60d=float(hv_cc_l.iloc[i]) if pd.notna(hv_cc_l.iloc[i]) else None,
            hv_yz_20d=float(hv_yz_s.iloc[i]) if pd.notna(hv_yz_s.iloc[i]) else None,
            iv_rank=(
                iv_rank(iv_val, rank_history.tolist())
                if iv_val is not None and not rank_history.empty
                else None
            ),
            iv_percentile=(
                iv_percentile(iv_val, rank_history.tolist())
                if iv_val is not None and not rank_history.empty
                else None
            ),
            iv_hv_spread=spread,
            sector=sector,
            company_name=company_name,
        )
        rows += 1
    return rows


def resolve_and_ingest(db, raw_ticker: str, period: str = "2y") -> ResolveResult:
    """
    Validate a user-supplied ticker, pull history from Yahoo (with international
    suffix fallback), and backfill HV into the DB. Idempotent.
    """
    normalized = normalize_ticker(raw_ticker)
    if normalized is None:
        return ResolveResult(
            ok=False, ticker=raw_ticker or "", rows_written=0, message="Invalid ticker format"
        )

    existing = db.get_available_tickers() or []
    if normalized in existing:
        return ResolveResult(
            ok=True,
            ticker=normalized,
            rows_written=0,
            message=f"{normalized} already in DB",
        )

    canonical, df = _fetch_with_fallback(normalized, period)
    if canonical is None or df.empty:
        suffix_list = _suffix_candidates(normalized)
        tried = f" (tried {', '.join(suffix_list)})" if suffix_list else ""
        return ResolveResult(
            ok=False,
            ticker=normalized,
            rows_written=0,
            message=f"No Yahoo data for {normalized}{tried}",
        )

    if canonical != normalized and canonical in existing:
        return ResolveResult(
            ok=True,
            ticker=canonical,
            rows_written=0,
            message=f"{canonical} already in DB",
        )

    if len(df) < DEFAULT_HV_LONG + 5:
        return ResolveResult(
            ok=False,
            ticker=canonical,
            rows_written=0,
            message=f"{canonical}: only {len(df)} bars, need at least {DEFAULT_HV_LONG + 5}",
        )

    company_name = _fetch_company_name(canonical)

    try:
        rows = _backfill_hv_history(db, canonical, df, company_name)
    except Exception as exc:
        log.exception("Backfill failed for %s", canonical)
        return ResolveResult(
            ok=False,
            ticker=canonical,
            rows_written=0,
            message=f"Backfill error: {exc}",
        )

    if rows == 0:
        return ResolveResult(
            ok=False,
            ticker=canonical,
            rows_written=0,
            message=f"{canonical}: no rows written after backfill",
        )

    tail = f" as {canonical}" if canonical != normalized else ""
    return ResolveResult(
        ok=True,
        ticker=canonical,
        rows_written=rows,
        message=f"Added {normalized}{tail} ({rows} days)",
    )
