"""Daily scrape: fetches option chain IVs for each ticker and updates the DB.

Usage:
    python scripts/daily_scrape.py --tickers SPY,AAPL
    python scripts/daily_scrape.py
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from volscope.analytics.historical_vol import (  # noqa: E402
    hv_close_to_close,
    hv_yang_zhang,
)
from volscope.analytics.vol_metrics import (  # noqa: E402
    iv_hv_spread,
    iv_percentile,
    iv_rank,
)
from volscope.config import (  # noqa: E402
    DEFAULT_HV_LONG,
    DEFAULT_HV_SHORT,
    DEFAULT_RANK_LOOKBACK,
    SCRAPE_DELAY_SECONDS,
)
from volscope.data.data_validation import validate_daily_row  # noqa: E402
from volscope.data.database import VolScopeDB  # noqa: E402
from volscope.data.earnings_fetcher import fetch_upcoming_earnings  # noqa: E402
from volscope.data.fundamentals import fetch_sector  # noqa: E402
from volscope.data.options_scraper import _import_yf, scrape_options_chain  # noqa: E402
from volscope.data.price_fetcher import fetch_ohlcv  # noqa: E402
from volscope.data.ticker_universe import all_tickers  # noqa: E402

log = logging.getLogger("volscope.daily_scrape")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _compute_hv_block(ticker: str) -> dict:
    """Compute the HV block from price history."""
    df = fetch_ohlcv(ticker, period="2y")
    if df.empty:
        return {}
    close = df["Close"]
    hv_s = hv_close_to_close(close, DEFAULT_HV_SHORT)
    hv_l = hv_close_to_close(close, DEFAULT_HV_LONG)
    try:
        hv_yz = hv_yang_zhang(df["Open"], df["High"], df["Low"], df["Close"], DEFAULT_HV_SHORT)
    except Exception:
        hv_yz = pd.Series(index=df.index, dtype=float)

    return {
        "hv_20d": float(hv_s.iloc[-1]) if pd.notna(hv_s.iloc[-1]) else None,
        "hv_60d": float(hv_l.iloc[-1]) if pd.notna(hv_l.iloc[-1]) else None,
        "hv_yz_20d": float(hv_yz.iloc[-1]) if pd.notna(hv_yz.iloc[-1]) else None,
    }


def _iv_history_from_db(db: VolScopeDB, ticker: str) -> list[float]:
    """Pull the last N days of iv_30d for this ticker — used for IV Rank/Percentile."""
    df = db.get_ticker_history(ticker)
    if df.empty or "iv_30d" not in df.columns:
        return []
    return df["iv_30d"].dropna().tail(DEFAULT_RANK_LOOKBACK).tolist()


def _sync_earnings(db: VolScopeDB, ticker: str) -> int:
    """Best-effort fetch of upcoming earnings dates and upsert into DB."""
    yf = _import_yf()
    if yf is None:
        return 0
    try:
        yf_t = yf.Ticker(ticker)
    except Exception:
        return 0
    dates = fetch_upcoming_earnings(yf_t)
    n = 0
    for d in dates:
        try:
            db.upsert_earnings(ticker, d)
            n += 1
        except Exception as exc:
            log.debug("upsert_earnings(%s, %s) failed: %s", ticker, d, exc)
    return n


# Plausibility caps per ticker class. If a scraped IV exceeds these it is
# almost certainly a solver bug (stale chain, weird strike, bad mid price)
# rather than a real market move. We keep the DB clean by refusing to write
# obviously-wrong values.
_IV_PLAUSIBILITY_CAPS: dict[str, float] = {
    "ETF": 120.0,          # any broad-market ETF (SPY, QQQ, IWM, sector XL*)
    "VOL_ETF": 400.0,      # volatility products can genuinely get wild
    "SINGLE_NAME": 500.0,  # individual stocks — meme spikes are real
    "CRYPTO": 300.0,       # crypto pairs are volatile but bounded
    "INDEX": 100.0,        # ^VIX, ^GSPC, etc.
}

_ETF_SECTORS = {
    "Index ETF", "Sector ETF", "Thematic ETF", "Commodity ETF",
    "Bond ETF", "Currency / Macro",
}
_VOL_ETF_SECTORS = {"Vol ETF"}
_CRYPTO_SECTORS = {"Crypto (spot pairs)"}
_INDEX_SECTORS = {"Indices (read-only)"}


def _iv_cap_for(ticker: str, sector: str | None) -> float:
    if sector in _VOL_ETF_SECTORS:
        return _IV_PLAUSIBILITY_CAPS["VOL_ETF"]
    if sector in _ETF_SECTORS:
        return _IV_PLAUSIBILITY_CAPS["ETF"]
    if sector in _CRYPTO_SECTORS:
        return _IV_PLAUSIBILITY_CAPS["CRYPTO"]
    if sector in _INDEX_SECTORS or ticker.startswith("^"):
        return _IV_PLAUSIBILITY_CAPS["INDEX"]
    return _IV_PLAUSIBILITY_CAPS["SINGLE_NAME"]


def _previous_iv(db: VolScopeDB, ticker: str) -> float | None:
    """Most recent non-null iv_30d for this ticker, or None."""
    hist = db.get_ticker_history(ticker)
    if hist.empty or "iv_30d" not in hist.columns:
        return None
    non_null = hist["iv_30d"].dropna()
    if non_null.empty:
        return None
    try:
        return float(non_null.iloc[-1])
    except (TypeError, ValueError):
        return None


def process_ticker(db: VolScopeDB, ticker: str, today: date) -> bool:
    snap = scrape_options_chain(ticker)
    if snap is None:
        log.warning("No option snapshot for %s", ticker)
        return False

    hv_block = _compute_hv_block(ticker)
    iv_30 = snap.get("iv_30d")
    hv_20 = hv_block.get("hv_20d")

    # Resolve sector once up front; used by the sanity check AND the upsert row.
    yf_mod = _import_yf()
    yf_t = yf_mod.Ticker(ticker) if yf_mod is not None else None
    sector = fetch_sector(ticker, yf_t)

    # Sanity check 1: hard plausibility cap per ticker class.
    if iv_30 is not None:
        cap = _iv_cap_for(ticker, sector)
        if iv_30 > cap:
            log.warning(
                "REJECTED %s: scraped IV %.1f%% exceeds %s cap %.0f%% — "
                "keeping previous value in DB",
                ticker,
                iv_30,
                sector or "default",
                cap,
            )
            iv_30 = None

    # Sanity check 2: implausible day-over-day jump (data-source artifact).
    if iv_30 is not None:
        prev_iv = _previous_iv(db, ticker)
        if prev_iv is not None and prev_iv > 0:
            abs_change = abs(iv_30 - prev_iv)
            rel_change = abs_change / prev_iv
            # >200% relative AND >20pt absolute is a near-certain data artifact.
            if rel_change > 2.0 and abs_change > 20.0:
                log.warning(
                    "REJECTED %s: IV jump %.1f -> %.1f (%.0f%% change) looks "
                    "like a data-source artifact; keeping previous value",
                    ticker,
                    prev_iv,
                    iv_30,
                    rel_change * 100,
                )
                iv_30 = None

    iv_history = _iv_history_from_db(db, ticker)
    if iv_30 is not None:
        iv_history = (iv_history + [iv_30])[-DEFAULT_RANK_LOOKBACK:]

    rank = iv_rank(iv_30, iv_history) if iv_30 is not None and len(iv_history) > 5 else None
    pct = iv_percentile(iv_30, iv_history) if iv_30 is not None and len(iv_history) > 5 else None

    spread_info = iv_hv_spread(iv_30, hv_20) if iv_30 is not None and hv_20 is not None else {}
    spread = spread_info.get("spread")

    row = {
        "spot_price": snap.get("spot_price"),
        "iv_30d": iv_30,
        "iv_60d": snap.get("iv_60d"),
        "iv_90d": snap.get("iv_90d"),
        "iv_180d": snap.get("iv_180d"),
        "iv_skew_25d": snap.get("iv_skew_25d"),
        "hv_20d": hv_20,
        "hv_60d": hv_block.get("hv_60d"),
        "hv_yz_20d": hv_block.get("hv_yz_20d"),
        "iv_rank": rank,
        "iv_percentile": pct,
        "iv_hv_spread": spread,
        "put_call_ratio": snap.get("put_call_ratio"),
        "total_call_volume": snap.get("total_call_volume"),
        "total_put_volume": snap.get("total_put_volume"),
        "total_open_interest": snap.get("total_open_interest"),
        "sector": sector,
    }

    problems = validate_daily_row(row)
    if problems:
        log.warning("Validation issues for %s: %s", ticker, "; ".join(problems))

    db.upsert_daily(ticker, today, **row)
    earnings_n = _sync_earnings(db, ticker)
    log.info(
        "Updated %s: IV30=%.2f HV20=%.2f spread=%s earnings=%d",
        ticker,
        iv_30 or 0.0,
        hv_20 or 0.0,
        f"{spread:+.2f}" if spread is not None else "n/a",
        earnings_n,
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default="")
    args = parser.parse_args(argv)

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        tickers = all_tickers()

    db = VolScopeDB()
    today = date.today()
    ok = 0
    failed: list[str] = []
    for i, t in enumerate(tickers):
        try:
            if process_ticker(db, t, today):
                ok += 1
            else:
                failed.append(t)
        except Exception as exc:
            log.error("Failed %s: %s", t, exc)
            failed.append(t)
        if i < len(tickers) - 1:
            time.sleep(SCRAPE_DELAY_SECONDS)
    db.close()
    log.info("Daily scrape: %d/%d tickers updated", ok, len(tickers))
    if failed:
        log.warning("Failed tickers (%d): %s", len(failed), ", ".join(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
