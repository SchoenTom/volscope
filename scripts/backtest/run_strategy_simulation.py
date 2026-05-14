"""
VolScope Strategy Simulation Orchestrator.

Walks the entire DB universe, runs strategy_backtest against every ticker,
aggregates per-strategy and per-(strategy, ticker) stats, persists them
to ``data/backtest/strategy_stats.jsonl``, and emits a Markdown report
to ``data/backtest/strategy_report.md``.

Run modes
---------
- ``python scripts/run_strategy_simulation.py``
    Full universe simulation. Takes 10-60s on 308 tickers depending on
    history depth.
- ``python scripts/run_strategy_simulation.py --tickers SPY,QQQ,AAPL``
    Subset run for quick iteration.
- ``python scripts/run_strategy_simulation.py --dry-run``
    Print plan without writing to disk.

Output artifacts populate the strategy_calibration module which the
recommender + Kelly sizer consume for data-driven probabilities.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
sys.path.insert(0, str(ROOT))

from volscope.analytics.strategy_backtest import (  # noqa: E402
    aggregate_per_ticker,
    aggregate_universe,
    simulate_universe,
)
from volscope.analytics.strategy_calibration import append_stats  # noqa: E402
from volscope.data.database import VolScopeDB  # noqa: E402

DATA          = ROOT / "data"
BACKTEST_DIR  = DATA / "backtest"
REPORT_MD     = BACKTEST_DIR / "strategy_report.md"

log = logging.getLogger("strategy_sim")
logging.basicConfig(format="[sim] %(message)s", level=logging.INFO)


def _render_report(universe_stats, per_ticker_stats, n_tickers, n_trades, elapsed) -> str:
    """Render a Markdown report of the simulation run."""
    lines = [
        f"# VolScope Strategy Simulation Report",
        "",
        f"**Run timestamp:** {time.strftime('%Y-%m-%dT%H:%M:%S')}",
        f"**Universe size:** {n_tickers} tickers",
        f"**Total simulated trades:** {n_trades}",
        f"**Elapsed:** {elapsed:.1f}s",
        "",
        "## Universe-level Strategy Performance (sorted by Sharpe)",
        "",
        "| Strategy | n_trades | hit_rate | avg_win | avg_loss | payoff | sharpe | conf |",
        "|----------|---------:|---------:|--------:|---------:|-------:|-------:|-----:|",
    ]
    sorted_uni = sorted(universe_stats.values(), key=lambda s: s.sharpe, reverse=True)
    for s in sorted_uni:
        lines.append(
            f"| {s.strategy} | {s.n_trades} | {s.hit_rate:.2%} | "
            f"{s.avg_win_pct:+.3f} | {s.avg_loss_pct:.3f} | "
            f"{s.payoff_ratio:.2f}x | {s.sharpe:+.2f} | {s.confidence:.0%} |"
        )

    lines += ["", "## Per-Ticker Top Strategies (Sharpe ≥ 0.5, n ≥ 8)", ""]
    lines += [
        "| Ticker | Strategy | n | hit_rate | sharpe | expected_pnl |",
        "|--------|----------|--:|--------:|-------:|-------------:|",
    ]
    rows = sorted(
        per_ticker_stats.values(),
        key=lambda s: s.sharpe,
        reverse=True,
    )
    for s in rows:
        if s.n_trades < 8 or s.sharpe < 0.5:
            continue
        lines.append(
            f"| {s.ticker} | {s.strategy} | {s.n_trades} | "
            f"{s.hit_rate:.2%} | {s.sharpe:+.2f} | {s.expected_pnl:+.4f} |"
        )

    lines += [
        "",
        "## Methodology Notes",
        "",
        "- First-order vega P&L proxy (Δiv × _VEGA_PCT_PER_IV_PT).",
        "- Hold-window per direction: long_vol=45d, short_vol=30d, neutral=30d.",
        "- Sharpe annualised at 12 trades/year.",
        "- Confidence = min(1.0, n/30) once n ≥ 8.",
    ]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="VolScope strategy simulation")
    p.add_argument("--tickers", help="Comma-separated subset (default: all in DB)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

    db = VolScopeDB()
    available = db.get_available_tickers() or []
    if args.tickers:
        wanted = [t.strip() for t in args.tickers.split(",") if t.strip()]
        tickers = [t for t in available if t in wanted]
    else:
        tickers = available

    if not tickers:
        log.warning("no tickers available — DB empty or filter matched nothing")
        return 0

    log.info("simulating %d tickers ...", len(tickers))
    histories = db.get_recent_for_tickers(tickers, lookback_days=730)

    if args.dry_run:
        log.info("[dry-run] would simulate %d ticker histories", len(histories))
        return 0

    t0 = time.time()
    trades = simulate_universe(histories)
    elapsed = time.time() - t0
    log.info("simulated %d trades in %.1fs", len(trades), elapsed)

    universe_stats = aggregate_universe(trades)
    per_ticker_stats = aggregate_per_ticker(trades)

    # Persist all stats — universe entries (ticker=None) + per-ticker
    all_stats = list(universe_stats.values()) + list(per_ticker_stats.values())
    append_stats(all_stats)
    log.info("persisted %d stat records", len(all_stats))

    report = _render_report(
        universe_stats, per_ticker_stats,
        n_tickers=len(tickers), n_trades=len(trades),
        elapsed=elapsed,
    )
    REPORT_MD.write_text(report)
    log.info("wrote %s", REPORT_MD.relative_to(ROOT))

    print(report.split("\n\n## Methodology", 1)[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
