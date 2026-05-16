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
]


@dataclass(frozen=True)
class Watchlist:
    name: str
    created_at: datetime
    regime_alarms_enabled: bool
    tickers: list[str]


@dataclass(frozen=True)
class WatchlistRegimeAlarm:
    ticker:        str
    fired:         bool
    transition:    str   # "ENTERED_CHEAP" | "ENTERED_RICH" | "REGIME_CHANGE_<from>_<to>" | ""
    current_iv_pct:  Optional[float]
    current_regime: Optional[str]


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
            last_alarm_at TIMESTAMP
        )
        """
    )


def create_watchlist(db, name: str, *, regime_alarms: bool = False) -> None:
    ensure_watchlist_tables(db)
    db.con.execute(
        """
        INSERT INTO watchlists (name, created_at, regime_alarms_enabled)
        VALUES (?, ?, ?)
        ON CONFLICT (name) DO UPDATE SET regime_alarms_enabled = excluded.regime_alarms_enabled
        """,
        [name, datetime.now(tz=timezone.utc), regime_alarms],
    )


def list_watchlists(db) -> list[Watchlist]:
    ensure_watchlist_tables(db)
    rows = db.con.execute(
        "SELECT name, created_at, regime_alarms_enabled FROM watchlists ORDER BY name"
    ).fetchall()
    out: list[Watchlist] = []
    for name, created_at, alarms in rows:
        items = db.con.execute(
            """
            SELECT ticker FROM watchlist_items
            WHERE watchlist_name = ? ORDER BY sort_order, ticker
            """,
            [name],
        ).fetchall()
        out.append(Watchlist(
            name=name, created_at=created_at,
            regime_alarms_enabled=bool(alarms),
            tickers=[t for (t,) in items],
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
    )
