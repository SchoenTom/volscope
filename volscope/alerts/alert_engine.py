"""
Vol Alert Engine — evaluate threshold rules against live vol data.

Answers the trader's passive question: "Tell me when vol gets cheap enough
to act — I don't want to stare at the app all day."

Supported metrics:
  iv_percentile — IV rank in historical distribution [0, 100]
  iv_rank       — IV rank by range [0, 100]
  vrp           — iv_30d / hv_20d ratio (variance risk premium)

Operators: < | > | <= | >=

Channels:
  log     — write to ~/.volscope_alerts.log (always done)
  desktop — macOS Notification Center via osascript (graceful fallback)
  email   — SMTP (optional; requires VOLSCOPE_SMTP_* env vars)

Usage in cron:
    python scripts/backtest/run_alerts.py

Dependencies: stdlib only (no streamlit, no yfinance).
"""
from __future__ import annotations

import math
import os
import smtplib
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import pandas as pd


# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_METRICS: tuple[str, ...] = ("iv_percentile", "iv_rank", "vrp")
SUPPORTED_OPERATORS: tuple[str, ...] = ("<", ">", "<=", ">=")
SUPPORTED_CHANNELS: tuple[str, ...] = ("log", "desktop", "email")

# Default built-in alert rules shown in the "create rule" form as suggestions.
DEFAULT_RULE_SUGGESTIONS: list[dict] = [
    {
        "label": "IV Percentile BUY",
        "metric": "iv_percentile",
        "operator": "<",
        "threshold": 20.0,
        "channel": "desktop",
    },
    {
        "label": "IV Percentile RICH",
        "metric": "iv_percentile",
        "operator": ">",
        "threshold": 80.0,
        "channel": "desktop",
    },
    {
        "label": "VRP below 0.90 (cheap vs realized)",
        "metric": "vrp",
        "operator": "<",
        "threshold": 0.90,
        "channel": "log",
    },
]

_DEFAULT_LOG = Path("~/.volscope_alerts.log").expanduser()


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AlertRule:
    """Immutable alert rule persisted in the DB.

    Attributes
    ----------
    id        : DB-assigned integer primary key.
    ticker    : Ticker symbol to watch, or "*" to check all command tickers.
    metric    : One of SUPPORTED_METRICS.
    operator  : One of SUPPORTED_OPERATORS.
    threshold : Numeric threshold for the comparison.
    channel   : One of SUPPORTED_CHANNELS.
    label     : User-facing rule name (e.g. "AAPL vol buy").
    enabled   : False = rule is paused without being deleted.
    """

    id: int
    ticker: str
    metric: str
    operator: str
    threshold: float
    channel: str
    label: str
    enabled: bool


@dataclass(frozen=True)
class AlertFired:
    """Immutable record of one alert firing.

    Attributes
    ----------
    rule_id   : FK to the AlertRule that fired.
    rule_label: Human label of the rule.
    ticker    : Ticker that triggered the rule.
    metric    : Metric name that was evaluated.
    value     : Actual metric value at fire time.
    threshold : Rule threshold.
    operator  : Rule operator.
    message   : Human-readable one-line summary.
    fired_at  : ISO-8601 datetime string (UTC).
    """

    rule_id: int
    rule_label: str
    ticker: str
    metric: str
    value: float
    threshold: float
    operator: str
    message: str
    fired_at: str


# ── Metric extraction ─────────────────────────────────────────────────────────

def compute_metric_value(metric: str, row: pd.Series) -> Optional[float]:
    """Extract a scalar metric value from a daily_vol row.

    Returns None when the metric is unknown or cannot be computed.
    """
    if metric == "iv_percentile":
        return _to_float(row.get("iv_percentile"))
    if metric == "iv_rank":
        return _to_float(row.get("iv_rank"))
    if metric == "vrp":
        iv = _to_float(row.get("iv_30d"))
        hv = _to_float(row.get("hv_20d"))
        if iv is not None and hv is not None and hv > 0:
            return iv / hv
        return None
    if metric == "convergence_score":
        # Read from the precomputed daily_vol column. Filled by
        # scripts/compute/compute_convergence_daily.py — when missing the alert
        # silently no-ops, never silently fires.
        return _to_float(row.get("convergence_score"))
    return None


# ── Rule evaluation ───────────────────────────────────────────────────────────

def evaluate_rule(
    rule: AlertRule,
    ticker: str,
    row: pd.Series,
) -> Optional[AlertFired]:
    """Check whether one rule fires for one ticker row.

    Returns an AlertFired if the condition is met, None otherwise.
    Silently returns None on any invalid data.
    """
    if not rule.enabled:
        return None
    if rule.ticker != "*" and rule.ticker.upper() != ticker.upper():
        return None

    value = compute_metric_value(rule.metric, row)
    if value is None:
        return None

    if not _compare(value, rule.operator, rule.threshold):
        return None

    op_str = rule.operator
    message = (
        f"[VolScope] {ticker} — {rule.label}: "
        f"{rule.metric} = {value:.2f} {op_str} {rule.threshold:.2f}"
    )
    return AlertFired(
        rule_id=rule.id,
        rule_label=rule.label,
        ticker=ticker,
        metric=rule.metric,
        value=value,
        threshold=rule.threshold,
        operator=rule.operator,
        message=message,
        fired_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat()[:19],
    )


