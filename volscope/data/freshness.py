"""
Centralised data-freshness assessment.

Single source of truth for "how stale is the data the operator is
looking at right now?". Every UI page should consult this module
rather than rolling its own ``days = today - last_scrape`` check —
because a naive subtraction over weekends + holidays produces the
"STALE +4d" badge on a Monday morning when the data is actually
fresh from Friday's EOD close.

Public surface
==============
- :class:`FreshnessLevel` — five-state classification
- :class:`FreshnessReport` — dataclass with level, days, message
- :func:`assess_freshness` — primary entry-point
- :func:`is_business_day` / :func:`business_days_between` — helpers

Holiday awareness
=================
The full NYSE calendar comes via ``pandas_market_calendars`` (an
already-installed-but-not-used dep). When that dep is missing the
module falls back to a hard-coded list of the 9 US federal-style
NYSE holidays for the years VolScope cares about (2025-2027), so
the freshness assessment is still correct on Saturday-after-July-4th.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Iterable, Optional

# ── NYSE holiday calendar (fallback) ─────────────────────────────────

# Hard-coded NYSE closed days when the pandas_market_calendars dep is
# unavailable. Covers 2025-2027 — VolScope's relevant horizon. Verified
# against the NYSE 2025-2027 holiday schedule.
_NYSE_HOLIDAYS_FALLBACK: tuple[date, ...] = (
    # 2025
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # MLK Day
    date(2025, 2, 17),  # Presidents Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
    # 2026
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),   # Good Friday 2026
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),   # Observed (Jul 4 is Saturday)
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
    # 2027
    date(2027, 1, 1),
    date(2027, 1, 18),
    date(2027, 2, 15),
    date(2027, 3, 26),  # Good Friday 2027
    date(2027, 5, 31),
    date(2027, 6, 18),  # Observed (Jun 19 is Saturday)
    date(2027, 7, 5),   # Observed (Jul 4 is Sunday)
    date(2027, 9, 6),
    date(2027, 11, 25),
    date(2027, 12, 24), # Observed (Dec 25 is Saturday)
)


def _nyse_holidays(years: Iterable[int]) -> set[date]:
    """Return the set of NYSE holiday dates for ``years``.

    Prefers ``pandas_market_calendars`` (more accurate, future-proof);
    falls back to ``_NYSE_HOLIDAYS_FALLBACK`` if the dep isn't
    available. Empty intersection when ``years`` is outside the
    fallback's coverage window — be aware.
    """
    try:
        import pandas_market_calendars as mcal
        nyse = mcal.get_calendar("NYSE")
        # The cal returns a DatetimeIndex of trading days. Holidays are
        # the WEEKDAY dates NOT present in that index.
        years = list(years)
        if not years:
            return set()
        start = date(min(years), 1, 1)
        end   = date(max(years), 12, 31)
        trading = set(
            d.date() for d in nyse.valid_days(start_date=start, end_date=end)
        )
        out: set[date] = set()
        cur = start
        while cur <= end:
            if cur.weekday() < 5 and cur not in trading:
                out.add(cur)
            cur += timedelta(days=1)
        return out
    except Exception:                                          # noqa: BLE001
        return {h for h in _NYSE_HOLIDAYS_FALLBACK if h.year in set(years)}


def is_business_day(d: date) -> bool:
    """True if ``d`` is a NYSE trading day (Mon-Fri, not a holiday)."""
    if d.weekday() >= 5:
        return False
    holidays = _nyse_holidays([d.year])
    return d not in holidays


def business_days_between(start: date, end: date) -> int:
    """Count NYSE trading days in the closed interval ``[start, end]``.

    Returns 0 if ``end < start``. Both endpoints are inclusive, so
    ``business_days_between(2026-05-14, 2026-05-15)`` (Thu→Fri) = 2.
    """
    if end < start:
        return 0
    holidays = _nyse_holidays(range(start.year, end.year + 1))
    n = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5 and cur not in holidays:
            n += 1
        cur += timedelta(days=1)
    return n


# ── Freshness classification ─────────────────────────────────────────

class FreshnessLevel(str, Enum):
    """Five-state classification for how recent the DB's last scrape is."""
    FRESH      = "FRESH"        # Same business day or 1 business day ago
    RECENT     = "RECENT"       # 2 business days ago
    STALE      = "STALE"        # 3-5 business days ago
    VERY_STALE = "VERY_STALE"   # > 5 business days ago
    MISSING    = "MISSING"      # No data at all


