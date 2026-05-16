"""Watchlists — TradingView-style flexible ticker groupings.

Persistence layer for user-defined watchlists. Designed for the
sidebar widget (`Watchlist · Add / Remove / Reorder`) and the
vol-regime alarm engine.

Schema (created on first call to ensure_tables):

    watchlists(
        name VARCHAR PRIMARY KEY,
        created_at TIMESTAMP,
        regime_alarms_enabled BOOLEAN DEFAULT FALSE,
    )

    watchlist_items(
        watchlist_name VARCHAR,
        ticker VARCHAR,
        sort_order INTEGER,
        added_at TIMESTAMP,
        PRIMARY KEY (watchlist_name, ticker),
    )

    watchlist_alarms(
        ticker VARCHAR PRIMARY KEY,
        last_regime VARCHAR,
        last_iv_percentile DOUBLE,
        last_alarm_at TIMESTAMP,
    )

A vol-regime alarm fires when the operator-tracked ticker
transitions across any of these boundaries:
  - IV percentile crosses 20 (entering CHEAP) or 80 (entering RICH)
  - vol_regime transitions CRUSHED/CHEAP ↔ FAIR/RICH/EXTREME

Notification channels (in priority order, configured via .env):
  1. Telegram (existing TELEGRAM__BOT_TOKEN integration)
  2. macOS desktop notification (osascript — no extra deps)
  3. Log line (always)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

__all__ = [
    "ALARM_TYPES",
    "Watchlist",
    "WatchlistRegimeAlarm",
    "ensure_watchlist_tables",
    "create_watchlist",
    "list_watchlists",
    "add_ticker_to_watchlist",
    "remove_ticker_from_watchlist",
    "reorder_watchlist",
    "get_watchlist_tickers",
    "set_regime_alarm",
    "check_regime_alarms",
    "check_all_alarms",
]


@dataclass(frozen=True)
class Watchlist:
    name: str
    created_at: datetime
    regime_alarms_enabled: bool   # legacy bool — true → "regime_change" is in alarm_types
    tickers: list[str]
    alarm_types: list[str]        # v0.9.8 — selected alarm-type keys (see ALARM_TYPES)
    alarm_thresholds: dict        # v0.9.8 — per-alarm parameters


@dataclass(frozen=True)
class WatchlistRegimeAlarm:
    """Result for one ticker × one alarm-type evaluation."""
    ticker:        str
    fired:         bool
    transition:    str   # e.g. ENTERED_CHEAP, IV_RANK_HIGH, EARNINGS_IN_3D, REGIME_CRUSHED→FAIR
    current_iv_pct:  Optional[float]
    current_regime: Optional[str]
    alarm_type:     str = "regime_change"   # which rule fired


# ── Alarm-type catalogue (v0.9.8) ──────────────────────────────────
#
# Each key maps to a human label + a default threshold. Operators pick
# which ones to enable per watchlist via the sidebar widget.
#
# Alarm-type evaluation logic lives in check_regime_alarms (legacy
# bool path) and the new check_all_alarms below.

ALARM_TYPES: dict[str, dict] = {
    "regime_change": {
        "label": "Vol Regime change",
        "help":  "Fires when the 6-state HMM regime label changes "
                 "(CRUSHED→FAIR, RICH→EXTREME, etc.).",
        "threshold_key":  None,
        "default":        None,
    },
    "iv_pct_high": {
        "label": "IV Percentile crosses HIGH",
        "help":  "Fires when IV percentile crosses ABOVE the threshold "
                 "(default 80). Use for short-premium opportunity flags.",
        "threshold_key":  "iv_pct_high",
        "default":        80.0,
    },
    "iv_pct_low": {
        "label": "IV Percentile crosses LOW",
        "help":  "Fires when IV percentile crosses BELOW the threshold "
                 "(default 20). Use for long-premium / earnings-week flags.",
        "threshold_key":  "iv_pct_low",
        "default":        20.0,
    },
    "iv_rank_high": {
        "label": "IV Rank crosses HIGH",
        "help":  "Fires when IV Rank crosses ABOVE the threshold "
                 "(default 80). Complements iv_pct_high — Rank captures "
                 "absolute range, Pct captures distribution position.",
        "threshold_key":  "iv_rank_high",
        "default":        80.0,
    },
    "iv_rank_low": {
        "label": "IV Rank crosses LOW",
        "help":  "Fires when IV Rank crosses BELOW the threshold "
                 "(default 20).",
        "threshold_key":  "iv_rank_low",
        "default":        20.0,
    },
    "earnings_imminent": {
        "label": "Earnings imminent",
        "help":  "Fires once when the next earnings event is within N "
                 "days (default 7). One-shot per event.",
        "threshold_key":  "earnings_imminent_days",
        "default":        7,
    },
    "price_move_1d": {
        "label": "Price move > X % (1-day)",
        "help":  "Fires when the abs 1-day price change exceeds the "
                 "threshold (default 5 %). Useful for catching gap-day "
                 "events without staring at the chart.",
        "threshold_key":  "price_move_1d_pct",
        "default":        5.0,
    },
}


def _serialise(obj) -> str:
    import json
    return json.dumps(obj or [])


def _deserialise(raw, default):
    if not raw:
        return default
    import json
    try:
        return json.loads(raw)
    except Exception:                                              # noqa: BLE001
        return default


def ensure_watchlist_tables(db) -> None:
    """Create watchlist tables if missing. Safe to call repeatedly."""
    db.con.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlists (
            name VARCHAR PRIMARY KEY,
            created_at TIMESTAMP NOT NULL,
            regime_alarms_enabled BOOLEAN DEFAULT FALSE
        )
        """
    )
    # v0.9.8 — multi-alarm-type support. alarm_types is a JSON-encoded
    # list of strings (e.g. ["regime_change", "iv_rank_high",
    # "earnings_imminent"]). thresholds is JSON-encoded dict of
    # per-alarm parameters (e.g. {"iv_rank_high": 80,
    # "earnings_imminent_days": 7}). Both columns are nullable; legacy
    # rows fall back to regime_alarms_enabled bool for backward compat.
    for _col, _typ in (
        ("alarm_types", "VARCHAR"),
        ("alarm_thresholds", "VARCHAR"),
    ):
        try:
            db.con.execute(
                f"ALTER TABLE watchlists ADD COLUMN IF NOT EXISTS {_col} {_typ}"
            )
        except Exception:                                          # noqa: BLE001
            pass

    db.con.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_items (
            watchlist_name VARCHAR NOT NULL,
            ticker VARCHAR NOT NULL,
            sort_order INTEGER DEFAULT 0,
            added_at TIMESTAMP NOT NULL,
            PRIMARY KEY (watchlist_name, ticker)
        )
        """
    )
    db.con.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist_alarms (
            ticker VARCHAR PRIMARY KEY,
            last_regime VARCHAR,
            last_iv_percentile DOUBLE,
            last_iv_rank DOUBLE,
            last_spot DOUBLE,
            last_alarm_at TIMESTAMP
        )
        """
    )
    # v0.9.8 — backfill the new alarm-tracking columns on legacy DBs
    for _col, _typ in (
        ("last_iv_rank", "DOUBLE"),
        ("last_spot", "DOUBLE"),
    ):
        try:
            db.con.execute(
                f"ALTER TABLE watchlist_alarms ADD COLUMN IF NOT EXISTS {_col} {_typ}"
            )
        except Exception:                                          # noqa: BLE001
            pass


