---
name: regime-detection-hmm
description: This skill should be used when authoring or reviewing the HMM-based regime detector. Two-state Gaussian, feature engineering, label-stability fix, and the hmmlearn API gotchas.
---

# Regime detection — 2-state Gaussian HMM

## Model

Two latent states (calm, stress) over observable features. `hmmlearn`
`GaussianHMM(n_components=2, covariance_type="full")` is the canonical
choice for VolScope.

```python
from hmmlearn.hmm import GaussianHMM
model = GaussianHMM(n_components=2, covariance_type="full",
                    n_iter=1000, random_state=42, init_params="stmc")
model.fit(X)   # X shape (T, n_features)
log_probs = model.predict_proba(X)
state_today = model.predict(X[-1:])[0]
```

## Features (v0.5.0 → v0.6.0)

**v0.5.0 (current — minimum viable):**
- `vix_delta` — daily change in VIX close
- `spy_rv20` — 20-day realised vol on SPY (Yang-Zhang)

**v0.6.0 (per Polavarapu SSRN 6539358 cross-asset paper):**
- SPY return
- VIX level
- TLT return (long-bond)
- GLD return (gold)
- ICE BofA HY OAS (high-yield spread)
- VIX9D / VIX (term-structure short ratio)
- VIX / VIX3M (term-structure long ratio)
- VRP (IV30 − HV20)
- SPY 20-day RV (Yang-Zhang)

The 9-feature model achieved Sharpe 0.881 vs 0.859 buy-and-hold.

## Label stability (CRITICAL)

`GaussianHMM` does NOT guarantee state ordering across fits — "state 0"
may be calm on Monday's fit and stress on Tuesday's fit. ALWAYS reorder
post-fit by a deterministic criterion:

```python
# Calm = lower mean realised vol (column index of spy_rv20 feature)
rv_col = 1  # adjust if feature order changes
means_rv = model.means_[:, rv_col]
stress_state_idx = int(np.argmax(means_rv))
calm_state_idx = 1 - stress_state_idx
```

Without this, downstream `p_calm > 0.6` gate flips silently between
retrains and the bot enters and exits short-vol on noise.

## Training cadence

- **Initial fit:** rolling 2-year window (~504 trading days).
  Minimum 252 days; below that the EM converges but transition matrix
  is too noisy.
- **Retrain:** quarterly. Daily retraining is overkill and introduces
  label-stability flickers; annual is too slow for regime shifts.
- **Persistence sanity:** `p_calm` should be ≥ 0.7 for at least 3
  consecutive days before triggering a regime change in the composite
  scorer. Single-day spikes are noise.

## Gotchas

- `hmmlearn.GaussianHMM.fit()` raises `ValueError` on fewer than ~60
  observations. Check `X.shape[0] >= 60` before calling.
- `covariance_type="full"` is more flexible than `"diag"` for our
  feature set but quadratically more expensive. With 2 states and 9
  features the cost is negligible.
- `random_state` matters — EM is sensitive to initial conditions.
  Pin it across retrains.
- `init_params="stmc"` initializes start probs, transmat, means,
  covars. Don't override unless you have prior values.

## Validation (v0.6.0 D11)

```python
# Generate synthetic 2-regime data with known transitions
# Fit HMM
# Assert: predicted regime sequence matches ground truth ≥ 90% accuracy
# Assert: label stability holds across re-shuffles of the data
```

## VolScope implementation

- `volscope/analytics/regime.py::RegimeDetector`
- Tests: `tests/test_analytics_regime.py` (extend in v0.6.0)

## When NOT to use HMM

- Single-asset, single-feature regimes — a moving-average crossover
  is sometimes better calibrated and definitely simpler.
- Sub-daily regimes — minute-bar features have autocorrelation
  structure HMM doesn't model. Use change-point detection instead
  (e.g. CUSUM, Bayesian online changepoint).
- Markets without a clear vol cycle (some commodities, FX) — HMM
  fits but the states don't correspond to anything actionable.
