"""
Data Validator — self-back-check IV / HV against redundant sources.

VolScope's data integrity rests on a single scrape source (yfinance). To
catch silent corruption, scraper drift, and computation bugs, the
validator runs five orthogonal consistency checks per row and per ticker:

  1. **IV/HV plausibility** — |IV30 − HV20| / HV20 should rarely exceed 3.
     Massive divergence is either a market shock (real) or a stale HV
     against fresh IV (data bug). We flag and let the user judge.
  2. **Term-structure monotonicity** — for normal contango, longer maturity
     should not have IV << shorter (with small tolerance for noise).
     Inversions are real (backwardation) but only when the spread is
     consistent with realized stress. A lone IV60 < IV30 with all other
     evidence calm is a scraper bug.
  3. **Cross-ticker proxy** — SPY's IV30 should track ^VIX within ±20%.
     QQQ should track ^VXN. Major divergence flags either ticker.
  4. **Time-series anomaly** — today's IV vs 7-day rolling mean.
     |z-score| > 4 without an event flags a data outlier.
  5. **Skew sanity** — 25Δ skew should be in [-30, +30] vol points for
     equity. Anything outside is almost certainly a delta-interpolation
     bug.

Each check produces a Finding; per-row results aggregate to a
ValidationReport with a single PASS / FLAG / FAIL label. The validator
is pure analytics and writes nothing — persistence is the caller's job.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ── Configuration ───────────────────────────────────────────────────────

# Cross-asset proxy table — vol indices that should track each ticker.
# Keys are tickers; values are (proxy_index, max_relative_divergence).
_PROXY_MAP: dict[str, tuple[str, float]] = {
    "SPY":   ("^VIX",  0.25),
    "^GSPC": ("^VIX",  0.20),
    "QQQ":   ("^VXN",  0.25),
    "^NDX":  ("^VXN",  0.20),
    "IWM":   ("^RVX",  0.30),
    "^RUT":  ("^RVX",  0.25),
    "FXI":   ("^VXFXI", 0.30),
    "GLD":   ("^GVZ",  0.30),
    "USO":   ("^OVX",  0.30),
}

# IV/HV plausibility — divergence above this absolute threshold is flagged.
# Calibrated against historical SPY data: |IV - HV| / HV is < 1.5 in 90%
# of days and < 3.0 except during sharp shocks.
_IV_HV_FLAG_RATIO = 1.5
_IV_HV_FAIL_RATIO = 3.5

# Term structure: small inversion is OK, big inversion is suspect.
_TERM_INVERSION_FLAG_PP = 5.0
_TERM_INVERSION_FAIL_PP = 15.0

# Time-series anomaly z-score thresholds.
_TS_FLAG_Z = 3.0
_TS_FAIL_Z = 5.0

# Skew sanity: equity 25Δ skew is typically [-10, +25] pts. Allow ±30 as
# a soft ceiling; outside ±50 is a near-certain interpolation bug.
_SKEW_FLAG_PP = 30.0
_SKEW_FAIL_PP = 50.0


# ── Output types ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Finding:
    """One validator check outcome."""
    check:     str        # "iv_hv" | "term_structure" | "proxy" | "time_series" | "skew"
    level:     str        # "OK" | "FLAG" | "FAIL"
    detail:    str
    metric:    Optional[float] = None    # the value that drove the decision


@dataclass(frozen=True)
class ValidationReport:
    """Aggregated validator output for one (ticker, date) row."""
    ticker:        str
    overall_level: str               # worst-of-checks: OK | FLAG | FAIL
    findings:      tuple[Finding, ...]
    n_passes:      int
    n_flags:       int
    n_fails:       int


# ── Individual checks ───────────────────────────────────────────────────

def check_iv_hv_consistency(row: pd.Series) -> Finding:
    """IV30 vs HV20 — flag when divergence is implausibly large."""
    iv = _safe_float(row.get("iv_30d"))
    hv = _safe_float(row.get("hv_20d"))
    if iv is None or hv is None or hv <= 0:
        return Finding(check="iv_hv", level="OK",
                       detail="insufficient data — skipped", metric=None)
    ratio = abs(iv - hv) / hv
    if ratio > _IV_HV_FAIL_RATIO:
        return Finding(check="iv_hv", level="FAIL",
                       detail=f"|IV−HV|/HV = {ratio:.2f} (>{_IV_HV_FAIL_RATIO}) — likely data corruption",
                       metric=ratio)
    if ratio > _IV_HV_FLAG_RATIO:
        return Finding(check="iv_hv", level="FLAG",
                       detail=f"|IV−HV|/HV = {ratio:.2f} (>{_IV_HV_FLAG_RATIO}) — verify event drove this",
                       metric=ratio)
    return Finding(check="iv_hv", level="OK",
                   detail=f"|IV−HV|/HV = {ratio:.2f} within normal", metric=ratio)


def check_term_structure(row: pd.Series) -> Finding:
    """Small inversion OK; large inversion (IV30 >> IV180) is suspect."""
    iv30 = _safe_float(row.get("iv_30d"))
    iv60 = _safe_float(row.get("iv_60d"))
    iv90 = _safe_float(row.get("iv_90d"))
    iv180 = _safe_float(row.get("iv_180d"))
    pts = [(30, iv30), (60, iv60), (90, iv90), (180, iv180)]
    pts = [(d, v) for d, v in pts if v is not None]
    if len(pts) < 2:
        return Finding(check="term_structure", level="OK",
                       detail="insufficient term points", metric=None)

    # Largest IV − farthest_back IV — when positive (backwardation)
    # the front month has more vol than the back; equity term structure
    # is normally contango.
    front_iv = pts[0][1]
    back_iv  = pts[-1][1]
    inversion = front_iv - back_iv
    if inversion > _TERM_INVERSION_FAIL_PP:
        return Finding(check="term_structure", level="FAIL",
                       detail=f"front-back inversion {inversion:+.1f}pp (>{_TERM_INVERSION_FAIL_PP}) — likely scraper bug",
                       metric=inversion)
    if inversion > _TERM_INVERSION_FLAG_PP:
        return Finding(check="term_structure", level="FLAG",
                       detail=f"front-back inversion {inversion:+.1f}pp — backwardation; verify regime",
                       metric=inversion)
    return Finding(check="term_structure", level="OK",
                   detail=f"front-back slope {-inversion:+.1f}pp", metric=inversion)


def check_skew_sanity(row: pd.Series) -> Finding:
    """25Δ skew should be within reasonable equity bounds."""
    skew = _safe_float(row.get("iv_skew_25d"))
    if skew is None:
        return Finding(check="skew", level="OK",
                       detail="no skew data", metric=None)
    if abs(skew) > _SKEW_FAIL_PP:
        return Finding(check="skew", level="FAIL",
                       detail=f"25Δ skew {skew:+.1f}pp (|·|>{_SKEW_FAIL_PP}) — interpolation bug suspected",
                       metric=skew)
    if abs(skew) > _SKEW_FLAG_PP:
        return Finding(check="skew", level="FLAG",
                       detail=f"25Δ skew {skew:+.1f}pp (|·|>{_SKEW_FLAG_PP}) — extreme but possible",
                       metric=skew)
    return Finding(check="skew", level="OK",
                   detail=f"25Δ skew {skew:+.1f}pp", metric=skew)


def check_time_series_anomaly(
    row: pd.Series,
    history: Optional[pd.DataFrame] = None,
    window: int = 7,
) -> Finding:
    """Today's IV vs rolling-mean of the past `window` days."""
    iv = _safe_float(row.get("iv_30d"))
    if iv is None or history is None or history.empty:
        return Finding(check="time_series", level="OK",
                       detail="no history for z-score", metric=None)
    ser = history.sort_values("date")["iv_30d"].dropna().tail(window + 1).iloc[:-1]
    if len(ser) < 3:
        return Finding(check="time_series", level="OK",
                       detail="< 3 history points", metric=None)
    mean = float(ser.mean())
    std  = float(ser.std(ddof=1))
    if std <= 0:
        return Finding(check="time_series", level="OK",
                       detail="zero variance in window", metric=None)
    z = (iv - mean) / std
    if abs(z) > _TS_FAIL_Z:
        return Finding(check="time_series", level="FAIL",
                       detail=f"z-score vs {window}d mean = {z:+.2f} (|·|>{_TS_FAIL_Z}) — outlier or shock",
                       metric=z)
    if abs(z) > _TS_FLAG_Z:
        return Finding(check="time_series", level="FLAG",
                       detail=f"z-score vs {window}d mean = {z:+.2f} — verify event",
                       metric=z)
    return Finding(check="time_series", level="OK",
                   detail=f"z-score vs {window}d mean = {z:+.2f}", metric=z)


