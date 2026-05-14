# VolScope — Autonomous Improvement Roadmap

**Owner:** Operator
**Trading context:** DAX Puts (Sep 2027), Nasdaq Puts (Dec 2026), knock-outs on MSTR / SNOW / 1810.HK
**Core question the app must answer:** "Is vol cheap enough to buy right now, and where is it cheapest?"
**Last updated:** 2026-04-20

---

## How this file works

Each autonomous run picks the **first [TODO]** item, implements it completely, marks it [DONE], and adds newly discovered items at the bottom. The priority order reflects trading impact, not engineering effort.

---

## Priority Queue

### [DONE 2026-04-20] 1. Buy/Wait Signal Badge — Command Center
**Impact: CRITICAL** — this is the ONE reason the user opens the app.

Implemented:
- `volscope/analytics/signal.py` — `VolSignal` frozen dataclass + `compute_signal()` + `market_summary()`
- `volscope/ui/components/metric_components.py` — `vol_signal_badge_html(signal)` — colored HTML badge
- `volscope/ui/views/command_center_page.py` — badges shown prominently per card; summary line above cards
- `tests/test_signal.py` — 40 passing tests (all edge cases: NaN, inf, borderline thresholds, disagreement)
- `tests/test_command_center.py` — 34 passing tests for fetchers and chart builders
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-20] 2. VDAX-New Data Reliability
**Impact: HIGH** — DAX is the user's primary market for puts.

Implemented 4-step fallback chain in `volscope/data/vol_index_fetcher.py`:
1. `^VDAX` via yfinance (currently broken on free Yahoo tier — returns empty)
2. `VDAX-NEW.DE` via yfinance (also broken/delisted on Yahoo as of 2026-04)
3. EWG (iShares MSCI Germany ETF) ATM IV proxy — yfinance options available, correlates well with DAX vol. History built from EWG 20d rolling HV.
4. `^GDAXI` 20d realized vol — last resort, labelled "DAX HV" (HV not IV)
New `fetch_vol_index_history_with_source()` returns `(series, source_label)`.
`vol_index_snapshot` and `bvol_snapshot` now include `source` key.
UI (`_vol_pulse_block_html`) shows proxy label below the index value.
17 new tests in `tests/test_vol_index_fetcher.py`. `make verify` → OVERALL: PASS.

---

### [DONE 2026-04-20] 3. Vol Pulse Refresh Button
**Impact: HIGH** — current data is cached for 5 min, but trader wants on-demand refresh.

Added "↻ Refresh" button in the Vol Pulse header row (right-aligned).
Calls `_load_vol_pulse.clear()` for targeted cache invalidation then `st.rerun()`.
No new tests needed (pure UI wiring, covered by smoke gate in make verify).

---

### [DONE 2026-04-20] 4. Extended Term Structure — 90d / 180d Storage
**Impact: HIGH** — user buys Sep 2027 DAX puts (long-dated). Seeing only 30d/60d misses the point.

Implemented:
- `volscope/data/database.py` — `iv_90d DOUBLE`, `iv_180d DOUBLE` added to `CREATE TABLE daily_vol` and auto-migrated via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Added to `_DAILY_FIELDS`.
- `volscope/data/options_scraper.py` — Expanded candidate selection: `iv_candidates` = all expiries ≤200d (sorted ascending, up to 8) covers 90d/180d targets. `vol_candidates_set` = 4 nearest to 30d (near-term OI/volume unchanged). Added `iv_90d` and `iv_180d` to return dict.
- `volscope/ui/components/chart_builders.py` — `create_term_structure_chart` now plots up to 4 points (30d·60d·90d·180d), skips None gracefully, slope from first→last point. `create_command_term_structure` extended to 4-point curves, x-axis range [20, 195].
- `tests/test_options_scraper.py` — Added 90d/180d expiries to fixture; 5 new tests for iv_90d/iv_180d computation.
- `tests/test_chart_builders_term.py` — 16 new tests for both chart functions (partial points, verdict labels, colors, tick labels).
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-20] 5. Signal History — "Was Vol Cheap When You Bought?"
**Impact: HIGH** — the user wants to learn from past entries.

