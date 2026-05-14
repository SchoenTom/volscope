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

---

## VolScope Operating System (v0.4.0, 2026-05-14)

This section is the **dauerhafte Framework** that structures every
future Claude Code session on VolScope. Read on session boot. Update
when you learn.

### Session Boot Sequence

When a session starts:

1. Read **this file** (`CLAUDE.md`) — get oriented in 60 seconds.
2. Read **`progress.md`** at repo root — know what the last session
   shipped and what's queued next.
3. Read **`docs/decisions.md`** last 5 entries — non-obvious recent
   choices that shape current state.
4. Run `git status` + `git log --oneline -10` — confirm working-tree
   state matches expectations.
5. Check active `TaskList` — claim or update as work proceeds.

Then report to the operator in ≤5 lines: where we are, what's open,
ready for direction.

### Tool Workflow Standards

Every action follows a chain. Don't jump straight from idea to Edit —
always use the surrounding tools.

**Bug fix workflow:**
1. `TaskCreate` — capture the bug as a task.
2. `Read` — load the file + its tests.
3. Bash `grep` — search for the pattern projectwide (the bug rarely
   lives in one place).
4. `Edit` — apply the fix.
5. Bash `pytest -x` (fast subset) — confirm green.
6. Bash `ruff check .` — confirm style.
7. Bash `mypy` on touched new-package files — confirm types.
8. Bash `streamlit run volscope/ui/app.py --server.headless true </dev/null &` —
   confirm the app still boots (kill after 10s).
9. `TaskUpdate` — mark completed.
10. Append to `progress.md` if it changed phase status or unblocked
    something.

**Feature workflow:**
1. `TaskCreate` per sub-task.
2. `Read` existing code in the domain — find the patterns to follow.
3. Bash `grep` — find similar features for reference.
4. Optionally `WebSearch` — only if the state-of-the-art is unclear
   (skip for standard patterns).
5. `Write` tests first (where the test infrastructure supports it).
6. `Write`/`Edit` the implementation.
7. Run the standard test-lint-type-app-boot chain (steps 5-8 of bug fix).
8. Append to `docs/decisions.md` if the implementation involved a
   non-trivial choice.
9. `TaskUpdate` + `progress.md` update.

**Research workflow:**
1. `WebSearch` — 2-3 queries to scope the area.
2. `WebFetch` — pull authoritative sources.
3. Synthesise in markdown (reply or doc).
4. If new insight that future Claudes would benefit from: append to
   the Gotchas section below + `docs/decisions.md`.

### Hard commands (memorise these)

| Action | Command |
|---|---|
| Install deps (full) | `.venv/bin/pip install -r requirements.txt` |
| Install bot extras | `.venv/bin/pip install transitions arch hmmlearn apscheduler ib_async` |
| Run app | `make run` (or `streamlit run volscope/ui/app.py --server.headless true </dev/null`) |
| Fast tests | `.venv/bin/python -m pytest -m "not slow and not integration and not perf" -x` |
| All new-module tests | `.venv/bin/python -m pytest tests/test_signal_factors.py tests/test_signal_composite.py tests/test_signal_filters.py tests/test_signal_ranking.py tests/test_persistence_db.py tests/test_persistence_killswitch_migration.py tests/test_risk_killswitch.py tests/test_lifecycle_machine.py tests/test_execution_ibkr_stub.py tests/test_analytics_garch.py tests/test_scheduler_jobs.py tests/test_chain_snapshots.py -q` |
| E2E smoke | `make verify-all` |
| Release DB lock | `make unlock` |
| Lint | `.venv/bin/ruff check .` |
| Type check (strict on new pkgs) | `.venv/bin/mypy --strict volscope/signals volscope/risk volscope/lifecycle volscope/execution volscope/scheduler volscope/persistence` |
| Coverage on new code | `.venv/bin/python -m pytest tests/test_signal_*.py tests/test_persistence_*.py tests/test_risk_*.py tests/test_lifecycle_*.py tests/test_execution_*.py tests/test_analytics_garch.py tests/test_scheduler_jobs.py tests/test_chain_snapshots.py --cov=volscope --cov-fail-under=65` |

### Hard rules (NEVER VIOLATE)

