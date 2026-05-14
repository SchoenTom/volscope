# Decision Log

A flat, append-only log of every non-trivial decision. Lighter than
ADRs (those are reserved for architecturally significant choices) —
this catches the day-to-day "why did we do it this way" so future-you
or future-agent doesn't have to spelunk through commits.

**Format per entry:**

```
## [ISO-Date] [Title]
**Choice:** what was chosen
**Alternatives:** what else was on the table
**Why:** 2-3 sentences
**Evidence:** files / tests / sources consulted
**Reversibility:** reversible | hard | irreversible
**Confidence:** low | medium | high
```

---

## 2026-05-14 Add IV Robustness Subsystem (v0.6.1)

**Choice:** New module `volscope/analytics/iv_robustness.py` with four
primitives (`robust_iv_rank`, `detect_contamination`,
`detect_structural_break`, `assess_iv_quality`); migration 006 adds
nine quality columns to `daily_vol`; nightly compute job; Scope-page
warning banner; Scanner QUALITY column; Discover toggle filter.
**Alternatives:** (a) Extend `volscope/signals/factors.py` directly
(rejected — Single Responsibility violation; bigger blast radius).
(b) Replace standard IVR entirely (rejected — breaks backward compat;
legacy metric is still useful in CLEAN cases).
**Why:** Observed 2026-05-14 dashboard bug: FISV showed IVR 12.5
("CHEAP") vs IVP 78.6 ("HIGH"). Standard IVR is range-based; a single
extreme IV spike (forecast reset / M&A / crisis) inflates the 52-week
MAX and pulls IVR toward 0 even when IV has just regime-shifted
permanently higher. Trading on the contaminated signal = short-vol
entry on a permanently-elevated ticker. Separate module allows
robustness to be toggled, tested in isolation, and owned by the
risk-auditor agent without touching signal-engineer's factors.
**Evidence:** FISV case study captured in `docs/IV_ROBUSTNESS.md` +
regression test `tests/test_iv_robustness.py::TestFISVRegression`.
External: FISV had a real forecast-reset / litigation crisis Q3-Q4 2025.
**Reversibility:** reversible — additive subsystem; existing `ivr` and
`ivp` in `factors.py` unchanged; the UI gate is a toggle.
**Confidence:** high.

## 2026-05-14 Wire `/full-review` as a real 5-agent panel

**Choice:** Implement `volscope/orchestration/full_review.py` +
`scripts/ops/full_review.py` to spawn 5 parallel `claude -p`
subprocesses (signal-engineer, risk-auditor, security-reviewer,
code-reviewer, observability-engineer), each with role-specific
rubric + isolated context. Aggregate via dedupe-by-(file, line±3,
category) with severity × agreement scoring.
**Alternatives:** Sequential agent calls inside one Claude session
(loses independence); single super-agent reviewer (less diversification);
keep it as a spec-only command (theatre).
**Why:** Operator's iid-ness question — without subprocess isolation
+ JSON contracts, the 7 subagent specs are decoration, not a review
committee. Real independence rewards rediscovery and surfaces
real disagreement.
**Evidence:** TradingAgents v0.2.4, wshobson/agents, Paperclip
6-agent postmortem (no direct A→B messaging — JSON via shared state).
**Reversibility:** reversible — orchestration layer is pure Python;
removing it leaves agent specs intact.
**Confidence:** high.

## 2026-05-14 Apply DuckDB migrations 001-005 to the live DB

**Choice:** Run `apply_migrations()` against
`~/Library/Application Support/VolScope/volscope.db` — adds 6 `bot_*`
tables + `bot_chain_latest` view that have been defined since v0.3.0
but never instantiated on the operator's actual DB.
**Alternatives:** Wait for live IBKR wiring (Phase 2.5+) to apply
migrations as part of that work.
**Why:** Without the live tables, `bot_chain_snapshots` cannot store
the option-chain data the paper engine needs for daily MTM. The
operator's DB has been running with v0.2.0 schema for 2 weeks while
v0.3.0+ test DBs had the new schema.
**Evidence:** Phase 1 exploration confirmed `bot_chain_snapshots`
returned ParserException ("Table not found") on the live DB.
**Reversibility:** hard — creating tables is non-destructive but
rolling back would require manual `DROP TABLE` + cleanup of any rows
the paper engine writes after migration.
**Confidence:** high.

## 2026-05-14 Fix `.parent.parent` → `.parent.parent.parent` in 17 scripts

