"""Smoke tests for the LEAPS dossier page wiring.

Streamlit pages are notoriously hard to test directly without booting
the server, so we verify the seams: imports succeed, the renderer is
callable, and the page is registered in the app's lazy registry.
"""
from __future__ import annotations


def test_dossier_module_imports_cleanly():
    """If any of the analytics modules fail at import time, the dossier
    page will silently break. Catch it here."""
    from volscope.ui.views import leaps_dossier_page          # noqa: F401
    from volscope.analytics import leaps_sizing               # noqa: F401
    from volscope.analytics import leaps_scenarios            # noqa: F401
    from volscope.analytics import leaps_pretrade             # noqa: F401
    from volscope.analytics import leaps_pdf                  # noqa: F401
    from volscope.analytics import leaps_watchlist            # noqa: F401


def test_dossier_renderer_is_registered():
    """The Dossier page must appear in the lazy registry the sidebar
    reads from, and be importable via the same path."""
    from volscope.ui.app import _PAGE_REGISTRY, _load_renderer
    assert "Dossier" in _PAGE_REGISTRY
    fn = _load_renderer("Dossier")
    assert callable(fn)


def test_leaps_lab_still_importable_after_dossier_addition():
    """Adding the Dossier page must not regress the Lab Index page."""
    from volscope.ui.app import _load_renderer
    assert callable(_load_renderer("LEAPS Lab"))


def test_dossier_module_exposes_expected_helpers():
    """Spot-check the rendering helpers the page composes from."""
    from volscope.ui.views.leaps_dossier_page import (
        _est_chip,
        _render_header,
        _render_sizing_section,
        _render_risk_section,
        _render_instrument_section,
        _render_anomaly_section,
        _render_scenarios_section,
        _render_execution_section,
        render_leaps_dossier_page,
    )
    # _est_chip is pure, can be called directly.
    chip_html = _est_chip()
    assert "EST" in chip_html
    assert "BSM" in chip_html


def test_alert_engine_understands_convergence_score_metric():
    """The 'add convergence alert' CTA writes a rule with metric =
    'convergence_score'. The engine must recognise it."""
    import pandas as pd
    from volscope.alerts.alert_engine import compute_metric_value
    row = pd.Series({"convergence_score": 72.5})
    assert compute_metric_value("convergence_score", row) == 72.5
    # Unknown metric returns None, not a crash.
    assert compute_metric_value("not_a_real_metric", row) is None
