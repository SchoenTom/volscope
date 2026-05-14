"""
Walk-forward harness + 4-test gauntlet orchestration.

Why this module exists
======================
A backtest without out-of-sample validation is just a curve-fit. The
walk-forward pattern (Bailey-López de Prado 2018 chapter 7) splits the
return history into a chronological *train* + *test* window so the
researcher cannot accidentally peek at future data. VolScope uses a
single fixed split (default 60/40) for simplicity; the gauntlet runs
all four statistical tests on the *test* portion of the returns.

Public surface
==============
- :func:`walk_forward_split` — chronological train/test cut.
- :func:`run_gauntlet` — orchestrates the four tests + Δ vs benchmark.
- :class:`GauntletResult` — bundle the operator pages render.

Note on terminology
===================
Some Bailey-López de Prado references call the held-out period
"validation" or "OOS". This module uses *test* because the operator
mental-model is "did the signal work on unseen data?" — terminologically
closer to "test set" in ML.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

from volscope.research.statistical_tests import (
    BootstrapResult,
    DeflatedSharpeResult,
    PermutationResult,
    TTestResult,
    block_bootstrap_sharpe,
    deflated_sharpe_ratio,
    permutation_test_alpha,
    t_test_sharpe,
)


@dataclass(frozen=True)
class WalkForwardSplit:
    """Chronological train/test cut of a returns series."""
    train: pd.Series
    test:  pd.Series
    split_date: pd.Timestamp


def walk_forward_split(
    returns: pd.Series,
    *,
    train_frac: float = 0.6,
) -> WalkForwardSplit:
    """Chronological split — first ``train_frac`` is train, rest is test.

    The series must be indexed by ``pd.DatetimeIndex`` so the operator
    can read off the split-date for display. Returns are not shuffled
    or otherwise resampled — the whole point is to preserve temporal
    ordering and prevent lookahead.
    """
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise TypeError("walk_forward_split requires a DatetimeIndex")
    if returns.empty:
        return WalkForwardSplit(
            train=returns, test=returns,
            split_date=pd.Timestamp("1970-01-01"),
        )
    n = len(returns)
    cut = max(2, int(round(n * train_frac)))
    cut = min(cut, n - 2)
    train = returns.iloc[:cut]
    test  = returns.iloc[cut:]
    split_date = pd.Timestamp(test.index[0]) if not test.empty else pd.Timestamp("1970-01-01")
    return WalkForwardSplit(train=train, test=test, split_date=split_date)


@dataclass(frozen=True)
class GauntletResult:
    """Bundle of test-set statistics returned by :func:`run_gauntlet`."""
    n_train:        int
    n_test:         int
    split_date:     pd.Timestamp

    test_returns:   pd.Series                       # for the equity curve plot
    bench_returns:  pd.Series | None

    t_test:         TTestResult
    bootstrap:      BootstrapResult
    permutation:    PermutationResult | None
    deflated:       DeflatedSharpeResult

    # Convenience: derived equity curves (cum-prod 1 + r).
    test_equity:    pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    bench_equity:   pd.Series | None = None


def _cum_equity(returns: pd.Series) -> pd.Series:
    """``(1 + r).cumprod()`` — starting from 1.0."""
    if returns.empty:
        return returns
    return (1.0 + returns).cumprod().rename("equity")


def run_gauntlet(
    strategy_returns: pd.Series,
    *,
    benchmark_returns: pd.Series | None = None,
    train_frac:         float = 0.6,
    n_bootstrap:        int = 10_000,
    n_permutations:     int = 10_000,
    n_trials_in_search: int = 1,
    seed:               int = 42,
) -> GauntletResult:
    """Run the full 4-test gauntlet on the *test* portion of returns.

    Parameters
    ----------
    strategy_returns
        Period returns of the candidate signal (decimal, daily).
    benchmark_returns
        Optional benchmark series. If provided, the permutation test
        compares strategy vs benchmark. If omitted, the permutation
        test is skipped (returns ``None``) — the t-test, bootstrap
        and DSR can still be run on the strategy alone.
    train_frac
        Chronological train/test split fraction. Default 0.6.
    n_bootstrap, n_permutations
        Number of resamples / permutations. Default 10 000 each
        follows the Gelato repo + López de Prado replications.
    n_trials_in_search
        Number of candidate parameter combinations the researcher
        explored before reporting this strategy. Drives the
        Deflated-Sharpe data-mining correction.
    seed
        Determinism.
    """
    split = walk_forward_split(strategy_returns, train_frac=train_frac)
    test = split.test

    t_res    = t_test_sharpe(test.values)
    boot_res = block_bootstrap_sharpe(
        test.values, n_resamples=n_bootstrap, seed=seed,
    )
    dsr_res  = deflated_sharpe_ratio(
        test.values, n_trials=n_trials_in_search,
    )

    perm_res: PermutationResult | None = None
    bench_test: pd.Series | None = None
    if benchmark_returns is not None and not benchmark_returns.empty:
        # Align benchmark to the test window so the permutation test
        # compares apples-to-apples (same timestamps, same length).
        bench_aligned = benchmark_returns.reindex(test.index).dropna()
        if len(bench_aligned) >= 5:
            bench_test = bench_aligned
            perm_res = permutation_test_alpha(
                test.reindex(bench_aligned.index).values,
                bench_aligned.values,
                n_permutations=n_permutations,
                seed=seed,
            )

    return GauntletResult(
        n_train=int(len(split.train)),
        n_test=int(len(split.test)),
        split_date=split.split_date,
        test_returns=test,
        bench_returns=bench_test,
        t_test=t_res,
        bootstrap=boot_res,
        permutation=perm_res,
        deflated=dsr_res,
        test_equity=_cum_equity(test),
        bench_equity=_cum_equity(bench_test) if bench_test is not None else None,
    )
