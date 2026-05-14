"""
Nightly chain-scrape driver — populates bot_chain_snapshots for the
paper engine.

Usage:
    python -m scripts.scrape.scrape_chains              # all bot tier-1 tickers
    python -m scripts.scrape.scrape_chains AAPL MSFT    # specific tickers
    python -m scripts.scrape.scrape_chains --max-exp 6  # cap expiries per ticker

Runtime: ~10-20s per ticker. The bot universe is ~14 tickers, so
~3-5 minutes total per nightly run.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

DEFAULT_UNIVERSE = [
    # Tier 1 — always tradable
    "SPY", "QQQ", "IWM", "XSP",
    # Tier 2 — pause around earnings
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "AMD", "QCOM", "MU",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="*", default=DEFAULT_UNIVERSE,
                         help="tickers to scrape (default: bot universe)")
    parser.add_argument("--max-exp", type=int, default=None,
                         help="cap expiries per ticker (faster, less data)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    log = logging.getLogger("chain_scrape")

    from volscope.data.chain_scraper import fetch_chain, upsert_rows
    from volscope.data.database import VolScopeDB

    db = VolScopeDB()
    try:
        total = 0
        t0 = time.time()
        for ticker in args.tickers:
            t_start = time.time()
            rows = fetch_chain(ticker, max_expiries=args.max_exp)
            n = upsert_rows(db, rows)
            total += n
            log.info("  %s: %4d rows in %.1fs", ticker, n, time.time() - t_start)
        log.info("DONE — %d rows across %d tickers in %.1fs",
                  total, len(args.tickers), time.time() - t0)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
