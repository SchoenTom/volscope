"""
VolScope — Volatility Intelligence Platform.

Version + commit SHA exposed as module-level constants. The SHA is
read once at import time (single subprocess call to ``git`` ~50 ms);
all subsequent accesses are free string lookups. Streamlit renders
this in the footer so the operator always knows which commit is
running.
"""
from __future__ import annotations


# ── Anaconda-version compatibility shim ─────────────────────────────
# Python 3.13.9 distributed by Anaconda produces a `sys.version` string
# like
#     '3.13.9 | packaged by Anaconda, Inc. | (main, Oct 21 2025, ...) ...'
# with TWO `| ... |` segments. CPython's `platform._sys_version()`
# regex only handles ONE such segment, so it raises
#     ValueError: failed to parse CPython sys.version: ...
# the first time pandas calls `platform.python_implementation()` at
# import. Result: every Streamlit page that touches pandas explodes.
#
# Operator hit this on 2026-05-19 — their `.venv/bin/python3` symlinks
# to `/opt/anaconda3/bin/python3`, exactly the failing combination.
#
# Fix: pre-emptively normalise `sys.version` BEFORE anything imports
# pandas (this module runs on every `import volscope`, which sits
# above pandas in the dep graph).
import sys as _sys
if (
    "Anaconda" in _sys.version
    and _sys.version.count("|") >= 2
):
    # Strip the "| packaged by Anaconda, Inc. |" segment.
    _parts = _sys.version.split("|")
    if len(_parts) >= 3:
        _normalised = _parts[0].strip() + " " + " ".join(p.strip() for p in _parts[2:])
        try:
            _sys.version = _normalised
        except Exception:  # noqa: BLE001
            pass


import subprocess
from pathlib import Path

__version__ = "0.9.2"


def _read_commit_sha() -> str:
    """Return the short HEAD SHA, or ``"unknown"`` on any failure."""
    repo_root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out or "unknown"
    except Exception:                               # noqa: BLE001
        return "unknown"


__commit__ = _read_commit_sha()
