"""
Cached data helpers — wrap heavy DB queries in Streamlit's cache_data so
pages can call freely without re-hitting DuckDB on every interaction.

Streamlit's cache_data hashes positional/keyword args. The ``_db`` prefix
tells the cache to SKIP hashing that argument — necessary because
``VolScopeDB`` is not naturally hashable. Cache invalidation is driven
by an explicit ``cache_key`` string the caller computes (typically the
last-scrape-date or the snapshot row count).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st


@st.cache_data(ttl=60, show_spinner=False)
def get_all_latest_cached(cache_key: str, _db) -> pd.DataFrame:
    """Return ``_db.get_all_latest()`` cached for 60 seconds.

    cache_key disambiguates: pass the last-scrape-date so the cache flushes
    on every fresh scrape but stays warm across sidebar interactions.
    """
    return _db.get_all_latest()


@st.cache_data(ttl=60, show_spinner=False)
def get_available_tickers_cached(cache_key: str, _db) -> list[str]:
    """Return ``_db.get_available_tickers()`` cached for 60 seconds."""
    return _db.get_available_tickers() or []


@st.cache_data(ttl=300, show_spinner=False)
def get_recent_for_tickers_cached(
    cache_key:    str,
    tickers:      tuple[str, ...],
    lookback:     int,
    _db,
) -> dict:
    """Cached bulk-history fetch for many tickers.

    Discover and other pages scan 200+ tickers and request 60d of history
    per ticker — without caching, every sidebar interaction triggers a
    full re-fetch. tuple-based cache key ensures rerun stability.
    """
    return _db.get_recent_for_tickers(list(tickers), lookback_days=lookback)


def make_cache_key(db) -> str:
    """Convenience: cache_key from last-scrape-date (or "no-data")."""
    try:
        last = db.get_last_scrape_date()
        if last is None:
            return "no-data"
        return last.isoformat()
    except Exception:
        return "no-data"


@st.cache_data(ttl=600, show_spinner=False)
def compute_sector_aggregates_cached(cache_key: str, full_df: pd.DataFrame) -> pd.DataFrame:
    """
    Cached wrapper around ``compute_sector_aggregates``.

    The underlying function runs a pandas groupby across 100k+ rows of
    ``daily_vol`` and is called per-render on Rotation, Flow, and
    Command Center. Without caching, each render pays the ~100-200 ms
    pandas cost; the result is identical until a new scrape arrives.

    Cache key uses ``make_cache_key(db)`` (the last-scrape-date), so a
    fresh scrape correctly invalidates. The DataFrame argument is
    hashed by Streamlit via its content fingerprint — passing the same
    underlying data is a cache hit.

    Reused at ~3 call sites across the UI; see ADR-0002 + v0.6.2
    decisions log entry.
    """
    from volscope.analytics.sector_rotation import compute_sector_aggregates
    return compute_sector_aggregates(full_df)
