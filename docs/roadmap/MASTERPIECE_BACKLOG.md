# VolScope — Masterpiece Backlog (v0.6.0 → v1.0)

Comprehensive consolidation of **everything we deferred, partially built,
or banked for later**, surfaced via two parallel research streams on
2026-05-14:

1. **Internal mining** of every roadmap doc / memory / decisions / TODO
   marker across the repo (Explore agent, ≤1500 words).
2. **External 2026 best-practice** research on the 6 deferred technical
   areas (general-purpose agent, ≤1000 words + ~30 citations).

This is the **source of truth** for "what's between us and a masterpiece."
Items are grouped by category, ordered by leverage within category.
Status legend:

- 🔴 **CRITICAL** — blocks live trading or auditability
- 🟠 **HIGH** — gates a phase exit
- 🟡 **MEDIUM** — polish + power-user UX
- 🟢 **LOW** — nice-to-have / explicit non-goal

---

## A. Math + Analytics Validation (Phase 0.5 full sweep)

> **2026 stack consensus** (research stream 2): four-layer pyramid =
> Hypothesis strategies + py_vollib_vectorized round-trip + QuantLib-Python
> cross-check + CPCV + mutmut ≥80% kill rate.

| ID | Item | Status | Source |
|---|---|---|---|
| A1 | 🟠 30+ Hull goldens ✅ (v0.5.0) — extend to 100+ across Hull, McDonald, Wilmott | partial | `docs/roadmap/5-prompt-sequence.md:64` |
| A2 | 🟠 Hypothesis property suite: put-call parity ✅ (v0.5.0) — add greeks-bounds, monotonicity, analytical-vs-numerical Δ within 1e-3, IV solver round-trip within 1e-4 | partial | `docs/roadmap/5-prompt-sequence.md:61-64` |
| A3 | 🟠 `py_vollib_vectorized` round-trip — price→σ→price on 50k Hypothesis grid, <1e-6 reconstruction | not started | research stream 2 |
| A4 | 🟠 `QuantLib-Python` golden cross-check — `ql.AnalyticEuropeanEngine` agreement <1e-8 with our BSM | not started | research stream 2 |
| A5 | 🟠 HV-estimator validation — generate log-normal returns with known σ, recover via CC/Parkinson/GK/YZ | not started | `docs/roadmap/5-prompt-sequence.md:67` |
| A6 | 🟡 Strike selection at target Δ — interpolation between brackets; real 45-DTE 16Δ chain test | not started | `docs/roadmap/5-prompt-sequence.md:68` |
| A7 | 🟡 IVR vs IVP definitional tests + single-spike contamination robustness | not started | `docs/roadmap/5-prompt-sequence.md:69` |
| A8 | 🟡 Date arithmetic edge cases — NYSE business days, 3rd-Friday expiries, weeklies, negative rates, very long T | not started | `docs/roadmap/5-prompt-sequence.md:70` |
| A9 | 🟠 `mutmut` 2.5.0 mutation testing — target ≥80% kill rate on `volscope/analytics/`, CI fail <70% | not started | research stream 2 |
| A10 | 🟠 `MATHEMATICAL_FOUNDATIONS.md` — LaTeX formulas + Hull/QuantLib citations + known approximation limits | not started | `docs/roadmap/5-prompt-sequence.md:109` |
| A11 | 🟡 IV data-quality `valid_iv` boolean — migration + scraper rejection | not started | `docs/roadmap/5-prompt-sequence.md:28-29` |

**v0.6.0 target:** A3 + A4 + A5 + A9 + A10. ~4-5 hours focused.

---

## B. Bot / Execution / Risk (Phase 2.5 production)

