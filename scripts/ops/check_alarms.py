"""Check watchlist regime alarms — runs after every daily_scrape.

For each watchlist with ``regime_alarms_enabled=True``, iterate the
contained tickers, pull the latest (vol_regime, iv_percentile) from
``daily_vol``, and call
``volscope.persistence.watchlists.check_regime_alarms``. Any alarm
that fires is dispatched via Telegram + macOS desktop notification +
WARNING log line.

Designed to run AT THE END of ``make scrape`` and as a separate
launchd job (5-minute cadence) so alarms fire even when Streamlit
isn't open.

CLI:
    python scripts/ops/check_alarms.py [--quiet]

Exit codes:
    0 — normal completion, fired count printed
    1 — DB unreachable / unrecoverable error
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from volscope.alerts.regime_alarm_dispatch import dispatch  # noqa: E402
from volscope.data.database import VolScopeDB  # noqa: E402
from volscope.persistence.watchlists import (  # noqa: E402
    check_regime_alarms, list_watchlists,
)

log = logging.getLogger("volscope.check_alarms")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _latest_regime_and_pct(db, ticker: str) -> tuple[str | None, float | None]:
    """Pull most recent (vol_regime, iv_percentile) for a ticker."""
    try:
        r = db.con.execute(
            """
            SELECT vol_regime, iv_percentile
            FROM daily_vol
            WHERE ticker = ?
            ORDER BY date DESC LIMIT 1
            """,
            [ticker],
        ).fetchone()
        if not r:
            return (None, None)
        return (r[0], float(r[1]) if r[1] is not None else None)
    except Exception as exc:
        log.debug("regime-pct fetch failed for %s: %s", ticker, exc)
        return (None, None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress non-error log lines.")
    args = parser.parse_args(argv)
    if args.quiet:
        log.setLevel(logging.WARNING)

    try:
        db = VolScopeDB()
    except Exception as exc:
        log.error("Cannot open DB: %s", exc)
        return 1

    try:
        watchlists = list_watchlists(db)
    except Exception as exc:
        log.error("Cannot list watchlists: %s", exc)
        db.close()
        return 1

    if not watchlists:
        log.info("No watchlists configured — nothing to check")
        db.close()
        return 0

    fired_total = 0
    checked_total = 0
    for wl in watchlists:
        if not wl.regime_alarms_enabled:
            continue
        if not wl.tickers:
            continue
        log.info(
            "Checking watchlist %r (%d tickers, alarms ON)",
            wl.name, len(wl.tickers),
        )
        for ticker in wl.tickers:
            checked_total += 1
            regime, iv_pct = _latest_regime_and_pct(db, ticker)
            if iv_pct is None and regime is None:
                continue  # ticker has no data yet
            try:
                alarm = check_regime_alarms(
                    db, ticker,
                    current_regime=regime, current_iv_pct=iv_pct,
                )
                if alarm.fired:
                    fired_total += 1
                    log.info(
                        "ALARM FIRED %s: %s (iv_pct=%s, regime=%s)",
                        ticker, alarm.transition, iv_pct, regime,
                    )
                    try:
                        result = dispatch(alarm)
                        log.info("dispatch result for %s: %s", ticker, result)
                    except Exception as exc:
                        log.error("dispatch failed for %s: %s", ticker, exc)
            except Exception as exc:
                log.error("check_regime_alarms failed for %s: %s", ticker, exc)

    log.info(
        "Done: checked %d ticker(s), %d alarm(s) fired",
        checked_total, fired_total,
    )
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