def evaluate_rules(
    rules: list[AlertRule],
    latest_rows: dict[str, pd.Series],
) -> list[AlertFired]:
    """Evaluate all enabled rules against all ticker rows.

    Parameters
    ----------
    rules       : List of AlertRule to check.
    latest_rows : Mapping of ticker → most-recent daily_vol pd.Series.

    Returns
    -------
    List of AlertFired, one entry per (rule, ticker) pair that triggered.
    """
    fired: list[AlertFired] = []
    for rule in rules:
        if not rule.enabled:
            continue
        # "*" wildcard checks every available ticker.
        tickers = list(latest_rows.keys()) if rule.ticker == "*" else [rule.ticker]
        for ticker in tickers:
            row = latest_rows.get(ticker)
            if row is None:
                continue
            result = evaluate_rule(rule, ticker, row)
            if result is not None:
                fired.append(result)
    return fired


# ── Channel dispatch ──────────────────────────────────────────────────────────

def dispatch_log(fired: AlertFired, log_path: Path = _DEFAULT_LOG) -> None:
    """Append alert to a plain-text log file."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as fh:
            fh.write(f"[{fired.fired_at}] {fired.message}\n")
    except Exception:
        pass


def dispatch_desktop(fired: AlertFired) -> bool:
    """Send a macOS Notification Center notification via osascript.

    Returns True on success, False when not on macOS or osascript fails.
    """
    if sys.platform != "darwin":
        return False
    script = (
        f'display notification "{fired.message}" '
        f'with title "VolScope Alert" '
        f'subtitle "{fired.ticker}"'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            timeout=5,
            capture_output=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def dispatch_email(fired: AlertFired) -> bool:
    """Send an email via SMTP using env vars VOLSCOPE_SMTP_*.

    Required env vars:
        VOLSCOPE_SMTP_HOST    — e.g. smtp.gmail.com
        VOLSCOPE_SMTP_PORT    — e.g. 587
        VOLSCOPE_SMTP_USER    — sender address
        VOLSCOPE_SMTP_PASS    — password or app-specific password
        VOLSCOPE_SMTP_TO      — recipient address

    Returns True on success, False otherwise.
    """
    host = os.environ.get("VOLSCOPE_SMTP_HOST", "")
    port = int(os.environ.get("VOLSCOPE_SMTP_PORT", "587"))
    user = os.environ.get("VOLSCOPE_SMTP_USER", "")
    pwd  = os.environ.get("VOLSCOPE_SMTP_PASS", "")
    to   = os.environ.get("VOLSCOPE_SMTP_TO", "")

    if not all([host, user, pwd, to]):
        return False

    msg = MIMEText(fired.message)
    msg["Subject"] = f"VolScope Alert — {fired.ticker} {fired.rule_label}"
    msg["From"] = user
    msg["To"] = to

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(user, pwd)
            smtp.sendmail(user, [to], msg.as_string())
        return True
    except Exception:
        return False


def dispatch_alert(
    fired: AlertFired,
    log_path: Path = _DEFAULT_LOG,
) -> None:
    """Dispatch a fired alert to all appropriate channels.

    Always logs to the log file.  Desktop / email are attempted based on
    the rule's channel setting.
    """
    dispatch_log(fired, log_path)
    if fired.channel in ("desktop",):
        dispatch_desktop(fired)
    elif fired.channel == "email":
        if not dispatch_email(fired):
            # Email unavailable — fall back to desktop
            dispatch_desktop(fired)


# ── HTML display helpers ───────────────────────────────────────────────────────

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


def _metric_label(metric: str) -> str:
    return {
        "iv_percentile": "IV Pct",
        "iv_rank":       "IV Rank",
        "vrp":           "VRP",
    }.get(metric, metric)


def alert_rule_html(rule: AlertRule) -> str:
    """One-line HTML row for displaying a rule in the UI."""
    from volscope.ui.styles.theme import COLORS

    enabled_dot = (
        f'<span style="color:{COLORS["accent"]};">●</span>'
        if rule.enabled
        else f'<span style="color:{COLORS["muted"]};">○</span>'
    )
    ticker_str = rule.ticker if rule.ticker != "*" else "all"
    metric_str = _metric_label(rule.metric)
    channel_icon = {"log": "📄", "desktop": "🔔", "email": "✉"}.get(rule.channel, "")
    return (
        f'<div style="font-family:{_MONO};font-size:11px;padding:4px 0;'
        f'display:flex;align-items:center;gap:8px;">'
        f'{enabled_dot}'
        f'<span style="color:{COLORS["text"]};font-weight:600;min-width:60px;">'
        f'{ticker_str}</span>'
        f'<span style="color:{COLORS["muted"]};">{metric_str} {rule.operator} {rule.threshold:.2f}</span>'
        f'<span style="color:{COLORS["label"]};font-size:10px;flex:1;">{rule.label}</span>'
        f'<span style="font-size:12px;">{channel_icon}</span>'
        f'</div>'
    )


def alert_fired_html(fired: AlertFired) -> str:
    """One-line HTML row for displaying a fired alert in the UI."""
    from volscope.ui.styles.theme import COLORS

    return (
        f'<div style="font-family:{_MONO};font-size:10px;padding:2px 0;'
        f'color:{COLORS["warn"]};">'
        f'⚡ [{fired.fired_at[:10]}] {fired.ticker} — {fired.rule_label}: '
        f'{fired.metric} = {fired.value:.2f} {fired.operator} {fired.threshold:.2f}'
        f'</div>'
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _to_float(v: object) -> Optional[float]:
    """Convert v to float; return None if invalid or NaN/Inf."""
    if v is None:
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _compare(value: float, operator: str, threshold: float) -> bool:
    """Apply a comparison operator."""
    if operator == "<":
        return value < threshold
    if operator == ">":
        return value > threshold
    if operator == "<=":
        return value <= threshold
    if operator == ">=":
        return value >= threshold
    return False
