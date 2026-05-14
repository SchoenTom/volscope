"""
Daily paper-engine driver — v0.3.0.

Cycle:

1. Generate signals (factor → composite → gates → ranking).
2. Execute new signals via paper_engine against latest chain snapshots.
3. Daily MTM all open trades, apply exit rules, roll up bot_pnl_daily.

Run via launchd or `make paper-engine`. Designed to be re-entrant —
running it twice on the same day is a no-op for already-executed signals.

Usage:
    python -m scripts.ops.run_paper_engine                  # full cycle
    python -m scripts.ops.run_paper_engine --mtm-only       # skip new entries
    python -m scripts.ops.run_paper_engine --dry-run        # print only
"""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mtm-only", action="store_true",
                         help="skip new entries; just mark open trades")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    log = logging.getLogger("paper_engine")

    from volscope.data.chain_quote import SlippageModel
    from volscope.data.database import VolScopeDB
    from volscope.lifecycle.daily_mtm import (
        apply_exits, compute_mtm, rollup_daily_pnl,
    )

    db = VolScopeDB()
    slippage = SlippageModel()
    try:
        if not args.mtm_only:
            # Phase 1: regenerate today's signals.
            # The legacy signals module already runs daily via
            # scripts/scrape/capture_signals.py. The full pipeline
            # (factor → composite → gates → ranking → blueprint factory →
            # paper_execute) is wired in scripts/ops/run_paper_engine.py
            # but the blueprint factory is strategy-specific and will be
            # filled in Phase 2.5. For v0.3.0 we focus on MTM.
            log.info("(new-entry phase will be wired in Phase 2.5)")

        log.info("computing MTM for open trades...")
        rows = compute_mtm(db, slippage=slippage)
        log.info("  %d open trades evaluated", len(rows))
        for row in rows:
            log.info("    %s %s | %s | unrealized=$%+.0f | %.0f%% of target | %dDTE",
                      row.trade_id[:8], row.underlying, row.direction,
                      row.unrealized_pnl, row.pct_of_target * 100, row.min_dte)
            if row.should_close:
                log.info("      → CLOSE: %s", row.close_reason)

        if args.dry_run:
            log.info("(dry-run — no DB writes)")
            return 0

        n_closed = apply_exits(db, rows)
        log.info("  closed %d trades", n_closed)
        rollup_daily_pnl(db)
        log.info("  bot_pnl_daily updated for today")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