**Choice:** Mass-rewrite the `_ROOT = Path(__file__).resolve().parent.parent`
pattern across `scripts/` to use 3 levels (the post-v0.2.0-reorg correct
path to the repo root). Used a Python regex sweep to ensure consistency.
**Alternatives:** Switch every script to use `pip install -e .`
exclusively (no sys.path manipulation needed).
**Why:** The bug was introduced by the v0.2.0 script reorg that moved
files from `scripts/foo.py` (2 levels above root) to
`scripts/<group>/foo.py` (3 levels). 14 of 18 scripts had the broken
2-level path, causing `ModuleNotFoundError: No module named 'volscope'`
when invoked. The operator hit this on a fresh ZIP download from
GitHub — exactly the "must work first-try" expectation.
**Evidence:** Operator's bug report 2026-05-14 (16:32 ET) + my Python
sweep that fixed 14 files.
**Reversibility:** reversible — the pattern is mechanically detectable.
**Confidence:** high.

---

## 2026-05-14 Make memory/ chat-archive a committed folder (31 MB of RTFs)

**Choice:** Commit the 31 MB of chat-dump RTFs as `memory/chat-archive/`.
**Alternatives:** (a) gitignore them, (b) move to a sibling repo via
git submodule, (c) delete entirely.
**Why:** Operator explicitly wants them as agent context — "everything
to know for agents". Git handles 31 MB without LFS; the value of
preserving conversation history for future Claude sessions outweighs
the size cost. Will switch to LFS if archive grows past ~100 MB.
**Evidence:** Operator's directive in session 2026-05-14, +
`memory/README.md` documents the trade-off.
**Reversibility:** reversible (can `git filter-repo` later).
**Confidence:** high.

## 2026-05-14 Rename SQL column `right` → `option_right`

**Choice:** Rename the call/put indicator column in
`bot_chain_snapshots` from `right` to `option_right`.
**Alternatives:** Keep `right`, quote it in every SQL statement
(`"right"`).
**Why:** `RIGHT` is a SQL reserved word (string function); DuckDB's
parser rejected it in DDL. Renaming is cleaner than quoting in every
query and future-proofs against parser updates.
**Evidence:** DuckDB ParserException on first migration apply (see
session log 2026-05-14).
**Reversibility:** reversible (migration would be `ALTER TABLE ...
RENAME COLUMN`); zero data live yet.
**Confidence:** high.

## 2026-05-14 Drop `uv` from CI in favour of stock `pip`

**Choice:** CI workflow uses `actions/setup-python` + `pip install -r
requirements.txt` instead of `astral-sh/setup-uv` + `uv sync`.
**Alternatives:** Generate a `uv.lock` file and commit it; switch CI to
fully `uv`-native.
**Why:** First CI run failed because `setup-uv@v3` requires `uv.lock`
which we don't have. Generating + maintaining a lockfile is friction
that doesn't pay off for a single-operator private repo at this stage.
Local dev still uses uv via `pyproject.toml`.
**Evidence:** CI run #25854641098 failure log; commit `79360b0`.
**Reversibility:** reversible — flip back when we're ready to commit
`uv.lock` and standardise on uv across dev + CI.
**Confidence:** medium (will revisit when team grows or build
reproducibility becomes critical).

## 2026-05-14 Private repo with NOTICE, flip to MIT later

**Choice:** Push as private with a proprietary NOTICE; plan a flip to
MIT once `docs/GOING_PUBLIC_CHECKLIST.md` gates clear.
**Alternatives:** Public + MIT from day 1; private forever.
**Why:** Private gives breathing room to iterate without external
scrutiny; MIT later opens the project to community contributors once
the bot logic is paper-validated and the audit log is clean.
**Evidence:** Operator's `AskUserQuestion` answer + checklist doc.
**Reversibility:** hard once public — git history would need a
filter-repo pass before flip.
**Confidence:** high.

## 2026-05-14 21-DTE mechanical close as a hard invariant

**Choice:** Every short-vol strategy config block must include
`dte_exit: 21`. Validator rejects any short-vol config that omits it.
**Alternatives:** Per-strategy override; soft default with operator
discretion.
**Why:** Gamma is 3-5× higher inside 21 DTE (tastytrade Market
Measures). Empirically (tastytrade 4,872 SPY trades + DTR 96k SPX
trades) the rule lifts realised win rate from 64% → 82% on the same
underlying logic. This is non-negotiable for the bot.
**Evidence:** `docs/adr/0005-21-dte-mechanical-close.md`.
**Reversibility:** reversible only after Phase 3 backtest validation
shows a different cut produces strictly better risk-adjusted returns.
**Confidence:** high.

