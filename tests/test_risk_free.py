"""Risk-free rate term structure (FRED) tests."""
from __future__ import annotations

import volscope.data.risk_free as rf
from volscope.config import RISK_FREE_RATE


def setup_function(_):
    rf.reset_cache()


def teardown_function(_):
    rf.reset_cache()


def test_get_rate_falls_back_when_curve_empty(monkeypatch):
    monkeypatch.setattr(rf, "_fetch_one", lambda series: None)
    rf.reset_cache()
    assert rf.get_rate(30) == RISK_FREE_RATE


def test_get_rate_interpolates_on_curve(monkeypatch):
    fake_curve = {30: 0.040, 90: 0.045, 180: 0.048, 365: 0.050}

    def fake_fetch(series: str):
        return {
            "DGS1MO": 0.040,
            "DGS3MO": 0.045,
            "DGS6MO": 0.048,
            "DGS1": 0.050,
        }[series]

    monkeypatch.setattr(rf, "_fetch_one", fake_fetch)
    rf.reset_cache()

    assert abs(rf.get_rate(30) - 0.040) < 1e-9
    assert abs(rf.get_rate(90) - 0.045) < 1e-9
    assert abs(rf.get_rate(365) - 0.050) < 1e-9
    # Linear interpolation midpoint between 90 and 180 days
    mid = rf.get_rate(135)
    assert 0.045 < mid < 0.048


def test_get_rate_extrapolates_to_endpoints(monkeypatch):
    monkeypatch.setattr(
        rf,
        "_fetch_one",
        lambda series: {"DGS1MO": 0.04, "DGS3MO": 0.045, "DGS6MO": 0.05, "DGS1": 0.055}[series],
    )
    rf.reset_cache()
    assert abs(rf.get_rate(7) - 0.04) < 1e-9   # below shortest → take shortest
    assert abs(rf.get_rate(800) - 0.055) < 1e-9  # above longest → take longest


def test_get_rate_rejects_implausible_yield(monkeypatch):
    """A bogus 50% yield from FRED should be filtered out."""
    monkeypatch.setattr(rf, "_fetch_one", lambda series: 0.50)
    rf.reset_cache()
    assert rf.get_rate(30) == RISK_FREE_RATE