def create_watchlist(
    db, name: str, *,
    regime_alarms: bool = False,
    alarm_types: Optional[list[str]] = None,
    alarm_thresholds: Optional[dict] = None,
) -> None:
    """Create or update a watchlist with multi-alarm config.

    Backward compat: ``regime_alarms=True`` enables the legacy single
    bool AND adds "regime_change" to alarm_types if alarm_types is
    None. New callers should pass ``alarm_types`` explicitly.
    """
    ensure_watchlist_tables(db)
    if alarm_types is None:
        alarm_types = ["regime_change"] if regime_alarms else []
    elif regime_alarms and "regime_change" not in alarm_types:
        alarm_types = alarm_types + ["regime_change"]
    db.con.execute(
        """
        INSERT INTO watchlists (
            name, created_at, regime_alarms_enabled,
            alarm_types, alarm_thresholds
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (name) DO UPDATE SET
            regime_alarms_enabled = excluded.regime_alarms_enabled,
            alarm_types           = excluded.alarm_types,
            alarm_thresholds      = excluded.alarm_thresholds
        """,
        [
            name, datetime.now(tz=timezone.utc), bool(regime_alarms),
            _serialise(alarm_types),
            _serialise(alarm_thresholds or {}),
        ],
    )


def list_watchlists(db) -> list[Watchlist]:
    ensure_watchlist_tables(db)
    rows = db.con.execute(
        """
        SELECT name, created_at, regime_alarms_enabled,
               alarm_types, alarm_thresholds
        FROM watchlists ORDER BY name
        """
    ).fetchall()
    out: list[Watchlist] = []
    for name, created_at, regime_bool, alarm_types_raw, thresh_raw in rows:
        items = db.con.execute(
            """
            SELECT ticker FROM watchlist_items
            WHERE watchlist_name = ? ORDER BY sort_order, ticker
            """,
            [name],
        ).fetchall()
        alarm_types = _deserialise(alarm_types_raw, [])
        # Backward compat: regime bool true but no alarm_types yet → include regime_change
        if regime_bool and "regime_change" not in alarm_types:
            alarm_types = list(alarm_types) + ["regime_change"]
        thresholds = _deserialise(thresh_raw, {})
        out.append(Watchlist(
            name=name, created_at=created_at,
            regime_alarms_enabled=bool(regime_bool),
            tickers=[t for (t,) in items],
            alarm_types=list(alarm_types),
            alarm_thresholds=dict(thresholds),
        ))
    return out


