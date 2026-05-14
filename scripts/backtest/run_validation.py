"""
VolScope data-validation runner — Pillar 2.

Standalone script. Idempotent. Cron-safe. Pulls the latest snapshot
from the DB, runs ``analytics.data_validator.validate_universe()`` over
all tickers, persists results to the ``validation_log`` table, and
dispatches a macOS notification when major tickers fail.

Run modes
---------
- ``python scripts/run_validation.py``          — full universe
- ``python scripts/run_validation.py --quiet``  — silent (cron use)
- ``python scripts/run_validation.py --dry-run`` — no persistence

Output artifacts
----------------
- ``validation_log`` DB table (one row per ticker × date)
- macOS notification on FAIL for major tickers
- ``data/audit/.last_validation.md`` — human-readable summary
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
sys.path.insert(0, str(ROOT))

from volscope.analytics.data_validator import (  # noqa: E402
    summarise_universe,
    validate_universe,
)
from volscope.data.database import VolScopeDB  # noqa: E402

# Tickers Tom actually trades — failures here trigger notifications.
_MAJOR_TICKERS: set[str] = {
    "SPY", "QQQ", "^VIX", "^GDAXI", "^NDX",
    "MSTR", "SNOW", "1810.HK", "NVDA",
}

_LAST_VALIDATION_PATH = ROOT / "data" / "audit" / ".last_validation.md"

log = logging.getLogger("validation")


def main() -> int:
    p = argparse.ArgumentParser(description="VolScope validation runner")
    p.add_argument("--quiet",   action="store_true", help="suppress info logging")
    p.add_argument("--dry-run", action="store_true", help="don't persist")
    args = p.parse_args()

    logging.basicConfig(
        format="[validation] %(message)s",
        level=logging.WARNING if args.quiet else logging.INFO,
    )

    db = VolScopeDB()
    latest = db.get_all_latest()
    if latest.empty:
        log.warning("no data in DB — skipping validation")
        return 0

    tickers = latest["ticker"].dropna().tolist() if "ticker" in latest.columns else []
    if not tickers:
        log.warning("no tickers — skipping")
        return 0

    log.info("validating %d tickers ...", len(tickers))
    histories = db.get_recent_for_tickers(tickers, lookback_days=30)

    # Cross-ticker proxy: feed the major vol indices' current IV30
    proxy_levels: dict[str, float] = {}
    for proxy in ["^VIX", "^VXN", "^RVX", "^VXFXI", "^GVZ", "^OVX"]:
        rows = latest[latest["ticker"] == proxy]
        if not rows.empty:
            try:
                proxy_levels[proxy] = float(rows.iloc[0]["iv_30d"])
            except Exception:
                pass

    t0 = time.time()
    reports = validate_universe(latest, histories, proxy_levels)
    elapsed = time.time() - t0
    summary = summarise_universe(reports)
    log.info("validation done in %.1fs: %s", elapsed, summary)

    if args.dry_run:
        log.info("dry-run — no persistence")
        return 0

    # Persist
    today = date.today()
    for r in reports:
        db.upsert_validation_report(
            ticker=r.ticker,
            target_date=today,
            overall_level=r.overall_level,
            n_passes=r.n_passes,
            n_flags=r.n_flags,
            n_fails=r.n_fails,
            details_json=json.dumps([asdict(f) for f in r.findings]),
        )

    # Dispatch notifications for major-ticker FAILs
    fails_for_major = [
        r for r in reports
        if r.ticker in _MAJOR_TICKERS and r.overall_level == "FAIL"
    ]
    if fails_for_major:
        body_parts = []
        for r in fails_for_major[:3]:
            first_fail = next((f for f in r.findings if f.level == "FAIL"), None)
            detail = (first_fail.detail[:60] if first_fail else "data anomaly")
            body_parts.append(f"{r.ticker}: {detail}")
        body = " · ".join(body_parts).replace('"', "'")
        try:
            subprocess.Popen(
                ["osascript", "-e",
                 f'display notification "{body}" with title "VolScope: validation FAIL"'],
                start_new_session=True,
            )
        except Exception as exc:
            log.warning("notification dispatch failed: %s", exc)

    # Human-readable summary
    _LAST_VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    md_lines = [
        f"# VolScope Validation — {today.isoformat()}",
        "",
        f"**Universe:** {summary['n_total']} tickers · "
        f"**OK:** {summary['n_ok']} · "
        f"**FLAG:** {summary['n_flag']} · "
        f"**FAIL:** {summary['n_fail']}",
        f"**Elapsed:** {elapsed:.1f}s",
        "",
    ]
    if fails_for_major:
        md_lines += ["## Major-ticker FAILs", ""]
        for r in fails_for_major:
            md_lines.append(f"- **{r.ticker}** — {r.findings[0].detail if r.findings else 'unknown'}")
        md_lines.append("")
    _LAST_VALIDATION_PATH.write_text("\n".join(md_lines))
    log.info("wrote %s", _LAST_VALIDATION_PATH.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
