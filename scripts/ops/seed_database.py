"""Seed the VolScope DuckDB with historical vol data for the ticker universe.

Usage:
    python scripts/seed_database.py --tickers SPY,AAPL,TSLA
    python scripts/seed_database.py                    # all universe tickers
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Make the project importable when run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from volscope.analytics.historical_vol import (  # noqa: E402
    hv_close_to_close,
    hv_yang_zhang,
)
from volscope.analytics.vol_metrics import iv_percentile, iv_rank  # noqa: E402
from volscope.config import (  # noqa: E402
    DEFAULT_HV_LONG,
    DEFAULT_HV_MATCHED,
    DEFAULT_HV_SHORT,
    DEFAULT_RANK_LOOKBACK,
)
from volscope.data.database import VolScopeDB  # noqa: E402
from volscope.data.price_fetcher import fetch_ohlcv  # noqa: E402
from volscope.data.ticker_universe import all_tickers, sector_of  # noqa: E402

log = logging.getLogger("volscope.seed")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Variance Risk Premium multiplier — matches ticker_resolver._SEED_VRP_MULT.
# IV proxy = Yang-Zhang HV × 1.12; produces a series that visibly differs
# from the close-to-close HV baseline so the Scope spread chart shows
# real signal instead of a flat line at zero. Real iv_30d from
# daily_scrape.py OVERWRITES this proxy when the scraper runs.
_SEED_VRP_MULT: float = 1.12


def seed_ticker(db: VolScopeDB, ticker: str, period: str = "2y") -> int:
    df = fetch_ohlcv(ticker, period=period)
    if df.empty:
        log.warning("No OHLCV data for %s — skipping", ticker)
        return 0

    close = df["Close"]
    hv_cc_s = hv_close_to_close(close, DEFAULT_HV_SHORT)
    hv_cc_l = hv_close_to_close(close, DEFAULT_HV_LONG)
    try:
        hv_yz_s = hv_yang_zhang(df["Open"], df["High"], df["Low"], df["Close"], DEFAULT_HV_SHORT)
    except Exception:
        hv_yz_s = pd.Series(index=df.index, dtype=float)
    try:
        hv_yz_m = hv_yang_zhang(df["Open"], df["High"], df["Low"], df["Close"], DEFAULT_HV_MATCHED)
    except Exception:
        hv_yz_m = pd.Series(index=df.index, dtype=float)

    # IV proxy series — YZ × VRP, NOT CC. CC stays as the hv_20d baseline.
    iv_proxy_series = hv_yz_s * _SEED_VRP_MULT

    sector = sector_of(ticker)
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
        # Fallback to scaled CC when YZ has no value yet (first window / bad OHLC)
        if iv_val is None and hv_val is not None:
            iv_val = hv_val * _SEED_VRP_MULT

        rank_history = iv_proxy_series.iloc[max(0, i - DEFAULT_RANK_LOOKBACK) : i].dropna()

        spread = None
        if iv_val is not None and hv_val is not None:
            spread = iv_val - hv_val

        hv_yz_30 = float(hv_yz_m.iloc[i]) if pd.notna(hv_yz_m.iloc[i]) else None
        spread_matched = None
        if iv_val is not None and hv_yz_30 is not None:
            spread_matched = iv_val - hv_yz_30

        db.upsert_daily(
            ticker,
            d,
            spot_price=float(close.iloc[i]),
            iv_30d=iv_val,
            hv_20d=hv_val,
            hv_60d=float(hv_cc_l.iloc[i]) if pd.notna(hv_cc_l.iloc[i]) else None,
            hv_yz_20d=float(hv_yz_s.iloc[i]) if pd.notna(hv_yz_s.iloc[i]) else None,
            hv_yz_30d=hv_yz_30,
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
            iv_hv_spread_matched=spread_matched,
            sector=sector,
        )
        rows += 1
    log.info("Seeded %s: %d rows", ticker, rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed VolScope DB with HV data.")
    parser.add_argument("--tickers", type=str, default="", help="Comma-separated tickers")
    parser.add_argument("--period", type=str, default="2y")
    args = parser.parse_args(argv)

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        tickers = all_tickers()

    db = VolScopeDB()
    total = 0
    for t in tickers:
        try:
            total += seed_ticker(db, t, args.period)
        except Exception as exc:
            log.error("Failed seeding %s: %s", t, exc)
    db.close()
    log.info("Seed complete: %d rows across %d tickers", total, len(tickers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
