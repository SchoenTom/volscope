"""
Statistical-significance tests for trading-signal alpha.

This module implements the four hurdles from Bailey & López de Prado
(2014), "The Deflated Sharpe Ratio: Correcting for Selection Bias,
Backtest Overfitting, and Non-Normality" (Journal of Portfolio
Management, 40 (5), 94-107):

    1. **t-test of Sharpe** (H₀: SR ≤ 0). Standard parametric test.
    2. **Block bootstrap** of Sharpe (Künsch 1989 moving-block).
       Preserves autocorrelation that the naïve IID bootstrap destroys.
    3. **Permutation test of alpha vs benchmark** (shuffle the
       strategy / benchmark label, recompute the alpha statistic).
    4. **Deflated Sharpe Ratio** — corrects for the multiplicity of
       trials a researcher would actually run before reporting a SR.

A strategy that clears all four hurdles at p < 0.01 is "well-supported".
None of these tests alone is sufficient — together they are the
academic gold standard for retail-vol-trader-grade evidence.

Conventions
-----------
- All ``returns`` arrays / Series are *period* returns in decimal form
  (0.012 = +1.2 %). Daily frequency is the default; annualisation uses
  ``trading_days_per_year = 252``.
- Sharpe is computed unannualised internally and annualised only for
  display. The bootstrap / permutation operate on daily SR samples.
- Random seeding is exposed so unit tests can be deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import e, sqrt
from typing import Sequence

import numpy as np
from scipy import stats

TRADING_DAYS_PER_YEAR = 252


# ── Core helpers ─────────────────────────────────────────────────────

def _sharpe(returns: np.ndarray, *, annualise: bool = True) -> float:
    """Plain Sharpe (mean / stddev). Returns 0.0 on a degenerate series.

    No risk-free-rate subtraction here — for *Sharpe of a signal* the
    interesting null is "the signal returns are no better than zero",
    not "no better than 3-month T-Bills". Callers can pre-subtract a
    rf series if they want excess Sharpe.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    if std <= 0.0:
        return 0.0
    sr_daily = float(np.mean(arr)) / std
    if annualise:
        return sr_daily * sqrt(TRADING_DAYS_PER_YEAR)
    return sr_daily


# ── 1. t-test of Sharpe ─────────────────────────────────────────────

@dataclass(frozen=True)
class TTestResult:
    """t-test of H₀: mean(returns) ≤ 0."""
    t_stat:        float
    p_value:       float
    sharpe_annual: float
    n_obs:         int


def t_test_sharpe(returns: Sequence[float]) -> TTestResult:
    """One-sided t-test that returns has positive mean (i.e. SR > 0).

    Implementation note: a t-test on the *return* mean is equivalent
    to a t-test on the *daily* Sharpe via t = SR_daily · √n, so we
    just call ``scipy.stats.ttest_1samp`` against zero and read the
    one-sided p-value from the resulting (two-sided) value.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 3:
        return TTestResult(t_stat=0.0, p_value=1.0, sharpe_annual=0.0,
                            n_obs=int(arr.size))
    res = stats.ttest_1samp(arr, popmean=0.0, alternative="greater")
    return TTestResult(
        t_stat=float(res.statistic),
        p_value=float(res.pvalue),
        sharpe_annual=_sharpe(arr, annualise=True),
        n_obs=int(arr.size),
    )


# ── 2. Block bootstrap of Sharpe ────────────────────────────────────

@dataclass(frozen=True)
class BootstrapResult:
    """Moving-block bootstrap confidence interval around annualised SR."""
    sharpe_point:  float
    sharpe_ci_low: float      # 2.5 %  quantile
    sharpe_ci_high: float     # 97.5 % quantile
    p_value:       float      # share of bootstrap SRs ≤ 0
    n_resamples:   int
    block_length:  int


def _moving_block_bootstrap_indices(
    n: int,
    block: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate one moving-block bootstrap sample's worth of indices.

    Künsch (1989): pick ⌈n / block⌉ random *starts* uniformly in
    [0, n-block], concatenate ``arr[start:start+block]`` for each,
    truncate to length n. Preserves the local autocorrelation
    structure that an IID bootstrap would shatter.
    """
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(low=0, high=max(1, n - block + 1), size=n_blocks)
    idx = np.concatenate(
        [np.arange(s, s + block) for s in starts]
    )
    return idx[:n]


