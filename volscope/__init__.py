"""
VolScope — Volatility Intelligence Platform.

Version + commit SHA exposed as module-level constants. The SHA is
read once at import time (single subprocess call to ``git`` ~50 ms);
all subsequent accesses are free string lookups. Streamlit renders
this in the footer so the operator always knows which commit is
running.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

__version__ = "0.8.0"


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
