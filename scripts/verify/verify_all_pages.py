#!/usr/bin/env python
"""
Exhaustive page-by-page verification using streamlit.testing.v1.AppTest.

For every entry in `_PAGE_REGISTRY`:
  1. Drive the app, navigate to the page via session-state injection.
  2. Run a single render pass.
  3. Report any uncaught exception, any "error card" rendered by the
     app's own error boundary, and the first 200 chars of the rendered
     markdown body so we know it isn't accidentally empty.

Run from project root:
    python scripts/verify_all_pages.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from streamlit.testing.v1 import AppTest                                 # noqa: E402

# Pages we want to exercise. Match _PAGE_REGISTRY in volscope/ui/app.py.
PAGES = [
    "Onboarding", "Command", "Portfolio", "Mega-Scan", "Discover",
    "Scope", "Scanner", "Heatmap", "Rotation", "Flow",
    "Pre-Trade", "LEAPS Lab", "Dossier", "Backtest", "Help",
]

APP_PATH = str(_ROOT / "volscope" / "ui" / "app.py")
TIMEOUT_SECONDS = 30


def _summarise_at(at: AppTest) -> dict:
    """Pull a digest of what was rendered so we can spot empty pages."""
    out = {
        "n_markdown":       len(at.markdown),
        "n_buttons":        len(at.button),
        "n_columns":        len(at.columns),
        "n_caption":        len(at.caption),
        "n_warning":        len(at.warning),
        "n_error":          len(at.error),
        "n_info":           len(at.info),
        "n_success":        len(at.success),
        "n_dataframe":      len(at.dataframe),
        "n_table":          len(at.table),
        "n_metric":         len(at.metric),
        "n_expander":       len(at.expander),
        "n_selectbox":      len(at.selectbox),
        "n_slider":         len(at.slider),
        "n_number_input":   len(at.number_input),
        "n_text_input":     len(at.text_input),
    }
    # First markdown snippet so we know the page rendered something
    if at.markdown:
        out["first_markdown_excerpt"] = at.markdown[0].value[:160]
    if at.error:
        out["error_msgs"] = [e.value[:200] for e in at.error]
    if at.warning:
        out["warning_msgs"] = [w.value[:200] for w in at.warning]
    return out


def verify_page(page: str) -> dict:
    """Run one page and capture everything."""
    try:
        at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_SECONDS)
        # Inject the desired page before the first run so the app's
        # default-landing logic doesn't override us.
        at.session_state["active_page"]      = page
        at.session_state["selected_ticker"]  = "PYPL"
        at.session_state["dossier_ticker"]   = "PYPL"
        at.session_state["onboarding_complete"] = True
        at.run()
    except Exception as exc:
        return {
            "page":   page,
            "status": "CRASHED-OUTER",
            "error":  f"{type(exc).__name__}: {exc}",
        }

    # Did the app raise an unhandled exception in the body?
    if at.exception:
        return {
            "page":   page,
            "status": "EXCEPTION-IN-BODY",
            "error":  str(at.exception[0].value)[:300],
            **_summarise_at(at),
        }

    summary = _summarise_at(at)
    # Heuristic: "import-error card" rendered by _render_import_error in
    # app.py contains the exact phrase "unavailable — import failed". The
    # raw HTML appears in the markdown body, not as st.error.
    body = " ".join(m.value for m in at.markdown)
    if "unavailable — import failed" in body or "render failed" in body:
        return {
            "page":   page,
            "status": "PAGE-ERROR-CARD",
            "error":  "app's error boundary fired; check terminal log",
            **summary,
        }

    # Has the page rendered anything visible?
    visible_count = (
        summary["n_markdown"] + summary["n_metric"] + summary["n_dataframe"]
        + summary["n_table"]  + summary["n_caption"]
    )
    if visible_count == 0:
        return {"page": page, "status": "EMPTY", **summary}

    return {"page": page, "status": "OK", **summary}


def main() -> int:
    print(f"Verifying {len(PAGES)} pages from {APP_PATH}")
    print("-" * 80)
    results = []
    for page in PAGES:
        print(f"… {page}", end=" ", flush=True)
        r = verify_page(page)
        results.append(r)
        flag = {
            "OK":                 "✓",
            "EMPTY":              "∅",
            "EXCEPTION-IN-BODY":  "✗",
            "CRASHED-OUTER":      "✗",
            "PAGE-ERROR-CARD":    "⚠",
        }.get(r["status"], "?")
        print(flag, r["status"])
        if r["status"] != "OK":
            err = r.get("error", "")
            if err:
                print(f"     {err}")
    print("-" * 80)

    n_ok = sum(1 for r in results if r["status"] == "OK")
    n_fail = sum(1 for r in results if r["status"] in ("EXCEPTION-IN-BODY", "CRASHED-OUTER"))
    n_warn = sum(1 for r in results if r["status"] in ("EMPTY", "PAGE-ERROR-CARD"))
    print(f"OK {n_ok} · WARN {n_warn} · FAIL {n_fail} · TOTAL {len(PAGES)}")

    print("\n=== Per-page digest ===")
    for r in results:
        if r["status"] == "OK":
            print(f"\n[{r['page']}]")
            keys = ("n_markdown", "n_buttons", "n_columns", "n_metric",
                    "n_dataframe", "n_caption", "n_expander", "n_selectbox",
                    "n_slider", "n_warning", "n_info", "n_success")
            for k in keys:
                if r.get(k):
                    print(f"  {k}={r[k]}")
            if "first_markdown_excerpt" in r:
                excerpt = r["first_markdown_excerpt"].replace("\n", " ")[:120]
                print(f"  excerpt: {excerpt!r}")
            if r.get("warning_msgs"):
                for w in r["warning_msgs"]:
                    print(f"  WARN: {w}")
        else:
            print(f"\n[{r['page']}] {r['status']}")
            for k, v in r.items():
                if k not in ("page", "status"):
                    print(f"  {k}: {v}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