def block_bootstrap_sharpe(
    returns: Sequence[float],
    *,
    n_resamples: int = 10_000,
    block: int | None = None,
    seed: int = 42,
) -> BootstrapResult:
    """Moving-block bootstrap of the annualised Sharpe ratio.

    Parameters
    ----------
    returns
        Daily strategy returns (decimal).
    n_resamples
        Number of bootstrap draws. Default 10 000 follows the Gelato
        repo + most replication literature.
    block
        Block length. Defaults to ``max(2, n_obs ** (1/3))`` — the
        Politis-White (2004) rule of thumb that scales block length
        with sample size so it tracks the decay of the autocorrelation
        function.
    seed
        For reproducibility in unit tests.

    Returns
    -------
    :class:`BootstrapResult` with the point Sharpe, 95 % CI, and the
    proportion of bootstrap SRs that fall at or below zero (the
    bootstrap p-value for H₀: SR ≤ 0).
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = arr.size
    if n < 10:
        return BootstrapResult(
            sharpe_point=0.0, sharpe_ci_low=0.0, sharpe_ci_high=0.0,
            p_value=1.0, n_resamples=0, block_length=0,
        )

    block_len = block or max(2, int(round(n ** (1.0 / 3.0))))
    rng = np.random.default_rng(seed)

    boot_srs = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        idx = _moving_block_bootstrap_indices(n, block_len, rng)
        boot_srs[i] = _sharpe(arr[idx], annualise=True)

    sr_point = _sharpe(arr, annualise=True)
    lo, hi = np.quantile(boot_srs, [0.025, 0.975])
    # Bootstrap p-value: how often the resampled SR falls at-or-below 0.
    p_val = float(np.mean(boot_srs <= 0.0))
    return BootstrapResult(
        sharpe_point=float(sr_point),
        sharpe_ci_low=float(lo),
        sharpe_ci_high=float(hi),
        p_value=p_val,
        n_resamples=int(n_resamples),
        block_length=int(block_len),
    )


# ── 3. Permutation test of alpha vs benchmark ───────────────────────

@dataclass(frozen=True)
class PermutationResult:
    """Permutation test of strategy-vs-benchmark alpha."""
    alpha_observed: float
    p_value:        float
    n_permutations: int


def permutation_test_alpha(
    strategy_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    *,
    n_permutations: int = 10_000,
    seed: int = 42,
) -> PermutationResult:
    """Test whether the strategy's mean return exceeds the benchmark's.

    Algorithm: stack the two series into a single pool, then on every
    iteration randomly assign half to ``strategy`` and half to
    ``benchmark``, recompute the difference of means, and accumulate.
    The p-value is the share of permuted differences that meet or
    exceed the observed alpha. This is the classic non-parametric
    test from Fisher (1935); no distributional assumption is required.
    """
    s = np.asarray(strategy_returns, dtype=float)
    b = np.asarray(benchmark_returns, dtype=float)
    s = s[np.isfinite(s)]
    b = b[np.isfinite(b)]
    if s.size < 5 or b.size < 5:
        return PermutationResult(alpha_observed=0.0, p_value=1.0,
                                  n_permutations=0)

    pool = np.concatenate([s, b])
    n_s = s.size
    alpha_obs = float(np.mean(s) - np.mean(b))

    rng = np.random.default_rng(seed)
    perm_alphas = np.empty(n_permutations, dtype=float)
    for i in range(n_permutations):
        rng.shuffle(pool)
        perm_alphas[i] = float(np.mean(pool[:n_s]) - np.mean(pool[n_s:]))

    # One-sided: share of permuted alphas at least as extreme.
    p_val = float(np.mean(perm_alphas >= alpha_obs))
    return PermutationResult(
        alpha_observed=alpha_obs,
        p_value=p_val,
        n_permutations=int(n_permutations),
    )


# ── 4. Deflated Sharpe Ratio (Bailey & López de Prado 2014) ─────────

# Euler-Mascheroni constant — appears in the SR_max expression.
_EULER_MASCHERONI = 0.5772156649015329


def _expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected maximum Sharpe across ``n_trials`` IID candidates.

    From Bailey-López de Prado (2014) eq. (10):

        E[max_n SR] ≈ √V[SR] · [
            (1 − γ_em)·Φ⁻¹(1 − 1/N) +
             γ_em      ·Φ⁻¹(1 − 1/(N·e))
          ]

    Intuition: if you try N strategies even when their *true* SR is
    zero, the *best* one you find will, by chance, have a sample SR
    on the order of √V[SR] · √(2 ln N). This is the bias the
    Deflated Sharpe corrects for.
    """
    if n_trials <= 1 or sr_variance <= 0.0:
        return 0.0
    inv_cdf_1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    inv_cdf_2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * e))
    return float(sqrt(sr_variance) * (
        (1.0 - _EULER_MASCHERONI) * inv_cdf_1
        + _EULER_MASCHERONI       * inv_cdf_2
    ))