Implemented:
- `volscope/data/database.py` — `positions` table (id, ticker, entry_date, entry_iv_30d, entry_iv_percentile, entry_vrp, notes, active). Methods: `add_position()`, `close_position()`, `get_positions(ticker, active_only)`.
- `volscope/ui/views/command_center_page.py` — `_position_row_html()` and `_positions_table_html()` builders. Trade Journal expander: shows last 3 entries per ticker with Entry IV / Current IV / Δ (green=IV fell=bought cheap, red=IV rose=paid rich), per-position close buttons, and a "Log New Entry" form.
- `tests/test_positions.py` — 23 tests covering DB CRUD, active filter, ordering, HTML builders, note truncation, delta color logic.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-20] 6. Universe Heatmap View (4th page)
**Impact: HIGH** — one-glance view of where vol is cheap/rich across all 200+ tickers.

Implemented:
- `volscope/ui/views/heatmap_page.py` — New "Heatmap" page. `_percentile_color()` maps iv_percentile to green→amber→red. `_build_heatmap_figure()` uses `go.Heatmap` with custom colorscale; packs tickers into rows of 20; collapses to sector medians when > 100 tickers. `render_heatmap_page()` shows controls (view mode toggle, jump-to-ticker), legend strip, interactive chart (click→navigate to Scope), and stats summary (N cheap / N normal / N rich).
- `volscope/ui/app.py` — Heatmap route added.
- `volscope/ui/components/sidebar.py` — "Heatmap" added to nav pages list.
- `tests/test_heatmap_page.py` — 20 tests for color mapping and figure builder.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-20] 7. Earnings IV Crush Estimator — SNOW and MSTR
**Impact: HIGH** — knock-out positions are sensitive to IV crush around earnings.

Implemented:
- `volscope/analytics/earnings_crush.py` — `CrushEstimate` frozen dataclass; `_find_nearest_iv()` nearest-date lookup in history; `compute_crush_estimate(db, ticker)` computes avg/min/max crush % from last 4 past events; `crush_badge_html()` renders amber ⚠ badge.
- `volscope/ui/views/scope_page.py` — Shows crush badge + "Historical crush: avg −X%, range …" below header when ER is upcoming.
- `volscope/ui/views/command_center_page.py` — Computes `crush_ests` per ticker; passes to `_market_card_html()`; ER badge shown on card.
- `tests/test_earnings_crush.py` — 22 tests: `_find_nearest_iv`, `compute_crush_estimate`, `crush_badge_html`.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-20] 8. IV Momentum Column — Scanner Enhancement
**Impact: MEDIUM** — makes the Scanner more actionable for scanning new opportunities.

Implemented:
- `volscope/ui/views/scan_page.py` — `_augment_with_derived_columns()` extended with `iv_change_30d` (30-day IV delta) and `perc_trend` (30-day percentile delta). Both use bulk_history. Added "30D D" and "PERC TREND" columns to `display_cols` and `column_config`. Added "Show only falling IV" filter checkbox. Updated help table.
- No new test file (pure scanner column logic; existing smoke + regression tests cover the render path).
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-20] 9. Put/Call Skew — Scope Page
**Impact: MEDIUM-HIGH** — for tail protection buyers, skew is as important as ATM IV.

Implemented:
- `volscope/data/options_scraper.py` — `_compute_skew_25d()` computes (put_IV − call_IV) at 25Δ by computing BSM delta at each strike, interpolating IV at delta=0.25 for calls and -0.25 for puts. Called on nearest-30d expiry in `scrape_options_chain()`. Returns `iv_skew_25d` in return dict.
- `volscope/data/database.py` — `iv_skew_25d DOUBLE` added to CREATE TABLE + ALTER TABLE migration + `_DAILY_FIELDS`.
- `volscope/ui/views/scope_page.py` — `_render_skew_metric()` shows "25Δ Skew (put−call): +Xpt" with color: green=neutral, amber=elevated, red=rich put skew.
- `tests/test_options_scraper.py` — Added `iv_skew_25d` to expected keys.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-20] 10. Intraday Price Chart — Scope Page 1D/5D View
**Impact: MEDIUM** — currently only daily OHLCV, no intraday context.

