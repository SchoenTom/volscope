#!/usr/bin/env python
"""
Daily convergence-score backfill.

Computes the LEAPS convergence score for every ticker in the latest
``daily_vol`` snapshot and writes the score plus its three sub-components
back into the same row. Idempotent — re-running on a snapshot already
populated overwrites with the same values.

Intended to run after ``scripts/daily_scrape.py`` and before
``scripts/run_alerts.py`` so the alert engine sees fresh scores.

Usage
-----
    python scripts/compute_convergence_daily.py             # today's snapshot
    python scripts/compute_convergence_daily.py --date 2026-05-09
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import duckdb                                                            # noqa: E402

from volscope.analytics.leaps_convergence import compute_convergence    # noqa: E402
from volscope.config import DB_PATH                                      # noqa: E402


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute daily convergence scores")
    parser.add_argument("--date", type=_parse_date, default=None,
                        help="Snapshot date (default: latest in DB)")
    parser.add_argument("--lookback-days", type=int, default=280,
                        help="History window per ticker for scoring")
    parser.add_argument("--benchmark-ticker", type=str, default="SPY")
    args = parser.parse_args()

    con = duckdb.connect(str(DB_PATH))
    try:
        snap_date = args.date
        if snap_date is None:
            snap_date = con.execute("SELECT MAX(date) FROM daily_vol").fetchone()[0]
            if snap_date is None:
                print("[convergence] no daily_vol rows — nothing to do")
                return 0
        print(f"[convergence] snapshot date: {snap_date}")

        # Latest row per ticker on snapshot date.
        # DuckDB 1.5.2 bug: `SELECT * FROM daily_vol WHERE date = '<lit>'`
        # returns an empty DataFrame even when COUNT(*) on the same query
        # finds matches. `BETWEEN` works around it. snap_iso is internal
        # (derived from MAX(date)), not user input — SQL injection is moot.
        snap_iso = snap_date.isoformat()
        latest = con.execute(
            f"SELECT * FROM daily_vol "
            f"WHERE date BETWEEN '{snap_iso}' AND '{snap_iso}'"
        ).fetchdf()
        if latest.empty:
            print(f"[convergence] no rows for {snap_date}")
            return 0
        print(f"[convergence] {len(latest)} tickers to score")

        # Histories.
        cutoff_iso = snap_date.isoformat()
        history_df = con.execute(
            f"""
            SELECT * FROM daily_vol
            WHERE date <= DATE '{cutoff_iso}'
            ORDER BY ticker, date
            """,
        ).fetchdf()
        history_by_ticker = {
            t: g.tail(args.lookback_days).reset_index(drop=True)
            for t, g in history_df.groupby("ticker")
        }
        bench = history_df[history_df["ticker"] == args.benchmark_ticker]
        if bench.empty:
            print(f"[convergence] benchmark {args.benchmark_ticker} missing — "
                  "neglect component will be silently dropped")

        n_written = 0
        for _, row in latest.iterrows():
            ticker = row.get("ticker")
            if ticker is None:
                continue
            hist = history_by_ticker.get(ticker)
            result = compute_convergence(row, hist, bench)
            con.execute(
                f"""
                UPDATE daily_vol
                SET convergence_score      = ?,
                    convergence_mispricing = ?,
                    convergence_neglect    = ?,
                    convergence_reversal   = ?
                WHERE ticker = ? AND date = DATE '{snap_date.isoformat()}'
                """,
                [
                    float(result.score),
                    None if result.mispricing is None else float(result.mispricing),
                    None if result.neglect    is None else float(result.neglect),
                    None if result.reversal   is None else float(result.reversal),
                    ticker,
                ],
            )
            n_written += 1
        print(f"[convergence] wrote scores for {n_written} tickers")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
