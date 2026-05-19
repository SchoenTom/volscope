"""
Universe-wide alert scanner.

Single entry point: ``scan_alerts(db)`` returns a list of ``Alert``
records — one per fired condition per ticker. Pure analytics, no UI.

Categories
----------
ANOMALY (red)   — extreme IV-percentile, IV/HV ratio, or convergence
FLOW    (orange)— extreme PCR, anomalous volume vs 20d-average
REGIME  (blue)  — IV-rank expansion / crush, spread sign-flips
EARNINGS (gold) — earnings ≤ 7d ahead, just-passed earnings

Design intent
-------------
* Each rule is a self-contained function ``rule_xxx(latest_row, …) -> Alert | None``
  so we can test rules in isolation and combine them in `scan_alerts`.
* Alerts carry a ``severity`` rank (0..4) so the UI can sort + colour
  consistently. ANOMALY=4, FLOW=3, REGIME=2, EARNINGS=1.
* ``timestamp`` is the date attached to the data row that triggered the
  alert (so historic scans are reproducible).
* Threshold constants live at the top — easy to tune.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

import pandas as pd


# ── Categories ────────────────────────────────────────────────────────
ANOMALY  = "anomaly"
FLOW     = "flow"
REGIME   = "regime"
EARNINGS = "earnings"

CATEGORY_LABELS: dict[str, str] = {
    ANOMALY:  "Anomaly",
    FLOW:     "Flow",
    REGIME:   "Regime",
    EARNINGS: "Earnings",
}

CATEGORY_COLORS: dict[str, str] = {
    ANOMALY:  "#ff4466",
    FLOW:     "#ff9f43",
    REGIME:   "#5b8cff",
    EARNINGS: "#ffd700",
}

CATEGORY_SEVERITY: dict[str, int] = {
    ANOMALY:  4,
    FLOW:     3,
    REGIME:   2,
    EARNINGS: 1,
}


# ── Thresholds (tunable) ──────────────────────────────────────────────
IV_PERC_LOW    = 5.0
IV_PERC_HIGH   = 95.0

IV_HV_CHEAP    = 0.65
IV_HV_RICH    = 1.50

CONVERGENCE_HIGH = 80.0

PCR_PUT_HEAVY  = 2.0
PCR_CALL_HEAVY = 0.3

VOL_SPIKE_MULT = 3.0

IV_RANK_EXPAND_TO  = 50.0
IV_RANK_EXPAND_FROM = 20.0
IV_RANK_CRUSH_TO   = 50.0
IV_RANK_CRUSH_FROM = 80.0
RANK_LOOKBACK_DAYS = 5

ER_NEAR_DAYS = 7
ER_FRESH_DAYS = 1


# ── Output type ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class Alert:
    """One alert instance fired by the scanner."""
    type:          str          # one of ANOMALY/FLOW/REGIME/EARNINGS
    severity:      int          # 1..4 (matches CATEGORY_SEVERITY)
    ticker:        str
    message:       str          # human-readable, includes the metric value
    timestamp:     date         # data-row date (or today for ER alerts)
    metric_value:  Optional[float] = None


# ── Helpers ───────────────────────────────────────────────────────────

def _f(value) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
        if math.isnan(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _row_date(row) -> date:
    d = row.get("date")
    if d is None:
        return date.today()
    try:
        return pd.Timestamp(d).date()
    except Exception:
        return date.today()


# ── Anomaly rules ─────────────────────────────────────────────────────

def rule_iv_percentile_low(row) -> Optional[Alert]:
    p = _f(row.get("iv_percentile"))
    if p is None or p >= IV_PERC_LOW:
        return None
    return Alert(
        type=ANOMALY, severity=CATEGORY_SEVERITY[ANOMALY],
        ticker=str(row.get("ticker", "?")),
        message=f"IV Percentile {p:.0f} — historisches Tief (< {IV_PERC_LOW:.0f})",
        timestamp=_row_date(row), metric_value=p,
    )


def rule_iv_percentile_high(row) -> Optional[Alert]:
    p = _f(row.get("iv_percentile"))
    if p is None or p <= IV_PERC_HIGH:
        return None
    return Alert(
        type=ANOMALY, severity=CATEGORY_SEVERITY[ANOMALY],
        ticker=str(row.get("ticker", "?")),
        message=f"IV Percentile {p:.0f} — historisches Hoch (> {IV_PERC_HIGH:.0f})",
        timestamp=_row_date(row), metric_value=p,
    )


def rule_iv_hv_cheap(row) -> Optional[Alert]:
    iv = _f(row.get("iv_30d"))
    hv = _f(row.get("hv_20d"))
    if iv is None or hv is None or hv <= 0:
        return None
    ratio = iv / hv
    if ratio >= IV_HV_CHEAP:
        return None
    discount = (1.0 - ratio) * 100.0
    return Alert(
        type=ANOMALY, severity=CATEGORY_SEVERITY[ANOMALY],
        ticker=str(row.get("ticker", "?")),
        message=f"Optionen {discount:.0f}% günstiger als reale Moves (IV/HV {ratio:.2f}×)",
        timestamp=_row_date(row), metric_value=ratio,
    )


def rule_iv_hv_rich(row) -> Optional[Alert]:
    iv = _f(row.get("iv_30d"))
    hv = _f(row.get("hv_20d"))
    if iv is None or hv is None or hv <= 0:
        return None
    ratio = iv / hv
    if ratio <= IV_HV_RICH:
        return None
    premium = (ratio - 1.0) * 100.0
    return Alert(
        type=ANOMALY, severity=CATEGORY_SEVERITY[ANOMALY],
        ticker=str(row.get("ticker", "?")),
        message=f"Optionen {premium:.0f}% teurer als reale Moves (IV/HV {ratio:.2f}×)",
        timestamp=_row_date(row), metric_value=ratio,
    )


def rule_convergence_high(row) -> Optional[Alert]:
    c = _f(row.get("convergence_score"))
    if c is None or c <= CONVERGENCE_HIGH:
        return None
    return Alert(
        type=ANOMALY, severity=CATEGORY_SEVERITY[ANOMALY],
        ticker=str(row.get("ticker", "?")),
        message=f"Dreifach-Konvergenz {c:.0f} — Mispricing + Neglect + Reversal aligned",
        timestamp=_row_date(row), metric_value=c,
    )


# ── Flow rules ────────────────────────────────────────────────────────

def rule_pcr_put_heavy(row) -> Optional[Alert]:
    pcr = _f(row.get("put_call_ratio"))
    if pcr is None or pcr <= PCR_PUT_HEAVY:
        return None
    return Alert(
        type=FLOW, severity=CATEGORY_SEVERITY[FLOW],
        ticker=str(row.get("ticker", "?")),
        message=f"Extremer Put-Überhang (PCR {pcr:.2f}) — Absicherung oder bearish",
        timestamp=_row_date(row), metric_value=pcr,
    )


def rule_pcr_call_heavy(row) -> Optional[Alert]:
    pcr = _f(row.get("put_call_ratio"))
    if pcr is None or pcr >= PCR_CALL_HEAVY:
        return None
    return Alert(
        type=FLOW, severity=CATEGORY_SEVERITY[FLOW],
        ticker=str(row.get("ticker", "?")),
        message=f"Extremer Call-Überhang (PCR {pcr:.2f}) — bullish Crowding",
        timestamp=_row_date(row), metric_value=pcr,
    )


def rule_volume_spike(row, history: pd.DataFrame | None) -> Optional[Alert]:
    if history is None or history.empty:
        return None
    today_vol = _f(row.get("total_call_volume"))
    today_put = _f(row.get("total_put_volume"))
    if today_vol is None and today_put is None:
        return None
    today = (today_vol or 0.0) + (today_put or 0.0)
    if today == 0:
        return None
    if "total_call_volume" not in history.columns:
        return None
    hist_total = (
        history["total_call_volume"].fillna(0).tail(20).astype(float)
        + history.get("total_put_volume", pd.Series(0)).fillna(0).tail(20).astype(float)
    )
    hist_total = hist_total[hist_total > 0]
    if len(hist_total) < 5:
        return None
    avg = float(hist_total.mean())
    if avg <= 0:
        return None
    ratio = today / avg
    if ratio < VOL_SPIKE_MULT:
        return None
    return Alert(
        type=FLOW, severity=CATEGORY_SEVERITY[FLOW],
        ticker=str(row.get("ticker", "?")),
        message=f"Ungewöhnliches Options-Volumen ({ratio:.1f}× 20d-avg)",
        timestamp=_row_date(row), metric_value=ratio,
    )


# ── Regime rules ──────────────────────────────────────────────────────

def rule_iv_expansion(row, history: pd.DataFrame | None) -> Optional[Alert]:
    if history is None or len(history) < RANK_LOOKBACK_DAYS + 1:
        return None
    rank_now = _f(row.get("iv_rank"))
    if rank_now is None or rank_now <= IV_RANK_EXPAND_TO:
        return None
    earlier = history.iloc[-(RANK_LOOKBACK_DAYS + 1)]
    rank_then = _f(earlier.get("iv_rank"))
    if rank_then is None or rank_then >= IV_RANK_EXPAND_FROM:
        return None
    return Alert(
        type=REGIME, severity=CATEGORY_SEVERITY[REGIME],
        ticker=str(row.get("ticker", "?")),
        message=f"IV-Expansion gestartet — Rank {rank_then:.0f} → {rank_now:.0f} in {RANK_LOOKBACK_DAYS}d",
        timestamp=_row_date(row), metric_value=rank_now,
    )


def rule_iv_crush(row, history: pd.DataFrame | None) -> Optional[Alert]:
    if history is None or len(history) < RANK_LOOKBACK_DAYS + 1:
        return None
    rank_now = _f(row.get("iv_rank"))
    if rank_now is None or rank_now >= IV_RANK_CRUSH_TO:
        return None
    earlier = history.iloc[-(RANK_LOOKBACK_DAYS + 1)]
    rank_then = _f(earlier.get("iv_rank"))
    if rank_then is None or rank_then <= IV_RANK_CRUSH_FROM:
        return None
    return Alert(
        type=REGIME, severity=CATEGORY_SEVERITY[REGIME],
        ticker=str(row.get("ticker", "?")),
        message=f"IV-Crush — Rank {rank_then:.0f} → {rank_now:.0f} in {RANK_LOOKBACK_DAYS}d",
        timestamp=_row_date(row), metric_value=rank_now,
    )


def rule_spread_signflip(row, history: pd.DataFrame | None) -> Optional[Alert]:
    if history is None or len(history) < 2:
        return None
    iv_now = _f(row.get("iv_30d"))
    hv_now = _f(row.get("hv_20d"))
    if iv_now is None or hv_now is None:
        return None
    spread_now = iv_now - hv_now
    prev = history.iloc[-2]
    iv_prev = _f(prev.get("iv_30d"))
    hv_prev = _f(prev.get("hv_20d"))
    if iv_prev is None or hv_prev is None:
        return None
    spread_prev = iv_prev - hv_prev
    if spread_now * spread_prev >= 0:
        return None  # no sign flip
    direction = "RICH → CHEAP" if spread_prev > 0 else "CHEAP → RICH"
    return Alert(
        type=REGIME, severity=CATEGORY_SEVERITY[REGIME],
        ticker=str(row.get("ticker", "?")),
        message=f"Spread dreht {direction} ({spread_prev:+.1f} → {spread_now:+.1f})",
        timestamp=_row_date(row), metric_value=spread_now,
    )


# ── Earnings rules ────────────────────────────────────────────────────

def rule_earnings_imminent(ticker: str, days_to_er: Optional[int]) -> Optional[Alert]:
    if days_to_er is None or days_to_er < 0 or days_to_er > ER_NEAR_DAYS:
        return None
    return Alert(
        type=EARNINGS, severity=CATEGORY_SEVERITY[EARNINGS],
        ticker=ticker,
        message=f"Earnings in {days_to_er}d — IV-Buildup-Phase",
        timestamp=date.today(), metric_value=float(days_to_er),
    )


def rule_earnings_just_passed(ticker: str, days_to_er: Optional[int]) -> Optional[Alert]:
    if days_to_er is None or not (-ER_FRESH_DAYS <= days_to_er < 0):
        return None
    return Alert(
        type=EARNINGS, severity=CATEGORY_SEVERITY[EARNINGS],
        ticker=ticker,
        message=f"Post-Earnings ({-days_to_er}d) — IV-Crush erwartet",
        timestamp=date.today(), metric_value=float(days_to_er),
    )


# ── Earnings lookup ───────────────────────────────────────────────────

def _days_to_next_earnings(db, ticker: str) -> Optional[int]:
    try:
        df = db.get_upcoming_earnings(ticker, date(1970, 1, 1))
    except Exception:
        return None
    if df is None or df.empty:
        return None
    today = pd.Timestamp.today().normalize()
    try:
        future = df[pd.to_datetime(df["earnings_date"]) >= today]
        if not future.empty:
            return int((pd.to_datetime(future["earnings_date"].iloc[0]) - today).days)
        past = df[pd.to_datetime(df["earnings_date"]) < today]
        if not past.empty:
            return int((pd.to_datetime(past["earnings_date"].iloc[-1]) - today).days)
    except Exception:
        return None
    return None


# ── Main scanner ──────────────────────────────────────────────────────

def scan_alerts(
    db,
    history_lookback: int = 25,
    allow_tickers: "set[str] | None" = None,
) -> list[Alert]:
    """
    Scan the ticker universe for active alerts.

    Reads ``daily_vol`` once, plus a tail of history per ticker for
    rules that need a previous reference (volume spike, regime shifts,
    spread sign-flips). Earnings rules use ``earnings`` table.

    Args:
        allow_tickers: if non-None, restrict the scan to this set of
            tickers (e.g. the union of all watchlists). Default
            ``None`` = full universe. Added 2026-05-19 — operator
            wanted the Alerts page to default to watchlist-scope so
            it doesn't drown the operator in 200+ universe-wide
            hits.

    Returns alerts sorted by (severity DESC, ticker ASC).
    """
    try:
        latest = db.get_all_latest()
    except Exception:
        return []
    if latest is None or latest.empty:
        return []
    if allow_tickers is not None:
        latest = latest[latest["ticker"].astype(str).str.upper().isin(
            {t.upper() for t in allow_tickers}
        )]
        if latest.empty:
            return []

    alerts: list[Alert] = []

    # Single-row anomaly + flow rules first (fast, no history needed).
    for _, row in latest.iterrows():
        for fn in (
            rule_iv_percentile_low,
            rule_iv_percentile_high,
            rule_iv_hv_cheap,
            rule_iv_hv_rich,
            rule_convergence_high,
            rule_pcr_put_heavy,
            rule_pcr_call_heavy,
        ):
            a = fn(row)
            if a is not None:
                alerts.append(a)

    # Rules that need short history per ticker.
    for _, row in latest.iterrows():
        ticker = str(row.get("ticker", ""))
        if not ticker:
            continue
        try:
            hist = db.get_ticker_history(ticker).tail(history_lookback)
        except Exception:
            hist = None
        for fn in (rule_volume_spike, rule_iv_expansion, rule_iv_crush, rule_spread_signflip):
            a = fn(row, hist)
            if a is not None:
                alerts.append(a)

        days_to_er = _days_to_next_earnings(db, ticker)
        for fn in (rule_earnings_imminent, rule_earnings_just_passed):
            a = fn(ticker, days_to_er)
            if a is not None:
                alerts.append(a)

    alerts.sort(key=lambda a: (-a.severity, a.ticker))
    return alerts


def count_by_category(alerts: Iterable[Alert]) -> dict[str, int]:
    """Aggregate counter for the sidebar badge + page filter strip."""
    out = {ANOMALY: 0, FLOW: 0, REGIME: 0, EARNINGS: 0}
    for a in alerts:
        if a.type in out:
            out[a.type] += 1
    return out
