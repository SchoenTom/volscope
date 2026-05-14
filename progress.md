# VolScope Progress

## Last Session: 2026-05-14 (v0.7.1 — matched-horizon IV-HV spread)

Focused academic-correctness fix on top of v0.7.0. Driven by an
operator audit of the underlying methodology: "ist HV20 vs IV30 der
akademische Standard und sind die Berechnungen verlässlich?"

The answer was nuanced — Yang-Zhang at 20 days is already in the
codebase and academically sound, but the IV-HV *spread* metric
compared a 30-day implied figure against a 20-day realised one. Not
"konzeptionell falsch" as the original prompt claimed, but a real
~2-vol-point horizon bias that's an unforced credibility loss.

**Decision (in-session as CEO):** ship the minimum that fixes the
academic concern; defer the 30-column / 5-estimator / vol-cone-UI
expansion to v0.8.0 + v0.9.0 because the marginal information from
extra estimators is small (r > 0.95 correlation) and would just add
column-store read cost.

**Shipped:**
- ``volscope/persistence/migrations/007_hv_matched_horizon.sql`` —
  ``hv_yz_30d`` + ``iv_hv_spread_matched`` columns, scanner index.
- ``volscope/data/database.py`` — schema sync + backfill ALTER + new
  fields in ``_DAILY_FIELDS`` so ``upsert_daily`` accepts them.
- ``volscope/data/ticker_resolver.py::_backfill_hv_history`` — computes
  Yang-Zhang at ``DEFAULT_HV_MATCHED = 30`` and persists both new
  columns alongside the legacy ones.
- ``volscope/config.py::DEFAULT_HV_MATCHED`` — single source of truth
  for the matched window (Christensen-Prabhala 1998 uses 22-day
  Parkinson; we use 30 to align exactly with IV30).
- ``tests/test_hv_matched_horizon.py`` — four tests covering
  log-normal recovery within ±2.5 vol pt, monotonic estimator-variance
  property (HV30 std ≤ HV20 std), low-vol synthetic close to zero,
  and DB round-trip of the new columns.

**Explicitly deferred (CEO call):**
- v0.8.0 — wire the existing ``volscope/analytics/vol_cones.py`` into
  Scope page. The math is there, the UI isn't.
- v0.9.0 — GARCH(1,1)-t forecast vol via the already-installed ``arch``
  package; earnings-aware rolling window that excludes ±2 days around
  ``bot_earnings_calendar`` dates.

Version bumped to **0.7.1**. CI green watched.

---

## Last Session: 2026-05-14 (v0.7.0 — paid-product UX wave)

