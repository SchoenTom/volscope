---
name: composite-scoring
description: This skill should be used when authoring or reviewing the composite signal score that blends factors into a 0-100 direction-aware score.
---

# Composite signal score — direction-aware, NaN-tolerant

## Weight scheme

```
ivr  0.15    ivp  0.20    vrp  0.20    term 0.15
skew 0.05    mom  0.10    reg  0.15
```

These weights trace to `memory/roadmaps/bot-masterplan.md`. Changes
require an ADR.

## Per-factor sub-scoring

Each factor maps to a 0-100 sub-score via `_sub_score(value, low, high,
direction)`. The bands:

| Factor | low | high |
|---|---|---|
| IVR | 30 | 50 |
| IVP | 30 | 70 |
| VRP (IV/HV) | 0.75 | 1.20 |
| Term slope | -0.05 | 0.05 |
| Skew (25Δ RR) | -5.0 | 5.0 |
| HV momentum (hv5/hv30) | 1.0 | 1.5 |

For short-vol direction: above `high` = 100, below `low` = 0. Long-vol
inverts. Inside the neutral band: linear interpolation, midpoint = 50.

## Direction inversion for skew + momentum

Skew + momentum invert for the OPPOSITE direction:
- Short vol favours negative skew (compensated put-rich).
- Long vol favours positive skew.
- Short vol favours decelerating momentum (vol cooling).
- Long vol favours accelerating momentum.

This is why `_sub_score(... direction="long_vol" if direction=="short_vol" else "short_vol")`.

## NaN tolerance

Any factor returning NaN drops out; its weight is redistributed to the
remaining factors proportionally. Composite returns NaN only when EVERY
factor is NaN.

## Sizing map

```
score < 50  → 0 (no trade)
50 ≤ score < 65 → 0.25
65 ≤ score < 80 → 0.50
80 ≤ score < 90 → 0.75
score ≥ 90 → 1.00
```

## VolScope implementation

- `volscope/signals/composite.py::composite_score`
- `volscope/signals/composite.py::size_from_score`
- Tests: `tests/test_signal_composite.py` (8 tests, golden + property)

## Gotchas

- `p_calm` only contributes to score for `direction="short_vol"`.
  Long-vol is regime-agnostic in v0.5.0 (subject to v0.6.0 D10 refinement).
- Don't add new factors without updating both `factors.py::factor_vector()`
  AND `composite.py::composite_score` — the latter consumes the dict
  keys directly.
- Don't change band thresholds without a corresponding ADR + Sunday
  review.
