"""
Perf smoke — end-to-end signal generation under 200 ms.

Tagged ``perf`` so the fast CI path skips it; a separate nightly job
runs it. Complements the existing tests/test_perf_smoke.py page-render
benchmarks.
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from volscope.signals.composite import composite_score
from volscope.signals.factors import factor_vector
from volscope.signals.filters import run_all_gates
from volscope.signals.ranking import SignalCandidate, rank_signals


@pytest.mark.perf
def test_signal_generation_under_200ms():
    """5-ticker universe, full factor → composite → gates → rank in <200 ms."""
    today = date(2026, 5, 14)
    universe = ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"]
    risk_cfg = {"position_sizing": {"max_concurrent_positions": 12}}

    rng = np.random.default_rng(42)
    ticker_history = {
        t: pd.Series(15 + 10 * rng.uniform(0, 1, 252)) for t in universe
    }

    t0 = time.perf_counter()
    candidates: list[SignalCandidate] = []
    for t in universe:
        factors = factor_vector(
            iv_30d=25.0, iv_90d=23.0, hv_5d=18.0, hv_20d=20.0, hv_30d=22.0,
            iv_history_252d=ticker_history[t],
            iv_25d_call=22.0, iv_25d_put=27.0,
        )
        score = composite_score(factors, direction="short_vol", p_calm=0.8)
        ok, results = run_all_gates(
            signal_today=True, signal_yesterday=True,
            today_volume=2000, adv_20d=2000, oi_at_target=1000,
            spread=0.05, mid=2.00, today=today,
            next_earnings=today + timedelta(days=30),
            source_confidence=1.0, macro_dates=[], p_calm=0.8,
            ivr_value=60, ivp_value=75, direction="short_vol",
        )
        candidates.append(SignalCandidate(
            ticker=t, direction="short_vol", composite_score=score,
            factors=factors, gates=results,
            sector="Tech" if t not in ("SPY", "QQQ") else None,
            is_index=t in ("SPY", "QQQ"),
        ))
    _ranked = rank_signals(candidates, universe_config={},
                            risk_config=risk_cfg, p_calm=0.8)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert elapsed_ms < 200, f"signal generation took {elapsed_ms:.1f}ms (>200ms gate)"
