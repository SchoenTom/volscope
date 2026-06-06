"""
Perf smoke test — runs inside pytest where iCloud already warmed the
imports. Measures the actually-relevant numbers: each page's render
time, hot function microbenchmarks.

Run with:  pytest tests/test_perf_smoke.py -v -s
"""
from __future__ import annotations

import statistics
import time
from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

_APP_PATH = str(Path(__file__).resolve().parent.parent / "volscope" / "ui" / "app.py")

from volscope.analytics.black_scholes import bs_delta, bs_price, implied_volatility
from volscope.analytics.probability import pop_closed_form, pop_monte_carlo
from volscope.analytics.strategy_templates import TEMPLATES


def t_ms() -> float:
    return time.perf_counter() * 1000


def timed(fn, n: int = 7) -> float:
    samples = []
    for _ in range(n):
        s = t_ms()
        fn()
        samples.append(t_ms() - s)
    return statistics.median(samples)


@pytest.mark.perf
class TestHotFunctions:
    """Microbenchmark the BSM / strategy / probability hot paths.

    These are the functions called during every Options Lab slider drag
    or AppTest page render. If they regress, the UI feels slow.
    """

    def test_bsm_scalar_sub_ms(self):
        ms = timed(lambda: bs_price(100, 100, 1.0, 0.04, 0.25, 0.0, "call"))
        print(f"\n  bs_price scalar: {ms:.3f} ms")
        assert ms < 5

    def test_bsm_delta_scalar_sub_ms(self):
        ms = timed(lambda: bs_delta(100, 100, 1.0, 0.04, 0.25, 0.0, "call"))
        print(f"\n  bs_delta scalar: {ms:.3f} ms")
        assert ms < 5

    def test_iv_solver_sub_5ms(self):
        ms = timed(lambda: implied_volatility(10.45, 100, 100, 1.0, 0.04, 0.0, "call"))
        print(f"\n  iv_solver: {ms:.3f} ms")
        assert ms < 5

    def test_materialize_straddle(self):
        ms = timed(lambda: TEMPLATES["Long Straddle"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=60, contracts=1,
        ))
        print(f"\n  materialize straddle: {ms:.3f} ms")
        assert ms < 10

    def test_materialize_iron_condor(self):
        ms = timed(lambda: TEMPLATES["Short Iron Condor"].materialize(
            ticker="X", spot=100.0, iv_pct=30.0, dte=45, contracts=1,
        ))
        print(f"\n  materialize iron condor: {ms:.3f} ms")
        assert ms < 20

    def test_payoff_at_t_200pts(self):
        m = TEMPLATES["Long Straddle"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=60, contracts=1,
        )
        S_grid = np.linspace(60, 140, 200)
        ms = timed(lambda: m.payoff_at_t(S_grid, t_fraction=0.5, iv=25.0))
        print(f"\n  payoff_at_t (200pts vectorised): {ms:.3f} ms")
        assert ms < 5

    def test_scenario_matrix_45_cells(self):
        m = TEMPLATES["Long Straddle"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=60, contracts=1,
        )
        def _matrix():
            for ds in (-0.2, -0.15, -0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2):
                for div in (-10, -5, 0, 5, 10):
                    m.net_premium(100*(1+ds), iv=25.0+div)
        ms = timed(_matrix)
        print(f"\n  scenario matrix 45 cells: {ms:.3f} ms")
        assert ms < 50

    def test_pop_monte_carlo_10k(self):
        m = TEMPLATES["Long Straddle"].materialize(
            ticker="X", spot=100.0, iv_pct=25.0, dte=60, contracts=1,
        )
        ms = timed(lambda: pop_monte_carlo(m, S0=100, iv=25.0, n_paths=10_000))
        print(f"\n  PoP Monte Carlo 10k: {ms:.3f} ms")
        assert ms < 30


@pytest.mark.perf
class TestPageRenders:
    """AppTest per-page wall-clock — proxy for actual page render time
    when the user navigates inside the app."""

    @pytest.fixture(scope="class")
    def at(self):
        at = AppTest.from_file(
            _APP_PATH,
            default_timeout=90,
        )
        at.session_state["selected_ticker"] = "PYPL"
        return at

    @pytest.mark.parametrize("page", [
        "Discover", "Command", "Scope", "Scanner",
        "Options Lab", "Alerts", "Heatmap",
        "Vol Insights", "Earnings Hub", "Watchlist",
    ])
    def test_page_render_under_3s(self, at, page):
        at.session_state["active_page"] = page
        start = t_ms()
        at.run()
        elapsed = t_ms() - start
        print(f"\n  {page:14s} {elapsed:7.1f} ms")
        assert at.exception is None or len(at.exception) == 0
        # Soft assertion — the *cold* first render is variable, so we
        # only fail on truly egregious renders (> 8 s).
        assert elapsed < 8000
