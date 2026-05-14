"""
Nightly cron — capture today's signals into ``signal_log``.

Wire into ``make scrape`` so we build a corpus of historical Signal
Engine recommendations. Future "signal performance over time" view
queries this table to compute per-signal-type hit rate, average P/L,
and Sharpe — turning the engine's daily output into an auditable
track record.

Run:
    python -m scripts.capture_signals             # all signals
    python -m scripts.capture_signals --dry-run   # print without writing
"""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="show what would be captured without writing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("capture_signals")

    from volscope.analytics.signals import generate_signals, persist_signals
    from volscope.data.database import VolScopeDB

    db = VolScopeDB()
    try:
        signals = generate_signals(db, include_filtered_shortvol=True)
        log.info("Generated %d signals today.", len(signals))
        for s in signals[:10]:
            log.info("  %s · %s · conf=%.0f · %s",
                      s.ticker, s.signal_type, s.confidence, s.strategy)
        if len(signals) > 10:
            log.info("  ... and %d more", len(signals) - 10)
        if args.dry_run:
            log.info("(dry-run — nothing persisted)")
            return 0
        rows = persist_signals(db, signals)
        log.info("Persisted %d rows into signal_log.", rows)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
