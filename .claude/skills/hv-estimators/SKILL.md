---
name: hv-estimators
description: This skill should be used when authoring or reviewing historical-volatility code. Covers CC / Parkinson / Garman-Klass / Yang-Zhang formulas, efficiency ranking, and when each is preferred.
---

# Historical-Volatility Estimators

Four estimators, increasing efficiency. All return annualised σ via
`× √252` from daily returns.

## 1. Close-to-Close (CC)

```
σ_CC = √(252 / (n-1)) · √(Σ (rᵢ - r̄)²)   where rᵢ = ln(Cᵢ / Cᵢ₋₁)
```

Simplest, most widely cited. **Efficient = 1 (baseline).** Uses only
closing prices.

## 2. Parkinson (1980)

```
σ_Park = √(252 / (4·n·ln 2)) · √(Σ (ln(Hᵢ/Lᵢ))²)
```

Uses daily high and low. **Efficient ≈ 5** relative to CC.
**Assumes zero drift.**

## 3. Garman-Klass (1980)

```
σ_GK = √(252/n) · √(Σ (0.5·(ln(Hᵢ/Lᵢ))² - (2·ln 2 - 1)·(ln(Cᵢ/Oᵢ))²))
```

Uses O, H, L, C. **Efficient ≈ 7.4** relative to CC.
**Still assumes zero drift.**

## 4. Yang-Zhang (2000)

The min-variance unbiased estimator combining overnight + intraday:

```
σ_YZ² = σ_overnight² + k · σ_open_to_close² + (1-k) · σ_RS²
```

Where `σ_RS²` is the Rogers-Satchell estimator (drift-independent),
and `k = 0.34 / (1.34 + (n+1)/(n-1))`.

**Efficient ≈ 14** relative to CC; min-variance unbiased; **handles
drift correctly** (only estimator that does).

## Which to use when

| Situation | Estimator | Why |
|---|---|---|
| Default for IV/HV ratio | YZ | Best efficiency; drift-correct |
| Quick mental math | CC | Familiar; matches Yahoo's reported HV |
| Heavy overnight gaps | YZ | Only one that decomposes overnight cleanly |
| Tickers with strong trends (NVDA, TSLA in 2024) | YZ | Drift-independent |
| Reproducing tastytrade research | CC | They use 20-day CC |
| Cross-checking | All 4 | Their ordered ranking is itself a sanity check |

**VolScope default:** `daily_vol.hv_yz_20d` is the canonical HV column;
fall back to `hv_20d` (CC) only when YZ unavailable.

## Sanity invariants (test on synthetic data)

Given returns generated from a known σ:

```
σ_CC ≥ σ_Park ≥ σ_GK ≥ σ_RS   (when drift = 0)
```

And on a long sample (n → ∞), all four estimators should converge to
the true σ within their standard error. The Hypothesis property test
at `tests/properties/` (v0.6.0 A5) generates 5-year log-normal series
and asserts:
- All 4 estimators within 0.005 of true σ at n=1260.
- YZ has the lowest sample variance across 100 simulations.

## Edge cases

| Input | Behaviour |
|---|---|
| Constant prices | σ = 0 (degenerate but defined) |
| Single jump (one row with abs return > 3σ) | Use median-based robust variant for spike-test |
| Missing OHLC fields | Fall back to CC if H or L missing |
| Weekend gaps | Don't time-weight; treat consecutive trading days as Δt=1 |
| Holidays | Same — exchange-calendars handles the date axis |

## VolScope implementation

- `volscope/analytics/hv_cc.py` (or wherever the family lives)
- Test goldens: `tests/test_hv_estimators.py` (extend in v0.6.0 A5)
- Validation against `vollib` HV: identical to 1e-10 for the
  drift-zero cases.

## Don't

- Don't subtract a sample mean from `ln(Cᵢ/Cᵢ₋₁)` if you're after the
  "RV" used in BSM — BSM uses the variance with mean 0 (drift is
  separated into r). Subtracting the sample mean introduces a small
  but nonzero bias on short windows.
- Don't use Yahoo's reported HV without checking which estimator they
  use (it's CC) — you'll get tiny mismatches that look like bugs.
