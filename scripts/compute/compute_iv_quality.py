"""
Compute IV robustness quality scores for every ticker.

Per the v0.6.1 IV Robustness Subsystem: walks every ticker in
daily_vol, pulls the 252-day IV history, runs
``assess_iv_quality()``, and writes the result back to the latest
daily_vol row (columns added in migration 006).

Runs nightly via launchd / cron after the daily scrape. Idempotent —
re-running the same date overwrites the row's quality columns with
fresh values.

Performance: ~30-60 ms per ticker (CUSUM fallback) or 50-200 ms per
ticker (ruptures Pelt). 14-ticker bot universe = under 5 seconds;
full 280-ticker universe = under 2 minutes.

Usage:
    python -m scripts.compute.compute_iv_quality                   # full universe
    python -m scripts.compute.compute_iv_quality --tickers AAPL MSFT
    python -m scripts.compute.compute_iv_quality --dry-run         # report only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="*", default=None,
                         help="specific tickers (default: all in daily_vol)")
    parser.add_argument("--dry-run", action="store_true",
                         help="report only; don't write back")
    parser.add_argument("--lookback", type=int, default=252,
                         help="days of history per ticker (default 252)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    log = logging.getLogger("compute_iv_quality")

    from volscope.analytics.iv_robustness import assess_iv_quality
    from volscope.data.database import VolScopeDB

    db = VolScopeDB()
    try:
        # Tickers in scope
        if args.tickers:
            tickers = list(args.tickers)
        else:
            tickers = [r[0] for r in db.con.execute(
                "SELECT DISTINCT ticker FROM daily_vol ORDER BY ticker"
            ).fetchall()]
        log.info("processing %d tickers (lookback=%d)", len(tickers), args.lookback)

        t0 = time.time()
        n_block = n_caution = n_trade = n_skip = 0
        for ticker in tickers:
            # Pull history
            hist = db.con.execute(
                f"""
                SELECT date, iv_30d, iv_rank, iv_percentile
                FROM daily_vol
                WHERE ticker = ? AND iv_30d IS NOT NULL
                ORDER BY date DESC
                LIMIT {args.lookback}
                """, [ticker]
            ).fetchdf()
            if len(hist) < 60:
                log.debug("  %s: skip (only %d obs)", ticker, len(hist))
                n_skip += 1
                continue
            hist = hist.sort_values("date").reset_index(drop=True)
            iv_series = pd.Series(
                hist["iv_30d"].astype(float).values,
                index=pd.to_datetime(hist["date"]),
            )
            # Get the most-recent IVR + IVP (already computed by scraper)
            latest = hist.iloc[-1]
            iv_rank_value = float(latest["iv_rank"]) if pd.notna(latest["iv_rank"]) else None
            iv_perc_value = float(latest["iv_percentile"]) if pd.notna(latest["iv_percentile"]) else None

            report = assess_iv_quality(
                ticker=ticker, iv_series=iv_series,
                iv_rank_value=iv_rank_value,
                iv_percentile_value=iv_perc_value,
            )
            if report.recommendation == "TRADE":
                n_trade += 1
            elif report.recommendation == "CAUTION":
                n_caution += 1
            else:
                n_block += 1

            if args.verbose:
                log.debug(
                    "  %s: %s score=%d cont=%s div=%.1f break=%s",
                    ticker, report.recommendation, report.quality_score,
                    report.contamination.value, report.divergence,
                    report.structural_break["break_date"] if report.structural_break else "—",
                )

            if args.dry_run:
                continue

            # Persist
            d = report.to_dict()
            sb = d["structural_break"] or {}
            db.con.execute(
                """
                UPDATE daily_vol
                SET robust_iv_rank = ?,
                    contamination_level = ?,
                    ivr_ivp_divergence = ?,
                    structural_break_date = ?,
                    structural_break_days_ago = ?,
                    structural_break_magnitude = ?,
                    iv_quality_score = ?,
                    iv_recommendation = ?,
                    iv_warnings = ?
                WHERE ticker = ?
                  AND date = (SELECT MAX(date) FROM daily_vol WHERE ticker = ?)
                """,
                [
                    d["robust_iv_rank"],
                    d["contamination"],
                    d["divergence"],
                    sb.get("break_date") if isinstance(sb, dict) else None,
                    sb.get("days_since_break") if isinstance(sb, dict) else None,
                    sb.get("magnitude") if isinstance(sb, dict) else None,
                    d["quality_score"],
                    d["recommendation"],
                    json.dumps(d["warnings"]),
                    ticker,
                    ticker,
                ],
            )

        elapsed = time.time() - t0
        log.info(
            "DONE — TRADE=%d CAUTION=%d BLOCK=%d skipped=%d in %.1fs",
            n_trade, n_caution, n_block, n_skip, elapsed,
        )
        if args.dry_run:
            log.info("(dry-run — nothing written)")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
