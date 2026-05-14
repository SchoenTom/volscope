"""
Safe coercion helpers for row-level data from pandas DataFrames.

pandas uses `pd.NA` as the missing-value marker for nullable int / string
extension dtypes. The idiomatic Python `value or default` fallback is
broken against `pd.NA` — the `or` operator calls `bool(pd.NA)` which raises
`TypeError: boolean value of NA is ambiguous`.

Every place in the codebase that used to write `row.get("col") or 0` was a
ticking bomb waiting for the first scrape to produce a nullable-int column.
These helpers replace the pattern with a single-import safe form:

    from volscope.utils.safe import safe_num, safe_int, safe_str

    vol = safe_num(row.get("total_call_volume"), default=0)
"""
from __future__ import annotations

from typing import Any

import pandas as pd


def is_missing(value: Any) -> bool:
    """True if `value` is Python None, numpy nan, or pandas NA."""
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def safe_num(value: Any, default: float = 0.0) -> float:
    """Coerce to float, returning `default` on missing / uncoercible input."""
    if is_missing(value):
        return float(default)
    try:
        f = float(value)
    except (TypeError, ValueError):
        return float(default)
    if f != f:  # NaN check
        return float(default)
    return f


def safe_int(value: Any, default: int = 0) -> int:
    """Coerce to int, returning `default` on missing / uncoercible input."""
    if is_missing(value):
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def safe_str(value: Any, default: str = "") -> str:
    """Coerce to str, returning `default` on missing input."""
    if is_missing(value):
        return str(default)
    try:
        return str(value)
    except Exception:
        return str(default)