## 2026-05-14 Quarter-Kelly position sizing as production-safe start

**Choice:** `kelly_fraction: 0.25` in `config/risk.yaml`.
**Alternatives:** Half-Kelly (0.5), Full Kelly (1.0), fractional based
on rolling volatility.
**Why:** Options returns are leptokurtic + negatively skewed; full
Kelly breaks down at Student-t v=4 (Turlakov 2016). Half-Kelly captures
~75% of expected growth at ~50% of drawdown. Quarter-Kelly is the
conservative-by-design starting point; promotion to 0.5 requires
6 months live + Sharpe ±0.3 of paper.
**Evidence:** `docs/adr/0004-quarter-kelly-position-sizing.md`.
**Reversibility:** reversible via Sunday review window + 90-day
cooldown.
**Confidence:** high.

---

## 2026-05-14 v0.6.2 — Performance + design polish wave

**Choice:** A1 cache `compute_sector_aggregates`, A2 open DuckDB
read-only in the UI with bootstrap fallback, A3 wrap the Bot
Dashboard live panels in `@st.fragment(run_every="30s")`,
B1 centralise glossary in `volscope/ui/glossary.py`, B2 add
`page_banner_html` orientation banner to the 8 most-visited pages,
B3 footer with `__version__` + short commit SHA.
**Alternatives:** Polars hot paths, Cmd+K palette, DiskCache for HMM
fits, Apple-design rewrite — banked to v0.7.0+ (lower leverage per
hour, higher risk per session).
**Why:** v0.6.1 hardened the math (FISV-class IV robustness). v0.6.2
makes the surface feel like a paid product: the three hottest
sector-rotation pages stop paying a ~100-200 ms pandas groupby on
every render; the UI stops fighting the scheduler for the DuckDB
write lock; the Bot Dashboard's three live panels poll
independently so the rest of the page never re-renders; glossary
terms now resolve from one place; every high-traffic page opens
with two-line "what + when" orientation; the footer tells the
operator which commit is running.
**Evidence:** `volscope/ui/components/cached_data.py` (cached
wrapper), `volscope/data/database.py` (`read_only=True` ctor),
`volscope/ui/app.py::get_db` (read-only first with writable
fallback), `volscope/ui/views/bot_dashboard_page.py` (three
`@st.fragment` helpers), `volscope/ui/glossary.py` (~30-term dict
+ `tooltip()`), `volscope/ui/components/html_utils.py::page_banner_html`,
`tests/test_glossary.py`.
**Reversibility:** reversible — every change is a single-file edit
that can be reverted without touching schemas, audit chain, or
risk thresholds.
**Confidence:** high.

---

## 2026-05-14 v0.7.0 — Paid-product UX wave (readability, charts, paper trading)

**Choice:** Four coordinated waves: (W1) fix the sidebar
collapse-button regression in `theme.py` + redesign the Add-Ticker
block + contrast-sweep Mono-9px-#424666 labels to DM-Sans-11px-#9aa0b3
across the sidebar (WCAG 1.8:1 → 5.2:1). (W2) Adopt
`streamlit-lightweight-charts` for the price surface on Scope /
Pre-Trade / Options-Lab; Plotly stays for IV/HV/skew/heatmaps; new
`volscope/ui/components/lwc_chart.py` accepts a yfinance OHLCV +
our daily_vol history and overlays IV30 / earnings markers. (W3)
8-tile OptionStrat-style Quick-Start rail in Options-Lab + inline
glossary tooltips on every builder-strip input. (W4) Paper-mode
banner + "Open Paper Portfolio" CTA + first-run `st.dialog` tutorial
+ Help-&-FAQ panel at the bottom of Pre-Trade.

**Alternatives considered:** (a) TradingView widget embed — killed
because it cannot render our own IV / regime / earnings overlays
(the entire reason VolScope exists). See ADR-0006. (b) Pure
Plotly upgrade — feasible but visually still feels like a research
plot, not a trader chart. (c) Defer paper-trade affordances to
v0.8.0 — rejected; operator confusion at the BUY button is a real
risk that one banner removes.

**Why:** v0.6.2 made the surface readable; v0.7.0 makes it *feel
like a paid product*. Every change targets a specific operator-
reported pain: invisible collapse button, ugly mono-9px labels,
spline-smoothed price chart vs TradingView, cryptic Options-Lab
first paint, paper-trading mode never explained.

