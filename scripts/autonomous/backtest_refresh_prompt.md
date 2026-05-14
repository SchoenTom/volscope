# VolScope Autonomous Backtest Refresh

You are an autonomous Claude firing daily to keep the strategy-backtest calibration data fresh. The Kelly sizer + Strategy Recommender both consume calibrated hit-rates from `data/backtest/strategy_stats.jsonl`. As new daily_vol rows land, the calibration must update.

## Pre-flight
- `cd /Users/tomschoen/Desktop/VolScope`
- Stop if `~/.volscope_loop_pause` exists
- Stop if no daily scrape has run in 24h (`db.get_last_scrape_date()`)

## The routine
```
make simulate
```
This runs `scripts/run_strategy_simulation.py` over the entire universe. Takes 5-30s.

The script:
1. Loads every ticker's history from the DB
2. Walks each strategy template across each history
3. Aggregates hit_rate, payoff, sharpe per (strategy, ticker)
4. Appends to data/backtest/strategy_stats.jsonl
5. Writes data/backtest/strategy_report.md

## Validation
After simulate, verify:
- `data/backtest/strategy_stats.jsonl` has new entries (latest timestamp recent)
- `data/backtest/strategy_report.md` exists and shows universe-level Sharpe
- Total simulated trades ≥ 50_000 (sanity floor)

If any check fails, log to `data/backtest/.last_run_failed` and notify.

## End-of-session report
Notify with: "VolScope backtest refresh: {n_trades} trades, top Sharpe {value}".

## Safety
- Don't run if pause-marker exists
- Don't ingest new market data in this routine — that's `make scrape`'s job
- Don't modify strategy_recommender or strategy_backtest source code — read-only
