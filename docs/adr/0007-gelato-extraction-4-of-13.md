# ADR-0007: Gelato Regime-Engine — extract 4 ideas, reject 9

## Status

Accepted — 2026-05-15.

## Context

The operator surfaced an extended prompt synthesising VolScope-
relevant takeaways from the open-source [Gelato Market-Making
Engine with Regime-Change
Detection](https://github.com/gelatotrade/Market-Making-Engine-Regime-Change-).
The prompt proposed 13 distinct conceptual transfers ranging from
multi-state HMM regime detection (high-value) to animated 3D
P&L surfaces driven by Plotly frames (high-cost, low-feasibility on
our stack).

This ADR records which ideas were adopted into v0.9.0 and which were
rejected, with reasoning, so the next operator iteration starts from
the same decision frame rather than re-litigating the trade-offs.

## Decision

**Adopt 4 of the 13 proposals; reject 9.** Shipped as v0.9.0:

### Adopted

1. **Statistical validation gauntlet** — `volscope/research/`.
   `t_test_sharpe`, `block_bootstrap_sharpe` (Künsch 1989 moving-block,
   Politis-White 2004 block-length heuristic), `permutation_test_alpha`
   (Fisher 1935), `deflated_sharpe_ratio` (Bailey & López de Prado
   2014 eq. 12). Orchestrated by `walk_forward.run_gauntlet`.
   Surfaced via the new **Research** page in the UI.
2. **6-state Vol Regime + Crisis tier** — `volscope/analytics/vol_regime.py`.
   `hmmlearn.GaussianHMM(n_components=5)` over a 6-feature input
   (`ivr_z, iv_hv_spread_z, term_slope, vix_level, vix_z, rv_z`),
   re-mapped by IV-rank-richness to stable labels
   `VOL_CRUSHED → CHEAP → FAIR → RICH → EXTREME`. A hard-coded
   `VOL_CRISIS` override fires when VIX > 40 OR |IV-HV spread| > 15
   vol points. Persisted as new daily_vol columns via migration 008.
3. **3D Payoff Surface in Options Lab** — `_render_payoff_surface`.
   Plotly `go.Surface(spot, days_remaining, P&L)` for the current
   candidate trade. Vertical translucent plane at current spot;
   horizontal plane at zero P&L (breakevens = surface-plane
   intersection). Contour projection on the floor.
4. **Persistent regime header strip** —
   `volscope/ui/components/regime_header.py`. 32 px top bar on
   Command Center, Discover, Scope, Pre-Trade, Bot — chip-coloured
   regime label, signal text, VIX level, universe IVR median, last-
   scrape date. Single source of truth for "what mood is the market
   in right now."

### Rejected

5. **Live IV surface (strike × tenor × IV)** — VolScope's EOD data
   has 4 tenors and ~3-5 strikes per tenor at best. A surface built
   from ~12 sparse points is a *fake* reichhaltigkeit, not the real
   chain-density surface Gelato gets from a live feed. Defer until
   we have live chain ingestion.
6. **IV term-structure ribbon (date × tenor × ATM IV) as 3D** —
   same sparsity problem. A 2D multi-line is strictly more readable.
7. **IV-rank surface (ticker × tenor × rank) as 3D** — the v0.8.0
   Treemap already conveys this signal at higher density.
8. **Animated morphing Surfaces via Plotly frames** — Plotly + Streamlit
   re-renders the entire WebGL canvas per frame. Gelato's smooth
   animation works because they use Three.js natively on a C++
   server. We'd ship a lagging imitation.
9. **Regime-probability landscape as 3D stacked area** — pseudo-3D
   stacked areas are unreadable. Standard 2D stacked area strictly
   better.
10. **Bottom regime-timeline scrubber on every page** — click-to-
    time-travel needs a custom JS component (not available in
    Streamlit nativly). Plus the additional Plotly heatmap per page
    would amplify the rerun overhead the operator already complained
    about on Pre-Trade.
11. **5×5 regime transition heatmap with cyan-dashed current-state
    highlight** — ~600 trading days per ticker yields ~12 transitions
    per state-pair. Statistically too thin to estimate the matrix
    stably. Re-evaluate once universe-wide HMM has ≥ 2000 days × 30+
    tickers of training data.
12. **Synthetic surface library `dome() / crater() / ripple()`** —
    developer tool, not product. Belongs in `tests/` if anywhere.
13. **IBKR fee model in the backtest** — premature. Phase-4 live
    trading is still kill-switch-blocked. Re-evaluate together with
    live wiring in v1.0.0.

## Consequences

- **Positive — credibility.** The 4-test gauntlet is the single
  biggest force-multiplier on operator trust: every signal claim
  ("65% mean-reversion hitrate") now has a falsifiability gate.
  This moves VolScope from "another retail tool" to "academically-
  defensible vol research workbench."
- **Positive — risk management.** The Crisis tier blocks long-vega
  entries during vol-explosion regimes even if individual names
  look cheap. Lost-cause trades into 2020-March-style events get
  the right "DO NOT" treatment automatically.
- **Positive — visualisation.** The 3D Payoff Surface gives the
  operator the full path of P&L from today to expiry, not just the
  expiry-payoff curve. Time-decay structure becomes visible.
- **Positive — context anchor.** The persistent regime header
  prevents the operator from acting on a "CHEAP" label on Discover
  while the market is in Crisis mode. The mood is always one
  glance away.
- **Negative — `hmmlearn` is now a hard dep.** Already in the
  project's optional-extras list per `CLAUDE.md` boot sequence;
  promoted to a hard dep in `requirements.txt` via this release.
- **Negative — research page is computationally heavy.** The
  4-test gauntlet across 10 000 bootstrap + permutation resamples
  takes ~10-30 s on the operator laptop. Streamlit-spinner
  feedback is shown, but the page is intentionally non-cached
  because the operator picks signal definitions interactively.

## Rejection rationale (the meta-decision)

The Gelato repo is genuinely a methodological masterclass — but
75% of it is C++ and the visual cinematography rides on a Three.js
+ WebGL stack we don't have. **The discipline transferred is
exactly the statistical-validation hurdle the prompt highlights.**
The animated surfaces and bottom-scrubbers look beautiful *because*
they live in a stack with sub-100ms render budgets; transplanted
into Streamlit they would look worse than our existing static
charts.

VolScope's job is not to copy the Gelato animation pipeline. It's
to inherit the *discipline of proving every signal claim*. v0.9.0
ships that discipline.

## References

- Bailey, D. H., & López de Prado, M. (2014). The Deflated Sharpe
  Ratio: Correcting for Selection Bias, Backtest Overfitting, and
  Non-Normality. *Journal of Portfolio Management*, 40(5), 94-107.
- Künsch, H. R. (1989). The Jackknife and the Bootstrap for General
  Stationary Observations. *The Annals of Statistics*, 17(3),
  1217-1241.
- Politis, D. N., & White, H. (2004). Automatic Block-Length
  Selection for the Dependent Bootstrap. *Econometric Reviews*,
  23(1), 53-70.
- de Kempenaer, J. (2005). The Relative Rotation Graph methodology
  (used at Bloomberg / Reuters / StockCharts).