| ID | Item | Status | Source |
|---|---|---|---|
| B1 | 🔴 Live IBKR wiring — Watchdog, rate-limit semaphore, BAG combo builder, walk-price algorithm (replace `ibkr_stub.py`) | not started | `docs/roadmap/5-prompt-sequence.md:142-150` |
| B2 | 🟠 Real scheduler handlers wired — premarket_load / connect_ibkr / generate_signals / execute_entries / midday_check / eod_management / eod_reconcile | stub | `progress.md:26` |
| B3 | 🟠 Reconciler on every reconnect — `ib.reqAllOpenOrders()` + `ib.reqExecutions()` diff vs `bot_order_intents` | scaffold | v0.5.0 stub at `scripts/ops/reconcile.py` |
| B4 | 🟠 Earnings calendar adapter — Finnhub primary, Alpha Vantage cross-check, SEC EDGAR ground truth | not started | `docs/roadmap/5-prompt-sequence.md:123` |
| B5 | 🟠 Telegram alerts wired (raw httpx) — connected to dispatcher for trade open/close/kill/orange/red | stub | `progress.md:26` |
| B6 | 🔴 30-day paper run — 30+ trades, all 8 kill paths fire-drilled, state machine never desyncs | not started | `progress.md:25`, `ROADMAP.md:11` |
| B7 | 🟡 SVI / SSVI surface fitting — Gatheral & Jacquier (2014), per-slice + joint surface | not started | `memory/roadmaps/bot-masterplan.md:125` |
| B8 | 🟡 Per-name GEX (Gamma Exposure) from chain — dealer-positioning overlay filter | not started | `ROADMAP.md:14` |
| B9 | 🟡 Calendar spreads on backwardation — dispersion plays across term structure | not started | `ROADMAP.md:14` |

**v0.6.0 target:** B2 + B3 + B4 + B5. Wires the existing v0.3.0 scaffold to live signal generation + alert delivery. B1 + B6 are Phase 2.5 / 4.

---

## C. UI / UX / Performance

> **2026 stack consensus** (research stream 2): `st.fragment(run_every="5s")`
> for sub-section refresh, centralised `GLOSSARY` dict + `help=` on every
> widget, `st.dialog` for onboarding + Cmd+K palette, Polars 5–15× faster
> than pandas on chain pivots, Plotly `Scattergl` above 1k points.

| ID | Item | Status | Source |
|---|---|---|---|
| C1 | 🟠 Per-page tooltips — every page banner with "what is this" + "when to use" + "Learn more →" | not started | `docs/roadmap/MASTER_PLAN.md:76-97` |
| C2 | 🟠 Centralised `volscope/ui/glossary.py` — IV / IVR / IVP / VRP / Greeks / regime + `help=GLOSSARY[...]` on every widget | not started | research stream 2 |
| C3 | 🟠 Onboarding tour — `st.dialog` gated on `session_state.first_run`, persist completion to DuckDB | not started | research stream 2 |
| C4 | 🟡 `st.fragment(run_every="5s")` — sub-section refresh on Bot Dashboard during market hours | not started | research stream 2 |
| C5 | 🟡 Cmd+K command palette via `streamlit-hotkeys` + `st.dialog` + fuzzy filter on page registry | not started | research stream 2 |
| C6 | 🟡 Polars for hot paths > 100k rows — option chain pivot + 252-day factor recompute | not started | `docs/roadmap/MASTER_PLAN.md:108` |
| C7 | 🟡 DuckDB read-heavy pragmas — `read_only=True` from UI, `threads=N`, `memory_limit`, `enable_object_cache` | not started | research stream 2 |
| C8 | 🟡 `DiskCache` for HMM fit, GARCH fit, backtest replay — survives process restarts | not started | `docs/roadmap/MASTER_PLAN.md:113` |
| C9 | 🟡 Plotly `Scattergl` (>1k points) + `plotly-resampler` (>100k) | not started | research stream 2 |
| C10 | 🟡 Loading skeletons + optimistic UI on slow operations | not started | `docs/roadmap/MASTER_PLAN.md:115` |
| C11 | 🟡 Keyboard shortcuts — j/k/hjkl//, vim-like navigation, table cell selection | not started | `docs/roadmap/MASTER_PLAN.md:117` |
| C12 | 🟡 Per-page render benchmarks — `tests/test_perf_smoke.py` targets per page | not started | `docs/roadmap/MASTER_PLAN.md:118` |
| C13 | 🟡 Footer with commit-SHA stamping — operator sees which code is running | not started | `docs/roadmap/MASTER_PLAN.md:119` |
| C14 | 🟡 Apple-design upgrade (Phase R2 from MASTERPLAN_TO_PERFECTION) — 5-size type scale, motion CSS, KPI hero/detail split | not started | `docs/process/MASTERPLAN_TO_PERFECTION.md:270-277` |
| C15 | 🟡 Sidebar button overflow fix — minor polish | not started | `docs/roadmap/5-prompt-sequence.md:27` |
| C16 | 🟢 Dark/light theme switch | non-goal | `memory/roadmaps/design-plan.md:357` |