1. **Tests green before commit.** `pytest -x` exit 0 — no exceptions.
2. **Never use yfinance `impliedVolatility`.** Always compute via own
   BSM Newton-Raphson solver. The Yahoo value is opaque, stale, and
   wrong by 1-3% in stress.
3. **Analytics returns None on bad input.** No raised exceptions from
   `volscope/analytics/*.py` — UI must keep rendering.
4. **Plotly = `go` only.** Never `plotly.express`. Always
   `plotly.graph_objects`.
5. **Plotly fillcolor.** Never 8-char hex (`#00d4aa22`). Always
   `rgba(...)` via the `rgba()` helper at
   `volscope/ui/styles/theme.py:15`.
6. **`st.metric` is forbidden.** Truncates values. Always use the
   custom KPI helpers in `volscope/ui/components/html_utils.py`.
7. **Live IBKR orders.** NEVER until Phase 4 with explicit operator
   opt-in. v0.3.0 paper engine is the production engine right now.
8. **No `--force` on main.** Branch protection enforces this; recovery
   via `chore/initial-fixup` branch per `CONTRIBUTING.md`.
9. **No `--no-verify` on commits.** Pre-commit hooks (ruff, mypy on
   new pkgs, gitleaks, fast pytest) are sacrosanct.
10. **Config changes are weekend-only.** `config/risk.yaml`,
    `config/strategies.yaml`, `config/tickers.yaml` — operator-only,
    Sunday 18:00 ET review window, 90-day cooldown.

### Gotchas (extend when you learn)

These are non-obvious "the codebase looks like X but actually behaves
like Y" facts. Extend this list when you discover a new one.

- **Plotly fillcolor**: rejects 8-char hex (`#00d4aa22`). Use
  `rgba()` helper at `volscope/ui/styles/theme.py:15`.
- **`st.metric` truncation**: values cut to "45..." when column is
  narrow. Use `kpi_grid_html()` from `volscope/ui/components/html_utils.py`.
- **DuckDB locking**: only one writer at a time. Dashboard
  uses `read_only=True` reads; bot is sole writer. `make unlock` if stuck.
- **DuckDB reserved words**: `RIGHT` is one (SQL string function). Use
  `option_right` in chain tables (see ADR-0002 + decision-log
  2026-05-14).
- **DuckDB partial indexes**: not supported. Use full index +
  `WHERE` in queries (caught in migration 001).
- **ib_async clientId=0**: master ID — sees manual GUI orders too.
  Bot uses specific IDs (1+) to stay isolated.
- **HMM regime fit**: needs ≥252 days of feature history (the model
  raises on shorter input). Test on synthetic 2-regime data first.
- **IBKR rate limit**: 50 messages/sec hard cap. Wrap calls in
  `asyncio.Semaphore(40)` for headroom.
- **DuckDB no PITR**: backup via `EXPORT DATABASE` after market close
  + hourly during. Documented in `docs/BACKUPS.md`.
- **iCloud File Provider stall**: project must live at `~/Desktop/VolScope`,
  not the iCloud mirror. First-import of large deps can stall 25-90s on
  fresh shells. `scripts/ops/keep_warm.sh` warms the cache.
- **scripts/ paths**: every script moved to `scripts/<group>/` in v0.2.0.
  Old direct-`scripts/file.py` references in code or launchd plists
  will break — grep before reorganising.
- **Yahoo `impliedVolatility`**: rate-limited since Nov 2024
  (≈360 req/hour/IP). Use sparingly; the bot's signal engine pulls
  EOD only.
- **`right` as a Python attribute**: keep using it on dataclasses
  (`Quote.right`, `LegSpec.right`); the SQL column rename
  doesn't propagate to Python.

### Project Identity (one paragraph)

VolScope is a **volatility-research workbench** with a **simulation
bot** + **paper-trading capability** for retail options traders.
Tech stack: Python 3.11+, Streamlit, DuckDB 1.4+, Plotly, yfinance
(dev/research), `ib_async` 2.1+ (paper/live). Operator: SchoenTom.
Stage: paper-development. **No live IBKR orders** until Phase 4
explicit opt-in with ≥100 closed paper trades. Vision: research
dashboard primary; bot is one user of the engine; paper trader is
manual workflow on the same DB.