def get_watchlist_tickers(db, name: str) -> list[str]:
    ensure_watchlist_tables(db)
    rows = db.con.execute(
        """
        SELECT ticker FROM watchlist_items
        WHERE watchlist_name = ? ORDER BY sort_order, ticker
        """,
        [name],
    ).fetchall()
    return [t for (t,) in rows]


def add_ticker_to_watchlist(db, watchlist: str, ticker: str) -> None:
    ensure_watchlist_tables(db)
    # Determine next sort_order
    r = db.con.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM watchlist_items WHERE watchlist_name = ?",
        [watchlist],
    ).fetchone()
    next_order = int(r[0]) if r else 0
    db.con.execute(
        """
        INSERT INTO watchlist_items (watchlist_name, ticker, sort_order, added_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (watchlist_name, ticker) DO NOTHING
        """,
        [watchlist, ticker.upper(), next_order, datetime.now(tz=timezone.utc)],
    )


def remove_ticker_from_watchlist(db, watchlist: str, ticker: str) -> None:
    ensure_watchlist_tables(db)
    db.con.execute(
        "DELETE FROM watchlist_items WHERE watchlist_name = ? AND ticker = ?",
        [watchlist, ticker.upper()],
    )


def reorder_watchlist(db, watchlist: str, ordered_tickers: list[str]) -> None:
    """Apply a new sort_order based on the position in <ordered_tickers>."""
    ensure_watchlist_tables(db)
    for idx, t in enumerate(ordered_tickers):
        db.con.execute(
            """
            UPDATE watchlist_items SET sort_order = ?
            WHERE watchlist_name = ? AND ticker = ?
            """,
            [idx, watchlist, t.upper()],
        )


def set_regime_alarm(db, ticker: str, *, regime: Optional[str], iv_pct: Optional[float]) -> None:
    """Persist the latest regime/iv-pct snapshot for an alarm-tracked ticker."""
    ensure_watchlist_tables(db)
    db.con.execute(
        """
        INSERT INTO watchlist_alarms (ticker, last_regime, last_iv_percentile, last_alarm_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (ticker) DO UPDATE SET
            last_regime = excluded.last_regime,
            last_iv_percentile = excluded.last_iv_percentile,
            last_alarm_at = excluded.last_alarm_at
        """,
        [ticker.upper(), regime, iv_pct, datetime.now(tz=timezone.utc)],
    )


