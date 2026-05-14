# scripts/verify/

End-to-end regression scripts. `verify_all.py` is the canonical smoke.

- `verify.py` — quick pre-commit verification.
- `verify_all.py` — 7-stage end-to-end (tests, BSM, render, invariants, suspect rows, sector daily, backtest).
- `verify_all_pages.py` / `verify_leaps_pages.py` / `verify_other_pages.py` — Streamlit page renderers.
