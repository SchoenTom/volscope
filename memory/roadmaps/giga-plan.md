---
name: VolScope Giga-Plan (Sector Rotation + Capital Flow + ML)
description: Approved 4-phase plan to evolve VolScope from descriptive dashboard to predictive trading tool — status, scope, risks
type: project
originSessionId: 73e04a0d-97ea-440d-b8de-90c927267bb9
---
**Status as of 2026-04-20:** Plan approved by Operator. Implementation started in a prior session but ran out of 1M-context mid-Phase-1 (hit "Extra usage required"). The plan document lives at `/Users/tomschoen/.claude/plans/iterative-hugging-thimble.md` — read it before proceeding.

**Why this plan exists:** Operator asked whether VolScope could go beyond descriptive ("here's where IV is") to predictive ("here's what's coming next and what to buy"). The plan answers with four phases, all on free data (Yahoo + FRED).

**Phase 1 — Sector Rotation Engine (Tag 1-2):**
- New `sector_daily` DuckDB table (median IV/perc/HV, PCR, OI, regime)
- `analytics/sector_rotation.py` — aggregates, momentum, HOT/COLD/NEUTRAL classification, Markov-like transition matrix ("if Energy heats, Industrials follow in ~15d 68%")
- New Rotation page with heatmap, regime strip, rotation predictions

**Phase 2 — Capital Flow Proxy (Tag 2-3):**
- 5 proxy components derivable from existing columns: OI change rate, Volume/OI ratio (low = institutional), PCR shift z-score, IV-HV divergence, volume clustering
- Composite 0-100 flow score per sector
- Divergence alerts (flow rising but price flat = accumulation signal)

**Phase 3 — ML Mean-Reversion Model (Tag 3-6):**
- Labels: `reverted_h ∈ {0,1}` if iv_percentile crosses 50 within t+1..t+h (h ∈ {20,40,60})
- 15 features: iv_percentile, iv_rank, iv_hv_spread, hv_ratio_20_60, crowded_score, days_to_earnings, sector_regime_z, term_structure, pcr_z, volume_z, oi_z, iv_ma_ratio, iv_velocity_5d, spot_return_20d, vix_proxy (SPY iv_percentile)
- XGBoost classifier, max_depth=5, n_estimators=200, Platt scaling for calibrated probabilities
- Scorer filters to iv_percentile<25 AND score>60

**Phase 4 — Backtest + Validation (Tag 6-8):**
- Walk-forward: train [0,252d], test [252,315d], roll 63d
- P&L simulation: ATM straddle entry, daily repricing, exit on percentile>50 OR stop-loss -50% OR 60d max hold
- Metrics: Win rate, Sharpe, Max DD, Profit Factor
- Baselines: naive (always buy if perc<20) + random — ML must beat both

**Why:** Operator has a gesperrt (blocked) IBKR account that can still deliver 15-min delayed market data if the IBKR stub is wired. But the plan assumes Yahoo+FRED to stay reliable without the blocker.

**How to apply:** If Operator says "continue the ML bot" or "start the giga plan" or "sector rotation," resume from the approved plan — don't re-plan from scratch. Check which Phase 1 files already exist (currently: none of `sector_rotation.py`, `capital_flow.py`, `ml/*`, `rotation_page.py`, `flow_page.py`, `ml_page.py`, `backtest_page.py`). New deps needed: `xgboost>=2.0`, `scikit-learn>=1.3`, `statsmodels>=0.14` — already installed on system per prior session. Risk mitigations in the plan doc (overfitting, lookahead, survivorship, proxy-IV artifacts) are non-negotiable.