Implemented:
- `volscope/ui/components/chart_builders.py` — `create_intraday_price_chart(bars, ticker, timeframe)` builds candlestick + volume bar chart using Plotly subplots. Volume bars colored green/red by close vs open.
- `volscope/ui/views/scope_page.py` — `_INTRADAY_CONFIG` maps 1D/5D/1M to period/interval/TTL. `_render_intraday_section()` shows timeframe radio selector, fetches bars via `@st.cache_data` (TTL=60s/300s/3600s), renders chart below the percentile chart.
- `make verify` → OVERALL: PASS

---

## Completed Items

1. **2026-04-20** — Buy/Wait Signal Badge (Command Center). `analytics/signal.py` + `metric_components.vol_signal_badge_html` + per-card badges + universe summary line. 74 new tests, all pass.
2. **2026-04-20** — VDAX-New Data Reliability. 4-step fallback: ^VDAX → VDAX-NEW.DE → EWG proxy → DAX HV. 17 tests.
3. **2026-04-20** — Vol Pulse Refresh Button. ↻ Refresh button with targeted cache clear.
4. **2026-04-20** — Extended Term Structure 90d/180d. iv_90d/iv_180d in scraper + DB + charts. 21 tests.
5. **2026-04-20** — Signal History / Trade Journal. `positions` table + Trade Journal expander on Command Center. 23 tests.
6. **2026-04-20** — Universe Heatmap. New Heatmap page with go.Heatmap, sector collapse, click-to-Scope. 20 tests.
7. **2026-04-20** — Earnings IV Crush Estimator. `analytics/earnings_crush.py` + CrushEstimate; crush badge on Scope + Command Center. 22 tests.
8. **2026-04-20** — IV Momentum Columns in Scanner. iv_change_30d + perc_trend + falling-IV filter.
9. **2026-04-20** — 25Δ Put/Call Skew. `_compute_skew_25d()` via BSM delta interpolation; iv_skew_25d in DB + Scope page metric.
10. **2026-04-20** — Intraday Price Chart 1D/5D/1M on Scope page with volume subplot and TTL caching.
11-15. **2026-04-20 to 2026-04-23** — Sector Rotation, Capital Flow, ML Signal, Backtest Engine, Position Sizing Calculator (see priority queue entries above).
16. **2026-04-23** — Vol Alert System. `alerts/alert_engine.py` (AlertRule/AlertFired, evaluate_rules, dispatch channels), alert_rules+alert_log DB tables, Alerts expander on Command Center, `scripts/run_alerts.py` for cron. 44 tests.

---

### [DONE 2026-04-21] 11. Sector Rotation Engine — Phase 1 of Giga-Plan
**Impact: HIGH** — moves VolScope from descriptive to predictive. Approved by Operator.

Implemented:
- `sector_daily` DuckDB table (sector, date, median_iv, median_perc, median_hv, mean_pcr, total_oi, total_vol, n_tickers, regime, regime_z). `upsert_sector_daily()` + `get_sector_history()` + `get_sector_latest()` + `get_all_vol_history_for_sectors()` in `database.py`.
- `scripts/sector_aggregate.py` (aliased as `scripts/compute_sector_rotation.py`) — aggregates daily_vol by sector/date, classifies regimes, upserts into `sector_daily`. `make sectors` target added.
- `volscope/analytics/sector_rotation.py` — `SectorRegime` dataclass; `compute_sector_aggregates()`; `compute_sector_momentum(windows=[5,10,21])`; `classify_sector_regime()` (HOT/NEUTRAL/COLD via z-score + HEATING/COOLING/STABLE trend); `compute_rotation_matrix(lag=21)` (Markov transition probabilities); `get_current_rotation_snapshot()` (who's next predictions).
- `volscope/ui/views/rotation_page.py` — sector IV percentile heatmap (go.Heatmap, 3M/6M/1Y/ALL window), regime strip with HOT/NEUTRAL/COLD badges + trend arrows, rotation prediction cards with probability bars, momentum table expander.
- Wired into `app.py` + `sidebar.py` nav as "Rotation" page.
- `tests/test_sector_rotation.py` — 41 tests: aggregation, momentum, regime classification, matrix, snapshot.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-21] 12. Capital Flow Proxy — Phase 2 of Giga-Plan
**Impact: HIGH** — adds smart money flow detection on top of Phase 1.

