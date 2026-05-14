"""
VolScope Research module — statistical validation harness for signal claims.

Why this module exists separately from ``analytics/``: the analytics layer
*computes* derived quantities (IV, HV, Greeks, factor scores). The research
layer *validates whether the computed signals actually have alpha*. Bailey
& López de Prado (2014), "The Deflated Sharpe Ratio", makes the case that
every backtested strategy must pass at least four hurdles before being
trusted: a t-test, a block bootstrap, a permutation test, and a
data-mining correction (Deflated SR). VolScope implements all four here.

Public surface
==============
- :func:`volscope.research.statistical_tests.t_test_sharpe`
- :func:`volscope.research.statistical_tests.block_bootstrap_sharpe`
- :func:`volscope.research.statistical_tests.permutation_test_alpha`
- :func:`volscope.research.statistical_tests.deflated_sharpe_ratio`
- :func:`volscope.research.walk_forward.walk_forward_split`
- :func:`volscope.research.walk_forward.run_gauntlet`
"""
from __future__ import annotations

from volscope.research.statistical_tests import (
    t_test_sharpe,
    block_bootstrap_sharpe,
    permutation_test_alpha,
    deflated_sharpe_ratio,
)
from volscope.research.walk_forward import (
    walk_forward_split,
    run_gauntlet,
    GauntletResult,
)

__all__ = [
    "t_test_sharpe",
    "block_bootstrap_sharpe",
    "permutation_test_alpha",
    "deflated_sharpe_ratio",
    "walk_forward_split",
    "run_gauntlet",
    "GauntletResult",
]