**v0.6.0 target:** C1 + C2 + C3 + C13. Product-grade UX for paying users. ~4 hours.

---

## D. Data / Backtest / ML

> **2026 stack consensus** (research stream 2): CPCV via
> `skfolio.model_selection.CombinatorialPurgedCV` with purge + embargo;
> Bootstrap CI 95% lower-bound > 0 gate; quarterly HMM retrain on rolling
> 2y window; 9-feature cross-asset model (Polavarapu SSRN 6539358).

| ID | Item | Status | Source |
|---|---|---|---|
| D1 | 🟠 Phase 3 backtest stack — vectorbt + optopsy + in-house event engine; match spintwig SPX IC 45-DTE Sharpe ±0.2 | not started | `ROADMAP.md:12` |
| D2 | 🟠 CPCV (Combinatorial Purged CV) via `skfolio` — purge + embargo + PBO + Deflated Sharpe | not started | research stream 2 |
| D3 | 🟠 Slippage calibration vs spintwig — entry/exit haircut from tastytrade published benchmarks | not started | `ROADMAP.md:12` |
| D4 | 🟠 Survivorship-bias hardening — historical S&P 500 constituent lists (CRSP); "name was in index at time T" filter | not started | `docs/process/MASTERPLAN_TO_PERFECTION.md:230-231` |
| D5 | 🟠 Bootstrap confidence intervals — 1000-sample BCa CI 95% on backtest Sharpe + Calmar; publish only if lower bound > 0 | not started | `docs/process/MASTERPLAN_TO_PERFECTION.md:212-226` |
| D6 | 🔴 Backtest chain ingest — populate `bot_chain_snapshots` for 60d-1100d expiries across top-50 universe | broken | `memory/roadmaps/leaps-lab-product.md:131-142` |
| D7 | 🔴 `sector_daily` table resurrection — currently 0 rows; `compute_sector_rotation.py` failing silently | broken | `memory/roadmaps/leaps-lab-product.md:134-136` |
| D8 | 🟠 ML mean-reversion classifier — XGBoost on 15 features; reversion-within-20/40/60d labels; filters `iv_perc<25 AND score>60` | research-only | `memory/roadmaps/giga-plan.md` |
| D9 | 🟠 Walk-forward retraining — rolling 252d train, 63d test, 63d step | not started | `memory/roadmaps/giga-plan.md` |
| D10 | 🟠 HMM on real history — quarterly retrain, rolling 2y window, 9-feature cross-asset (SPY r, VIX, TLT, GLD, ICE HY OAS + second moments + VIX9D/VIX + VIX/VIX3M + VRP) | not started | research stream 2 |
| D11 | 🟠 Label-stability fix — reorder HMM states post-fit by mean-VIX so "high-vol" stays state 1 across retrains | not started | research stream 2 |

**v0.6.0 target:** D6 + D7 (unblock everything else). Then D1 + D2 + D5 in v0.7.0.

---

## E. Infrastructure / Hosting / Ops

> **2026 stack consensus** (research stream 2): `chrony` (macOS Homebrew /
> Linux native) — pool with `iburst` + `makestep 1.0 3` + `chronyc tracking`
> |offset|<10ms target.