def check_cross_proxy(
    ticker:    str,
    row:       pd.Series,
    proxy_iv:  Optional[float],
) -> Finding:
    """Cross-ticker proxy: SPY's IV30 should track VIX within ±20%."""
    if ticker.upper() not in _PROXY_MAP:
        return Finding(check="proxy", level="OK",
                       detail="no proxy mapping", metric=None)
    proxy_sym, max_div = _PROXY_MAP[ticker.upper()]
    if proxy_iv is None:
        return Finding(check="proxy", level="OK",
                       detail=f"{proxy_sym} unavailable — skipped", metric=None)
    iv = _safe_float(row.get("iv_30d"))
    if iv is None or iv <= 0:
        return Finding(check="proxy", level="OK",
                       detail="ticker IV missing", metric=None)
    rel = abs(iv - proxy_iv) / proxy_iv
    if rel > max_div * 2:
        return Finding(check="proxy", level="FAIL",
                       detail=f"vs {proxy_sym}: {rel:.0%} divergence (cap {max_div*2:.0%}) — corruption likely",
                       metric=rel)
    if rel > max_div:
        return Finding(check="proxy", level="FLAG",
                       detail=f"vs {proxy_sym}: {rel:.0%} divergence (cap {max_div:.0%}) — verify",
                       metric=rel)
    return Finding(check="proxy", level="OK",
                   detail=f"vs {proxy_sym}: {rel:.0%} within {max_div:.0%}", metric=rel)


