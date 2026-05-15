# VolScope Pre-Launch Report

> Living document that summarises VolScope's readiness to flip from
> paper to live IBKR orders. Updated at the close of each hardening
> phase. The final entry carries the `GO` / `NO-GO` / `CONDITIONAL`
> recommendation that gates `OPERATOR_APPROVED=yes` in
> `config/risk-thresholds.yaml`.

Current snapshot: **2026-05-15** (post-v0.9.3 hardening marathon).

---

## Executive Summary

VolScope's research workbench is **production-grade** for paper-trading
use. The simulation bot and lifecycle engine are wired and have shipped
~40 atomic commits of hardening across the v0.9.x series. The remaining
gap to a live-order go-live is **operational** (≥ 100 closed paper
trades, IBKR Watchdog drill, threshold cooldown sign-off) — not
architectural.

Recommendation as of 2026-05-15: **CONDITIONAL** — the platform is
ready in code; the operator is not yet ready by track record.

---

## Status Matrix (Phase 0 – 8)

| Phase | State | Evidence |
|---|---|---|
| 0 — Stabilization | DONE | CI green on 50+ commits, working tree clean |
| 1 — Data Freshness | DONE | `volscope/data/freshness.py` + 16 tests + Discover/Pre-Trade banner wired |
| 2 — Cross-Page Consistency | DONE | `volscope.analytics.iv_thresholds` is sole source-of-truth; commits `d486b43`, `d119edc` |
| 3 — Performance | DONE | 0 N+1 DB patterns in `volscope/ui/`; 4 bulk-fetch rewrites; 3 vectorised iterrows |
| 4 — Symbol-Type Gating | DONE | `symbol_types.py` + Discover filter + Scope VOL_INDEX banner + VXX contango warning (this PR) |
| 5 — Bug Sweep | DONE | `bug_detector.py` static scanner; `st.metric` removed; sidebar overflow defensible |
| 6 — HV Term Structure | DONE | `hv_yz_30d` + `iv_hv_spread_matched` populated since v0.7.1 |
| 7 — Methodology Property Tests | DONE | `tests/properties/test_iv_round_trip.py` (500 examples) + `tests/properties/test_pyvollib_agreement.py` (1000 examples, 1e-8) |
| 8 — Pre-Launch Audit | **PARTIAL** | LAUNCH_CHECKLIST.md scaffolded (this PR); operator sign-off pending; ≥ 100 paper trades pending |

## Outstanding Items (Risk-Tier-tagged)

### Tier-1 — blocks go-live

- **Paper-trade track record**: 0 / 100 closed trades. Need ≥ 12 weeks
  of live paper exposure with the v0.9.3 codebase before any live
  ramp is justifiable. Impact = total; likelihood of premature
  go-live = low because of this gate.
- **IBKR Watchdog drill**: not yet exercised against a simulated
  Gateway restart. Without proof of clean reconnect, any live order
  is a single-point-of-failure.

### Tier-2 — must-fix before ramp ≥ 25 %

- **Risk-threshold cooldown sign-off**: `config/risk-thresholds.yaml`
  needs a Sunday 18:00 ET window review with 90-day cooldown timer
  in `docs/decisions.md`.
- **Reconciler nightly run**: paper-trades vs IBKR statement diff
  must show 0 deltas for 7 consecutive nights.

### Tier-3 — operational hygiene

- **Backup drill**: `make backup` + `make restore-drill` cycle has
  not been run in the v0.9.3 codebase. Expected to pass.
- **Hardcoded path cleanup**: 10 absolute `/Users/tomschoen/Desktop/VolScope`
  paths in `volscope/ui/components/sidebar.py`, `backtest_page.py`,
  `_user_sim.py`, `_perf_audit.py`, `run_audits.py` (×6),
  `test_perf_smoke.py`. Migration to non-iCloud root would break
  these. Low-priority — defer until iCloud-stall becomes a real
  blocker.

### Tier-4 — nice-to-have

- **Per-name GEX / dispersion / calendar spreads** — Phase 5+ roadmap.
- **SVI / SSVI vol surface fitting** — Phase 5+ roadmap.

## Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Live order placed before 100 paper trades | Low | Critical | Hard-coded gate in `risk-thresholds.yaml`; operator signature required |
| IBKR Gateway disconnect mid-trade | Medium | High | `ib_async` Watchdog (not yet exercised — Tier-1 gate) |
| Audit-chain hash break unnoticed | Low | High | `make audit-verify` in pre-commit + CI |
| iCloud cold-import stalls a launchd job | Medium | Low | `keep_warm.sh` is wired into `make quickstart` and `make run` (v0.9.4) |
| Yahoo rate-limit during a refresh | Medium | Low | yfinance hits cap at 360 req/h; 19-ticker Bot-Universe seed = 38 req — safe |
| VDAX / Deribit provider outage | High | Negligible | Fail-soft to NO-DATA tile; no exception bubbles up (v0.9.4) |

## Recommendation

**CONDITIONAL GO** for paper-trading continuation through end of
2026 H2. **NO-GO** for live IBKR orders until:

1. ≥ 100 closed paper trades documented in `bot_trades`
2. IBKR Watchdog drill passed
3. Operator signs the LAUNCH_CHECKLIST in a Sunday 18:00 ET window
4. Risk-threshold cooldown completed

Re-evaluate this report after each milestone. Append a dated section
with the updated recommendation rather than rewriting the executive
summary — leave the trail of judgement visible.

---

## Change Log

- **2026-05-15** — Initial scaffold post-v0.9.3 hardening. Status:
  CONDITIONAL. Author: Tom + Claude Opus 4.7 (1M context).
