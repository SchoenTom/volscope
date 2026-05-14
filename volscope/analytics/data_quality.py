"""
Data quality checks for single-ticker rows.

These heuristics catch the kinds of bugs we've actually seen in the wild:
  1. IV >> plausible ceiling (e.g. old SPY 78% from a broken scraper run)
  2. IV near zero (< 3% annualized) — almost certainly a solver artifact
  3. IV so far from HV that the spread is an outlier vs the ticker's own
     historical spread distribution (beyond ±3σ)
  4. Missing essential fields (iv_30d present but hv_20d null)

Plus two completeness checks added 2026-05-01 after a data-quality audit
revealed liquid tickers (QQQ/SPY/AAPL) showing iv_60d/90d/180d as NaN
because their last scrape pre-dated the term-structure schema:

  5. Freshness: how stale is the row relative to today?
  6. Term-structure completeness: which of {30d, 60d, 90d, 180d, skew}
     are missing?

The goal is a simple per-row label the UI can show:
    OK        — nothing wrong
    WARN      — suspicious but not clearly wrong
    SUSPECT   — very likely a data bug, treat with caution
    STALE     — data > 7 days old, calculations may be misleading
    PARTIAL   — term-structure incomplete, downstream features degraded
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd


@dataclass
class QualityReport:
    level: str  # "OK" | "WARN" | "SUSPECT"
    reasons: list[str]


#: Per-category plausibility ceilings. Matches the scraper sanity layer.
_IV_CEILINGS: dict[str, float] = {
    "etf": 120.0,
    "vol_etf": 400.0,
    "single_name": 500.0,
    "index": 100.0,
    "crypto": 300.0,
}


def _category_for_sector(sector: Optional[str]) -> str:
    if sector is None:
        return "single_name"
    s = sector.lower()
    if "vol etf" in s:
        return "vol_etf"
    if "etf" in s or "currency" in s or "thematic" in s or "bond" in s or "commodity" in s:
        return "etf"
    if "crypto" in s:
        return "crypto"
    if "indices" in s or "index" in s:
        return "index"
    return "single_name"


def check_row(row: pd.Series, history: Optional[pd.DataFrame] = None) -> QualityReport:
    """
    Return a QualityReport for a single daily_vol row, optionally using
    the ticker's own history for spread-outlier detection.
    """
    reasons: list[str] = []
    level = "OK"

    iv = row.get("iv_30d")
    hv = row.get("hv_20d")
    sector = row.get("sector")

    # 1. Missing-essential check.
    if pd.isna(iv) or iv is None:
        # No IV is not necessarily wrong (e.g. fresh add before scrape).
        return QualityReport(level="OK", reasons=[])

    iv_val = float(iv)

    # 2. Per-category ceiling.
    category = _category_for_sector(sector)
    ceiling = _IV_CEILINGS[category]
    if iv_val > ceiling:
        reasons.append(f"IV {iv_val:.0f}% exceeds {category} ceiling {ceiling:.0f}%")
        level = "SUSPECT"

    # 3. Near-zero floor.
    if iv_val < 3.0:
        reasons.append(f"IV {iv_val:.2f}% below plausibility floor 3%")
        level = "SUSPECT"

    # 4. Spread z-score outlier.
    if hv is not None and not pd.isna(hv) and history is not None and not history.empty:
        hv_val = float(hv)
        spread_now = iv_val - hv_val
        if "iv_30d" in history.columns and "hv_20d" in history.columns:
            hist_spreads = (history["iv_30d"] - history["hv_20d"]).dropna()
            if len(hist_spreads) >= 30:
                mean = float(hist_spreads.mean())
                std = float(hist_spreads.std(ddof=1))
                if std > 0:
                    z = (spread_now - mean) / std
                    if abs(z) > 4.0:
                        reasons.append(
                            f"IV-HV spread {spread_now:+.1f} is {abs(z):.1f}σ "
                            f"from historical mean {mean:+.1f}"
                        )
                        level = "SUSPECT"
                    elif abs(z) > 3.0:
                        reasons.append(
                            f"IV-HV spread {spread_now:+.1f} is {abs(z):.1f}σ out"
                        )
                        if level == "OK":
                            level = "WARN"

    return QualityReport(level=level, reasons=reasons)


# ── Freshness ────────────────────────────────────────────────────────────

# Threshold tuning is calibrated against the user's actual scrape cadence:
#   - Daily scrape (ideal) → FRESH ≤ 2d, AGING 3-14d, STALE > 14d
#   - Weekly scrape         → FRESH still narrow but AGING absorbs the lag
# Above 14 days = STALE; calculations risk being misleading because spot
# and IV have moved meaningfully. Below 2 days = FRESH (gold standard for
# entry decisions). 2-14 days = AGING — usable for context but the trader
# should know the data isn't intraday-fresh.
_FRESH_DAYS_MAX = 2
_AGING_DAYS_MAX = 14


@dataclass
class FreshnessReport:
    level:    str          # "FRESH" | "AGING" | "STALE"
    age_days: int          # calendar days from row date to today
    row_date: Optional[date]


def check_freshness(
    row: pd.Series,
    today: Optional[date] = None,
) -> FreshnessReport:
    """How recent is this daily_vol row relative to today?

    Returns FRESH (≤2 days) / AGING (3-7 days) / STALE (>7 days).
    When the row has no date or date is in the future, returns STALE.
    """
    today = today or date.today()
    raw_date = row.get("date") if isinstance(row, pd.Series) else None
    row_dt: Optional[date] = None
    if raw_date is not None:
        try:
            row_dt = pd.Timestamp(raw_date).date()
        except Exception:
            row_dt = None
    if row_dt is None or row_dt > today:
        return FreshnessReport(level="STALE", age_days=999, row_date=row_dt)
    age = (today - row_dt).days
    if age <= _FRESH_DAYS_MAX:
        level = "FRESH"
    elif age <= _AGING_DAYS_MAX:
        level = "AGING"
    else:
        level = "STALE"
    return FreshnessReport(level=level, age_days=age, row_date=row_dt)


# ── Term-structure completeness ──────────────────────────────────────────

_TERM_FIELDS: tuple[str, ...] = ("iv_30d", "iv_60d", "iv_90d", "iv_180d", "iv_skew_25d")


@dataclass
class CompletenessReport:
    level:           str               # "FULL" | "PARTIAL" | "MINIMAL"
    present_fields:  tuple[str, ...]
    missing_fields:  tuple[str, ...]
    n_present:       int
    n_total:         int


def check_completeness(row: pd.Series) -> CompletenessReport:
    """Which of the 5 term-structure / skew fields are populated?

    FULL    = all 5 present (rare in practice — few US single-names have
              true 180d listed, and skew sometimes fails to compute)
    PARTIAL = 2-4 of 5 present (typical for well-scraped major tickers)
    MINIMAL = 0-1 present (degraded — most term-structure features unusable)
    """
    present: list[str] = []
    missing: list[str] = []
    for f in _TERM_FIELDS:
        v = row.get(f) if isinstance(row, pd.Series) else None
        try:
            if v is None or pd.isna(v):
                missing.append(f)
                continue
            fv = float(v)
            if math.isnan(fv) or math.isinf(fv):
                missing.append(f)
            else:
                present.append(f)
        except (TypeError, ValueError):
            missing.append(f)
    n_p = len(present)
    if n_p >= 5:
        level = "FULL"
    elif n_p >= 2:
        level = "PARTIAL"
    else:
        level = "MINIMAL"
    return CompletenessReport(
        level=level,
        present_fields=tuple(present),
        missing_fields=tuple(missing),
        n_present=n_p,
        n_total=len(_TERM_FIELDS),
    )


# ── Composite quality badge for UI ───────────────────────────────────────

@dataclass
class CompositeQuality:
    """Single-glance per-row data-quality summary for the UI."""
    overall_level: str            # "OK" | "WARN" | "SUSPECT" | "STALE" | "PARTIAL"
    plausibility:  QualityReport
    freshness:     FreshnessReport
    completeness:  CompletenessReport
    one_liner:     str


from volscope.utils.timing import instrumented  # noqa: E402


@instrumented("analytics.composite_quality")
def composite_quality(
    row:     pd.Series,
    history: Optional[pd.DataFrame] = None,
    today:   Optional[date] = None,
) -> CompositeQuality:
    """Combine plausibility + freshness + completeness into one report.

    Worst-of-three escalation rule: STALE/SUSPECT > WARN/PARTIAL > OK.
    """
    plaus = check_row(row, history)
    fresh = check_freshness(row, today)
    comp = check_completeness(row)

    if plaus.level == "SUSPECT":
        overall = "SUSPECT"
    elif fresh.level == "STALE":
        overall = "STALE"
    elif comp.level == "MINIMAL":
        overall = "PARTIAL"
    elif plaus.level == "WARN" or fresh.level == "AGING" or comp.level == "PARTIAL":
        overall = "WARN"
    else:
        overall = "OK"

    parts: list[str] = []
    if fresh.level != "FRESH":
        parts.append(f"{fresh.level.lower()} {fresh.age_days}d")
    if comp.level != "FULL":
        parts.append(f"term {comp.n_present}/{comp.n_total}")
    if plaus.reasons:
        parts.append(plaus.reasons[0][:50])
    one_liner = " · ".join(parts) if parts else "all-clear"

    return CompositeQuality(
        overall_level=overall,
        plausibility=plaus,
        freshness=fresh,
        completeness=comp,
        one_liner=one_liner,
    )


# ── HTML helper for trader-facing surfaces ───────────────────────────────

_BADGE_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


def quality_badge_html(report: CompositeQuality) -> str:
    """Compact one-line badge suitable for page headers / card subtitles."""
    color_map = {
        "OK":      "#00d4aa",
        "WARN":    "#ff9f43",
        "SUSPECT": "#ff4466",
        "STALE":   "#ff9f43",
        "PARTIAL": "#7db4ff",
    }
    color = color_map.get(report.overall_level, "#8a8f9e")
    return (
        f'<span style="font-family:{_BADGE_MONO};font-size:10px;'
        f'background:{color}22;color:{color};border-left:2px solid {color};'
        f'padding:2px 8px;border-radius:3px;font-weight:600;">'
        f'{report.overall_level} · {report.one_liner}'
        f'</span>'
    )


def summarize_quality(
    latest: pd.DataFrame, histories: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """
    Run `check_row` for every ticker in `latest`, return a DataFrame with
    columns: ticker, level, reason. Rows with level='OK' are excluded —
    the caller cares about flags, not noise.
    """
    out: list[dict] = []
    for _, row in latest.iterrows():
        ticker = row.get("ticker")
        if ticker is None:
            continue
        hist = histories.get(ticker, pd.DataFrame())
        report = check_row(row, hist)
        if report.level == "OK":
            continue
        out.append(
            {
                "ticker": ticker,
                "level": report.level,
                "reason": " · ".join(report.reasons),
            }
        )
    return pd.DataFrame(out)