**Evidence:** `volscope/ui/styles/theme.py` (collapse-button +
floating reopen pinned `position:fixed`), `volscope/ui/components/sidebar.py`
(Add-Ticker block, brand strip), `volscope/ui/components/lwc_chart.py`
(LWC wrapper + yfinance OHLCV fetcher), `docs/adr/0006-tradingview-lightweight-charts-for-price.md`,
`volscope/ui/views/scope_page.py::_render_history_price_lwc`,
`volscope/ui/views/pretrade_page.py::_render_paper_mode_banner`
/ `_maybe_show_paper_intro` / `_render_help_and_faq`,
`volscope/ui/views/options_lab_page.py::_render_quickstart_tiles`,
`requirements.txt` (streamlit-lightweight-charts pin).

**Reversibility:** reversible — every change is additive (new
component module, new helper functions, two-line theme.py edit).
The TradingView dep can be removed by deleting `lwc_chart.py`
calls; pages fall back to the existing Plotly path automatically
because `render_lwc_safe()` returns False on import failure.

**Confidence:** high.

---

## 2026-05-14 v0.7.1 — Matched-horizon IV-HV spread (academic correctness)

**Choice:** Add ``hv_yz_30d`` (Yang-Zhang at 30 trading days) and the
derived ``iv_hv_spread_matched = iv_30d - hv_yz_30d`` to ``daily_vol``.
Wire both into the seed-backfill in ``ticker_resolver._backfill_hv_history``.
Keep ``hv_20d`` (close-to-close) and the legacy ``iv_hv_spread`` columns
unchanged so existing scanner / discover code paths keep working.
**Alternatives considered:**
- 30 new columns covering 5 estimators × 5 windows + cone metrics (the
  prompt the operator originally drafted) — rejected as over-engineered.
  Five estimators are highly correlated (r > 0.95 between YZ / GK /
  Parkinson), so storing all of them daily wastes column-store reads
  without adding independent signal. Two estimators (YZ as primary,
  CC as sanity) is the academic standard for cross-validation.
- Vol-cone columns + UI in the same release — deferred to v0.8.0;
  the cone math already lives in ``volscope/analytics/vol_cones.py``
  but isn't wired to a page yet, which is a focused UI pass on its own.
- GARCH(1,1)-t forecast volatility — deferred to v0.9.0; that's
  forward-looking, the matched-horizon HV fix is backward-looking, and
  conflating them slows both shipping cycles.
**Why:** Up to v0.7.0, ``iv_hv_spread = iv_30d - hv_20d`` compared a
30-day implied figure against a 20-day realised figure (~28 calendar
days). The horizon mismatch is small (~2 vol points typical bias) but
real, and is an unforced academic-correctness loss for a workbench
that aspires to paid-product credibility. Yang-Zhang at 30 trading
days is the industry default for daily-OHLC equity data: drift-
independent, handles overnight gaps, ~3-5× more efficient than CC in
practice (theoretical bound 7× per Yang-Zhang 2000, lower in real
data with imperfect OHLC quality).
**Evidence:**
- ``volscope/persistence/migrations/007_hv_matched_horizon.sql`` (new
  columns + scanner index)
- ``volscope/data/database.py`` (CREATE TABLE + backfill ALTER + ``_DAILY_FIELDS`` extended)
- ``volscope/data/ticker_resolver.py::_backfill_hv_history`` (computes
  ``hv_yz_m`` at ``DEFAULT_HV_MATCHED`` and persists ``hv_yz_30d`` +
  ``iv_hv_spread_matched``)
- ``volscope/config.py::DEFAULT_HV_MATCHED = 30``
- ``tests/test_hv_matched_horizon.py`` — three properties: log-normal
  recovery within ±2.5 vol pt, HV30 std ≤ HV20 std (estimator variance
  monotonicity), DB round-trip for the new columns.
**Reversibility:** fully reversible. Legacy columns / spread untouched;
new columns are additive and nullable on existing rows. Reverting
the column writes is a one-line revert in ``_backfill_hv_history``;
the migration leaves the columns NULL on rollback, no data loss.
**Confidence:** high.

---

## 2026-05-14 v0.8.0 — Page redesigns (Heatmap → Treemap, Rotation → RRG, Portfolio hero, Flow bars, Options-Lab expiry picker, universe expansion)

**Choice:** Five coordinated page redesigns + universe expansion +
an absolute-date expiry picker for Options Lab. Specifically:

1. **Heatmap** — replaced the naive 20-column grid heatmap with a
   proper TradingView-style sector treemap (``plotly.graph_objects.
   Treemap``). Rectangle size = total OI (deeper option markets get
   more visual real-estate, the correct prioritisation for a vol
   tool). Color = IV percentile on a green→red gradient OR
   symmetric Δ-IV mode (1d / 30d). Click-to-Scope path simplified
   to the treemap's native ``label`` field.
