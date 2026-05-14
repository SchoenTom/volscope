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
from volscope.config import DEFAULT_HV_LONG, DEFAULT_HV_SHORT, DEFAULT_RANK_LOOKBACK  # noqa: E402
from volscope.data.database import VolScopeDB  # noqa: E402
from volscope.data.price_fetcher import fetch_ohlcv  # noqa: E402
from volscope.data.ticker_universe import all_tickers, sector_of  # noqa: E402

log = logging.getLogger("volscope.seed")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def seed_ticker(db: VolScopeDB, ticker: str, period: str = "2y") -> int:
    df = fetch_ohlcv(ticker, period=period)
    if df.empty:
        log.warning("No OHLCV data for %s — skipping", ticker)
        return 0

    close = df["Close"]
    hv_s = hv_close_to_close(close, DEFAULT_HV_SHORT)
    hv_l = hv_close_to_close(close, DEFAULT_HV_LONG)
    try:
        hv_yz = hv_yang_zhang(df["Open"], df["High"], df["Low"], df["Close"], DEFAULT_HV_SHORT)
    except Exception:
        hv_yz = pd.Series(index=df.index, dtype=float)

    sector = sector_of(ticker)
    rows = 0
    for i, idx in enumerate(df.index):
        if i < DEFAULT_HV_LONG:
            continue
        d = idx.date() if hasattr(idx, "date") else idx
        iv_proxy = float(hv_s.iloc[i]) if pd.notna(hv_s.iloc[i]) else None
        history = hv_s.iloc[max(0, i - DEFAULT_RANK_LOOKBACK) : i].dropna()
        db.upsert_daily(
            ticker,
            d,
            spot_price=float(close.iloc[i]),
            iv_30d=iv_proxy,
            hv_20d=iv_proxy,
            hv_60d=float(hv_l.iloc[i]) if pd.notna(hv_l.iloc[i]) else None,
            hv_yz_20d=float(hv_yz.iloc[i]) if pd.notna(hv_yz.iloc[i]) else None,
            iv_rank=iv_rank(iv_proxy, history.tolist()) if iv_proxy is not None else None,
            iv_percentile=iv_percentile(iv_proxy, history.tolist()) if iv_proxy is not None else None,
            iv_hv_spread=0.0 if iv_proxy is not None else None,
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
