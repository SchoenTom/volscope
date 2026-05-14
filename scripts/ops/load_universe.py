"""
VolScope universe-load runner — Pillar A.

Robust bulk loader for the curated universe. Idempotent (skip already-
loaded), per-ticker retry with backoff, partial-failure logging, optional
resume from previous failures.

Usage
-----
    python scripts/load_universe.py                # full universe
    python scripts/load_universe.py --resume       # only retry last failures
    python scripts/load_universe.py --max-seconds 600 --quiet
    python scripts/load_universe.py --tickers AAPL,MSFT,SPY
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from volscope.data.database import VolScopeDB  # noqa: E402
from volscope.data.universe_loader import (  # noqa: E402
    TickerOutcome,
    load_universe,
    persist_report,
    resume_failures,
)


def main() -> int:
    p = argparse.ArgumentParser(description="VolScope universe loader")
    p.add_argument("--tickers", help="Comma-separated subset (default: full universe)")
    p.add_argument("--resume", action="store_true",
                   help="Re-try only the tickers from the latest failures file")
    p.add_argument("--max-seconds", type=float, default=None,
                   help="Wall-clock budget; stop cleanly at next ticker boundary")
    p.add_argument("--retry-attempts", type=int, default=3,
                   help="Per-ticker retry count")
    p.add_argument("--quiet", action="store_true", help="Suppress per-ticker progress")
    args = p.parse_args()

    logging.basicConfig(
        format="[load] %(message)s",
        level=logging.WARNING if args.quiet else logging.INFO,
    )

    if args.tickers:
        target = [t.strip() for t in args.tickers.split(",") if t.strip()]
    elif args.resume:
        target = resume_failures()
        if not target:
            print("No failures file found — nothing to resume.")
            return 0
        print(f"Resuming with {len(target)} tickers from latest failures file.")
    else:
        target = None  # full universe

    db = VolScopeDB()

    def _on_progress(outcome: TickerOutcome, idx: int, total: int) -> None:
        if args.quiet:
            return
        glyph = {
            "loaded":  "✓",
            "retried": "↻",
            "skipped": "·",
            "failed":  "✗",
        }.get(outcome.status, "?")
        print(f"  [{idx:>3}/{total}] {glyph} {outcome.ticker:<14} "
              f"({outcome.status}, attempts={outcome.attempts}) {outcome.message[:60]}")

    print("Starting universe load…")
    report = load_universe(
        db,
        tickers=target,
        progress_callback=_on_progress,
        max_seconds=args.max_seconds,
        retry_attempts=args.retry_attempts,
    )
    report_path = persist_report(report)

    print()
    print(f"=== LOAD REPORT ({report.elapsed_s:.0f}s) ===")
    print(f"  Total:    {report.n_total}")
    print(f"  Skipped:  {report.n_skipped} (already loaded or time budget)")
    print(f"  Loaded:   {report.n_loaded}")
    print(f"  Failed:   {report.n_failed}")
    if report.n_total > report.n_skipped:
        print(f"  Coverage: {report.coverage_pct():.1f}%")
    print(f"  Report:   {report_path}")
    if report.n_failed > 0:
        print(f"  → re-run with --resume to retry just the failures")

    return 0 if report.n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
