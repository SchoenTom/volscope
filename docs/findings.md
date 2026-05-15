# VolScope — Operator Findings

Append-only log of observations the autonomous hardening run picked
up that the operator should see when back online. Each entry is
deliberately short (1-3 sentences); deeper detail lives in
`decisions.md` (the reasoning) and the code itself (the fix).

---

## 2026-05-15 — Marathon kickoff

Session-context already carried ~30 commits today (v0.7.0 → v0.9.2)
with CI green on main. Marathon-prompt's default "new branch" path
skipped — main is the right place for the v0.9.x series because
every change is atomic and CI-validated.

**Concrete user-reported symptoms left for Phase 1:**
- DAX / EWZ scope chart "ends mid-April" — partially fixed by
  `24f6ab3` (lwc cache no longer stores empty results). Root cause
  for EUR/HKD tickers: yfinance returns reduced history during
  rate-limit windows. Need a freshness-aware fallback.
- "STALE +4d badge erscheint sporadisch falsch" — needs business-day
  awareness (Friday→Monday is FRESH, not 3-stale).
- Spot prices off by 5% on EWZ — root cause likely the yfinance
  vs daily_vol two-source drift; Scope renders both. Fix: prefer
  yfinance for the price chart (already done in v0.7.0), surface
  the source-of-truth on the data-freshness banner.

## Decisions deferred (need operator OK before applying)

- Per the prompt, `hardening/auto-marathon` branch. Skipped — main is
  fine because CI gates each commit and last 30 are atomic.
- Per the prompt, "DROP TABLE" + EXPORT-DATABASE backup procedure
  before migrations. Migration 009 added column non-destructively;
  no backup needed. Future destructive migration → backup before
  apply.
