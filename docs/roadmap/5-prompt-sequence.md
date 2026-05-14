# The 5-prompt mega-sequence (future autonomous sessions)

Operator-provided anchor sequence for taking VolScope from v0.2.0 to a
production-grade autonomous bot. Each prompt is a single Claude Code
session (2-8 hours of focused execution).

This file is the **anchor doc** for future autonomous sessions —
quoted as the source of truth when an agent picks up Phase 3+ work.

> Note from v0.2.0 (2026-05-14): Prompt 1 ("Fundament") was largely
> executed in this session. Items below it are still open. Boxes marked
> ✅ are done in v0.2.0.

---

## PROMPT 1: Fundament — Phase 0 + GitHub-Ready + Hygiene

**Estimated runtime: 2–3 hours.**

### Bug fixes (Phase 0)

- ✅ Pre-Trade fillcolor crash — `rgba()` helper used throughout.
- ✅ "keyboard" placeholder ghost — `theme.py` font-fallback hardened.
- ✅ `st.metric` truncation — replaced with `kpi_grid_html`.
- ✅ Sparse heatmap — forward / backward fill along the time axis.
- ✅ Rotation page empty join — dead tautology removed.
- [ ] Sidebar button overflow (low priority polish).
- [ ] IV data-quality `valid_iv` boolean column on `daily_vol` +
      migration + scraper rejection.

### GitHub setup

- ✅ `.gitignore`, `.env.example`, `NOTICE`, `pyproject.toml`,
      `pre-commit`, CI workflow, CODEOWNERS, ISSUE_TEMPLATEs,
      `dependabot.yml`.
- ✅ `WELCOME-AGENT.md`, `ROADMAP.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
      `SECURITY.md`, `docs/{ARCHITECTURE,DEVELOPER_GUIDE,OPERATOR_GUIDE,
      BACKUPS,GOING_PUBLIC_CHECKLIST}.md`.
- ✅ ADR-0001 through ADR-0005 seeded.

### Hygiene & tooling

- ✅ `pyproject.toml` migration from `requirements.txt`.
- ✅ `structlog` configured (logger module).
- ✅ Pydantic settings + YAML loader (Phase 1 config files).

**v0.2.0 STATUS: 90% of Prompt 1 done. Items remaining: IV-data
quality `valid_iv` column, sidebar overflow polish.**

---

## PROMPT 2: Mathematical Validation

**Estimated runtime: 3–4 hours.**

The "boring but critical" prompt. Validate every analytics function
against published reference values. Property-based testing with
Hypothesis. Numerical stability for edge cases.

### Black-Scholes validation

- [ ] Hull worked examples (Ch. 15, 19) — 30+ golden test cases.
- [ ] Put-call parity property test (1000+ Hypothesis examples).
- [ ] Greeks consistency: delta bounds, gamma positivity, vega
      positivity, analytical-vs-numerical delta.
- [ ] Edge cases: T=0, σ=0, deep OTM/ITM, long T, negative rates.

### Newton-Raphson IV solver

- [ ] Round-trip property test (generate price from σ, recover σ).
- [ ] Convergence guarantees (< 50 iterations for tradable options).
- [ ] Arbitrage-bound enforcement.
- [ ] Cross-check against `py_vollib_vectorized`.

### HV estimators

- [ ] Close-to-close against known-variance log-normal returns.
- [ ] Parkinson, Garman-Klass, Yang-Zhang efficiency (Monte-Carlo).
- [ ] Edge cases: constant prices, single jump, missing data,
      weekend gaps, overnight jumps.

### IV Rank vs IV Percentile

- [ ] Definitional tests.
- [ ] Single-spike contamination consistency check.

### Strike selection at target delta

- [ ] Interpolation between bracket strikes.
- [ ] Real-chain test on SPY 45-DTE 16-delta.

### Strategy P&L

- [ ] Iron Condor max-loss / max-profit / breakevens / POP.
- [ ] Credit spread, strangle.
- [ ] POP vs POT (probability of profit vs probability of touch).

### Date arithmetic

- [ ] Business days, NYSE holidays, third-Friday expiries, weeklies.

**Acceptance:**

- `pytest tests/golden/` 30+ Hull-reference tests green.
- `pytest tests/properties/` 5000+ Hypothesis iterations green.
- Coverage on `volscope/analytics/` ≥ 95%.
- Mutation testing (mutmut) score > 80%.
- `notebooks/validation.ipynb` with VolScope-vs-py_vollib plots.
- `docs/MATHEMATICAL_FOUNDATIONS.md` with LaTeX formulas + citations.

---

## PROMPT 3: Signal Engine + Bot Dashboard (Phase 1 production)

**Estimated runtime: 4–6 hours.**

Build the production-grade signal engine on top of the v0.2.0 scaffold.

### Concrete deliverables

- HMM regime training pipeline on real VIX + SPY history.
- Earnings calendar adapter (Finnhub primary, Alpha Vantage cross-check,
  SEC EDGAR ground truth).
- Bot Dashboard live refresh via `st.fragment` every 5s during market hours.
- Composite-score live-table with sortable columns + green/yellow/red
  gate indicators.
- Open-trades table with MTM, %-of-PT, DTE-to-21.
- Telegram alerts via raw httpx for signal events.

### Acceptance

- Daily scan produces ranked signal list with regime-conditioned scores.
- HMM `p_calm` displayed in dashboard.
- Telegram alerts deliver on every signal event in a 24h dry run.

---

## PROMPT 4: Paper Trading Loop (Phase 2 production)

**Estimated runtime: 6–8 hours.**

Wire the Phase 2 scaffolds (already shipped in v0.2.0) to live IBKR paper.

### Concrete deliverables

- `volscope/execution/ibkr_client.py` extending the v0.2.0 stub with
  Watchdog, rate-limit semaphore, BAG combo builder, walk-price algo.
- `volscope/execution/paper_engine.py` using LIVE IBKR quotes + the
  slippage model from `config/risk.yaml`.
- State machine wired into the audit log via `bot_signals_log` +
  `bot_orders_log`.
- All 8 kill-switch paths fire-drilled.
- APScheduler running the 8 daily jobs.

### Acceptance

- 30+ days running, ≥ 30 paper round-trips.
- State machine never desyncs from broker on reconnect.
- Kill switch tested for all 8 paths.

---

## PROMPT 5: Performance & UX Turbo

**Estimated runtime: 2–3 hours.**

- Polars for hot paths > 100k rows.
- `asyncio` instead of threading.
- DuckDB pragmas for speed.
- Streamlit fragments for sub-section refresh.
- Plotly WebGL for large charts.
- DiskCache for expensive computations.
- Loading skeletons + optimistic updates.
- Cmd+K command palette.
- Keyboard shortcuts (j/k navigation, hjkl in tables).

### Acceptance

- Every page renders < 200ms end-to-end.
- All interactive controls feel instant.
- Power-user features (palette, shortcuts) documented in
  `docs/OPERATOR_GUIDE.md`.

---

## Suggested order

1. **Done (v0.2.0)**: most of Prompt 1.
2. **Next session**: Prompt 2 (math validation) — the unglamorous gate
   that separates hobby from production.
3. **After paper validation**: Prompt 3 → Prompt 4 → Prompt 5.
