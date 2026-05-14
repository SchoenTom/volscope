# ADR-0004: Quarter-Kelly position sizing as the production-safe start

## Status

Accepted — 2026-05-14.

## Context

The Kelly criterion (f* = μ/σ²) gives the geometric-growth-optimal bet
size IF the return distribution is well-behaved. For short-premium
options it is **not**:

- Returns are leptokurtic and negatively skewed.
- One outlier (Aug 2024, Feb 2018, Mar 2020) permanently impairs
  growth — non-ergodic.
- Vol-selling on AAPL + MSFT + NVDA + META is effectively one trade —
  Kelly's independence assumption breaks.
- Full Kelly drawdowns can hit 50%+; survival probability collapses.

Turlakov (2016, arXiv:1612.07194) shows full-Kelly breaks down at
Student-t v=4 — exactly the regime options returns live in.

The practitioner standard for fat-tailed equity strategies is
**0.25× Kelly** initially, with a path to **0.5× Kelly** only after
6 months of live results matching backtest within 1 standard error.

## Decision

Start production at `kelly_fraction = 0.25`. Capture in
`config/risk.yaml` as a top-level constant:

```yaml
position_sizing:
  kelly_fraction: 0.25
  max_risk_per_trade_defined: 0.02
  max_risk_per_trade_undefined: 0.01
  ...
```

Promote to 0.5 ONLY through the standard parameter-change process
(Sunday 18:00 review window, 90-day cooldown, walk-forward backtest
required, written acceptance of higher DD probability).

## Consequences

- **Positive — drawdown survivability**: half-Kelly captures ~75% of
  expected growth at ~50% of drawdown. Quarter-Kelly is even more
  conservative.
- **Positive — psychology**: smaller losses keep the operator from
  panic-reverting the strategy after a bad week.
- **Positive — error margin**: covers the gap between historical-edge
  estimate and true edge (which is always lower than backtested).
- **Negative — undertrading**: foregoing expected growth. Acceptable
  given we are early-paper-stage.

## Promotion gate

Move 0.25 → 0.5 requires ALL of:

- ≥ 6 months of live (not paper) trading.
- Realized Sharpe within ±0.3 of paper Sharpe.
- Max drawdown within ±5pp of expected.
- No single losing trade > 1.5× expected max loss.
- Walk-forward backtest passes at 0.5×.
- Operator pre-commits in writing: "I accept 30-40% DD probability".

## Citation

- Turlakov, M. (2016). "On the Kelly criterion and continuous betting."
  arXiv:1612.07194.
- Vince, R. (2011). "The Leverage Space Trading Model."
- López de Prado, M. (2018). *Advances in Financial Machine Learning*,
  Ch. 14 ("Backtest Statistics").
