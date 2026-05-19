---
name: VolScope Project
description: VolScope volatility intelligence platform — architecture, current state, data sources, operational discipline, and recovery context from April 2026 session
type: project
originSessionId: 73e04a0d-97ea-440d-b8de-90c927267bb9
---
VolScope work is always done in `<repo-root>` (never the iCloud mirror).

**The one question the app exists to answer:** "Are options cheap or expensive right now — buy now or wait?" See [volscope-vision.md](volscope-vision.md) for the four signals Operator explicitly prioritized and the non-goals.

**Operator's trading context (drives feature decisions):** DAX Puts (Sep 2027), Nasdaq Puts (Dec 2026), knock-outs on MSTR / SNOW / 1810.HK (Xiaomi). Command Center is the default landing page and must answer the core question on open without any clicking.

**Stack:** Python 3.13 + Streamlit + DuckDB + yfinance + Plotly. Dark terminal theme (JetBrains Mono + DM Sans).

**Architecture:**
- `volscope/analytics/` — BSM (Newton-Raphson + Manaster-Koehler + bisection), HV estimators (C2C, Parkinson, GK, Yang-Zhang), IV metrics (rank, percentile, VRP), signal.py (Buy/Wait state machine), data_quality.py (sector IV ceilings + spread-z-score outlier flags), crowded_trades.py, opportunity.py
- `volscope/data/` — options_scraper (self-computed IV, never Yahoo's column), DuckDB with auto-migration on open, FRED risk-free rates, ticker resolver (int'l exchange suffixes: .DE, .L, .PA, .HK), vol_index_fetcher (VIX/VDAX/VXFXI via yfinance, BVOL via Deribit), ibkr_scraper.py (stub, activates with `pip install ib_insync` + TWS login — delivers delayed data even on gesperrt trading accounts)
- `volscope/ui/` — 4 pages: Command (default), Discover, Scope, Scanner
- `scripts/verify.py` — 4-gate external audit (spec + pytest + golden + smoke)

**DB:** `~/Library/Application Support/VolScope/volscope.db` (iCloud-safe). Auto-migrates legacy rows (where old seed wrote `iv_30d == hv_20d`) silently on `VolScopeDB.__init__(auto_migrate=True)`.

**Verify:** `make verify` must print OVERALL: PASS — this is the external oracle, never bypass it. See [auto-dreaming-blueprint.md](auto-dreaming-blueprint.md) for why Claude must not self-grade.

**Dream / Giga-Plan (approved, Phases 1+2 DONE):** Sector Rotation + Capital Flow + ML Mean-Reversion Bot + Backtest. Plan doc: `~/.claude/plans/iterative-hugging-thimble.md`. Summary: [volscope-giga-plan.md](volscope-giga-plan.md). Phases 1 (sector_rotation.py, rotation_page.py) and 2 (capital_flow.py, flow_page.py) done 2026-04-21. ML + Backtest are Items 13–14 in roadmap.

**Autonomous improvement crons (session-only, reactivate each session):**
- Roadmap: `~/.claude/plans/volscope-roadmap.md` — completed/pending items with trading-impact priority
- 5 daily CEST slots (06:47, 10:17, 13:43, 17:51, 21:23)
- Each run picks first `[TODO]` item, implements fully, marks `[DONE]`, appends discoveries
- Ask Operator to "activate VolScope crons" at session start — they don't persist

**All 10 original roadmap items DONE 2026-04-20 in a single session:**
1. ~~Buy/Wait signal badge~~ — `analytics/signal.py`
2. ~~VDAX 4-step fallback~~ — EWG proxy + DAX HV
3. ~~Vol Pulse refresh button~~
4. ~~Extended term structure 90d/180d~~ — iv_90d/iv_180d in DB + charts
5. ~~Trade journal~~ — `positions` table, Trade Journal expander, Command Center
6. ~~Universe Heatmap~~ — new 5th nav page with go.Heatmap
7. ~~Earnings IV crush estimator~~ — `analytics/earnings_crush.py`, badge on Scope + Command Center
8. ~~IV momentum columns in Scanner~~ — iv_change_30d, perc_trend, falling-IV filter
9. ~~25Δ skew~~ — BSM delta interpolation, iv_skew_25d in DB, Scope metric
10. ~~Intraday price chart 1D/5D/1M~~ — candlestick + volume subplot on Scope

**2026-04-22 fix:** `create_skew_chart` was built by a prior run but not wired into scope_page.py. Fixed: Scope page bottom row is now 2-column [IV Percentile | 25Δ Skew Historical]. 22 new tests in test_skew.py.

**Current roadmap (Items 13–15 DONE; Item 16 is next [TODO]):**
- 13. ~~ML mean-reversion signal~~ — `analytics/ml_signal.py` (numpy+scipy logistic regression, ML badge on Command Center cards). 41 tests, PASS.
- 14. ~~Backtest engine~~ — `analytics/backtest.py` (signal-conditional IV hit rates, rolling 3M chart, calibration table, Scope page expander). 45 tests, PASS.
- 15. ~~Position sizing calculator~~ — `analytics/position_sizing.py` (SizingResult, compute_sizing, vega P&L approx). Command Center Position Sizer expander: max-alloc slider, per-ticker table. 44 tests, PASS. Done 2026-04-23.
- 16. Vol alert system — threshold notifications (desktop/log/email)

**Session-recovery context (April 2026):** Prior Opus 4.6 session built 278+ tests across 35 Ralph-loop tasks + the Giga-Plan blueprint, but forgot to write durable memory before the context ended. Operator asked the next Claude to re-read the full transcript (`<repo-root>/VolScope-Memory1-Chat.rtf`) and persist the hard-won maturity. The Auto-Dreaming philosophy document is at `~/Downloads/auto-dreaming-blueprint.pdf` — it is the working philosophy for all VolScope iteration.

**How to apply:** Always use the Desktop path. When Operator mentions VolScope, read the roadmap and giga-plan memory before suggesting features. If it's a new session, remind Operator the crons need reactivation. Never declare work done without `make verify` passing — the oracle is external by design.
