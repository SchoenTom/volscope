# VolScope — Developer Guide

## What is this?
Volatility Intelligence Platform for retail options traders.
Python-only. Streamlit frontend. DuckDB backend.

## Commands
- `make setup` — Install dependencies
- `make test` — Run all tests
- `make run` — Start Streamlit app
- `make scrape` — Run daily data scrape
- `pytest tests/ -v` — Verbose test output
- `streamlit run volscope/ui/app.py` — Start app

## Architecture
- `volscope/analytics/` — All financial math (BSM, HV, metrics)
- `volscope/data/` — Data pipeline (scraper, DB, fetcher)
- `volscope/ui/` — Streamlit pages and components
- `tests/` — pytest test suite

## Conventions
- Type hints everywhere
- Docstrings on every public function
- Tests before implementation (TDD)
- All financial calculations validated against known values
- Edge cases handled gracefully (return None, not crash)

## Autonomous Bot Masterplan (canonical north star)

**Anchor doc:** `~/.claude/plans/volscope-bot-masterplan.md`

5-phase build to a production-grade autonomous IV mean-reversion options
bot executing via Interactive Brokers (ib_async). All future autonomous
iteration must trace to a deliverable in that plan. Phase 0 (bug fixes)
+ Phase 1 (signal engine scaffold) shipped 2026-05-14:

- `config/` — strategies.yaml, risk.yaml, tickers.yaml, calendar.yaml
- `volscope/signals/` — factors.py (IVR, IVP, IV/HV, term, skew, momentum),
  composite.py (0-100 weighted score + size_from_score), filters.py (8
  hard gates: persistence, volume, OI, BAS, earnings, macro, regime,
  consensus)
- `volscope/analytics/regime.py` — 2-state Gaussian HMM (hmmlearn)
- `volscope/persistence/migrations/001_init.sql` — 5 bot_* tables
  (trades, legs, pnl_daily, signals_log, orders_log) + idempotent runner
- `volscope/ui/views/bot_dashboard_page.py` — operator-facing read-only
  view (NLV, Greeks, regime, signals, open trades, equity curve)
- Phase 0 bug fixes: dead-tautology in rotation_page removed; Material
  Symbols ghost text CSS hardened (font-size:0); sector heatmap
  forward/back-fill densified; st.metric truncation replaced with kpi_grid;
  Pre-Trade fillcolor already rgba() throughout.

## NEUE FEATURE: IV Mean-Reversion Trading System (2026-05-14)

VolScope is no longer just a research tool — it now actively *generates
trade signals*. The missing link is filled: a bidirectional scanner
that turns vol-state extremes into ready-to-execute setups.

Workflow:
   Scanner detects extreme  →  Signal emitted with direction +
   confidence + strategy + params  →  User clicks "→ Options Lab"
   →  Lab opens with pre-filled ticker / template / strike / DTE
   →  User reviews P&L + Greeks + Scenario matrix  →  User paper-buys.

Academic basis:
   - 65 % of large-cap US tickers show statistically significant IV
     mean-reversion (MDPI Risks 2024, N=100, 2018-2023).
   - 85 % of the time IV ≥ realised vol (Volatility Risk Premium,
     Bali et al. 2008).
   - 16-Δ Iron Condor at 45 DTE managed @ 50 % credit → 78-83 %
     win rate (Cohen & Donohue 2024).
   - ROI rises ~60 % when filtering for IVR > 30 (10-year SPY backtest).

Implemented in:
   - `volscope/analytics/signals.py`     — Signal Engine
   - `volscope/ui/views/signals_page.py` — Dashboard
   - Sidebar entry "Signals" under DECISIONS
   - Options Lab consumes `ol_ticker / ol_template / ol_override_strike
     / ol_dte` from session_state, so the prefill flow works without
     touching Lab internals.

