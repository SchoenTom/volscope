"""
Earnings Watch — agent that surfaces upcoming-earnings events on
tracked positions and computes the implied move + IV-elevation context.

Unlike ``earnings_crush`` (which estimates HISTORICAL post-earnings IV
drops to warn against rich pre-earnings entries), this module focuses
on the FORWARD view: which of my positions has earnings approaching,
how much is the market pricing the move, and how does that compare to
typical realised earnings moves.

The output ``EarningsAlert`` is intended for two surfaces:
  - Portfolio page: per-position banner ("⚠ MSTR ER in 4 days, expected
    move ±12% (consensus); historical avg crush -22pt")
  - Daily macOS notification (via run_alerts.py extension)

Pure analytics — composes earnings_fetcher + expected_move +
earnings_crush. No I/O of its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from volscope.analytics.expected_move import ConsensusMove, compute_expected_move
from volscope.analytics.earnings_crush import CrushEstimate


# ── Output ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EarningsAlert:
    """Forward-looking earnings alert for one ticker."""
    ticker:           str
    earnings_date:    date
    days_to_earnings: int
    severity:         str          # "info" | "watch" | "warn" | "alert"
    expected_move:    Optional[ConsensusMove]
    crush_estimate:   Optional[CrushEstimate]
    iv_pct_now:       Optional[float]
    headline:         str
    body:             str


# ── Severity escalation rules ───────────────────────────────────────────

# Days-to-earnings escalation. The trader cares MORE the closer ER is.
def _severity_for_dte(dte: int) -> str:
    if dte < 0:
        return "info"           # already happened
    if dte <= 1:
        return "alert"          # last call
    if dte <= 3:
        return "warn"
    if dte <= 7:
        return "watch"
    return "info"


# IV-percentile elevation modifier. If IV is rich AND ER is approaching,
# the position is in a textbook IV-crush trap — escalate severity.
_PCTL_RICH_THRESHOLD = 70.0


def _bump_severity_for_iv_richness(base: str, iv_pct: Optional[float]) -> str:
    if iv_pct is None or iv_pct < _PCTL_RICH_THRESHOLD:
        return base
    order = ["info", "watch", "warn", "alert"]
    idx = order.index(base) if base in order else 0
    return order[min(idx + 1, len(order) - 1)]


# ── Builder ─────────────────────────────────────────────────────────────

def build_earnings_alert(
    ticker:           str,
    earnings_date:    date,
    spot:             float,
    iv_pct:           Optional[float],
    iv_percentile:    Optional[float] = None,
    options_df:       Optional[pd.DataFrame] = None,
    crush_estimate:   Optional[CrushEstimate] = None,
    today:            Optional[date] = None,
) -> Optional[EarningsAlert]:
    """Build an EarningsAlert for one (ticker, earnings_date) pair.

    Returns None when earnings_date is more than 30 calendar days away
    (we don't surface alerts that far out — too much noise).
    """
    today = today or date.today()
    dte = (earnings_date - today).days

    if dte > 30 or dte < -7:
        return None

    severity = _severity_for_dte(dte)
    severity = _bump_severity_for_iv_richness(severity, iv_percentile)

    em = (
        compute_expected_move(ticker, spot, iv_pct, max(1, dte), options_df)
        if spot > 0 and (iv_pct is not None or options_df is not None)
        else None
    )

    headline, body = _build_text(
        ticker=ticker,
        dte=dte,
        em=em,
        crush=crush_estimate,
        iv_pct=iv_pct,
        iv_percentile=iv_percentile,
        severity=severity,
    )

    return EarningsAlert(
        ticker=ticker,
        earnings_date=earnings_date,
        days_to_earnings=dte,
        severity=severity,
        expected_move=em,
        crush_estimate=crush_estimate,
        iv_pct_now=iv_pct,
        headline=headline,
        body=body,
    )


def _build_text(
    ticker:        str,
    dte:           int,
    em:            Optional[ConsensusMove],
    crush:         Optional[CrushEstimate],
    iv_pct:        Optional[float],
    iv_percentile: Optional[float],
    severity:      str,
) -> tuple[str, str]:
    """Compose a human-readable headline + body."""
    if dte < 0:
        headline = f"{ticker} earnings reported {abs(dte)}d ago"
    elif dte == 0:
        headline = f"⚠ {ticker} earnings TODAY"
    elif dte == 1:
        headline = f"⚠ {ticker} earnings in 1 day"
    else:
        headline = f"{ticker} earnings in {dte} days"

    body_parts: list[str] = []
    if em is not None and em.consensus_em_pct is not None:
        body_parts.append(
            f"Expected move ±{em.consensus_em_pct:.1f}% "
            f"(consensus, conf {em.confidence*100:.0f}%)"
        )
    if iv_percentile is not None:
        body_parts.append(f"IV pctl {iv_percentile:.0f}")
    if crush is not None and crush.avg_crush_pct is not None:
        body_parts.append(
            f"hist crush avg {crush.avg_crush_pct:+.1f}pt "
            f"(min {crush.min_crush_pct:+.1f} / max {crush.max_crush_pct:+.1f})"
        )

    body = " · ".join(body_parts) if body_parts else "no quantitative read available"
    return headline, body


# ── Universe scan ───────────────────────────────────────────────────────

def scan_portfolio_earnings(
    db,
    portfolio_tickers: list[str],
    today:             Optional[date] = None,
    max_horizon_days:  int = 30,
) -> list[EarningsAlert]:
    """Scan portfolio tickers for upcoming earnings and build alerts.

    Pulls the next earnings date per ticker from ``earnings`` table,
    the latest spot/IV from ``daily_vol``, and the earnings crush
    distribution from ``earnings_crush.compute_crush_estimate``.

    Returns a list of alerts sorted by severity (alert > warn > watch > info)
    then by days_to_earnings ascending.
    """
    today = today or date.today()
    alerts: list[EarningsAlert] = []

    for ticker in portfolio_tickers:
        try:
            er_df = db.get_upcoming_earnings(ticker, today)
            if er_df is None or er_df.empty:
                continue
            next_er = pd.to_datetime(er_df.iloc[0]["earnings_date"]).date()
            if (next_er - today).days > max_horizon_days:
                continue

            hist = db.get_ticker_history(ticker)
            if hist is None or hist.empty:
                continue
            latest = hist.sort_values("date").iloc[-1]
            spot = float(latest.get("spot_price") or 0.0)
            iv = latest.get("iv_30d")
            iv_pct = float(iv) if iv is not None and not pd.isna(iv) else None
            iv_perc = latest.get("iv_percentile")
            iv_perc_v = float(iv_perc) if iv_perc is not None and not pd.isna(iv_perc) else None

            # Earnings crush from existing analytics (silently skip on failure)
            try:
                from volscope.analytics.earnings_crush import compute_crush_estimate
                crush = compute_crush_estimate(db, ticker)
            except Exception:
                crush = None

            alert = build_earnings_alert(
                ticker=ticker,
                earnings_date=next_er,
                spot=spot,
                iv_pct=iv_pct,
                iv_percentile=iv_perc_v,
                options_df=None,    # caller can pass live chain if available
                crush_estimate=crush,
                today=today,
            )
            if alert is not None:
                alerts.append(alert)
        except Exception:
            # Per-ticker failures are not fatal to the scan
            continue

    severity_rank = {"alert": 0, "warn": 1, "watch": 2, "info": 3}
    alerts.sort(key=lambda a: (severity_rank.get(a.severity, 99), a.days_to_earnings))
    return alerts


# ── HTML helper ─────────────────────────────────────────────────────────

_BADGE_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"

_SEVERITY_COLOR = {
    "alert": "#ff4466",
    "warn":  "#ff9f43",
    "watch": "#7db4ff",
    "info":  "#8a8f9e",
}


def alert_card_html(alert: EarningsAlert) -> str:
    """Compact HTML card for Portfolio / Command Center surfaces."""
    color = _SEVERITY_COLOR.get(alert.severity, "#8a8f9e")
    return (
        f'<div style="background:#15162088;border:1px solid #1e2038;'
        f'border-left:3px solid {color};border-radius:6px;padding:10px 12px;'
        f'margin-bottom:6px;font-family:{_BADGE_MONO};">'
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:center;margin-bottom:4px;">'
        f'<span style="color:{color};font-weight:700;font-size:12px;">'
        f'{alert.headline}'
        f'</span>'
        f'<span style="background:{color}22;color:{color};padding:1px 6px;'
        f'border-radius:3px;font-size:9px;font-weight:700;">'
        f'{alert.severity.upper()}'
        f'</span>'
        f'</div>'
        f'<div style="color:#e0e4ef;font-size:11px;line-height:1.5;">'
        f'{alert.body}'
        f'</div>'
        f'</div>'
    )
