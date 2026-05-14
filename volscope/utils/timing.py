"""
Lightweight performance instrumentation.

Wraps callable code blocks, captures elapsed time, and appends a JSONL
record under ``data/perf/<date>.jsonl`` for offline analysis. The dev
panel reads these files to surface p50/p95 timings per instrumented
name.

Design constraints
------------------
- **Zero overhead when not used**: import is cheap; not calling the
  context manager is free.
- **< 1 ms per call when used**: single ``time.perf_counter`` pair plus
  a single line append. No locks (OS guarantees < 4 KB writes are
  atomic on POSIX for our use).
- **Fail-quiet**: instrumentation failures (disk full, permission)
  must never break the wrapped code path. Errors swallowed, logged.
- **Bounded growth**: callers wrap *page-level* functions, not hot-path
  per-row analytics. Wrapping a function called 300 times per render
  will produce 300 lines per render — explicitly disallowed by the
  documented usage pattern.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import date
from functools import wraps
from pathlib import Path
from typing import Callable, Iterator, Optional, TypeVar

log = logging.getLogger(__name__)

_PERF_DIR = Path(__file__).resolve().parents[2] / "data" / "perf"


F = TypeVar("F", bound=Callable)


@contextmanager
def instrument(name: str, extra: Optional[dict] = None) -> Iterator[None]:
    """Time a code block and append a record to today's JSONL.

    Usage
    -----
    >>> with instrument("page.megascan", {"n_tickers": 283}):
    ...     render_megascan_page(db, settings)

    The record schema is::

        {
          "ts":         <unix epoch float>,
          "name":       "page.megascan",
          "elapsed_ms": 423.7,
          "n_tickers":  283
        }

    Parameters
    ----------
    name  : Stable identifier for the wrapped code path. Convention:
            ``"page.<short>"`` for page renders,
            ``"analytics.<short>"`` for heavy analytics,
            ``"db.<short>"`` for DB queries.
    extra : Optional dict merged into the JSONL record. Useful for
            cardinality-tagging (n_tickers, n_positions, etc.). Keep
            keys finite — high-cardinality tags break aggregation.

    Failure mode
    ------------
    If the JSONL append fails, the failure is logged at WARNING level
    and silently swallowed. The wrapped code is unaffected.
    """
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        try:
            _append_record(name, elapsed_ms, extra)
        except Exception as exc:
            log.warning("instrument(%s) failed to persist: %s", name, exc)


def instrumented(name: str) -> Callable[[F], F]:
    """Decorator form — wraps a function call with ``instrument(name)``.

    Usage
    -----
    >>> @instrumented("analytics.edge_table")
    ... def compute_edge_table(...): ...

    Note: the decorator reads no arguments by design. If you need
    per-call extra fields, use the context-manager form inside the
    function body.
    """
    def deco(fn: F) -> F:
        @wraps(fn)
        def inner(*args, **kwargs):
            with instrument(name):
                return fn(*args, **kwargs)
        return inner  # type: ignore[return-value]
    return deco


def percentiles_for(
    name:  str,
    days:  int = 7,
    percs: tuple[int, ...] = (50, 95),
) -> dict[int, Optional[float]]:
    """Return percentile timings for a given instrument name.

    Reads the last ``days`` JSONL files, filters records by name, and
    computes the requested percentiles. Returns ``{p: None}`` for
    each percentile when no records found.

    Used by the dev panel; not by hot-path code.
    """
    samples: list[float] = []
    today = date.today()
    for d in range(days):
        target = today.fromordinal(today.toordinal() - d)
        fpath = _PERF_DIR / f"{target.isoformat()}.jsonl"
        if not fpath.exists():
            continue
        try:
            for line in fpath.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("name") == name:
                    ms = rec.get("elapsed_ms")
                    if isinstance(ms, (int, float)):
                        samples.append(float(ms))
        except Exception as exc:
            log.warning("percentiles_for read %s failed: %s", fpath, exc)
            continue

    out: dict[int, Optional[float]] = {p: None for p in percs}
    if not samples:
        return out
    samples.sort()
    n = len(samples)
    for p in percs:
        # Nearest-rank percentile, 1-based.
        rank = max(1, min(n, int(round(p / 100.0 * n))))
        out[p] = samples[rank - 1]
    return out


def list_instrumented_names(days: int = 7) -> list[str]:
    """Return distinct names seen in the last `days` JSONL files."""
    seen: set[str] = set()
    today = date.today()
    for d in range(days):
        target = today.fromordinal(today.toordinal() - d)
        fpath = _PERF_DIR / f"{target.isoformat()}.jsonl"
        if not fpath.exists():
            continue
        try:
            for line in fpath.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    name = json.loads(line).get("name")
                except Exception:
                    continue
                if isinstance(name, str):
                    seen.add(name)
        except Exception:
            continue
    return sorted(seen)


def n_records_for(name: str, days: int = 7) -> int:
    """Total record count for a given instrument name over N days."""
    n = 0
    today = date.today()
    for d in range(days):
        target = today.fromordinal(today.toordinal() - d)
        fpath = _PERF_DIR / f"{target.isoformat()}.jsonl"
        if not fpath.exists():
            continue
        try:
            for line in fpath.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    if json.loads(line).get("name") == name:
                        n += 1
                except Exception:
                    continue
        except Exception:
            continue
    return n


# ── Internal ─────────────────────────────────────────────────────────────

def _append_record(name: str, elapsed_ms: float, extra: Optional[dict]) -> None:
    _PERF_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts":         round(time.time(), 3),
        "name":       name,
        "elapsed_ms": round(elapsed_ms, 2),
    }
    if extra:
        for k, v in extra.items():
            # Skip non-JSON-serialisable values silently
            try:
                json.dumps(v)
                rec[k] = v
            except (TypeError, ValueError):
                pass
    fpath = _PERF_DIR / f"{date.today().isoformat()}.jsonl"
    with fpath.open("a") as f:
        f.write(json.dumps(rec) + "\n")
