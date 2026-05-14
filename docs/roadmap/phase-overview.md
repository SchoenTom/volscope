# Phase Overview

Single-page table of the bot-build phases. Detail lives in
[`/memory/roadmaps/bot-masterplan.md`](../../memory/roadmaps/bot-masterplan.md).

| Phase | Status | Scope | Exit gate |
|---|---|---|---|
| **0 — Stabilise** | ✅ DONE (v0.2.0) | Fix 5 known dashboard bugs (fillcolor, keyboard, st.metric, heatmap, rotation). | All pages render clean. |
| **1 — Signal engine** | ✅ DONE (v0.2.0) | Config YAMLs, factors / composite / filters / ranking, HMM regime scaffold, GARCH wrapper, Bot Dashboard. | Daily signal list, regime gauge, alerts deliver. |
| **2 — Paper loop** | 🔧 SCAFFOLD (v0.2.0) → IN PROGRESS | ib_async stub + state machine + APScheduler + kill switch + preflight + reconcile. Live IBKR wiring + alert delivery in Phase 2.5. | 30+ days running, ≥30 paper trades, state machine never desyncs, kill-switch fire-drill ×3. |
| **3 — Backtest validation** | ⏳ PLANNED | Three-tier stack: vectorbt + optopsy + in-house event engine. Slippage calibration vs spintwig. CPCV in CI. | Match published spintwig SPX IC 45-DTE Sharpe within ±0.2. |
| **4 — Go-live ramp** | ⏳ PLANNED | Pass go-live gate (100 trades, Sharpe ≥0.5, DD ≤20%, win rate ≥65%). Ramp 10% → 25% → 50% → 100% over 12 weeks. | 8 weeks live with positive net-of-slippage realized P&L. |
| **5+ — Advanced** | ⏳ FUTURE | SVI per-slice, SSVI joint surface, per-name GEX from chain data, calendar spreads on backwardation, dispersion plays. | Each new strategy ≥ 6 months paper before live. |

## What gates Phase 1 → Phase 2 transition?

- Phase 1 ✅: all signal-engine scaffolds shipped + tested.
- Phase 2 entry: deliverable is the **scaffold** of state machine,
  scheduler, kill switch — not live IBKR orders.
- Phase 2 exit: 30+ days paper-traded with the full loop wired up.

## What's in v0.2.0 specifically

- `volscope/signals/{factors,composite,filters,ranking}.py`
- `volscope/analytics/{regime,garch}.py`
- `volscope/execution/ibkr_stub.py`
- `volscope/lifecycle/machine.py`
- `volscope/scheduler/jobs.py`
- `volscope/risk/kill_switch.py`
- `volscope/persistence/migrations/001_init.sql` + `002_killswitch.sql`
- Bot Dashboard page (read-only)
- Memory + docs reorganisation
- Full git-hygiene stack (CI, gitleaks, ADRs, dependabot)