def check_regime_alarms(
    db, ticker: str, *,
    current_regime: Optional[str], current_iv_pct: Optional[float],
    cheap_threshold: float = 20.0,
    rich_threshold: float = 80.0,
) -> WatchlistRegimeAlarm:
    """Evaluate whether a regime/iv-pct transition fired for <ticker>.

    Returns a WatchlistRegimeAlarm with ``fired=True`` when the
    transition crossed a CHEAP / RICH boundary or the named regime
    changed since the last snapshot.

    Side-effect: updates watchlist_alarms with the latest snapshot
    so the next call has the new baseline.
    """
    ensure_watchlist_tables(db)
    r = db.con.execute(
        "SELECT last_regime, last_iv_percentile FROM watchlist_alarms WHERE ticker = ?",
        [ticker.upper()],
    ).fetchone()

    prev_regime, prev_iv = (r[0], r[1]) if r else (None, None)
    transition = ""
    fired = False

    # IV percentile boundary crossings (the primary signal Tom asked for)
    if current_iv_pct is not None and prev_iv is not None:
        if prev_iv >= cheap_threshold and current_iv_pct < cheap_threshold:
            transition = "ENTERED_CHEAP"
            fired = True
        elif prev_iv <= rich_threshold and current_iv_pct > rich_threshold:
            transition = "ENTERED_RICH"
            fired = True

    # Named regime change (secondary)
    if not fired and prev_regime and current_regime and prev_regime != current_regime:
        transition = f"REGIME_CHANGE_{prev_regime}_TO_{current_regime}"
        fired = True

    # Persist latest snapshot
    set_regime_alarm(db, ticker, regime=current_regime, iv_pct=current_iv_pct)

    return WatchlistRegimeAlarm(
        ticker=ticker.upper(),
        fired=fired,
        transition=transition,
        current_iv_pct=current_iv_pct,
        current_regime=current_regime,
        alarm_type="regime_change",
    )


# ── v0.9.8 — multi-alarm-type evaluator ──────────────────────────────

def _get_last_snapshot(db, ticker: str) -> dict:
    """Return the most recently stored snapshot for an alarm-tracked ticker."""
    try:
        r = db.con.execute(
            "SELECT last_regime, last_iv_percentile, last_iv_rank, last_spot, "
            "last_alarm_at FROM watchlist_alarms WHERE ticker = ?",
            [ticker.upper()],
        ).fetchone()
    except Exception:
        r = None
    if not r:
        return {}
    return {
        "regime":   r[0],
        "iv_pct":   float(r[1]) if r[1] is not None else None,
        "iv_rank":  float(r[2]) if r[2] is not None else None,
        "spot":     float(r[3]) if r[3] is not None else None,
        "ts":       r[4],
    }


def _persist_snapshot(
    db, ticker: str, *,
    regime: Optional[str],
    iv_pct: Optional[float],
    iv_rank: Optional[float],
    spot: Optional[float],
) -> None:
    ensure_watchlist_tables(db)
    db.con.execute(
        """
        INSERT INTO watchlist_alarms (
            ticker, last_regime, last_iv_percentile, last_iv_rank,
            last_spot, last_alarm_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (ticker) DO UPDATE SET
            last_regime         = excluded.last_regime,
            last_iv_percentile  = excluded.last_iv_percentile,
            last_iv_rank        = excluded.last_iv_rank,
            last_spot           = excluded.last_spot,
            last_alarm_at       = excluded.last_alarm_at
        """,
        [
            ticker.upper(), regime,
            iv_pct, iv_rank, spot, datetime.now(tz=timezone.utc),
        ],
    )


