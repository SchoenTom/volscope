"""Tests for the LEAPS-convergence scorer + suggester."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from volscope.analytics.leaps_convergence import (
    CONVERGENCE_THRESHOLD,
    ConvergenceResult,
    LeapsSuggestion,
    compute_convergence,
    compute_mispricing_score,
    compute_neglect_score,
    compute_reversal_score,
    rank_universe,
    suggest_leaps,
)


# ── Mispricing ───────────────────────────────────────────────────────────

def _pypl_row() -> pd.Series:
    """Reference row from the PYPL strategy deck (10-May-2026 snapshot)."""
    return pd.Series({
        "ticker":         "PYPL",
        "iv_30d":         30.2,
        "hv_20d":         44.7,
        "iv_rank":        12.0,
        "iv_percentile":  29.0,
        "spot_price":     45.32,
        "sector":         "Financial Services",
    })


def test_mispricing_pypl_is_high():
    """The PYPL deck inputs should land in the actionable band.

    The deck quotes IV=30.2, HV=44.7, IV-Rank=12, IV-Pct=29 — strong but not
    extreme on every component (percentile 29 is "cheaper than 71% of the
    year", not "annual floor"). The composite scores ~67, which is the
    actionable band. The "extreme" band (≥80) is reserved for deeper combos
    such as IV-Rank<5 + IV-Pct<10 + IV/HV<0.5.
    """
    score = compute_mispricing_score(_pypl_row())
    assert score is not None
    assert score >= 65.0, f"expected ≥65, got {score:.1f}"


def test_mispricing_average_market_is_low():
    """A generic ticker with IV>HV and IV near percentile-50 should score low."""
    row = pd.Series({
        "iv_30d":         25.0,
        "hv_20d":         20.0,        # IV/HV = 1.25 — options rich vs realised
        "iv_rank":        55.0,
        "iv_percentile": 60.0,
    })
    score = compute_mispricing_score(row)
    assert score is not None
    assert score <= 20.0


def test_mispricing_returns_none_on_missing():
    """No silent zero-fill — missing data must propagate as None."""
    assert compute_mispricing_score(pd.Series({"iv_30d": 30, "hv_20d": None,
                                               "iv_rank": 10, "iv_percentile": 20})) is None


def test_mispricing_safe_on_zero_hv():
    """Zero HV would otherwise divide-by-zero — must short-circuit cleanly."""
    assert compute_mispricing_score(pd.Series({"iv_30d": 30, "hv_20d": 0,
                                               "iv_rank": 10, "iv_percentile": 20})) is None


# ── Neglect ──────────────────────────────────────────────────────────────

def _build_history(returns_pct: float, n_days: int = 260, start_price: float = 50.0) -> pd.DataFrame:
    """Synthesise a price series with a target trailing return."""
    end_price = start_price * (1.0 + returns_pct)
    prices = np.linspace(start_price, end_price, n_days)
    dates = pd.date_range(end=date.today(), periods=n_days, freq="B")
    return pd.DataFrame({
        "date":       dates,
        "spot_price": prices,
        "hv_20d":     [25.0] * n_days,
        "hv_60d":     [30.0] * n_days,
    })


def test_neglect_pypl_underperforms_spy_by_50pp_scores_high():
    """PYPL down 22 % vs SPY up 29 % → 51pp underperformance → score ~100."""
    pypl = _build_history(-0.22)
    spy  = _build_history(+0.29)
    score = compute_neglect_score(pypl, spy)
    assert score is not None
    assert score >= 95.0


def test_neglect_outperformer_scores_zero():
    """A name that beats the benchmark is the opposite of neglected."""
    winner = _build_history(+0.40)
    spy    = _build_history(+0.10)
    assert compute_neglect_score(winner, spy) == 0.0


def test_neglect_returns_none_when_history_too_short():
    """Less than ~60 sessions of data — silently scoring would mislead."""
    short = _build_history(-0.20, n_days=30)
    spy   = _build_history(+0.10)
    assert compute_neglect_score(short, spy) is None


# ── Reversal ─────────────────────────────────────────────────────────────

def test_reversal_deep_drawdown_with_cooling_vol_scores_high():
    """Stock at -55% from 52w high + recent 20d HV well below 60d HV."""
    n = 260
    prices = np.concatenate([
        np.linspace(100, 100, 130),     # high plateau
        np.linspace(100, 45, 130),      # crash
    ])
    df = pd.DataFrame({
        "date":       pd.date_range(end=date.today(), periods=n, freq="B"),
        "spot_price": prices,
        "hv_20d":     [20.0] * n,        # recent realised vol cooling
        "hv_60d":     [40.0] * n,
    })
    score = compute_reversal_score(df)
    assert score is not None
    assert score >= 70.0


def test_reversal_at_highs_scores_low():
    """No drawdown, no cooling — convexity asymmetry is absent."""
    df = _build_history(+0.30)
    df["hv_20d"] = 30.0
    df["hv_60d"] = 30.0
    score = compute_reversal_score(df)
    assert score is not None
    assert score <= 10.0


# ── Composite + ranker ──────────────────────────────────────────────────

def test_compute_convergence_pypl_passes_threshold():
    """The reference PYPL set-up must clear the actionable gate."""
    pypl = _build_history(-0.22)
    spy  = _build_history(+0.29)
    # Splice the deck's mispricing inputs into the latest row.
    pypl.loc[pypl.index[-1], "iv_30d"]        = 30.2
    pypl.loc[pypl.index[-1], "hv_20d"]        = 44.7
    pypl.iloc[-1, pypl.columns.get_loc("hv_60d")] = 30.0
    pypl["iv_rank"] = 12.0
    pypl["iv_percentile"] = 29.0
    pypl["ticker"] = "PYPL"
    pypl["spot_price"] = np.linspace(58, 45.32, len(pypl))   # closing path

    row = pypl.iloc[-1]
    result = compute_convergence(row, pypl, spy)
    assert isinstance(result, ConvergenceResult)
    assert result.is_actionable(), f"score {result.score} < threshold {CONVERGENCE_THRESHOLD}"
    assert "mispricing" in result.drivers or "neglect" in result.drivers


def test_compute_convergence_renormalises_when_benchmark_missing():
    """Missing benchmark must renormalise weights, not zero out neglect."""
    pypl = _build_history(-0.20)
    pypl.iloc[-1, pypl.columns.get_loc("hv_60d")] = 30.0
    pypl["iv_30d"] = 30.0
    pypl["hv_20d"] = 45.0
    pypl["iv_rank"] = 12.0
    pypl["iv_percentile"] = 29.0
    pypl["ticker"] = "PYPL"
    pypl["spot_price"] = np.linspace(58, 45.32, len(pypl))

    row = pypl.iloc[-1]
    result = compute_convergence(row, pypl, benchmark_history=None)
    assert result.score > 0
    assert result.neglect is None
    assert result.mispricing is not None
    assert result.reversal is not None


def test_rank_universe_orders_by_score_descending():
    pypl_hist = _build_history(-0.22)
    aapl_hist = _build_history(+0.30)
    spy_hist  = _build_history(+0.29)

    latest = pd.DataFrame([
        {
            "ticker": "PYPL", "iv_30d": 30.2, "hv_20d": 44.7,
            "iv_rank": 12.0, "iv_percentile": 29.0, "spot_price": 45.32, "sector": "Fin",
        },
        {
            "ticker": "AAPL", "iv_30d": 22.0, "hv_20d": 18.0,
            "iv_rank": 60.0, "iv_percentile": 70.0, "spot_price": 200.0, "sector": "Tech",
        },
    ])
    histories = {"PYPL": pypl_hist, "AAPL": aapl_hist}
    out = rank_universe(latest, histories, spy_hist, n=10)
    assert list(out["ticker"]) == ["PYPL", "AAPL"]
    assert out.iloc[0]["score"] > out.iloc[1]["score"]


# ── LEAPS suggestion ─────────────────────────────────────────────────────

def test_suggest_leaps_pypl_reproduces_deck_structure():
    """The deck quotes spot 45.32, IV 30.2 %, strike 80, premium 2.5–3.5,
    delta ~0.25, vega ~0.20. Our suggestion must land in those ranges."""
    s = suggest_leaps("PYPL", spot=45.32, iv=0.302, target_dte_days=730,
                      today=date(2026, 5, 10))
    assert s is not None
    assert s.strike == 79.0 or s.strike == 80.0
    assert 1.5 <= s.est_premium <= 5.0, f"premium {s.est_premium}"
    assert 0.18 <= s.delta <= 0.32,     f"delta {s.delta}"
    # Vega per 1 % σ
    assert 0.10 <= s.vega_per_pct <= 0.30, f"vega/% {s.vega_per_pct}"
    # Expiry honoured
    assert s.expiry == date(2026, 5, 10) + timedelta(days=730)
    # Theta is negative for a long call
    assert s.theta_per_day < 0
    # Payoff ladder is monotone in spot
    spots = [p[0] for p in s.payoff]
    assert spots == sorted(spots)


def test_suggest_leaps_returns_none_on_degenerate_inputs():
    assert suggest_leaps("X", spot=0, iv=0.3) is None
    assert suggest_leaps("X", spot=10, iv=0.0) is None


def test_suggest_leaps_breakeven_equals_strike_plus_premium():
    """Breakeven is rounded to 2dp for display — match the same precision."""
    s = suggest_leaps("PYPL", spot=45.32, iv=0.302)
    assert s is not None
    assert s.breakeven == pytest.approx(s.strike + s.est_premium, abs=0.01)
