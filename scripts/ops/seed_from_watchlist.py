"""Seed only the tickers that live in the operator's watchlists.

Operator feedback 2026-05-16: "first launch should load fewer tickers,
specifically those from the watchlist". Reads every watchlist's
ticker list, deduplicates, falls back to SPY if no watchlists exist.

Run via ``make seed-watchlist``.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from volscope.data.database import VolScopeDB  # noqa: E402

log = logging.getLogger("volscope.seed_watchlist")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    db = VolScopeDB()
    try:
        from volscope.persistence.watchlists import list_watchlists
    except Exception as exc:
        log.error("Cannot import watchlists module: %s", exc)
        db.close()
        return 1

    try:
        wls = list_watchlists(db)
    except Exception as exc:
        log.warning("No watchlists yet — falling back to SPY: %s", exc)
        wls = []

    tickers: list[str] = []
    seen: set[str] = set()
    for wl in wls:
        for t in wl.tickers:
            if t not in seen:
                seen.add(t)
                tickers.append(t)

    if not tickers:
        log.info(
            "No watchlist tickers configured — seeding SPY + QQQ as baseline "
            "(grow via sidebar add-ticker or Watchlist page CSV import)",
        )
        tickers = ["SPY", "QQQ"]

    log.info("Seeding %d ticker(s): %s", len(tickers), ", ".join(tickers))

    db.close()  # release lock before seed_database reopens

    import subprocess
    rc = subprocess.call(
        ["python", "scripts/ops/seed_database.py",
         "--tickers", ",".join(tickers)],
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