@dataclass(frozen=True)
class FreshnessReport:
    """Report returned by :func:`assess_freshness`.

    Attributes
    ----------
    level
        Five-state classification.
    days_old
        Calendar days between today and the last scrape.
    business_days_old
        NYSE trading days between today and the last scrape — this is
        the number the badge should show, not ``days_old``.
    last_scrape
        The scrape date the assessment was made against (or ``None``).
    expected_next_update
        The next NYSE trading day after the last scrape, or ``None``
        if there's no last scrape.
    warning_message
        Operator-facing one-line summary suitable for a banner.
    color_hint
        ``"green" | "amber" | "red" | "grey"`` — keeps the colour
        choice central rather than scattered across each page's
        banner-rendering code.
    """
    level:                FreshnessLevel
    days_old:             int
    business_days_old:    int
    last_scrape:          Optional[date]
    expected_next_update: Optional[date]
    warning_message:      str
    color_hint:           str


_BUSINESS_DAY_THRESHOLDS: tuple[tuple[int, FreshnessLevel, str], ...] = (
    (1,  FreshnessLevel.FRESH,      "green"),
    (2,  FreshnessLevel.RECENT,     "green"),
    (5,  FreshnessLevel.STALE,      "amber"),
    (99, FreshnessLevel.VERY_STALE, "red"),
)


def _classify_business_days(b_days: int) -> tuple[FreshnessLevel, str]:
    """Pick (level, colour) from the threshold table."""
    for threshold, level, color in _BUSINESS_DAY_THRESHOLDS:
        if b_days <= threshold:
            return level, color
    # Defensive: the 99-threshold catches everything reasonable.
    return FreshnessLevel.VERY_STALE, "red"


def _next_business_day(d: date) -> date:
    """Return the next NYSE trading day strictly after ``d``."""
    nxt = d + timedelta(days=1)
    while not is_business_day(nxt):
        nxt += timedelta(days=1)
    return nxt


def assess_freshness(
    last_scrape: Optional[date],
    *,
    asof: Optional[date] = None,
) -> FreshnessReport:
    """Primary entry point.

    Parameters
    ----------
    last_scrape
        The most recent date the database has data for. Typically
        ``VolScopeDB.get_last_scrape_date()``.
    asof
        The "today" against which freshness is judged. Defaults to
        :func:`date.today`. Allows unit-tests to be deterministic
        (e.g. test the Monday-morning-after-Friday-scrape scenario).
    """
    today = asof or date.today()

    if last_scrape is None:
        return FreshnessReport(
            level=FreshnessLevel.MISSING,
            days_old=0,
            business_days_old=0,
            last_scrape=None,
            expected_next_update=None,
            warning_message="No scrape on record — run `make scrape`.",
            color_hint="grey",
        )

    days_old = (today - last_scrape).days
    if days_old < 0:                                            # clock skew safety
        days_old = 0
    # business_days_between returns the count *inclusive of both
    # endpoints*. For freshness purposes we want "trading days strictly
    # between last_scrape and today" — so subtract 1, clamped to 0.
    b_days = max(0, business_days_between(last_scrape, today) - 1)

    level, color = _classify_business_days(b_days)
    next_update = _next_business_day(last_scrape)

    if level == FreshnessLevel.FRESH:
        msg = f"Fresh — last scrape {last_scrape.isoformat()}"
    elif level == FreshnessLevel.RECENT:
        msg = (
            f"Recent — last scrape {last_scrape.isoformat()} "
            f"({b_days} trading-day{'s' if b_days != 1 else ''} ago)"
        )
    elif level == FreshnessLevel.STALE:
        msg = (
            f"Stale — last scrape {b_days} trading-days ago "
            f"({last_scrape.isoformat()}). Run `make scrape` to refresh."
        )
    else:                                                       # VERY_STALE
        msg = (
            f"Very stale — last scrape {b_days} trading-days ago "
            f"({last_scrape.isoformat()}). Pipeline may be broken."
        )

    return FreshnessReport(
        level=level,
        days_old=days_old,
        business_days_old=b_days,
        last_scrape=last_scrape,
        expected_next_update=next_update,
        warning_message=msg,
        color_hint=color,
    )