2. **Rotation** — replaced the dense sector × date heatmap with a
   Relative Rotation Graph (RRG, Julius de Kempenaer 2005) adapted
   to vol semantics. X = sector IV percentile minus cross-sector
   median, Y = 21-day momentum of that ratio. Four quadrants labelled
   in vol language: Vol Heating / Cooling / Cold / Warming. 8-week
   trails per sector with head markers. Heatmap kept as secondary tab.
3. **Portfolio Performance section** — IBKR / TradeRepublic-style
   hero: big NLV at the top with today's $ + % delta pill, then a
   1D / 1W / 1M / 3M / YTD / All time-range pill, then the equity
   curve rendered via streamlit-lightweight-charts (TradingView feel)
   with a Plotly fallback. The 6-cell KPI strip (Sharpe, Max DD,
   etc.) moves below the curve.
4. **Flow** — replaced the heatmap-first layout with a sortable
   horizontal Plotly bar chart of current flow scores per sector
   as the default tab. Heatmap retained as second tab for time-
   series analysis. Divergence alert cards kept (they're the
   actionable signal).
5. **Options Lab — absolute expiry picker** — added an "EXPIRY"
   row above the builder strip with four preset tiles (Weekly,
   Monthly, Quarterly, LEAPS) showing both the absolute date AND
   the DTE, plus a custom ``st.date_input``. Selecting any preset
   or date writes ``ol_dte`` in session_state so the existing DTE
   slider picks it up. Relative DTE slider stays for fast iteration.
6. **Ticker universe expansion** — 630 → 842 unique tickers
   (~34% increase). Added leveraged & inverse ETFs (TQQQ family,
   SOXL family, NUGT/DUST, BOIL/KOLD, TMF/TMV, etc.), spot-crypto
   ETFs (IBIT, FBTC, ETHA), S&P 500 mid-cap completers, more ADRs
   (LatAm: MELI/NU/PAGS, Europe: SE/GRAB/GLOB), recent listings with
   liquid options (RDDT, ARM, CART, ALAB), additional biotech and
   high-vol meme names.

**Alternatives considered:**
- TradingView widget embed for the heatmap — rejected (ADR-0006):
  it would not render our IV-percentile / IV-change overlays.
- Equity-rotation style RRG semantics ("Leading / Weakening / etc.")
  — rejected; remapped to vol semantics so the chart reads correctly
  for a vol-focused tool.
- Single-page-redesign approach (do all 5 in one massive rewrite) —
  rejected as over-risk. Each page redesign is additive (old code
  retained as secondary tab where useful), so any single regression
  is locally fixable.

**Why:** v0.7.x made the surface readable and the math correct.
v0.8.0 is the visual-credibility wave: the operator described the
Heatmap and Rotation specifically as "Schandflecke" compared to
TradingView / IBKR / TradeRepublic. The new charts mirror the
industry-standard patterns those tools use (treemap, RRG, hero-NLV
with time-range pills, sortable bar chart) so the operator no
longer pays a credibility tax on the visual layer.

**Evidence:**
- ``volscope/ui/views/heatmap_page.py::_build_treemap_figure``
- ``volscope/ui/views/rotation_page.py::_compute_rrg_panel``,
  ``::_build_rrg_figure``
- ``volscope/ui/views/portfolio_page.py::_render_performance_section``
- ``volscope/ui/views/flow_page.py::render_flow_page`` (bar-first
  tab layout)
- ``volscope/ui/views/options_lab_page.py::_render_expiry_picker``
  + ``_next_friday`` / ``_next_third_friday`` / ``_next_quarterly_friday``
  / ``_next_january_leaps`` helpers
- ``volscope/data/ticker_universe.py`` (842 unique tickers after
  dedupe, verified by smoke test)

**Reversibility:** fully reversible. The Heatmap, Rotation and Flow
redesigns retain the previous chart as a secondary tab — operators
can compare side-by-side. The Portfolio hero is a layout change on
top of the existing analytics (compute_portfolio_performance is
unchanged). Options Lab expiry picker is additive — the DTE slider
behaviour is unchanged. The universe expansion only ADDS tickers;
existing scraper / scanner code is untouched.

**Confidence:** high for the visual redesigns; medium for the RRG
quadrant labelling (vol semantics may need a second pass once an
operator uses it in anger — e.g. "Cooling" might be more usefully
named "Mean-Reverting" in vol context). Universe expansion is
mechanical, no behavioural risk.

---

(append new decisions here, newest at the top)