| ID | Item | Status | Source |
|---|---|---|---|
| E1 | 🟠 Branch protection on main — awaiting CI green | pending v0.5.0 J | `docs/roadmap/MASTER_PLAN.md:129` |
| E2 | 🟠 DuckDB encrypted backup + restore drill scripts — `backup_db.py` + `restore_db.py` + monthly `make restore-drill` | pending v0.5.0 F | plan |
| E3 | 🟠 NTP/chrony automation — `chrony` config + `chronyc tracking` health check in CI + drift-alarm > 100 ms | not started | research stream 2 |
| E4 | 🟠 `zoneinfo` boundary enforcement — `core/time.py` UTC-only API; `pandas_market_calendars` v5+ for NYSE half-days | not started | research stream 2 |
| E5 | 🟠 Verify-all framework (Phase R3) — 8-stage: unit + py_vollib + property + data-quality + page-render + backtest + visual + perf, `make verify-all` < 5 min | partial (7 stages) | `docs/process/MASTERPLAN_TO_PERFECTION.md:234-256` |
| E6 | 🟡 User-journey timer (Phase R6) — Playwright wall-clock from "Lab open" → "PDF download", p95 < 90s gate | not started | `docs/process/MASTERPLAN_TO_PERFECTION.md:295-298` |
| E7 | 🟡 Pages stabilisation (Phase R7) — Onboarding `@st.cache_data(ttl=3600)`, Rotation debug, ml_signal NaN suppression | not started | `docs/process/MASTERPLAN_TO_PERFECTION.md:300-303` |
| E8 | 🟡 `pip-audit --strict` fail-on-critical (currently warn-only) | pending v0.5.0 J | plan |
| E9 | 🟡 SBOM via `cyclonedx-py` — supply-chain provenance for live capital | not started | plan |
| E10 | 🟡 Healthchecks.io heartbeat wired — already stubbed in `scheduler/jobs.py`; needs URL + dashboard | scaffold | `volscope/scheduler/jobs.py` |
| E11 | 🟢 Live intraday IV streaming via WebSocket | non-goal v1 | `memory/roadmaps/giga-master.md` |

**v0.6.0 target:** E1 + E2 + E3 + E4. Lockdown + safety net.

---

## F. Documentation / Onboarding / Product

| ID | Item | Status | Source |
|---|---|---|---|
| F1 | 🟠 CLAUDE.md trim to ≤220 lines — move path-scoped content to `.claude/rules/{analytics,ui,persistence}.md` | pending v0.5.0 A | plan |
| F2 | 🟠 MATHEMATICAL_FOUNDATIONS.md — LaTeX + Hull/QuantLib citations + known limits | not started | A10 above |
| F3 | 🟡 Onboarding tour of top-5 pages — `st.dialog` modal + driver.js overlay | not started | C3 above |
| F4 | 🟡 In-page glossary tooltips — IV / IVR / IVP / VRP / Greeks on hover | not started | C2 above |
| F5 | 🟡 VOLSCOPE_AGENT_HANDOFF.md refresh — add Validation Framework + Phase 2.5 readiness | not started | `docs/process/MASTERPLAN_TO_PERFECTION.md:305-307` |
| F6 | 🟢 GOING_PUBLIC_CHECKLIST.md gate run — before MIT flip; audit log review, community readiness | gated | `docs/decisions.md:67-78` |
| F7 | 🟡 Per-page docstrings consistent — every Streamlit view starts with a 5-line "What this page is" docstring | partial | scan of `volscope/ui/views/*.py` |

**v0.6.0 target:** F1 + F2. Both gate everything else conceptually.

---

## G. `.claude/` Operating System (v0.5.0 in flight)

| ID | Item | Status | Source |
|---|---|---|---|
| G1 | 🟠 7 subagents in `.claude/agents/` — signal-engineer ✅, risk-auditor ✅, test-author ✅; pending: code-reviewer, security-reviewer, observability-engineer, doc-writer | in flight v0.5.0 G | plan |
| G2 | 🟠 10 skills in `.claude/skills/` — BSM, IV solver, HV estimators, regime, composite, audit-chain verifier, DuckDB migrations, IBKR adapter, paper engine, kill switch | pending | plan |
| G3 | 🟠 5 slash commands — `/morning-standup`, `/pre-merge-check`, `/full-review`, `/restore-drill`, `/audit-chain-verify` | pending | plan |
| G4 | 🟠 5 path-scoped rules — analytics, ui, persistence, live-trading, secrets | pending | plan |
| G5 | 🟡 **`/full-review` 5-agent panel** — parallel subprocess invocation, JSON `ReviewArtifact` schema with `schema_version`, aggregator + dedupe on (file, line, category), PASS/REVISE/REJECT loop max 3 iterations | research-only | research stream 2 |

