# IV Robustness Subsystem — v0.6.1

## Problem statement

Standard IV Rank is computed against the 52-week MIN-MAX range:

$$
\mathrm{IVR}_t = 100 \cdot \frac{\mathrm{IV}_t - \min_{s \in [t-252, t]} \mathrm{IV}_s}{\max - \min}
$$

This is **vulnerable to single-spike contamination**: one extreme IV
event (forecast reset, M&A, FDA decision, crisis) stretches the
range, making IVR show a misleadingly low "CHEAP" verdict even when
IV Percentile (which is rank-based, not range-based) correctly
signals the option is elevated.

The canonical case (observed 2026-05-14 on the operator's dashboard):

| Ticker | IVR | IVP | Standard verdict | Reality |
|---|---|---|---|---|
| FISV | 12.5 | 78.6 | "CHEAP" (sell vol) | IV elevated post Q3-Q4 2025 forecast crisis |

A trader following the dashboard would have entered a short-vol
position on a ticker whose IV had just regime-shifted permanently
higher. The "12.5" came from a spike to ~232% IV during the crisis
inflating the 52-week MAX; the realised post-spike regime is ~50%
which IS high relative to the pre-crisis baseline of ~30-40%.

## Subsystem architecture

A new module `volscope/analytics/iv_robustness.py` (separate from
the legacy `volscope/signals/factors.py` for backward compatibility).
Four primitives:

### 1. `robust_iv_rank(iv_series, lookback=252, lower=0.05, upper=0.95)`

Replaces MIN/MAX with the **5th / 95th percentile** of the lookback
window. A single spike no longer pulls the bounds; the metric
measures "where is current IV in its typical range."

For FISV the standard IVR ≈ 12.5; robust IVR (assuming the post-spike
regime is the operating region) lands closer to 50-60, agreeing with
IVP.

### 2. `detect_contamination(ivr, ivp) → (level, divergence)`

Categorises `|IVR − IVP|`:

| Divergence | Level | Action |
|---|---|---|
| ≤ 15 | CLEAN | metrics agree |
| 15-30 | MILD | prefer IVP |
| 30-50 | SEVERE | use IVP only |
| > 50 | EXTREME | consider blocking ticker |

FISV at 66.1 → EXTREME.

### 3. `detect_structural_break(iv_series)`

Pelt change-point detection (via the `ruptures` library) with a
CUSUM-based fallback when ruptures isn't installed. Identifies the
most-recent regime shift where the pre/post-break mean IV differs
by ≥30%. Returns the break date, days-since-break, magnitude, and
direction.

FISV's Oct-Nov 2025 spike + Dec 2025 elevated-regime structure
produces a break in late Q3-Q4 2025.

### 4. `assess_iv_quality(ticker, iv_series, ivr, ivp) → IVQualityReport`

Composite 0-100 quality score with deductions:

| Trigger | Deduction |
|---|---|
| SEVERE contamination | -25 |
| EXTREME contamination | -50 |
| Structural break < 90 d ago | -30 |
| Structural break 90-180 d ago | -15 |
| Robust IVR differs from raw IVR by >30 pt | -20 |
| Insufficient data | forced to 0 |

Recommendation:

- ≥ 70 → **TRADE** (no banner, defaults fine)
- 40-69 → **CAUTION** (amber banner on Scope, lower-confidence trade)
- < 40 → **BLOCK** (red banner, excluded from Discover by default)

## Pipeline

1. **Migration `006_iv_quality.sql`** adds 9 nullable columns to
   `daily_vol`: `robust_iv_rank`, `contamination_level`,
   `ivr_ivp_divergence`, `structural_break_date`,
   `structural_break_days_ago`, `structural_break_magnitude`,
   `iv_quality_score`, `iv_recommendation`, `iv_warnings`.
2. **Nightly compute job** `scripts/compute/compute_iv_quality.py`
   walks every ticker in `daily_vol`, runs `assess_iv_quality`,
   writes the result back to the latest row.
3. **UI consumes the persisted columns** — no expensive computation
   in the render path.

CLI:

```bash
make compute-iv-quality                     # full universe (~5s for 14 tickers)
make quality-audit                          # dry-run + verbose report
python -m scripts.compute.compute_iv_quality --tickers AAPL FISV --verbose
```

## UI integration

### Scope page

Above the headline KPIs:

- **TRADE** → silent (no banner).
- **CAUTION** → amber banner with quality score + warnings + robust IVR.
- **BLOCK** → red banner: "do not trade until next quality scan."

Component: `volscope/ui/components/iv_quality_banner.py`.

### Scanner page

New **QUALITY** column with `ProgressColumn` rendering (0-100 score).
Sortable. Tooltip explains the threshold table.

### Discover page

Toggle **"Exclude low-quality data"** (default ON). When enabled,
filters out any ticker where `iv_recommendation = 'BLOCK'`. Caption
displays the count of hidden tickers so the operator sees the
filter is doing something.

## When to use which metric

| Situation | Metric of choice |
|---|---|
| Clean ticker (CLEAN contamination) | Standard IVR (familiar, well-known) |
| MILD contamination | IVP (rank-based, spike-immune) |
| SEVERE contamination | IVP — IVR is misleading |
| EXTREME contamination | None — wait for next scan |
| Want to compare across spike + post-spike regimes | Robust IVR |
| Day-to-day comparison within a stable regime | Standard IVR is fine |

## Known limitations

- **The Pelt algorithm cannot distinguish "permanent regime shift"
  from "extended outlier."** Both fire the structural break flag.
  Reading the news context still matters.
- **The 30% magnitude floor for break detection** filters out small
  shifts that are likely noise but can miss genuine 20-25% regime
  changes. Operator-tunable via `magnitude_floor=` keyword.
- **Robust IVR with the default 5/95 percentile** ignores the most
  extreme 10% of observations. In some bull markets where IV
  consistently drifts higher, this can compress the range too much.
  Tunable via `lower_quantile=` / `upper_quantile=`.
- **The quality score is rule-based, not statistically calibrated.**
  Deductions are operator-tuned heuristics. v0.7.0+ may calibrate
  against a backtest of "tickers where TRADE recommendation produced
  realised positive Sharpe."
- **Insufficient-data tickers are treated identically to
  high-contamination tickers** (both BLOCK). The operator can tell
  them apart by reading the `iv_warnings` JSON column.

## Citations

- Killick, R., Fearnhead, P., & Eckley, I. A. (2012). "Optimal
  detection of changepoints with a linear computational cost."
  *Journal of the American Statistical Association*, 107(500),
  1590-1598.
- López de Prado, M. (2018). *Advances in Financial Machine
  Learning*, Ch. 7 (Cross-validation in finance) + Ch. 11 (Regime
  detection).
- Tom's FISV observation, 2026-05-14 (the bug that drove this
  subsystem into existence).

## Testing

`tests/test_iv_robustness.py` covers:

- **Unit** — each primitive on synthetic clean data.
- **Edge cases** — insufficient data, invalid values, single
  spikes, short segments, no break, small shift below floor.
- **Canonical FISV regression** — synthetic IV profile mirrors the
  observed FISV May-2026 dashboard state; asserts SEVERE/EXTREME
  contamination + structural break + CAUTION/BLOCK recommendation.

If any of those tests fail in CI, the v0.6.1 promise is broken and
the build is rejected.
