---
name: black-scholes-pricing
description: This skill should be used when authoring or reviewing any Black-Scholes-Merton price / Greeks code. Contains the formulae, sign conventions, q-dividend treatment, and the validated cross-check points against Hull and py_vollib.
---

# Black-Scholes-Merton — pricing + Greeks reference

VolScope uses continuous-dividend (q-continuous) convention throughout.

## Formulae

For a European option on an underlying paying continuous dividend yield q:

```
d1 = (ln(S/K) + (r - q + σ²/2)·T) / (σ·√T)
d2 = d1 - σ·√T

Call: C = S·e^(-qT)·N(d1) - K·e^(-rT)·N(d2)
Put : P = K·e^(-rT)·N(-d2) - S·e^(-qT)·N(-d1)
```

Where `N(·)` is the standard normal CDF.

## Greeks

```
Delta_call = e^(-qT) · N(d1)
Delta_put  = e^(-qT) · (N(d1) - 1)   = e^(-qT)·N(d1) - e^(-qT)
Gamma      = e^(-qT) · n(d1) / (S · σ · √T)
Vega       = S · e^(-qT) · n(d1) · √T     (per 1.00 change in σ; divide by 100 for "per 1%")
Theta_call = -S·e^(-qT)·n(d1)·σ/(2·√T) - r·K·e^(-rT)·N(d2) + q·S·e^(-qT)·N(d1)
Theta_put  = -S·e^(-qT)·n(d1)·σ/(2·√T) + r·K·e^(-rT)·N(-d2) - q·S·e^(-qT)·N(-d1)
Rho_call   = K·T·e^(-rT)·N(d2)
Rho_put    = -K·T·e^(-rT)·N(-d2)
```

`n(·)` = standard normal PDF.

## VolScope implementation

- `volscope/analytics/black_scholes.py::bs_price`
- `volscope/analytics/black_scholes.py::bs_delta` / `bs_gamma` /
  `bs_vega` / `bs_theta` / `bs_rho`
- Validated against Hull worked examples (`tests/golden/test_bs_hull.py`)
  and py_vollib (`tests/properties/test_put_call_parity.py`).

## Edge cases (DO handle, do NOT crash)

| Input | Expected behaviour |
|---|---|
| S ≤ 0 or K ≤ 0 | return 0.0 |
| T = 0 | return intrinsic: max(S-K,0) for call, max(K-S,0) for put |
| σ = 0 | discounted intrinsic: max(0, S·e^(-qT) - K·e^(-rT)) for call |
| σ very small | floor to 1e-4 in vega to avoid divide-by-zero (n(d1) handles this analytically) |
| Negative rates (-2% ≤ r ≤ 15%) | works without modification |
| Unknown option_type | raise ValueError |

## Put-call parity (invariant — must hold at 1e-6)

```
C - P = S·e^(-qT) - K·e^(-rT)
```

If this breaks for any (S, K, T, r, σ, q) tuple, the BSM implementation
has a bug. The Hypothesis property test at
`tests/properties/test_put_call_parity.py` enforces this on 1000
random examples per CI run.

## Cross-references in code

- Pricing: `volscope/analytics/black_scholes.py::bs_price`
- IV solver: `volscope/analytics/bsm_iv.py` (Newton-Raphson + bisection)
- Strategy P&L: `volscope/analytics/strategy_templates.py` uses these
  per-leg

## When NOT to use this skill

- Multi-step or path-dependent options (American, Asian, barrier) —
  BSM is inadmissible; use binomial / Monte Carlo instead.
- Options on futures — substitute the futures-style formula
  (Black 1976).
- Crypto or 24/7 markets — divide T by 365 instead of 252.
