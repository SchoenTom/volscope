"""
Risk-free rate term structure from FRED (Federal Reserve Economic Data).

FRED CSV endpoints are public and require no API key. We fetch four points on
the Treasury curve once per day and linearly interpolate to a target maturity.

Series:
    DGS1MO  — 1-month constant-maturity Treasury yield
    DGS3MO  — 3-month
    DGS6MO  — 6-month
    DGS1    — 1-year
"""
from __future__ import annotations

import datetime
import logging
import threading
import urllib.request
from typing import Optional

log = logging.getLogger(__name__)

_FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

_SERIES: dict[int, str] = {
    30: "DGS1MO",
    90: "DGS3MO",
    180: "DGS6MO",
    365: "DGS1",
}

_cache: dict[str, object] = {"date": None, "curve": {}}
# Guards _cache against partial writes when two Streamlit tab reruns
# call _refresh_curve() concurrently on a cold boot (each chart render
# would otherwise see a half-populated curve and solve IV at an
# inconsistent rate).
_cache_lock = threading.Lock()


_FRED_TIMEOUT_S = 5


def _fetch_one(series: str) -> Optional[float]:
    """Fetch the most recent non-missing value of a FRED series."""
    url = _FRED_URL.format(series=series)
    try:
        with urllib.request.urlopen(url, timeout=_FRED_TIMEOUT_S) as resp:
            text = resp.read().decode()
    except Exception as exc:
        log.warning("FRED %s fetch failed: %s", series, exc)
        return None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines[1:]):  # skip header
        parts = line.split(",")
        if len(parts) == 2 and parts[1] not in (".", ""):
            try:
                return float(parts[1]) / 100.0  # percent → fraction
            except ValueError:
                continue
    return None


def _refresh_curve() -> dict[int, float]:
    import concurrent.futures

    today = datetime.date.today()
    # Fast path: serve a same-day cache without holding the lock across
    # the network fetch.
    if _cache.get("date") == today and _cache.get("curve"):
        return _cache["curve"]  # type: ignore
    # If we already tried today and FRED was unreachable, do NOT retry on
    # every render (that was a 4 x 5 s block per call on a restricted
    # network). get_rate() falls back to the static config rate.
    if _cache.get("tried") == today:
        return {}

    # Fetch the 4 curve points CONCURRENTLY (was serial — up to 4 x 5 s).
    curve: dict[int, float] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_fetch_one, series): days
                for days, series in _SERIES.items()}
        for fut in concurrent.futures.as_completed(futs):
            days = futs[fut]
            try:
                rate = fut.result()
            except Exception:                                  # noqa: BLE001
                rate = None
            if rate is not None and 0.0 <= rate < 0.20:
                curve[days] = rate

    with _cache_lock:
        _cache["tried"] = today
        if curve and not (_cache.get("date") == today and _cache.get("curve")):
            _cache["date"] = today
            _cache["curve"] = curve
    return _cache["curve"] if curve else {}  # type: ignore


def get_term_structure() -> dict[int, float]:
    """Return the cached or freshly-fetched yield curve as {days: rate_fraction}."""
    return _refresh_curve()


def get_rate(days_to_expiry: int) -> float:
    """
    Linear interpolation of the Treasury curve at a given maturity. Falls back
    to the static config rate if FRED is unreachable.
    """
    from volscope.config import RISK_FREE_RATE

    curve = get_term_structure()
    if not curve:
        return RISK_FREE_RATE

    sorted_days = sorted(curve.keys())
    if days_to_expiry <= sorted_days[0]:
        return curve[sorted_days[0]]
    if days_to_expiry >= sorted_days[-1]:
        return curve[sorted_days[-1]]
    for i in range(len(sorted_days) - 1):
        d0, d1 = sorted_days[i], sorted_days[i + 1]
        if d0 <= days_to_expiry <= d1:
            r0, r1 = curve[d0], curve[d1]
            w = (days_to_expiry - d0) / (d1 - d0)
            return r0 + w * (r1 - r0)
    return RISK_FREE_RATE


def reset_cache() -> None:
    """Clear in-memory cache (for tests)."""
    _cache["date"] = None
    _cache["curve"] = {}
    _cache.pop("tried", None)
