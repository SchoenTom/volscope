# ADR-0005: 21-DTE mechanical close for short-vol trades

## Status

Accepted — 2026-05-14.

## Context

For short-premium / short-vol trades (iron condors, short strangles,
credit spreads), the question is: when do you exit?

Three families of rule:

1. **Hold to expiration** — capture every penny of theta. POP looks
   highest on paper.
2. **Profit target only** — close at X% of max profit, ignore time.
3. **Profit target + mechanical close on DTE = N** — close at 50% PT
   OR at DTE ≤ 21, whichever fires first.

The 21-DTE rule is the canonical tastytrade Market Measures finding:
**gamma is 3-5× higher inside 21 DTE** than in the 45-DTE entry zone.
That gamma compresses your profit window AND magnifies losses on
adverse moves. The probability-weighted EV inside 21 DTE is
*lower* than outside, even though the absolute remaining premium
looks tempting.

Empirical confirmation:

- tastytrade 4,872 SPY iron-condor trades (2005-2019): held to
  expiration = 64% win rate, 27 days in trade. **Managed at 50% PT +
  21-DTE close = 82% win rate, 14 days in trade.**
- Project Finance 71,417 trades: 16Δ/5Δ IC at 30-60 DTE entry,
  50-75% PT optimal.
- DTR Trading 96,624 SPX trades: stops actually HURT long-term
  performance; the 21-DTE mechanical close is the protective rule.

## Decision

Every short-vol strategy in `config/strategies.yaml` includes
`dte_exit: 21` as a non-negotiable parameter. The state machine
auto-transitions MANAGED → CLOSING when DTE ≤ 21, regardless of P&L.

## Consequences

- **Positive — sharper win rate**: 64% → 82% on the tastytrade dataset.
- **Positive — capital recycling**: 14 days in trade vs. 27 means
  ~2× capital turnover per year.
- **Positive — drawdown smoothing**: closing before the gamma zone
  prevents the worst single-trade outcomes.
- **Negative — foregone theta**: ~half the remaining premium left
  on the table per trade. Accepted as the cost of bounded risk.
- **Negative — earlier slippage**: closing more often = more bid-ask
  haircuts. The slippage model in `config/risk.yaml` accounts for
  this; backtest validation in Phase 3 will confirm net edge survives.

## What this means in code

- `volscope/lifecycle/machine.py` (Phase 2): MANAGED → CLOSING
  transition condition includes `dte_remaining <= 21`.
- `volscope/strategies/*.py` (Phase 2+): every short-vol strategy
  must set `dte_exit: 21` in its config block; the validator rejects
  any short-vol config that omits it.

## Citation

- tastytrade Market Measures research on gamma in the final 21 days.
- Cohen & Donohue (2024) "Active management of iron condors:
  78-83% realized win rate."
