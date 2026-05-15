# VolScope Launch Checklist

> Gate for promoting paper-bot to **live IBKR orders** (Phase 4 of the
> roadmap). Every item must be `[x]` before `OPERATOR_APPROVED=yes`
> can be applied to `config/risk-thresholds.yaml`.

Owner: SchoenTom (operator). Reviewer: none yet (private repo).

---

## CI + Code Health

- [ ] CI green on the last 10 commits to `main` (`gh run list --branch main --limit 10`)
- [ ] Coverage ≥ 60 % (`pytest --cov=volscope --cov-report=term` floor)
- [ ] `ruff check volscope/ tests/` returns 0 findings
- [ ] `mypy volscope/` returns 0 errors on the strict-typed modules
- [ ] `gitleaks detect --no-banner --redact` clean on full history
- [ ] `pip-audit` shows 0 high/critical CVEs in `requirements.txt`

## Hardening Phases (memory state cross-check)

- [ ] Phase 0 — Stabilization: working tree clean, CI green
- [ ] Phase 1 — Data Freshness: NYSE-aware FreshnessReport + banner wired everywhere
- [ ] Phase 2 — Cross-Page Consistency: `volscope.analytics.iv_thresholds` is the single source of truth, no hardcoded percentile cutoffs
- [ ] Phase 3 — Performance: 0 N+1 DB patterns in `volscope/ui/`
- [ ] Phase 4 — Symbol-Type gating: VOL_INDEX banner on Scope, VXX contango warning on Scope (this PR)
- [ ] Phase 5 — Bug Sweep: `st.metric` ban enforced by `bug_detector.py`
- [ ] Phase 6 — HV Term Structure: hv_yz_30d + iv_hv_spread_matched populated
- [ ] Phase 7 — Methodology Property Tests: Hypothesis round-trip + py_vollib golden tests passing
- [ ] Phase 8 — Pre-Launch Audit: this checklist filed + signed + PRE_LAUNCH_REPORT.md GO

## Data Layer

- [ ] DuckDB Backup Drill: `make backup` then `make restore-drill` exits 0
- [ ] `bot_audit_chain` verify: `make audit-verify` returns 0 violations
- [ ] Migration registry up-to-date (`009_bot_trades_actor.sql` applied)
- [ ] `volscope.db` size monitored; growth < 10 MB/week sustainable
- [ ] Latest scrape ≤ 24 h old (`make scrape` last-run timestamp)

## Configuration + Secrets

- [ ] `.env` present locally with all required keys filled
  - [ ] `IBKR__HOST`, `IBKR__PORT`, `IBKR__CLIENT_ID`, `IBKR__ACCOUNT`
  - [ ] `TELEGRAM__BOT_TOKEN`, `TELEGRAM__CHAT_ID` (alerts channel)
  - [ ] `FINNHUB_API_KEY` (earnings)
  - [ ] `VOLSCOPE_BACKUP_KEY` retrievable from macOS Keychain
- [ ] `config/risk-thresholds.yaml` reviewed in a Sunday 18:00 ET window
- [ ] 90-day cooldown timer documented in `docs/decisions.md` for last threshold edit

## Paper Trading Track Record

- [ ] ≥ 100 closed paper trades in `bot_trades` table
- [ ] Win-rate + median return reported in `docs/PRE_LAUNCH_REPORT.md`
- [ ] Max drawdown over the paper period within risk limits
- [ ] No `try: except: pass` swallowed a real bot failure (audit log review)

## IBKR Integration

- [ ] `ib_async` Watchdog tested under simulated Gateway restart (3 min outage)
- [ ] BAG combos open + close on a paper account
- [ ] Walk-price implementation: bid + 1 tick × 5 retries, then mid
- [ ] Reconciler: nightly diff of `bot_trades` vs IBKR statement returns 0 deltas
- [ ] Rate limit: `asyncio.Semaphore(40)` enforced on all IBKR calls

## Kill-Switch Paths (all 8 must be exercised)

- [ ] Manual Telegram `/halt` command
- [ ] Daily loss limit (`-2 %` portfolio NAV)
- [ ] Weekly loss limit (`-5 %` portfolio NAV)
- [ ] Open-position concentration (> 25 % single ticker)
- [ ] Net delta exposure (> ±$25 k unhedged)
- [ ] Vega exposure (> $5 k absolute)
- [ ] Gateway disconnect (3× reconnect failed)
- [ ] Audit-chain hash break (any single mismatch)

## Regime + Model Health

- [ ] HMM regime fit on ≥ 252 days of OHLCV
- [ ] 6-state regime classifier returns sensible posteriors on SPY last 30 days
- [ ] Crisis-override (`VIX>40` OR `|IV-HV|>15`) triggers within one bar of true condition
- [ ] GARCH(1,1) on 5 main tickers converges (no failed fits in last week)

## Documentation + Hand-off

- [ ] `docs/PRE_LAUNCH_REPORT.md` filed with GO / NO-GO / CONDITIONAL
- [ ] `WELCOME-AGENT.md` reflects current canonical entry point
- [ ] `progress.md` last 5 sessions narrate the launch ramp
- [ ] `docs/decisions.md` has a sign-off ADR (`ADR-XXXX go-live ramp`)

---

## Signature

Operator: ______________________  Datum: __________

> By signing, the operator confirms that all items above are checked
> AND that a 12-week graduated ramp (10 % → 25 % → 50 % → 100 %) is
> the planned exposure path.
