"""
Universe loader — robust bulk ingestion of the curated ticker list.

The existing sidebar bulk-load works but is fragile: a single transient
yfinance failure can stall the whole run, no retry, no resume. This
module implements a production-grade loader with:

  - **Idempotency** — already-loaded tickers are skipped
  - **Per-ticker retry** — exponential backoff on transient errors
  - **Partial-failure logging** — failed tickers persisted to JSONL so
    a re-run can resume from there
  - **Streaming progress** — yields per-ticker status events
  - **Time budgeting** — caller can cap wall-clock seconds

The pure-logic core ``load_universe()`` is callable from a CLI script
(scripts/ops/load_universe.py) and from the Streamlit sidebar. UI streams
progress events with a callback; tests pass synthetic callbacks.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

ROOT_DATA = Path(__file__).resolve().parents[2] / "data"
LOAD_DIR = ROOT_DATA / "load"


# ── Public output types ─────────────────────────────────────────────────

@dataclass(frozen=True)
class TickerOutcome:
    """One ticker's load outcome — emitted as a stream event."""
    ticker:        str
    status:        str           # "skipped" | "loaded" | "failed" | "retried"
    rows_written:  int = 0
    attempts:      int = 1
    message:       str = ""


@dataclass
class LoadReport:
    """Aggregated report for one full universe-load run."""
    started_at:   str
    elapsed_s:    float
    n_total:      int
    n_skipped:    int
    n_loaded:     int
    n_failed:     int
    failures:     list[dict] = field(default_factory=list)

    def coverage_pct(self) -> float:
        attempted = self.n_total - self.n_skipped
        if attempted <= 0:
            return 0.0
        return (self.n_loaded / attempted) * 100.0


# ── Configuration ──────────────────────────────────────────────────────

# Per-ticker retry parameters. Tuned for yfinance's intermittent 429s.
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.5     # seconds; doubled on each retry
_RETRY_FACTOR = 2.0


# ── Core loop ──────────────────────────────────────────────────────────

ProgressCallback = Callable[[TickerOutcome, int, int], None]


def load_universe(
    db,
    tickers:           Optional[Iterable[str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
    max_seconds:       Optional[float] = None,
    retry_attempts:    int = _RETRY_ATTEMPTS,
) -> LoadReport:
    """Bulk-load tickers into the DB.

    Parameters
    ----------
    db                : VolScopeDB instance.
    tickers           : Iterable of Yahoo symbols (default: full curated universe).
    progress_callback : Called as ``cb(outcome, idx, total)`` after each ticker.
    max_seconds       : Optional wall-clock budget. Loader stops cleanly at the
                        next ticker boundary if exceeded; remaining tickers are
                        reported as skipped (not failed).
    retry_attempts    : Per-ticker retry count.

    Returns
    -------
    LoadReport
        Always a valid object — never raises. Callers persist + render.
    """
    from volscope.data.ticker_resolver import resolve_and_ingest
    from volscope.data.ticker_universe import all_tickers

    target_list = list(tickers) if tickers is not None else list(all_tickers())
    started = time.time()

    try:
        existing = set(db.get_available_tickers() or [])
    except Exception as exc:
        log.warning("get_available_tickers failed: %s", exc)
        existing = set()

    n_skipped = 0
    n_loaded = 0
    n_failed = 0
    failures: list[dict] = []
    total = len(target_list)

    for idx, raw in enumerate(target_list, start=1):
        # Time budget check — stop cleanly at boundary
        if max_seconds is not None and (time.time() - started) >= max_seconds:
            outcome = TickerOutcome(
                ticker=str(raw),
                status="skipped",
                message="time budget exhausted",
            )
            n_skipped += 1
            if progress_callback is not None:
                progress_callback(outcome, idx, total)
            continue

        # Idempotency — skip already-loaded
        sym = (raw or "").strip().upper()
        if sym in existing:
            outcome = TickerOutcome(
                ticker=sym, status="skipped", message="already loaded",
            )
            n_skipped += 1
            if progress_callback is not None:
                progress_callback(outcome, idx, total)
            continue

        # Try with backoff
        outcome = _ingest_with_retry(db, sym, retry_attempts)
        if outcome.status == "loaded" or outcome.status == "retried":
            n_loaded += 1
            existing.add(outcome.ticker)
        else:
            n_failed += 1
            failures.append({
                "ticker":  outcome.ticker,
                "attempts": outcome.attempts,
                "message": outcome.message,
            })
        if progress_callback is not None:
            progress_callback(outcome, idx, total)

    elapsed = time.time() - started
    report = LoadReport(
        started_at=datetime.fromtimestamp(started).isoformat(timespec="seconds"),
        elapsed_s=round(elapsed, 1),
        n_total=total,
        n_skipped=n_skipped,
        n_loaded=n_loaded,
        n_failed=n_failed,
        failures=failures,
    )
    return report


def _ingest_with_retry(db, sym: str, attempts: int) -> TickerOutcome:
    """Resolve+ingest one ticker with exponential backoff on failure.

    Returns a TickerOutcome reflecting the FINAL outcome — "loaded" on
    first-try success, "retried" if a later attempt succeeded, "failed"
    if all attempts exhausted.
    """
    from volscope.data.ticker_resolver import resolve_and_ingest
    last_msg = ""
    for attempt in range(1, max(1, attempts) + 1):
        try:
            res = resolve_and_ingest(db, sym)
            if res.ok:
                return TickerOutcome(
                    ticker=res.ticker, status=("loaded" if attempt == 1 else "retried"),
                    rows_written=res.rows_written, attempts=attempt,
                    message=res.message,
                )
            last_msg = res.message
        except Exception as exc:
            last_msg = f"{exc.__class__.__name__}: {exc}"

        # Backoff before next attempt unless this was the last one
        if attempt < attempts:
            delay = _RETRY_BASE_DELAY * (_RETRY_FACTOR ** (attempt - 1))
            time.sleep(min(delay, 12.0))

    return TickerOutcome(
        ticker=sym, status="failed", attempts=attempts, message=last_msg,
    )


# ── Persistence ────────────────────────────────────────────────────────

def persist_report(report: LoadReport) -> Path:
    """Persist the report (and failures) to data/load/<ts>.report.json
    and data/load/<ts>.failures.jsonl. Returns the report path.

    The JSONL is in the format expected by ``resume_failures``.
    """
    LOAD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = LOAD_DIR / f"{stamp}.report.json"
    failures_path = LOAD_DIR / f"{stamp}.failures.jsonl"

    report_path.write_text(json.dumps(asdict(report), indent=2))
    if report.failures:
        with failures_path.open("w") as f:
            for failure in report.failures:
                f.write(json.dumps(failure) + "\n")
    return report_path


def latest_failures_file() -> Optional[Path]:
    """Return the most-recent failures.jsonl path, or None."""
    if not LOAD_DIR.exists():
        return None
    files = sorted(LOAD_DIR.glob("*.failures.jsonl"))
    return files[-1] if files else None


def resume_failures() -> list[str]:
    """Read the latest failures file and return its tickers as a fresh load list."""
    fpath = latest_failures_file()
    if fpath is None or not fpath.exists():
        return []
    out: list[str] = []
    for line in fpath.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        t = entry.get("ticker")
        if t:
            out.append(str(t))
    return out
