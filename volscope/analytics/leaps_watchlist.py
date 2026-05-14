"""
LEAPS watchlist persistence.

A user-pinned list of tickers, stored as a JSON blob in the existing
``user_settings`` key-value table so we don't grow new schema for a
single concept. Serialised as ``{"items": [{"ticker": "PYPL",
"pinned_at": "2026-05-10"}, ...]}``.

Pure helpers — no Streamlit imports, so the dossier and any future cron
job ("rescan watchlist nightly") share the same persistence path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Optional

from volscope.data.database import VolScopeDB


WATCHLIST_KEY = "leaps.watchlist"


@dataclass(frozen=True)
class WatchlistEntry:
    ticker:    str
    pinned_at: date


def _serialise(entries: list[WatchlistEntry]) -> str:
    return json.dumps({
        "items": [
            {"ticker": e.ticker, "pinned_at": e.pinned_at.isoformat()}
            for e in entries
        ]
    })


def _deserialise(raw: Optional[str]) -> list[WatchlistEntry]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out: list[WatchlistEntry] = []
    for item in payload.get("items", []):
        try:
            out.append(WatchlistEntry(
                ticker=str(item["ticker"]),
                pinned_at=date.fromisoformat(str(item["pinned_at"])),
            ))
        except (KeyError, ValueError):
            continue
    return out


def load_watchlist(db: VolScopeDB) -> list[WatchlistEntry]:
    """Return the persisted watchlist (most-recent-first)."""
    raw = db.get_user_setting(WATCHLIST_KEY)
    items = _deserialise(raw)
    return sorted(items, key=lambda e: e.pinned_at, reverse=True)


def pin_to_watchlist(
    db: VolScopeDB, ticker: str, today: Optional[date] = None,
) -> list[WatchlistEntry]:
    """Add a ticker to the watchlist if not already present.

    Returns the new watchlist. Re-pinning an existing ticker refreshes its
    ``pinned_at`` date so it floats to the top.
    """
    today = today or date.today()
    items = load_watchlist(db)
    items = [e for e in items if e.ticker != ticker]
    items.insert(0, WatchlistEntry(ticker=ticker, pinned_at=today))
    db.set_user_setting(WATCHLIST_KEY, _serialise(items))
    return items


def unpin_from_watchlist(db: VolScopeDB, ticker: str) -> list[WatchlistEntry]:
    """Remove a ticker. No-op when absent."""
    items = [e for e in load_watchlist(db) if e.ticker != ticker]
    db.set_user_setting(WATCHLIST_KEY, _serialise(items))
    return items


def is_pinned(db: VolScopeDB, ticker: str) -> bool:
    return any(e.ticker == ticker for e in load_watchlist(db))
