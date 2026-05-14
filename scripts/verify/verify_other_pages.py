#!/usr/bin/env python
"""
Smoke-verify every non-LEAPS page renders without raising.

Skips Onboarding because it makes network calls (Yahoo + Deribit) at
render time and dominates total runtime — it is verified separately on
the live HTTP endpoint.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

from streamlit.testing.v1 import AppTest                                 # noqa: E402

APP_PATH = str(_ROOT / "volscope" / "ui" / "app.py")
TIMEOUT = 60

PAGES = [
    "Command", "Portfolio", "Mega-Scan", "Discover",
    "Scope", "Scanner", "Heatmap", "Rotation", "Flow",
    "Pre-Trade", "LEAPS Lab", "Dossier", "Backtest", "Help",
]


def verify(page: str) -> tuple[str, dict]:
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT)
    at.session_state["active_page"]      = page
    at.session_state["selected_ticker"]  = "PYPL"
    at.session_state["dossier_ticker"]   = "PYPL"
    at.session_state["onboarding_complete"] = True
    try:
        at.run()
    except Exception as exc:
        return "CRASHED-OUTER", {"error": f"{type(exc).__name__}: {exc}"}

    if at.exception:
        return "EXCEPTION", {"error": str(at.exception[0].value)[:200]}

    body = " ".join(m.value for m in at.markdown)
    if "unavailable — import failed" in body or "render failed" in body:
        return "ERROR-CARD", {"error": "app's error boundary fired"}

    n_visible = (len(at.markdown) + len(at.metric) + len(at.dataframe)
                 + len(at.table) + len(at.caption))
    if n_visible == 0:
        return "EMPTY", {"markdown_count": 0}

    return "OK", {
        "markdown": len(at.markdown),
        "buttons":  len(at.button),
        "metric":   len(at.metric),
        "expander": len(at.expander),
        "dataframe": len(at.dataframe),
        "warning":  len(at.warning),
        "info":     len(at.info),
        "error":    len(at.error),
        "first_excerpt": (at.markdown[0].value[:120].replace("\n", " ")
                          if at.markdown else ""),
    }


def main() -> int:
    print(f"Verifying {len(PAGES)} pages")
    print("=" * 80)
    results = []
    for page in PAGES:
        print(f"… {page} ", end="", flush=True)
        status, detail = verify(page)
        results.append((page, status, detail))
        flag = {"OK": "✓", "EMPTY": "∅", "ERROR-CARD": "⚠",
                "EXCEPTION": "✗", "CRASHED-OUTER": "✗"}.get(status, "?")
        print(f"{flag} {status}")
        if status != "OK":
            print(f"     {detail.get('error', detail)}")

    print()
    print("=" * 80)
    n_ok = sum(1 for _, s, _ in results if s == "OK")
    n_fail = sum(1 for _, s, _ in results if s in ("EXCEPTION", "CRASHED-OUTER"))
    n_warn = sum(1 for _, s, _ in results if s in ("EMPTY", "ERROR-CARD"))
    print(f"OK {n_ok} · WARN {n_warn} · FAIL {n_fail} · TOTAL {len(PAGES)}")

    print()
    print("Per-page detail:")
    for page, status, detail in results:
        if status == "OK":
            keys = ["markdown", "buttons", "metric", "expander", "dataframe",
                    "warning", "info", "error"]
            stats = " · ".join(f"{k}={detail[k]}" for k in keys if detail.get(k))
            excerpt = detail.get("first_excerpt", "")
            print(f"  {page:14s} {stats}")
            if excerpt:
                print(f"  {' '*14} excerpt: {excerpt!r}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
