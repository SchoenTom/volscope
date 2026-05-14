# VolScope Progress

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