**v0.6.0 target:** G5 (the real implementation; v0.5.0 just defines).

---

## H. Strategy / Feature Ideas (mentioned but never built)

| ID | Item | Status | Source |
|---|---|---|---|
| H1 | 🟢 Strategy Recommender module | anti-feature | `docs/process/MASTERPLAN_TO_PERFECTION.md:327` |
| H2 | 🟡 Cross-Asset Hedge Engine (`cross_asset_hedge.py`) — half-finished | parked | `docs/process/MASTERPLAN_TO_PERFECTION.md:327` |
| H3 | 🟡 Earnings IV-crush distribution per regime | enhancement | `memory/roadmaps/early-roadmap.md:91-99` |
| H4 | 🟢 Term-structure chart on Scope (iv_30d vs iv_60d) | nice-to-have | `CLAUDE.md:131` |

---

## Known Technical Debt (always-on Gotchas — keep CLAUDE.md current)

| Item | File:Line | Mitigation |
|---|---|---|
| Plotly fillcolor rejects 8-char hex | `CLAUDE.md:247` | `rgba()` helper at `volscope/ui/styles/theme.py:15` |
| DuckDB exclusive lock | `CLAUDE.md:251` | `make unlock`; UI is read-only; bot is sole writer |
| `ib_async` clientId=0 visibility | `CLAUDE.md:258` | Bot uses IDs ≥1 to stay isolated from manual GUI |
| HMM regime fit needs ≥252 days | `CLAUDE.md:261` | Raise on shorter; backtest awareness |
| Yahoo IV rate-limited (~360/h/IP) | `CLAUDE.md:272` | EOD only; respect caps |
| iCloud File Provider stall | `CLAUDE.md:266` | Project at `~/Desktop/VolScope`; `keep_warm.sh` |

---

## Recommended v0.6.0 → v1.0 sequence

### v0.6.0 — Math foundations + UX + ops (5-7 hours)
- A3, A4, A5, A9, A10 — math validation full sweep
- B2, B3, B4, B5 — wire scheduler handlers + alerts
- C1, C2, C3, C13 — UI productisation
- D6, D7 — unblock backtest data foundation
- E1, E2, E3, E4 — branch protection + backup + NTP
- F1, F2 — CLAUDE.md trim + math foundations doc
- G5 — `/full-review` 5-agent panel real

### v0.7.0 — Backtest validation gate (4-6 hours)
- D1, D2, D5 — vectorbt + optopsy + CPCV + Bootstrap CI
- D3, D4 — slippage calibration + survivorship hardening
- D8, D9 — ML classifier + walk-forward retrain
- D10, D11 — HMM real-history training + label-stability
- E5 — verify-all 8-stage
- A1, A2 — extend goldens to 100+; full property suite

### v0.8.0 — Live IBKR canary (8-12 weeks)
- B1 — full ib_async client (Watchdog, semaphore, BAG, walk-price)
- B6 — 30-day paper run + 8-path fire-drill
- E6, E7, E8 — operational hardening
- Go-live gate verification per `config/risk-thresholds.yaml`
- 10% capital ramp → 25% → 50% → 100% over 12 weeks

### v0.9.0 — Performance & UX turbo (3-4 hours)
- C4, C5, C6, C7, C8, C9, C10, C11, C12, C14 — full UX polish
- E10 — Healthchecks.io live
- F3, F4 — onboarding tour + glossary

### v1.0 — Public flip (when GOING_PUBLIC_CHECKLIST gates clear)
- F6 — MIT LICENSE swap
- B7, B8, B9 — advanced strategies (SVI, GEX, calendars, dispersion)
- E9 — SBOM
- H2 — finish cross-asset hedge engine if business case clear

---

## Estimated total to v1.0

- v0.6.0: 7h
- v0.7.0: 6h
- v0.8.0: 8-12 weeks (real-money paper validation)
- v0.9.0: 4h
- v1.0: 1 day

**Critical path:** v0.6.0 + v0.7.0 + v0.8.0 = ~13h of coding + 8-12
weeks of paper-trading validation. That's the masterpiece.
