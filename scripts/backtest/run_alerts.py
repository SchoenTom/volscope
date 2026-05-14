#!/usr/bin/env python3
"""
run_alerts.py — Standalone Vol Alert checker for cron.

Evaluates all enabled alert rules against the latest vol data in the DB
and dispatches notifications (log file, macOS desktop, email).

Usage:
    python scripts/run_alerts.py

Cron example (every 15 minutes on weekdays):
    */15 9-17 * * 1-5 cd /path/to/VolScope && python scripts/run_alerts.py >> /tmp/volscope_alerts_cron.log 2>&1

Environment variables for email channel:
    VOLSCOPE_SMTP_HOST, VOLSCOPE_SMTP_PORT, VOLSCOPE_SMTP_USER,
    VOLSCOPE_SMTP_PASS, VOLSCOPE_SMTP_TO

Override DB path:
    VOLSCOPE_DATA_DIR=/some/path python scripts/run_alerts.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is on the path when called from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from volscope.alerts.alert_engine import AlertRule, dispatch_alert, evaluate_rules
from volscope.data.database import VolScopeDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_alerts")


def main() -> int:
    """Run alert checks. Returns exit code (0 = ok, 1 = error)."""
    try:
        db = VolScopeDB()
    except Exception as exc:
        log.error("Cannot open DB: %s", exc)
        return 1

    # Load all enabled rules.
    rules_df = db.get_alert_rules()
    if rules_df.empty:
        log.info("No alert rules configured — nothing to check.")
        return 0

    rules: list[AlertRule] = [
        AlertRule(
            id=int(r["id"]),
            ticker=str(r["ticker"]),
            metric=str(r["metric"]),
            operator=str(r["operator"]),
            threshold=float(r["threshold"]),
            channel=str(r["channel"]),
            label=str(r["label"]),
            enabled=bool(r["enabled"]),
        )
        for _, r in rules_df.iterrows()
        if r["enabled"]
    ]
    if not rules:
        log.info("All rules are disabled — nothing to check.")
        return 0

    log.info("Checking %d rule(s) …", len(rules))

    # Fetch the most recent row for every ticker that appears in rules.
    wildcard_rules = [r for r in rules if r.ticker == "*"]
    specific_tickers = list({r.ticker for r in rules if r.ticker != "*"})

    # For wildcard rules, check all tickers in the DB.
    if wildcard_rules:
        all_latest = db.get_all_latest()
        ticker_list = all_latest["ticker"].tolist() if not all_latest.empty else []
    else:
        ticker_list = specific_tickers

    if not ticker_list:
        log.info("No tickers to check.")
        return 0

    # Build latest_rows mapping.
    latest_rows = {}
    for ticker in ticker_list:
        hist = db.get_ticker_history(ticker)
        if not hist.empty:
            latest_rows[ticker] = hist.iloc[-1]

    if not latest_rows:
        log.info("No data found in DB for checked tickers.")
        return 0

    # Evaluate and dispatch.
    fired_list = evaluate_rules(rules, latest_rows)
    if not fired_list:
        log.info("No rules triggered.")
        return 0

    log.info("%d alert(s) fired:", len(fired_list))
    for fired in fired_list:
        log.info("  %s", fired.message)
        try:
            db.log_alert_fired(
                rule_id=fired.rule_id,
                fired_at=fired.fired_at,
                ticker=fired.ticker,
                metric=fired.metric,
                metric_value=fired.value,
                message=fired.message,
            )
        except Exception as exc:
            log.warning("Could not log fired alert to DB: %s", exc)
        try:
            dispatch_alert(fired)
        except Exception as exc:
            log.warning("Dispatch error for %s: %s", fired.ticker, exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
