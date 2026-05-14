#!/usr/bin/env python
"""
CLI: walk-forward backtest of the LEAPS-convergence rule.

Examples
--------
    # Run the default 365d-hold backtest against the live DB
    python scripts/run_leaps_backtest.py

    # Different horizon
    python scripts/run_leaps_backtest.py --horizon-days 180

    # Higher conviction gate
    python scripts/run_leaps_backtest.py --threshold 75

    # Output to JSON for the dossier mini-chart
    python scripts/run_leaps_backtest.py --json /tmp/bt.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

# Allow running from project root without an install.
_ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from volscope.analytics.leaps_backtest import (                          # noqa: E402
    add_bootstrap_ci, run_backtest, summarise,
)
from volscope.analytics.leaps_convergence import CONVERGENCE_THRESHOLD  # noqa: E402
from volscope.config import DB_PATH                                     # noqa: E402

import duckdb                                                            # noqa: E402


def _serialise(obj):
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    if isinstance(obj, date):
        return obj.isoformat()
    return str(obj)


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward LEAPS backtest")
    parser.add_argument("--horizon-days", type=int, default=365,
                        help="Hold horizon in days (default: 365)")
    parser.add_argument("--threshold", type=float, default=CONVERGENCE_THRESHOLD,
                        help=f"Convergence gate (default: {CONVERGENCE_THRESHOLD})")
    parser.add_argument("--sample-every", type=int, default=21,
                        help="Score every Nth trading day (default: 21 ≈ monthly)")
    parser.add_argument("--strike-uplift", type=float, default=0.75,
                        help="Strike uplift over spot (default: 0.75)")
    parser.add_argument("--target-dte", type=int, default=730,
                        help="Days-to-expiry target (default: 730)")
    parser.add_argument("--json", type=str, default=None,
                        help="Write the full result as JSON to this path")
    parser.add_argument("--limit-tickers", type=int, default=None,
                        help="Restrict to top-N tickers by row count (debug)")
    parser.add_argument("--bootstrap", type=int, default=1000,
                        help="Bootstrap samples for the mean-CI (0 disables)")
    args = parser.parse_args()

    print(f"[backtest] DB: {DB_PATH}")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    panel = con.execute("SELECT * FROM daily_vol").fetchdf()
    bench = con.execute("SELECT * FROM daily_vol WHERE ticker = 'SPY'").fetchdf()
    con.close()

    print(f"[backtest] panel rows: {len(panel):,} · tickers: "
          f"{panel['ticker'].nunique() if not panel.empty else 0}")
    print(f"[backtest] benchmark rows: {len(bench):,}")

    if args.limit_tickers and not panel.empty:
        keep = (
            panel.groupby("ticker").size().sort_values(ascending=False)
            .head(args.limit_tickers).index.tolist()
        )
        panel = panel[panel["ticker"].isin(keep + ["SPY"])]
        print(f"[backtest] restricted to top-{args.limit_tickers} → {len(panel):,} rows")

    result = run_backtest(
        panel=panel,
        benchmark_panel=bench,
        horizon_days=args.horizon_days,
        threshold=args.threshold,
        target_dte_days=args.target_dte,
        strike_uplift=args.strike_uplift,
        sample_every_n_days=args.sample_every,
    )
    if args.bootstrap > 0 and result.n_trades > 0:
        result = add_bootstrap_ci(result, n_samples=args.bootstrap)
    print(f"[backtest] {summarise(result)}")
    if result.by_year:
        print("[backtest] by entry year:")
        for year, stats in sorted(result.by_year.items()):
            print(
                f"           {year}: n={stats['n']:>3}  "
                f"win {stats['win_rate']*100:5.1f}%  "
                f"median {stats['median']:+7.1f}%  mean {stats['mean']:+7.1f}%"
            )

    if args.json:
        out = {
            "n_trades": result.n_trades,
            "win_rate": result.win_rate,
            "median_return": result.median_return,
            "mean_return": result.mean_return,
            "p25_return": result.p25_return,
            "p75_return": result.p75_return,
            "max_return": result.max_return,
            "min_return": result.min_return,
            "horizon_days": result.horizon_days,
            "threshold": result.threshold,
            "by_year": result.by_year,
            "trades": [
                {**t.__dict__,
                 "entry_date": t.entry_date.isoformat(),
                 "exit_date":  t.exit_date.isoformat(),
                 "expiry":     t.expiry.isoformat()}
                for t in result.trades
            ],
        }
        Path(args.json).write_text(json.dumps(out, default=_serialise, indent=2))
        print(f"[backtest] wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
