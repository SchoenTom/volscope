# Roadmap

VolScope evolves through 5 phases. Detail in
[`/memory/roadmaps/bot-masterplan.md`](memory/roadmaps/bot-masterplan.md);
the user-facing summary lives here.

| Phase | Status | Scope | Exit gate |
|---|---|---|---|
| **0 — Stabilise** | ✅ DONE (v0.2.0) | Bug fixes: fillcolor, keyboard ghost, st.metric, heatmap, rotation. | All pages render clean. |
| **1 — Signal engine** | ✅ DONE (v0.2.0) | Factor library, HMM regime scaffold, GARCH, composite scoring, hard-gate filters, ranker, Bot Dashboard. | Daily ranked signal list. |
| **2 — Paper loop** | 🔧 SCAFFOLD (v0.2.0) | State machine, scheduler, kill switch, ib_async stub, preflight, reconcile. | 30+ days running, ≥30 paper trades, all 8 kill paths fire-drilled. |
| **3 — Backtest validation** | ⏳ PLANNED | vectorbt + optopsy + in-house engine, CPCV, slippage calibration. | Match published spintwig SPX IC 45-DTE Sharpe ±0.2. |
| **4 — Go-live ramp** | ⏳ PLANNED | Pass go-live gate (100 trades, Sharpe ≥0.5, DD ≤20%). Ramp 10% → 25% → 50% → 100% over 12 weeks. | 8 weeks live with positive net-of-slippage P&L. |
| **5+ — Advanced** | ⏳ FUTURE | SVI / SSVI surfaces, per-name GEX, calendar spreads, dispersion. | Each strategy ≥6 mo paper before live. |

## What's next after v0.2.0

The agreed agenda is captured in
[`docs/roadmap/5-prompt-sequence.md`](docs/roadmap/5-prompt-sequence.md).
In order:

1. **Prompt 2 — Mathematical validation** (the unglamorous gate that
   separates hobby from production). Hull-reference goldens,
   Hypothesis property tests, edge-case numeric stability.
2. **Prompt 3 — Phase 1 production polish** (HMM training on real data,
   Finnhub earnings adapter, live `st.fragment` refresh, Telegram).
3. **Prompt 4 — Phase 2 production** (wire `ibkr_stub.py` to real
   paper Gateway, BAG combo builder, Watchdog, run 30 days of paper).
4. **Prompt 5 — Performance & UX turbo** (Polars hot paths, fragment
   refresh, Cmd+K palette, keyboard shortcuts).

## How decisions get made

- **Bug fixes / refactors / docs**: open a PR. CI + 1 reviewer.
- **Architecturally significant**: write an ADR
  (`docs/adr/NNNN-short-name.md`). Discuss in the PR.
- **Live-trading impacting**: explicit operator approval in the PR body.
- **Strategy parameter changes**: Sunday 18:00 ET review window, 90-day
  cooldown, backtest required.
