---
name: iv-solver
description: This skill should be used when implementing or reviewing the implied-volatility solver. Newton-Raphson primary, bisection fallback, with arbitrage bounds + Brenner-Subrahmanyam initial guess.
---

# IV solver — Newton-Raphson + bisection

## Goal

Given an option market price, recover the implied volatility σ such that
`bs_price(S, K, T, r, σ, q, option_type) == market_price` within tolerance.

## Initial guess

**Brenner-Subrahmanyam** (1988) approximation — robust for any moneyness:

```
σ₀ ≈ √(2π/T) · (C - max(S·e^(-qT) - K·e^(-rT), 0)/2) / S
```

For an ATM option this collapses to `σ₀ ≈ √(2π/T) · C / S`. Use this
as the Newton-Raphson seed; it's within ~10% of true σ for most cases.

## Newton-Raphson iteration

```
σ_{n+1} = σ_n - (bs_price(σ_n) - market_price) / bs_vega(σ_n)
```

Converges in 3-5 iterations for typical options. Stop when
`|bs_price - market| < 1e-6` or after 50 iterations.

## When Newton-Raphson fails (fall back to bisection)

- Vega is near zero (deep OTM / ITM at extreme T).
- σ wandered into [σ_max, ∞) or (−∞, 0].

Bisection bracket: σ ∈ [0.001, 5.0] for equities. Always converges (50
iterations max).

## Arbitrage bounds — refuse to solve

Before iterating, verify the market price respects these:

```
Call: max(S·e^(-qT) - K·e^(-rT), 0) ≤ C ≤ S·e^(-qT)
Put : max(K·e^(-rT) - S·e^(-qT), 0) ≤ P ≤ K·e^(-rT)
```

If the market price is outside these bounds, **return None** — no σ
exists. Do not iterate; the input is unusable.

## Edge cases

| Input | Return |
|---|---|
| price ≤ 0 | None |
| price < intrinsic (no extrinsic) | None or σ ≈ 0 |
| price > upper arbitrage bound | None |
| T ≤ 0 | None |
| S, K ≤ 0 | None |

## VolScope implementation

- `volscope/analytics/bsm_iv.py` (path may vary)
- Validated round-trip: generate price from known σ → recover σ →
  must agree within 1e-4 (Hypothesis property test, v0.6.0 backlog A3).

## Cross-validation against py_vollib

```python
import py_vollib_vectorized as pvv
ours = newton_raphson_iv(price, S, K, T, r, q, option_type)
theirs = pvv.vectorized_implied_volatility(
    price=price, S=S, K=K, t=T, r=r, flag=option_type[0].lower()
).iloc[0]
assert abs(ours - theirs) < 1e-4
```

## Gotchas

- **Don't use Yahoo's `impliedVolatility` column.** It's not derived
  from the same conventions and is rate-limited. Always compute IV
  ourselves from the bid/ask mid using this solver.
- **Vega floor at 1e-4** in the Newton update step to avoid
  divide-by-zero at σ → 0 (where vega → ∞ analytically but the
  floating-point representation collapses).
- **Initial guess sign:** Brenner-Subrahmanyam returns negative σ if
  the price is below intrinsic; clamp to a small positive (e.g. 0.01)
  before the first iteration.
