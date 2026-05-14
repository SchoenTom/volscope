---
name: VolScope LEAPS Lab — convergence scanner & PYPL anchor
description: Anchor strategy for VolScope's deep-OTM LEAPS scanner. Convergence of three signals (vol mispricing × neglect × reversal) producing concrete deep-OTM call suggestions. (thesis position — outside bot scope) deck is the reference case the system reproduces.
type: project
originSessionId: 8c0ffaad-9d3f-43f4-a15d-4ab42bd90d4c
---
The (thesis position — outside bot scope) / Jan-2029 LEAPS deck ((reference deck — see operator's archive),
2026-05-10 snapshot) is the canonical pattern VolScope's LEAPS Lab page
operationalises. The thesis: vol is mispriced (IV/HV ≈ 0.67, IV-Rank 12,
IV-Pct 29) **and** the name has lagged SPY by ~50pp on a TTM basis **and**
the chart shows a Wave-II base — three independent signals pointing the
same way, which only happens 1–2× per year per ticker.

Where it lives in code:
- `volscope/analytics/leaps_convergence.py` — pure scorer/suggester
  - `compute_mispricing_score(row)` — IV/HV ratio + IV-Rank + IV-Pct, equal weight
  - `compute_neglect_score(hist, benchmark, lookback=252)` — TTM relative-strength gap vs SPY
  - `compute_reversal_score(hist)` — drawdown from 52w high + HV cooling (20d/60d)
  - `compute_convergence(row, hist, benchmark)` → `ConvergenceResult`
  - `suggest_leaps(ticker, spot, iv, dte=730, uplift=0.75)` → `LeapsSuggestion` with Greeks + payoff ladder
  - `rank_universe(latest, histories, benchmark, n)` — wires it all together
- `volscope/ui/views/leaps_page.py` — Streamlit page (registered in app.py + sidebar EXECUTION group)
- `tests/test_leaps_convergence.py` — 15 unit tests covering all components

**Why:** Anomaly detection without a concrete trade output is just
academic. The PYPL deck Operator delivered shows what "actionable" means —
strike, expiry, premium, breakeven, Greek profile, payoff ladder — and
the LEAPS Lab page reproduces that exact format for every ticker that
clears the convergence gate (composite ≥ 65, weights 50/30/20 for
mispricing/neglect/reversal).

**How to apply:** When Operator asks for new "anomaly-driven" features in
VolScope, treat the three-signal convergence pattern as the default
output shape. Single-signal scanners (IV cheap alone, neglect alone)
stay useful as filters, but the headline product is the convergence
view. NKE on the live universe (spot $45.68, suggested strike $80,
premium $2.42, Δ+0.23, ν/% +0.20) is a live PYPL-twin worth tracking.

**Lab v2 (shipped 2026-05-10, autonomous session)** — see `LEAPS_LAB_HANDOFF.md`
in the project root. New artefacts:
- `leaps_sizing.py` — budget → contracts → personalised payoff
- `leaps_scenarios.py` — spot×time matrix + vega-gain + theta runway + risk table
- `leaps_pretrade.py` — liquidity/ER/quality gates + IBKR/Tasty/TR order templates
- `leaps_backtest.py` + `scripts/run_leaps_backtest.py` — walk-forward
- `leaps_pdf.py` — reportlab dossier export, structurally mirrors PYPL deck
- `leaps_watchlist.py` — pin/unpin via `user_settings` JSON
- `leaps_dossier_page.py` — single-ticker UI; trader IA = Header → Sizing → Risk → Instrument → (collapsed) Anomaly/Scenarios/Execution
- `daily_vol` schema gains `convergence_score` + 3 sub-component columns
- `make convergence` + `make backtest-leaps` Makefile targets

Key UX rule the Plan-agent surfaced and the build honors: every BSM-
derived premium renders with a persistent `EST · BSM` chip, because
`options_snapshots` is still empty. Without that chip the page would
silently mislead a trader pasting a model price into IBKR.

DuckDB 1.5.2 quirk found during the build: `SELECT * FROM daily_vol
WHERE date = '<lit>'` returns 0 rows while `SELECT COUNT(*)` returns
the right count. `BETWEEN` works around it. Reflected in
`compute_convergence_daily.py`.
