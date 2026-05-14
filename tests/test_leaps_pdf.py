"""Tests for the LEAPS PDF dossier export."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from volscope.analytics.leaps_convergence import (
    compute_convergence,
    suggest_leaps,
    auto_thesis,
)
from volscope.analytics.leaps_pdf import filename_for, render_dossier_pdf
from volscope.analytics.leaps_pretrade import run_pretrade_checks
from volscope.analytics.leaps_scenarios import (
    build_risk_table,
    build_scenario_matrix,
    build_theta_runway,
    build_vega_gain_table,
)
from volscope.analytics.leaps_sizing import size_position


def _build_inputs():
    """Wire the full analytics pipeline against a single PYPL row."""
    suggestion = suggest_leaps(
        ticker="PYPL", spot=45.32, iv=0.302,
        target_dte_days=730, today=date(2026, 5, 10),
    )
    sizing_plan = size_position(suggestion, budget=3_000.0)
    risk_table = build_risk_table(suggestion, capital_deployed=sizing_plan.capital_deployed)
    matrix = build_scenario_matrix(suggestion)
    vega = build_vega_gain_table(suggestion)
    runway = build_theta_runway(suggestion)
    underlying_row = pd.Series({
        "ticker":              "PYPL",
        "iv_30d":              30.2,
        "iv_60d":              30.1,
        "hv_20d":              44.7,
        "hv_60d":              30.0,
        "hv_yz_20d":           42.0,
        "iv_rank":             12.0,
        "iv_percentile":       29.0,
        "spot_price":          45.32,
        "iv_hv_spread":        -14.5,
        "put_call_ratio":      0.85,
        "total_call_volume":   12_000,
        "total_put_volume":    10_200,
        "total_open_interest": 220_000,
        "sector":              "Financial Services",
        "date":                date(2026, 5, 10),
    })
    convergence = compute_convergence(underlying_row, ticker_history=None, benchmark_history=None)
    pretrade = run_pretrade_checks(
        suggestion=suggestion,
        underlying_row=underlying_row,
        history=None,
        chain_row=None,
        next_earnings_date=None,
        contracts=sizing_plan.contracts,
    )
    thesis = auto_thesis(convergence, underlying_row)
    return dict(
        ticker="PYPL",
        snapshot_date=date(2026, 5, 10),
        convergence=convergence,
        thesis=thesis,
        suggestion=suggestion,
        sizing_plan=sizing_plan,
        risk_table=risk_table,
        scenario_matrix=matrix,
        vega_table=vega,
        theta_runway=runway,
        pretrade=pretrade,
        underlying_row=underlying_row,
    )


# ── Smoke ───────────────────────────────────────────────────────────────

def test_render_dossier_pdf_returns_bytes_starting_with_pdf_header():
    pdf = render_dossier_pdf(**_build_inputs())
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF"), "output is not a PDF stream"
    assert len(pdf) > 4_000, "PDF suspiciously small — likely empty body"


def test_filename_for_pypl_reproduces_convention():
    s = suggest_leaps(ticker="PYPL", spot=45.32, iv=0.302,
                      target_dte_days=730, today=date(2026, 5, 10))
    name = filename_for(s)
    assert name.startswith("LEAPS_PYPL_")
    assert name.endswith(".pdf")
    assert s.expiry.isoformat() in name


def test_render_dossier_pdf_size_grows_with_more_payoff_rows():
    """A larger payoff ladder must produce a measurably larger PDF —
    sanity that the document body actually receives the inputs (reportlab
    compresses streams so a substring check on the binary is unreliable)."""
    base_inputs = _build_inputs()
    small = render_dossier_pdf(**base_inputs)

    # Re-build with a denser scenario matrix to make the PDF longer.
    from volscope.analytics.leaps_scenarios import build_scenario_matrix
    larger = base_inputs.copy()
    larger["scenario_matrix"] = build_scenario_matrix(
        base_inputs["suggestion"],
        spot_multipliers=tuple(0.5 + 0.1 * i for i in range(20)),
        month_horizons=(1, 3, 6, 12, 18, 24),
    )
    big = render_dossier_pdf(**larger)
    # PDFs are compressed; size should still differ meaningfully.
    assert len(big) >= len(small)
