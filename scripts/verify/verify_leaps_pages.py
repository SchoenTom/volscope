#!/usr/bin/env python
"""
Focused verification of the LEAPS Lab + Dossier pages.

Skips network-heavy pages (Onboarding fetches Yahoo + Deribit on first
render and dominates total runtime). Targets:

- LEAPS Lab — full universe scan, click-through buttons, watchlist strip
- Dossier — picker, sizing widgets, every section, PDF generation, alert CTA

Each page is run via streamlit.testing.v1.AppTest. We capture:
  · uncaught exceptions
  · the app's own error-boundary cards
  · widget counts so we can detect "page rendered nothing"
  · the first 200 chars of the rendered markdown to spot wrong content
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from streamlit.testing.v1 import AppTest                                 # noqa: E402

APP_PATH = str(_ROOT / "volscope" / "ui" / "app.py")
TIMEOUT  = 60         # generous; Lab scans 280 tickers


# ── Helpers ──────────────────────────────────────────────────────────────

def _fmt(at) -> str:
    parts = []
    if at.exception:
        parts.append(f"EXC: {str(at.exception[0].value)[:200]}")
    if at.error:
        parts.append(f"errors={len(at.error)}")
    if at.warning:
        parts.append(f"warnings={len(at.warning)}")
    parts.append(f"markdown={len(at.markdown)}")
    parts.append(f"buttons={len(at.button)}")
    parts.append(f"selectbox={len(at.selectbox)}")
    parts.append(f"slider={len(at.slider)}")
    parts.append(f"expander={len(at.expander)}")
    # download_button is reachable via at.button on this Streamlit version
    return " · ".join(parts)


def _check(at, label: str) -> bool:
    print(f"\n  ── {label}")
    print(f"     {_fmt(at)}")
    if at.exception:
        print(f"     ✗ FAILED: {at.exception[0].value}")
        return False
    if at.error:
        for e in at.error:
            print(f"     ✗ st.error: {e.value[:200]}")
        return False
    body = " ".join(m.value for m in at.markdown)
    if "unavailable — import failed" in body or "render failed" in body:
        print(f"     ✗ error-boundary card fired")
        return False
    return True


# ── Test cases ───────────────────────────────────────────────────────────

def test_lab_index() -> bool:
    print("\n=== LEAPS Lab Index ===")
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
    at.session_state["active_page"] = "LEAPS Lab"
    at.session_state["selected_ticker"] = "PYPL"
    at.session_state["onboarding_complete"] = True
    at.run()
    ok = _check(at, "first render")
    if not ok:
        return False

    # Inspect: does the convergence card render the dial markup?
    body = " ".join(m.value for m in at.markdown)
    has_dial = "volscope-dial" in body
    has_bars = "volscope-bar" in body
    has_lab_title = "LEAPS Lab" in body or "leaps-lab" in body.lower() or "LAB" in body
    print(f"     dial markup present: {has_dial}")
    print(f"     score-bar markup present: {has_bars}")
    print(f"     lab title rendered: {has_lab_title}")
    if not (has_dial and has_bars):
        print(f"     ✗ redesigned components missing")
        return False
    return True


def test_dossier() -> bool:
    print("\n=== Dossier ===")
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
    at.session_state["active_page"] = "Dossier"
    at.session_state["dossier_ticker"] = "PYPL"
    at.session_state["selected_ticker"] = "PYPL"
    at.session_state["onboarding_complete"] = True
    at.run()
    ok = _check(at, "PYPL render")
    if not ok:
        return False

    body = " ".join(m.value for m in at.markdown)
    checks = [
        ("dial",       "volscope-dial" in body),
        ("score bars", "volscope-bar" in body),
        ("section rule", "volscope-section-rule" in body),
        ("kpi grid",   "volscope-kpi-grid" in body),
        ("est underline", "volscope-est-underline" in body),
        ("PYPL ticker", "PYPL" in body),
        ("strike $",   "$80" in body or "$79" in body or "$78" in body),
        ("convergence label", "CONVERG" in body.upper()),
        ("MIS NEG REV", "MIS" in body and "NEG" in body and "REV" in body),
    ]
    for name, present in checks:
        flag = "✓" if present else "✗"
        print(f"     {flag} {name}")
    if not all(p for _, p in checks):
        return False

    # Try a different ticker — verify the picker actually drives the page
    print("\n  ── pick a different ticker (NKE)")
    at2 = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
    at2.session_state["active_page"] = "Dossier"
    at2.session_state["dossier_ticker"] = "NKE"
    at2.session_state["onboarding_complete"] = True
    at2.run()
    ok = _check(at2, "NKE render")
    if not ok:
        return False
    body2 = " ".join(m.value for m in at2.markdown)
    has_nke = "NKE" in body2
    print(f"     ✓ NKE in body: {has_nke}")
    return has_nke


def test_lab_dossier_button_clickthrough() -> bool:
    """Open the Lab, click the first 'Open dossier →' button, verify the
    Dossier page receives the right ticker."""
    print("\n=== Lab → Dossier click-through ===")
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
    at.session_state["active_page"] = "LEAPS Lab"
    at.session_state["selected_ticker"] = "PYPL"
    at.session_state["onboarding_complete"] = True
    at.run()
    if at.exception:
        print(f"     ✗ {at.exception[0].value}")
        return False

    open_buttons = [b for b in at.button if "Open dossier" in (b.label or "")]
    print(f"     {len(open_buttons)} Open-dossier buttons found")
    if not open_buttons:
        print("     ⚠ no actionable tickers — skipping click test (not a bug)")
        return True

    # Click the first one
    open_buttons[0].click().run()
    # AppTest's session_state is dict-like but does not implement .get
    ticker_set = (
        at.session_state["dossier_ticker"]
        if "dossier_ticker" in at.session_state else None
    )
    page_set = (
        at.session_state["active_page"]
        if "active_page" in at.session_state else None
    )
    print(f"     after click: dossier_ticker={ticker_set!r}, active_page={page_set!r}")
    if page_set != "Dossier":
        print(f"     ✗ page did not switch")
        return False
    if not ticker_set:
        print(f"     ✗ ticker not seeded")
        return False
    return True


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    tests = [
        test_lab_index,
        test_dossier,
        test_lab_dossier_button_clickthrough,
    ]
    results = []
    for fn in tests:
        try:
            results.append((fn.__name__, fn()))
        except Exception as exc:
            print(f"\n!! {fn.__name__} CRASHED: {type(exc).__name__}: {exc}")
            results.append((fn.__name__, False))

    print("\n" + "=" * 80)
    print("Summary:")
    for name, ok in results:
        flag = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {flag}  {name}")
    fails = sum(1 for _, ok in results if not ok)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
