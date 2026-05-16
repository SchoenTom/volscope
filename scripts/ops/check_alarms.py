"""Check watchlist alarms — multi-type, market-hours gated, rich messages.

v0.9.8 rewrite:
  - Reads each watchlist's ``alarm_types`` JSON + ``alarm_thresholds``
    (not just the legacy regime-alarms bool).
  - Evaluates EVERY enabled alarm type per ticker via
    volscope.persistence.watchlists.check_all_alarms.
  - Gates firing on NYSE-business-hours (no alarms on weekends or
    holidays — operator's "Saturday QQQ alarm" complaint).
  - Builds an enriched message per fired alarm with current vs
    threshold, regime, spot, and a Scope deep-link hint.

CLI:
    python scripts/ops/check_alarms.py [--quiet] [--ignore-market-hours]

Exit codes: 0 normal · 1 DB unreachable.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from volscope.alerts.regime_alarm_dispatch import dispatch_message  # noqa: E402
from volscope.data.database import VolScopeDB  # noqa: E402
from volscope.data.freshness import is_business_day  # noqa: E402
from volscope.persistence.watchlists import (  # noqa: E402
    ALARM_TYPES, WatchlistRegimeAlarm, check_all_alarms, list_watchlists,
)

log = logging.getLogger("volscope.check_alarms")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ── Market-hours gate ───────────────────────────────────────────────

def _market_is_active(now: Optional[datetime] = None, *, post_close_window_hours: int = 2) -> tuple[bool, str]:
    """Return (active, reason). Active iff:
      - today is an NYSE business day AND
      - now is in 09:00-21:00 NY time (covers session + 2h post-close
        when end-of-day scrapes typically run).

    Returns (False, reason) so logs explain WHY we skipped.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)
    today = now.date()
    if not is_business_day(today):
        return False, f"{today} is not an NYSE business day (weekend or holiday)"
    # Convert to NY time approximately (UTC-4 EDT / UTC-5 EST). For
    # operator-facing gate we don't need exact tz; the wide
    # 09:00-21:00 NY window survives DST.
    utc_hour = now.hour
    # Treat NY = UTC-4 (EDT) as default — EST shifts the window by 1h
    # but the 09-21 buffer absorbs it.
    ny_hour_approx = (utc_hour - 4) % 24
    if ny_hour_approx < 9:
        return False, f"NY time ~{ny_hour_approx:02d}:00 — too early"
    if ny_hour_approx >= 21:
        return False, f"NY time ~{ny_hour_approx:02d}:00 — past post-close window"
    return True, "ok"


# ── Enriched message builder ──────────────────────────────────────

def _enrich(alarm: WatchlistRegimeAlarm, current: dict, thresholds: dict, watchlist: str) -> dict:
    """Augment a raw alarm with operator-facing context.

    Returns a dict suitable for Telegram + macOS dispatch with:
      title  — short single-line label
      body   — multi-line explanation: which rule, current vs
               threshold, current regime + spot, deep-link hint
    """
    icon_map = {
        "regime_change":     "≈",
        "iv_pct_high":       "⬆",
        "iv_pct_low":        "⬇",
        "iv_rank_high":      "▲",
        "iv_rank_low":       "▼",
        "earnings_imminent": "📅",
        "price_move_1d":     "⚡",
    }
    meta = ALARM_TYPES.get(alarm.alarm_type, {})
    icon = icon_map.get(alarm.alarm_type, "•")
    label = meta.get("label", alarm.alarm_type)

    iv_pct = current.get("iv_pct")
    iv_rank = current.get("iv_rank")
    regime = current.get("regime")
    spot = current.get("spot")
    days_er = current.get("days_to_earnings")
    pchg = current.get("price_change_1d_pct")

    title = f"{icon} {alarm.ticker} · {label}"

    # Build body with cur/threshold + context. Each line is
    # short enough to fit a Telegram preview.
    lines: list[str] = []
    if alarm.alarm_type == "regime_change":
        lines.append(f"Vol regime: {alarm.transition.replace('REGIME_', '').replace('_TO_', ' → ')}")
    elif alarm.alarm_type.startswith("iv_pct_"):
        thr = thresholds.get("iv_pct_high" if alarm.alarm_type == "iv_pct_high" else "iv_pct_low",
                             80.0 if alarm.alarm_type == "iv_pct_high" else 20.0)
        lines.append(f"IV Percentile {iv_pct:.0f} crossed threshold {thr:.0f}" if iv_pct is not None else f"IV Pct crossed {thr}")
    elif alarm.alarm_type.startswith("iv_rank_"):
        thr = thresholds.get("iv_rank_high" if alarm.alarm_type == "iv_rank_high" else "iv_rank_low",
                             80.0 if alarm.alarm_type == "iv_rank_high" else 20.0)
        lines.append(f"IV Rank {iv_rank:.0f} crossed threshold {thr:.0f}" if iv_rank is not None else f"IV Rank crossed {thr}")
    elif alarm.alarm_type == "earnings_imminent":
        thr = thresholds.get("earnings_imminent_days", 7)
        lines.append(f"Earnings in {days_er} day(s) (threshold {thr})" if days_er is not None else "Earnings imminent")
    elif alarm.alarm_type == "price_move_1d":
        thr = thresholds.get("price_move_1d_pct", 5.0)
        lines.append(f"Price moved {pchg:+.1f}% (threshold ±{thr:.1f}%)" if pchg is not None else "Price move beyond threshold")
    else:
        lines.append(alarm.transition)

    # Context line (one-liner with regime + spot + watchlist tag)
    ctx_parts = []
    if regime:
        ctx_parts.append(f"regime {regime}")
    if spot is not None:
        ctx_parts.append(f"spot ${spot:,.2f}")
    ctx_parts.append(f"from watchlist «{watchlist}»")
    lines.append(" · ".join(ctx_parts))

    # Deep-link hint (will not be rendered as a real link in
    # Telegram-text but the operator can manually open Scope)
    lines.append(f"→ open Scope: /?ticker={alarm.ticker}&page=Scope&source=alarm")

    body = "\n".join(lines)
    return {"title": title, "body": body}