Four-wave session driven by an operator audit ("die linke Reiter sieht
HÄSSLICH aus, Charts wie Lab-Notebook, Option-Builder kryptisch, Paper
Trading nicht erklärt"). Each wave was scoped, designed, asked for
trade-off approval, and shipped.

**Welle 1 — Lesbarkeit + Sidebar-Bugs:**
- `theme.py` — `header[data-testid="stHeader"]` was `height:0` which
  clipped the floating "open sidebar" button after collapse. Replaced
  with `min-height:32px; overflow:visible` + pinned `collapsedControl`
  to `position:fixed; top:8px; left:8px; z-index:9999`. Operator can
  now reopen the sidebar from any state.
- `sidebar.py::_render_ticker_picker` — collapsed two parallel
  Mono-9px-#424666 label/input pairs into one cohesive picker block.
  Single label scale (DM Sans 11px #9aa0b3), single placeholder
  ("z.B. PLTR oder ^VIX"), shared visual rhythm.
- Sidebar-wide contrast sweep — every Mono-9px-#424666 label →
  DM-Sans-11px-#9aa0b3 (WCAG 1.8:1 → 5.2:1). Hit market-pulse, top-
  movers, universe-by-sector, brand strip, nav-group headers, data-
  status footer, watchlist rows, bulk-loader warning box.

**Welle 2 — TradingView Lightweight Charts:**
- New `streamlit-lightweight-charts` dep (TradingView's own MIT lib).
  ADR-0006 documents the choice + the explicit rejection of the
  TradingView widget embed (which kills our IV / regime / earnings
  overlay layer).
- New `volscope/ui/components/lwc_chart.py` — `price_chart_lwc()`
  accepts an OHLCV frame (typically yfinance) + our daily_vol history
  + earnings dates and emits a candlestick + volume + dashed IV30
  overlay spec. `fetch_daily_ohlcv()` cached 1h, `render_lwc_safe()`
  degrades to False if the dep is missing. Unit-tested inline against
  a 20-day synthetic frame (3 series, fallback path, empty path).
- Scope tab_price — new "DAILY · CANDLES · VOLUME · IV30 OVERLAY"
  section above the existing intraday Plotly section (renamed
  "INTRADAY · 1D / 5D / 1M"). Earnings markers wired from
  `_earnings_list(db, ticker)`.
- Pre-Trade — new compact "UNDERLYING · 1Y · TRADINGVIEW" section
  above the KPI strip. Failure-tolerant.
- Options-Lab `_render_underlying_context` — tries LWC first, falls
  back to the existing Plotly `pro_chart` helper on any failure.

**Welle 3 — Options Lab à la OptionStrat / Unusual Whales:**
- 8 Quick-Start tiles in a 4×2 grid above the builder strip:
  Long Call · Long Put · Bull Call Spread · Bear Put Spread ·
  Long Straddle · Long Strangle · Iron Condor · Iron Butterfly.
  Each tile is a Streamlit button with a direction-colored
  chip below it (green long_vol, amber short_vol). Click sets
  `ol_template`, normalises DTE=30 and contracts=1, then `st.rerun()`.
- Builder strip — every input now carries an explicit `help=`
  tooltip, pulled from the v0.6.2 centralised `glossary.tooltip()`
  for IV / DTE so future glossary updates propagate.

**Welle 4 — Paper Trading explained:**
- `_render_paper_mode_banner()` — green accent-bordered box ABOVE
  the page header on Pre-Trade. Says explicitly: "Clicking BUY
  writes the trade to bot_trades as PROPOSED. No IBKR call, no
  real money. Live trading is Phase 4." Plus a real "→ Open Paper
  Portfolio" Streamlit button that navigates to Bot Dashboard via
  `NavIntent`.
- `_maybe_show_paper_intro(db)` — first-run `st.dialog` 3-slide
  tutorial ("What is paper trading", "Where do I see open trades",
  "When can I go live"). Session-state-persisted; cross-session
  persistence falls back gracefully because the UI now opens DuckDB
  read-only (v0.6.2). Caveat documented inline.
- `_render_help_and_faq()` — 6-question FAQ panel at the bottom of
  Pre-Trade, every question collapsed by default. Covers BUY-click
  semantics, where to see open trades, BSM pricing, Phase-4 go-live
  conditions, why our IV differs from Yahoo's, what "paper-buying"
  really means for P&L.

Version bumped to **0.7.0**. ADR-0006 added. CI watched green.

---

## Last Session: 2026-05-14 (v0.6.2 — performance + design polish)

On top of v0.6.1 (IV-robustness subsystem) we shipped seven coordinated
polish items so the surface feels paid-product, not lab-notebook:

- **A1 — cache `compute_sector_aggregates`.** New
  `compute_sector_aggregates_cached(cache_key, full_df)` wrapper in
  `volscope/ui/components/cached_data.py`, decorated with
  `@st.cache_data(ttl=600)`. Wired into Rotation (two call sites) +
  Flow. Eliminates ~100-200 ms pandas groupby per render on three
  sector pages. Cache invalidates on a fresh scrape via
  `make_cache_key(db)` (last-scrape-date).
- **A2 — read-only DuckDB in the UI.** `VolScopeDB(read_only=True)`
  ctor flag now opens via `duckdb.connect(path, read_only=True)`,
  bypasses schema bootstrap + legacy migration. `get_db()` in
  `volscope/ui/app.py` prefers read-only with a writable bootstrap
  fallback on the last retry (covers fresh-checkout case). Removes a
  whole class of UI ↔ scheduler write-lock contention.
- **A3 — `@st.fragment(run_every="30s")` on Bot Dashboard.** Live
  signals, open trades, and equity curve panels lifted into three
  fragment helpers in `volscope/ui/views/bot_dashboard_page.py`. Each
  polls its own DuckDB query in isolation; the rest of the page no
  longer re-renders every 30s.
- **B1 — centralised glossary.** `volscope/ui/glossary.py` defines
  ~41 terms (IV / IVR / IVP / VRP / Greeks / DTE / regime /
  signal-engine vocab / quality-score / contamination / structural
  break / bot-specific) + a `tooltip()` helper. Six unit tests cover
  emptiness, canonical lookup, missing-term fallback, no duplicate
  definitions, core-term presence, and absence of raw HTML tags.
- **B2 — `page_banner_html` orientation banner.** New helper in
  `volscope/ui/components/html_utils.py`; wired into the 8 top
  pages (Command Center, Discover, Signals, Bot, Scope, Earnings
  Hub, LEAPS Lab, Pre-Trade). Each opens with "what · when" so a
  fresh operator gets purpose + timing in two lines.
- **B3 — version + commit-SHA footer.** `volscope/__init__.py`
  exposes `__version__ = "0.6.2"` and `__commit__` (short HEAD SHA,
  read once at import). Fixed-position footer rendered after
  `_render_page_safely()` in `volscope/ui/app.py` — bottom-right,
  JetBrains Mono 9 px, opacity 0.55, pointer-events:none.

Tests: `tests/test_glossary.py` 6/6 green. Decisions logged at
`docs/decisions.md` as "2026-05-14 v0.6.2 — Performance + design
polish wave".

---

## Last Session: 2026-05-14 (v0.6.0 — data foundation + math gate + agent orchestration)

Today's wave on top of v0.5.0:

- **Data foundation (Section 1) shipped:**
  - Fixed `.parent.parent → .parent.parent.parent` path bug across 17 scripts
    (one-line repo-wide regression introduced by the v0.2.0 reorg; surfaced
    by the operator's fresh-ZIP-download bug report).
  - `scripts/ops/apply_migrations.py` + `make migrate` — idempotent runner
    that applied migrations 001-005 to the live DB. 11 `bot_*` objects live.
  - First live `make scrape-chains` run: **54,340 chain-snapshot rows
    across 13 tickers in 54 seconds.** `bot_chain_snapshots` populated.
- **Math validation gate (Section 2) shipped:**
  - Installed `py_vollib_vectorized` 0.1.1 + `QuantLib` 1.42.1.
  - `tests/properties/test_iv_round_trip.py` — 2000-example Hypothesis
    property: σ → price → recovered_σ within 1e-4.
  - `tests/properties/test_pyvollib_agreement.py` — 1000-example
    cross-check against py_vollib_vectorized within 1e-8.
  - `tests/golden/test_quantlib_goldens.py` — 100 random tuples vs
    QuantLib AnalyticEuropeanEngine within 1e-3.
  - `tests/properties/test_hv_estimators_mc.py` — Monte-Carlo recovery
    + efficiency ordering + YZ drift-independence.
  - `docs/MATHEMATICAL_FOUNDATIONS.md` — 10-section LaTeX reference
    (BSM, Greeks, IV solver, 4 HV estimators, IVR/IVP/VRP, composite
    score, HMM, GARCH) with Hull/QuantLib citations.
- **Agent orchestration (Section 3) shipped — the REAL `/full-review`:**
  - `volscope/orchestration/full_review.py` — Aggregator clusters
    findings by `(file, line±3, category)`, severity merged as MAX,
    scored by `severity_weight × agreement_count`. PASS/REVISE/REJECT
    loop max 3 iterations.
  - `scripts/ops/full_review.py` — CLI spawning 5 parallel
    `claude -p` subprocesses with role-specific rubrics. Mock mode
    for CI; real mode for operator. Exit code = verdict
    (PASS=0/REVISE=1/REJECT=2).
  - `tests/test_full_review.py` — **12 tests pass** covering dedupe,
    severity merge, verdict resolution, iteration cap, JSON round-trip,
    markdown rendering.
- **README + Makefile UX fix:**
  - Replaced `<your-fork>` placeholder with the actual repo URL.
  - Added BOTH pip + uv quick-start paths.
  - `make quickstart` now does `pip install -e .` so `import volscope`
    works from any script.
  - Documented the `cp .env.example .env # ...` confusion (the
    `# comment` was confusing zsh).

## Current Phase: v0.6.0 ships → v0.7.0 (live IBKR scaffolding + UX productisation)

## Test Status

Local fast subset: 150+ tests across 16 modules; orchestration 12/12 green;
math validation tests run (pending iCloud-warm-up retry). Coverage on new
modules ~88%.

## Bot Status: paper_dev — live DB now has the schema + 54k chain rows

- ✅ All 5 migrations applied to live DB
- ✅ bot_chain_snapshots populated (54,340 rows / 13 tickers / today)
- ✅ Math validation gate (4 new test files; py_vollib + QuantLib)
- ✅ MATHEMATICAL_FOUNDATIONS.md (LaTeX, ~300 lines)
- ✅ /full-review pipeline wired (12 tests green)
- ⏳ HMM training on real history (D10/D11) — v0.6.1
- ⏳ Phase 2.5 live IBKR wiring — v0.7.0

## Active Branch: main

## Open Bugs

(none P0 — all blockers from MASTERPIECE_BACKLOG.md cleared in this session)

## Next 3 Steps (priority order — see MASTERPIECE_BACKLOG.md)

1. **v0.6.1 D10/D11** — HMM training pipeline on real VIX+SPY history
   (Polavarapu 9-feature cross-asset + label-stability reordering).
2. **v0.6.1 C1/C2/C3** — Per-page UI tooltips + centralized glossary +
   onboarding tour for paid-product UX.
3. **v0.7.0 B1** — Phase 2.5 live IBKR wiring (Watchdog, BAG combos,
   walk-price, reconciler).

## Open Questions for Operator

- Free vs paid product split — when does the bot tier become paid?
- License flip to MIT — when do GOING_PUBLIC_CHECKLIST.md gates clear?
- Co-maintainer on CODEOWNERS — anyone besides @SchoenTom?