@dataclass(frozen=True)
class DeflatedSharpeResult:
    """Bailey & López de Prado Deflated Sharpe."""
    sharpe_observed:     float        # annualised
    sharpe_expected_max: float        # annualised, under H₀ of zero alpha
    dsr:                 float        # P(true SR > 0 | observed)
    p_value:             float        # 1 - dsr; how often pure noise wins
    n_obs:               int
    n_trials:            int
    skew:                float
    kurt:                float


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    n_trials: int = 1,
    sr_variance: float | None = None,
) -> DeflatedSharpeResult:
    """Deflated Sharpe per Bailey & López de Prado (2014) eq. (12).

    Formula::

        DSR(SR) = Φ( (SR − SR_max) · √(N_obs − 1)
                    / √(1 − γ̂₃·SR + (γ̂₄ − 1)/4 · SR²) )

    where γ̂₃ = sample skew of returns, γ̂₄ = sample excess kurtosis,
    and SR is the *daily* (un-annualised) Sharpe so the higher-moment
    correction is in the correct frequency.

    Parameters
    ----------
    returns
        Daily strategy returns.
    n_trials
        Number of candidate strategies the researcher considered
        before reporting this one. If you grid-searched 1296
        parameter combinations, pass 1296 here. Default 1 disables
        the data-mining correction (= classic SR with skew/kurt
        correction only).
    sr_variance
        Optional cross-trial variance of SR estimates. If omitted,
        defaults to ``Var(SR_daily) / N_obs`` which is the asymptotic
        variance of a single SR estimate — a conservative choice
        when the operator has not actually run the trials.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = arr.size
    if n < 10:
        return DeflatedSharpeResult(
            sharpe_observed=0.0, sharpe_expected_max=0.0,
            dsr=0.5, p_value=0.5, n_obs=int(n),
            n_trials=int(n_trials), skew=0.0, kurt=0.0,
        )

    sr_daily = _sharpe(arr, annualise=False)
    sr_annual = sr_daily * sqrt(TRADING_DAYS_PER_YEAR)

    skew = float(stats.skew(arr, bias=False))
    # ``scipy.stats.kurtosis`` returns *excess* kurtosis (γ₄ − 3) by
    # default; the BLdP formula expects γ̂₄ such that γ̂₄ − 1 enters
    # the correction. So we want excess kurt + 3 = γ̂₄, then subtract
    # 1 inside the formula. Equivalently: (excess + 3 − 1)/4 = (excess + 2)/4.
    excess_kurt = float(stats.kurtosis(arr, bias=False, fisher=True))

    # Default SR variance: asymptotic of a single estimate (no
    # multiplicity reduction beyond the n_trials counting below).
    v_sr = (
        sr_variance if sr_variance is not None
        else (1.0 / max(2, n - 1))
    )
    sr_max_daily = _expected_max_sharpe(n_trials, v_sr)
    sr_max_annual = sr_max_daily * sqrt(TRADING_DAYS_PER_YEAR)

    # BLdP denominator with skew/kurt correction (eq. 12).
    denom_sq = 1.0 - skew * sr_daily + (excess_kurt + 2.0) / 4.0 * sr_daily ** 2
    denom_sq = max(denom_sq, 1e-9)
    denom = sqrt(denom_sq)

    z = (sr_daily - sr_max_daily) * sqrt(n - 1) / denom
    dsr = float(stats.norm.cdf(z))
    return DeflatedSharpeResult(
        sharpe_observed=sr_annual,
        sharpe_expected_max=sr_max_annual,
        dsr=dsr,
        p_value=float(1.0 - dsr),
        n_obs=int(n),
        n_trials=int(n_trials),
        skew=skew,
        kurt=excess_kurt,
    )