# ── Data fetch — pull all the inputs a single ticker needs ──────────

def _fetch_current(db, ticker: str) -> dict:
    """Pull the latest snapshot of all signals an alarm might consume."""
    try:
        r = db.con.execute(
            """
            SELECT date, vol_regime, iv_percentile, iv_rank, spot_price
            FROM daily_vol
            WHERE ticker = ?
            ORDER BY date DESC LIMIT 2
            """,
            [ticker],
        ).fetchall()
    except Exception as exc:
        log.debug("fetch_current(%s) failed: %s", ticker, exc)
        return {}
    if not r:
        return {}

    latest = r[0]
    prev = r[1] if len(r) > 1 else None

    today_spot = float(latest[4]) if latest[4] is not None else None
    prev_spot = float(prev[4]) if prev and prev[4] is not None else None
    price_chg_pct = None
    if today_spot is not None and prev_spot is not None and prev_spot > 0:
        price_chg_pct = ((today_spot - prev_spot) / prev_spot) * 100.0

    days_to_er = None
    try:
        er_df = db.get_upcoming_earnings(ticker, date.today())
        if er_df is not None and not er_df.empty:
            next_er = er_df.iloc[0]["earnings_date"]
            days_to_er = (next_er - date.today()).days
    except Exception:
        pass

    return {
        "regime":              latest[1],
        "iv_pct":              float(latest[2]) if latest[2] is not None else None,
        "iv_rank":             float(latest[3]) if latest[3] is not None else None,
        "spot":                today_spot,
        "price_change_1d_pct": price_chg_pct,
        "days_to_earnings":    days_to_er,
    }


# ── Main loop ──────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress non-error log lines.")
    parser.add_argument(
        "--ignore-market-hours", action="store_true",
        help="Fire alarms even outside NYSE business hours (testing only).",
    )
    args = parser.parse_args(argv)
    if args.quiet:
        log.setLevel(logging.WARNING)

    if not args.ignore_market_hours:
        active, reason = _market_is_active()
        if not active:
            log.info("Skipping alarm check: %s", reason)
            return 0

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
        if not wl.alarm_types or not wl.tickers:
            continue
        log.info(
            "Checking watchlist %r (%d tickers, %d alarm-types)",
            wl.name, len(wl.tickers), len(wl.alarm_types),
        )
        for ticker in wl.tickers:
            checked_total += 1
            current = _fetch_current(db, ticker)
            if not current:
                continue
            try:
                fired = check_all_alarms(
                    db, ticker,
                    alarm_types=wl.alarm_types,
                    thresholds=wl.alarm_thresholds or {},
                    current=current,
                )
                for alarm in fired:
                    fired_total += 1
                    msg = _enrich(alarm, current, wl.alarm_thresholds or {}, wl.name)
                    log.info("FIRED %s: %s", msg["title"], msg["body"].replace("\n", " | "))
                    try:
                        result = dispatch_message(msg["title"], msg["body"])
                        log.info("dispatch result for %s: %s", ticker, result)
                    except Exception as exc:
                        log.error("dispatch failed for %s: %s", ticker, exc)
            except Exception as exc:
                log.error("check_all_alarms failed for %s: %s", ticker, exc)

    log.info(
        "Done: checked %d ticker(s), %d alarm(s) fired",
        checked_total, fired_total,
    )
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