## Ideas & Improvements
- **DB outside iCloud scope** (implemented): default `DB_PATH` moved to
  `~/Library/Application Support/VolScope/volscope.db` on macOS (XDG_DATA_HOME
  on Linux). The old location `<project>/data/volscope.db` collided with
  macOS File Provider, which held a write handle on files under Desktop and
  broke DuckDB's exclusive lock. Override with `VOLSCOPE_DATA_DIR=/some/path`.
- **Verify runtime smoke uses process groups** (implemented): `scripts/verify.py`
  now spawns streamlit via `start_new_session=True` and sends SIGTERM (then
  SIGKILL) to the entire process group on teardown. Previously, terminating
  the Python subprocess left a Tornado child alive, which kept the DB lock,
  which broke the next `make run`.
- **Verify uses an isolated temp DB** (implemented): the runtime smoke sets
  `VOLSCOPE_DATA_DIR` to a temp dir so it never touches the user's real DB,
  and deletes it on teardown.
- **Graceful DB-unavailable page** (implemented): if `get_db()` still fails
  after a 5-attempt backoff retry, `volscope/ui/app.py` shows a friendly
  error card with the DB path and a copy-pasteable CHECKPOINT command
  instead of a raw traceback.
- **International exchange fallback** (implemented): the resolver tries bare
  first, then a suffix list driven by input shape. Digits → `.HK`, `.TW`,
  `.SS`, `.SZ`, `.T`, `.KS`. Alpha → `.L`, `.DE`, `.PA`, `.AS`, `.AX`, `.TO`.
  Known edge case: for ambiguous digit codes (e.g. `2330` has both HK and TW
  listings), HK wins due to priority order. User can disambiguate by typing
  the explicit suffix (`2330.TW`). A future improvement is volume-weighted
  ranking, but it costs an extra Yahoo call per candidate.
- **Company name + sector pill on Scope header** (implemented): the resolver
  fetches `shortName` / `longName` via yfinance on first add and stores it in
  `daily_vol.company_name`. Schema migrates via `ALTER TABLE ... ADD COLUMN
  IF NOT EXISTS`. The Scope header now reads `◈ AAPL  Apple Inc. [Tech]`.
- **Discover as landing page** (implemented): the PDF spec is categorical —
  users land where the opportunities are, not on an empty Scope.
- **Left-border colored cards** (implemented): Discover cards get a 4px green
  / red / blue left accent matching the PDF. Hover lifts with a soft shadow
  in the accent color.
- **JetBrains Mono + DM Sans** (implemented): Google Fonts imported, tabular
  numerals for data, DM Sans for UI chrome — the Bloomberg-in-your-pocket feel.
- **Inline ProgressColumn bars in Scanner** (implemented): `iv_percentile` and
  `iv_rank` render as in-cell bars via `st.column_config.ProgressColumn`. No
  more flat dataframe.
- **ER annotation on IV/HV chart** (implemented): earnings vlines now get a
  gold "ER" badge at the top of the chart.
- **Shaded zones on Percentile chart** (implemented): green band 0-20, red
  band 80-100, with inline CHEAP/RICH labels on the threshold lines.
- **On-demand ticker resolver** (implemented): `volscope/data/ticker_resolver.py`
  + sidebar form. Any Yahoo symbol (e.g. `PLTR`, `^VIX`, `BRK.B`) validates,
  pulls 2y OHLCV, backfills HV into `daily_vol`, and becomes a first-class
  ticker without touching `ticker_universe.py`. Idempotent — re-adds are no-ops.
- **52-week IV range bar** (implemented): horizontal range visualization with
  cheap/rich zone shading and a verdict label — the "gut-punch" glance that
  tells a trader where IV sits in its annual context.
- Term-structure chart (future): render iv_30d vs iv_60d as a small curve on the
  Scope page to surface contango/backwardation directly.
- Earnings IV-crush estimator (future): compare pre/post-earnings IV drops to
  build a historical crush distribution per ticker.
- Universe heatmap (future): single-glance grid of IV percentile across all
  tickers, colored by z-score.