Implemented:
- `volscope/analytics/capital_flow.py` — 5 z-score proxy components (OI change rate, Vol/OI ratio, PCR shift, IV-HV divergence, volume clustering); `compute_flow_score()` → 0-100 composite; `detect_flow_divergence()` → ACCUMULATION/DISTRIBUTION alerts.
- `volscope/ui/views/flow_page.py` — flow heatmap (sector × time), ranked bar chart, divergence alert cards, component breakdown expander, disclaimer. Wired into `app.py` + sidebar nav.
- `tests/test_capital_flow.py` — 40 tests covering all functions and edge cases.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-22] 13. ML Mean-Reversion Signal — Phase 3 of Giga-Plan
**Impact: HIGH** — moves from heuristic buy/wait to data-driven probability estimates.

Implemented:
- `volscope/analytics/ml_signal.py` — L2-regularised logistic regression (numpy + scipy only, no sklearn). Features: iv_percentile, vrp (iv_30d/hv_20d), iv_rank, iv_change_7d, put_call_ratio. Target: y=1 if iv_30d falls in next 10 trading days. L-BFGS-B optimizer. Median imputation for NaN features, zero-mean/unit-variance standardisation. Returns None when < 60 training rows.
- `MLPrediction` frozen dataclass: ticker, date, buy_prob [0,1], n_train, features_used.
- `ml_badge_html()` — colored badge: green "ML BUY" (≥65%), blue "ML LEAN" (≥50%), gray "ML NEUTRAL" (≥35%), amber "ML WAIT" (<35%).
- `volscope/ui/views/command_center_page.py` — ML badge shown on each card below signal badge. lookback_days changed to 730 for ML training data. ML predictions computed per ticker (silently skipped on failure).
- `tests/test_ml_signal.py` — 41 tests across 7 classes: feature engineering, target construction, optimizer, None guards, output contract, frozen dataclass, badge HTML.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-22] 14. Backtest Engine — "Was the Signal Right?"
**Impact: HIGH** — closes the feedback loop; Operator can audit past signal accuracy.

Implemented:
- `volscope/analytics/backtest.py` — `BacktestResult` dataclass; `run_backtest(history_df, ticker, hold_days=10)` computes signal-conditional IV outcomes. For each row: signal at t, iv_30d at t+hold_days. BUY hit = IV fell, RICH hit = IV rose. Also computes max IV spike during hold window for BUY signals. `rolling_hit_rate()` computes 63-row (~3M) rolling BUY hit rate. `build_calibration_table()` returns human-readable summary DataFrame.
- `volscope/ui/components/chart_builders.py` — `create_backtest_hit_rate_chart()` (rolling 3M BUY hit rate, 50% reference line, fill-to-zero) and `create_backtest_distribution_chart()` (overlapping histograms per signal category, colored green/amber/red).
- `volscope/ui/views/scope_page.py` — `_render_backtest_section()` expander at bottom of Scope page: calibration table + rolling hit rate chart + IV change distribution chart.
- `tests/test_backtest.py` — 45 tests: edge cases, output contract, hit rate correctness on controlled data, max drawdown, rolling_hit_rate, calibration table, chart builder smoke tests.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-23] 15. Position Sizing Calculator
**Impact: HIGH** — Operator buys knock-outs and puts; sizing depends on vol regime.