def check_all_alarms(
    db, ticker: str, *,
    alarm_types: list[str],
    thresholds: dict,
    current: dict,
) -> list[WatchlistRegimeAlarm]:
    """Evaluate EVERY enabled alarm type for one ticker.

    Parameters
    ----------
    alarm_types : keys into ALARM_TYPES that the watchlist enabled
    thresholds  : per-alarm threshold dict (key matches ALARM_TYPES[k]["threshold_key"])
    current     : snapshot dict with optional keys
                  regime, iv_pct, iv_rank, spot, days_to_earnings, price_change_1d_pct

    Returns
    -------
    list of WatchlistRegimeAlarm, one entry per alarm-type that FIRED.
    Side effect: persists the new snapshot so subsequent calls have a
    baseline for crossing-detection.
    """
    if not alarm_types:
        return []
    prev = _get_last_snapshot(db, ticker)
    fired_list: list[WatchlistRegimeAlarm] = []

    cur_regime = current.get("regime")
    cur_iv_pct = current.get("iv_pct")
    cur_iv_rank = current.get("iv_rank")
    cur_spot = current.get("spot")
    days_to_er = current.get("days_to_earnings")
    price_chg = current.get("price_change_1d_pct")

    def _fire(transition: str, alarm_type: str) -> None:
        fired_list.append(WatchlistRegimeAlarm(
            ticker=ticker.upper(),
            fired=True,
            transition=transition,
            current_iv_pct=cur_iv_pct,
            current_regime=cur_regime,
            alarm_type=alarm_type,
        ))

    # ── regime_change ──
    if "regime_change" in alarm_types:
        prev_r = prev.get("regime")
        if prev_r and cur_regime and prev_r != cur_regime:
            _fire(f"REGIME_{prev_r}_TO_{cur_regime}", "regime_change")

    # ── iv_pct_high / iv_pct_low — boundary crossings ──
    if "iv_pct_high" in alarm_types and cur_iv_pct is not None and prev.get("iv_pct") is not None:
        thr = float(thresholds.get("iv_pct_high", 80.0))
        if prev["iv_pct"] <= thr < cur_iv_pct:
            _fire(f"IV_PCT_ABOVE_{thr:.0f}", "iv_pct_high")
    if "iv_pct_low" in alarm_types and cur_iv_pct is not None and prev.get("iv_pct") is not None:
        thr = float(thresholds.get("iv_pct_low", 20.0))
        if prev["iv_pct"] >= thr > cur_iv_pct:
            _fire(f"IV_PCT_BELOW_{thr:.0f}", "iv_pct_low")

    # ── iv_rank_high / iv_rank_low — boundary crossings ──
    if "iv_rank_high" in alarm_types and cur_iv_rank is not None and prev.get("iv_rank") is not None:
        thr = float(thresholds.get("iv_rank_high", 80.0))
        if prev["iv_rank"] <= thr < cur_iv_rank:
            _fire(f"IV_RANK_ABOVE_{thr:.0f}", "iv_rank_high")
    if "iv_rank_low" in alarm_types and cur_iv_rank is not None and prev.get("iv_rank") is not None:
        thr = float(thresholds.get("iv_rank_low", 20.0))
        if prev["iv_rank"] >= thr > cur_iv_rank:
            _fire(f"IV_RANK_BELOW_{thr:.0f}", "iv_rank_low")

    # ── earnings_imminent — one-shot crossing into the window ──
    if "earnings_imminent" in alarm_types and days_to_er is not None:
        thr = int(thresholds.get("earnings_imminent_days", 7))
        # Fire only on the FIRST day inside the window since last snapshot.
        # Without a prior snapshot, this fires immediately (one-shot
        # behaviour expected on new alarm setup).
        prev_ts = prev.get("ts")
        if days_to_er <= thr and (prev_ts is None or days_to_er == thr):
            _fire(f"EARNINGS_IN_{int(days_to_er)}_DAYS", "earnings_imminent")

    # ── price_move_1d — abs daily change beyond threshold ──
    if "price_move_1d" in alarm_types and price_chg is not None:
        thr = float(thresholds.get("price_move_1d_pct", 5.0))
        if abs(price_chg) >= thr:
            direction = "UP" if price_chg > 0 else "DOWN"
            _fire(f"PRICE_{direction}_{abs(price_chg):.1f}%", "price_move_1d")

    # Persist the latest snapshot regardless of whether alarms fired
    _persist_snapshot(
        db, ticker,
        regime=cur_regime,
        iv_pct=cur_iv_pct,
        iv_rank=cur_iv_rank,
        spot=cur_spot,
    )
    return fired_list