# ── Aggregator ──────────────────────────────────────────────────────────

def validate_row(
    ticker:   str,
    row:      pd.Series,
    history:  Optional[pd.DataFrame] = None,
    proxy_iv: Optional[float] = None,
) -> ValidationReport:
    """Run all 5 checks against one row, aggregate to a single report."""
    findings = (
        check_iv_hv_consistency(row),
        check_term_structure(row),
        check_skew_sanity(row),
        check_time_series_anomaly(row, history),
        check_cross_proxy(ticker, row, proxy_iv),
    )
    levels = [f.level for f in findings]
    if "FAIL" in levels:
        overall = "FAIL"
    elif "FLAG" in levels:
        overall = "FLAG"
    else:
        overall = "OK"
    return ValidationReport(
        ticker=ticker,
        overall_level=overall,
        findings=findings,
        n_passes=sum(1 for L in levels if L == "OK"),
        n_flags=sum(1 for L in levels if L == "FLAG"),
        n_fails=sum(1 for L in levels if L == "FAIL"),
    )


from volscope.utils.timing import instrumented  # noqa: E402


@instrumented("analytics.validate_universe")
def validate_universe(
    latest:        pd.DataFrame,
    histories:     dict[str, pd.DataFrame],
    proxy_levels:  Optional[dict[str, float]] = None,
) -> list[ValidationReport]:
    """Run validate_row over the full latest snapshot.

    ``proxy_levels`` is a dict {proxy_symbol: latest_iv30} so the validator
    can cross-check SPY against VIX, QQQ against VXN, etc. Missing keys
    cause that specific check to report OK with "skipped".
    """
    proxy_levels = proxy_levels or {}
    out: list[ValidationReport] = []
    if "ticker" not in latest.columns:
        return out
    for _, row in latest.iterrows():
        ticker = str(row.get("ticker") or "")
        proxy_sym = _PROXY_MAP.get(ticker.upper(), (None, 0))[0]
        proxy_iv = proxy_levels.get(proxy_sym) if proxy_sym else None
        hist = histories.get(ticker)
        out.append(validate_row(ticker, row, hist, proxy_iv))
    return out


def summarise_universe(reports: list[ValidationReport]) -> dict:
    """Roll up universe-level validation counts."""
    if not reports:
        return {"n_total": 0, "n_ok": 0, "n_flag": 0, "n_fail": 0}
    return {
        "n_total": len(reports),
        "n_ok":    sum(1 for r in reports if r.overall_level == "OK"),
        "n_flag":  sum(1 for r in reports if r.overall_level == "FLAG"),
        "n_fail":  sum(1 for r in reports if r.overall_level == "FAIL"),
    }


# ── Helpers ─────────────────────────────────────────────────────────────

def _safe_float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None