Implemented:
- `volscope/analytics/position_sizing.py` — `SizingResult` frozen dataclass; `compute_sizing(signal_category, max_allocation, entry_iv, current_iv) → SizingResult`; `sizing_summary_html()`. Size multipliers: BUY=1.0, LEAN_BUY=0.5, WAIT/RICH=0.0. Vega P&L approx: `pnl_pct ≈ (current_iv − entry_iv) / entry_iv × 100%` (first-order for long-dated ATM options).
- `volscope/ui/views/command_center_page.py` — `_render_position_sizer()` expander: max-allocation slider (persisted in session state), per-ticker table showing Signal→Size/Suggested/Est. P&L. Entry IV sourced from most recent active Trade Journal entry; current IV from DB.
- `tests/test_position_sizing.py` — 44 tests: multiplier completeness, frozen dataclass, all sizing paths, vega P&L formula, HTML rendering.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-04-23] 16. Vol Alert System — Threshold Notifications
**Impact: MEDIUM-HIGH** — passive monitoring between trading sessions.

Implemented:
- `volscope/alerts/alert_engine.py` — `AlertRule` / `AlertFired` frozen dataclasses; `compute_metric_value()` (iv_percentile, iv_rank, vrp); `evaluate_rule()` / `evaluate_rules()` with wildcard ticker support; `dispatch_log()`, `dispatch_desktop()` (osascript), `dispatch_email()` (SMTP env vars); `alert_rule_html()` / `alert_fired_html()` HTML helpers.
- `volscope/data/database.py` — `alert_rules` + `alert_log` tables; `add_alert_rule()`, `delete_alert_rule()`, `set_alert_rule_enabled()`, `get_alert_rules()`, `log_alert_fired()`, `get_alert_log()`.
- `volscope/ui/views/command_center_page.py` — `_render_alerts_expander()`: rule list with enable/delete buttons, live-check button, create-rule form; wired into `render_command_center_page()`.
- `scripts/run_alerts.py` — standalone cron-safe script; loads rules from DB, fetches latest rows, evaluates, logs + dispatches.
- `tests/test_alerts.py` — 44 tests covering constants, dataclass contracts, metric extraction, rule evaluation, wildcard, dispatch_log, dispatch_desktop, HTML builders, all DB CRUD methods.
- `make verify` → OVERALL: PASS

---

### [DONE 2026-05-01] 17. Edge Score — Composite Long-Vol Entry Engine
**Impact: HIGH** — VolScope's first single-number recommendation. Collapses
all existing signals (IV percentile, VRP, IV rank, ML mean-reversion,
sector regime, capital flow) into one 0–100 ranked Edge Score per ticker
with one-line justification. Hedge-fund-grade "where's the best entry now?"
top of Command Center.

Implemented:
- `volscope/analytics/edge_score.py` — `EdgeScore` frozen dataclass; weighted
  composite (perc 30%, VRP 20%, rank 15%, ML 15%, regime 10%, flow 10%);
  renormalises weights when components are missing so partial data doesn't
  penalise the score; `compute_edge_score()`, `compute_edge_table()`,
  `rank_edges()`. Liquidity gate: total_open_interest < 1000 → flagged
  illiquid and sorted to bottom regardless of raw score.
- ML interpretation explicit: `ml_score = 100 * (1 - buy_prob)` because
  Operator's book is long-vol entries (he wants IV to RISE, not fall). Documented
  in module docstring as opposite direction from existing "ML BUY" badge.
- `volscope/ui/views/command_center_page.py` — `_edges_strip_html()`
  renders compact ranked panel at the TOP of Command Center (above YOUR
  MARKETS); each row: rank · ticker (illiquid badge) · score · bar +
  one-liner · confidence. Wired before YOUR MARKETS.
- `tests/test_edge_score.py` — 47 tests across 7 classes: output contract,
  component math (each component's known input → known output), weight
  math + renormalisation, liquidity gate, NaN/inf/string edge cases,
  one-liner content, ranking + table.
- `make verify` → OVERALL: PASS (867 total tests, +47 new).

---

## Discovered Issues (add here during runs)

- VDAX `^VDAX` availability in yfinance needs verification in production
- Deribit DVOL API has 365-day limit on history; for longer history need multiple calls
- `iv_60d` is sometimes None when options with 60+ day expiry are unavailable (e.g., illiquid stocks)
- Command Center `_load_vol_pulse` is module-level cached — if Streamlit session restarts, cache is cold until first load
- Item 9 (25Δ Skew): prior run computed `_compute_skew_25d` and `create_skew_chart` but did NOT wire chart into scope_page.py — fixed 2026-04-22 (scope_page.py now shows 2-column bottom row: [Percentile | Skew]). 22 tests added in test_skew.py.

---

## Run Log

| Date | Item | Notes |
|------|------|-------|
| 2026-04-20 | Setup | Roadmap created, 5 daily crons activated |
| 2026-04-20 | Item 1 — Signal Badge | `analytics/signal.py`, `metric_components.vol_signal_badge_html`, Command Center cards updated. 74 tests, make verify PASS. |
| 2026-04-20 | Item 2 — VDAX Reliability | 4-step fallback: ^VDAX → VDAX-NEW.DE → EWG proxy → DAX HV. `source` field in all snapshots. 17 tests, make verify PASS. |
| 2026-04-20 | Item 3 — Vol Pulse Refresh | ↻ Refresh button, targeted cache clear via _load_vol_pulse.clear(), st.rerun(). |
| 2026-04-20 | Item 4 — Extended Term Structure | iv_90d/iv_180d in DB + scraper; 4-point curves in both term structure charts. 21 new tests, make verify PASS. |
| 2026-04-20 | Item 5 — Signal History | `positions` table + DB methods; Trade Journal expander on Command Center with entry log, Δ IV colors, close buttons, log form. 23 tests, make verify PASS. |
| 2026-04-20 | Item 6 — Universe Heatmap | New Heatmap page with go.Heatmap, sector collapse, click-to-Scope, legend, stats. Sidebar nav updated. 20 tests, make verify PASS. |
| 2026-04-20 | Item 7 — Earnings IV Crush | `analytics/earnings_crush.py` + CrushEstimate; crush badge on Scope + Command Center cards. 22 tests, make verify PASS. |
| 2026-04-20 | Item 8 — IV Momentum Columns | Scanner: iv_change_30d + perc_trend columns + falling-IV filter. make verify PASS. |
| 2026-04-20 | Item 9 — 25Δ Skew | `_compute_skew_25d()` in scraper using BSM delta interpolation; iv_skew_25d in DB; skew metric on Scope page. make verify PASS. |
| 2026-04-20 | Item 10 — Intraday Price Chart | `create_intraday_price_chart()` + `_render_intraday_section()` with 1D/5D/1M timeframe selector, TTL caching, volume subplot. make verify PASS. |
| 2026-04-21 | Item 11 — Sector Rotation Engine | `sector_daily` table + DB methods; `analytics/sector_rotation.py` (aggregates, momentum, regime z-score, Markov matrix, snapshot); `rotation_page.py` (heatmap, regime strip, prediction cards); `make sectors` script. 41 tests, make verify PASS. |
| 2026-04-21 | Item 12 — Capital Flow Proxy | `analytics/capital_flow.py` (5 z-score proxies, composite flow score, divergence detection); `flow_page.py` (heatmap, ranking bars, alert cards). 40 tests, make verify PASS. |
| 2026-04-22 | Skew integration fix + new items | Found `create_skew_chart` was built but not wired into scope_page.py. Added 2-column bottom row [Percentile | Skew] to Scope page. 22 new tests in test_skew.py. Added Items 13–16 to roadmap. make verify PASS. |
| 2026-04-22 | Item 14 — Backtest Engine | `analytics/backtest.py` — signal-conditional IV outcomes, rolling hit rate, calibration table. Chart builders: hit rate + distribution. Scope page expander. 45 tests, make verify PASS. |
| 2026-04-22 | Item 13 — ML Mean-Reversion Signal | `analytics/ml_signal.py` — L2-regularised logistic regression (numpy+scipy, no sklearn). Features: iv_percentile, vrp, iv_rank, iv_change_7d, put_call_ratio. ML badge on Command Center cards (BUY/LEAN/NEUTRAL/WAIT). 41 tests, make verify PASS. |
| 2026-04-23 | Item 15 — Position Sizing Calculator | `analytics/position_sizing.py` — SizingResult dataclass, compute_sizing(), vega P&L approx. Command Center Position Sizer expander: max-alloc slider, per-ticker table (Signal→Size/Suggested/Est. P&L). 44 tests, make verify PASS. |
| 2026-04-23 | Item 16 — Vol Alert System | `alerts/alert_engine.py` (AlertRule/AlertFired dataclasses, evaluate_rules, dispatch_log/desktop/email, HTML helpers); alert_rules + alert_log tables in DB; Alerts expander on Command Center; `scripts/run_alerts.py` for cron. 44 tests, make verify PASS. |
| 2026-05-01 | Loop iter #1 | ui/quick_wins — Set width=200 on NAME/SECTOR columns — eliminates the most visible bug. — maturity=25.3 |
| 2026-05-01 | Loop iter #2 | ui/bugs — Heatmap textfont size=9 is too small; at >100 tickers, ticker labels overlap and — maturity=60.3 |
| 2026-05-01 | Loop iter #3 | ui/bugs — Default landing page is Command Center; on first run with empty DB user sees bla — maturity=60.3 |
| 2026-05-01 | Loop iter #4 | universe/universe_gaps — Only 5 indices (^VIX, ^GSPC, ^NDX, ^DJI, ^RUT); critical vol indices missing: ^V — maturity=63.4 |
| 2026-05-01 | Loop iter #5 | universe/universe_gaps — Only 7 China/ADR tickers, no actual HK listings even though Operator trades 1810.HK. — maturity=63.4 |
| 2026-05-01 | Loop iter #6 | math/math_bugs — BSM vega returns 0 for σ ≤ 0 — mathematically wrong and causes Newton-Raphson IV — maturity=63.4 |
| 2026-05-01 | Loop iter #7 | math/quick_fixes — Vega σ→0 floor. — maturity=63.4 |
| 2026-05-01 | Loop iter #8 | ui/bugs — Scanner NAME and SECTOR TextColumn have no width hints; long company names (e.g. — maturity=63.4 |
| 2026-05-01 | Loop iter #9 | math/math_bugs — IV-percentile tie-handling broken: when current==history values, percentile = 0% — maturity=63.4 |
| 2026-05-01 | Loop iter #10 | math/quick_fixes — Tie-handling fix is a 1-line copy-paste; immediate quality bump. — maturity=63.4 |
| 2026-05-01 | Loop iter #11 | universe/universe_gaps — No European single-names; 282 tickers are 95% US-listed. — maturity=63.4 |
| 2026-05-01 | Loop iter #12 | universe/recommendation_flaws — Cheap context string mentions 'historical floor' at percentile≥90 but does not c — maturity=63.4 |
| 2026-05-01 | Loop iter #13 | ui/bugs — Scanner filters reset on every rerun; user-set 'Sector = Tech' clears when user  — maturity=63.4 |
| 2026-05-01 | Loop iter #14 | ui/bugs — Scanner filters reset on every rerun; user-set 'Sector = Tech' clears when user  — maturity=75.8 |
| 2026-05-01 | Loop iter #15 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=75.8 |
| 2026-05-01 | Loop iter #16 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=78.1 |
| 2026-05-01 | Loop iter #17 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=80.3 |
| 2026-05-01 | Loop iter #18 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=84.1 |
| 2026-05-01 | Loop iter #19 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=87.1 |
| 2026-05-01 | Loop iter #20 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=87.1 |
| 2026-05-01 | Loop iter #21 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=87.1 |
| 2026-05-01 | Loop iter #22 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=87.1 |
| 2026-05-01 | Loop iter #23 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=87.1 |
| 2026-05-01 | Loop iter #24 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=87.1 |
| 2026-05-01 | Loop iter #25 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=98.3 |
| 2026-05-01 | Loop iter #26 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=98.3 |
| 2026-05-01 | Loop iter #27 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=98.3 |
| 2026-05-02 | Loop iter #28 | universe/recommendation_flaws — _compute_dual_score uses only IV-percentile + IV-HV spread; no absolute IV-floor — maturity=98.3 |
| 2026-05-05 | Loop iter #29 | math/findings — simulate_ticker hardcodes hold_days=45 on line 176 (ignores hold_days param pass — maturity=98.8 |
