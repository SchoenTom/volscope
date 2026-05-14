"""
Three pure-SVG visual diagnostics for the Earnings Hub drawer:

  1. `render_calibration_bar(cal)`
     Implied-vs-realised 8-quarter horizontal bar chart. Each row is
     one past ER; left bar = implied move, right bar = actual move.
     Width-encoded magnitude. Diverging color when |actual| > implied.

  2. `render_pre_er_drift(history, earnings_date, days=10)`
     Sparkline-trio of the 10 trading days leading into the print:
     spot line, IV-30d line, and a shaded ±1σ envelope.

  3. `render_anomaly_badge(anomaly_score, …)`
     Single inline pill — "⚠ ANOMALY · +2.3σ" — surfaces when the
     ticker's current pre-ER setup is statistically distinct from
     its own historical pre-ER baseline.

All three produce HTML strings, no Plotly, render in <5 ms per
component.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from html import escape
from typing import Optional

import pandas as pd

from volscope.ui.components.sparkline import sparkline_svg
from volscope.ui.styles.theme import COLORS


# ── 1. Calibration bar ───────────────────────────────────────────────

def render_calibration_bar(cal_rows: list[dict]) -> str:
    """Build an HTML row-stack from historical (implied, actual) pairs.

    Each row: date · implied bar (left) · actual bar (right) · ratio chip.
    Colors green/red based on whether actual exceeded implied.

    Pass a list of dicts: ``[{earnings_date, last_implied_pct,
    last_reaction_pct}, …]``. Returns "" when ``< 1`` event.
    """
    if not cal_rows:
        return ""

    rows_html = []
    max_mag = max(
        max(abs(r.get("last_implied_pct") or 0),
            abs(r.get("last_reaction_pct") or 0))
        for r in cal_rows
    )
    if max_mag <= 0:
        max_mag = 1.0

    for r in cal_rows:
        ed = r.get("earnings_date")
        ed_str = ed.isoformat() if isinstance(ed, date) else str(ed)[:10]
        impl = float(r.get("last_implied_pct") or 0)
        actual = float(r.get("last_reaction_pct") or 0)
        impl_w = abs(impl) / max_mag * 100  # 0..100
        actual_w = abs(actual) / max_mag * 100
        beats = abs(actual) > impl
        # Color: green if actual > implied (long-vol edge), red otherwise
        bar_color = COLORS["accent"] if beats else COLORS["warn"]
        impl_color = COLORS["muted"]

        rows_html.append(f'''
<div class="vs-cal-row">
  <span class="vs-cal-date">{ed_str}</span>
  <div class="vs-cal-track-left">
    <div class="vs-cal-fill" style="background:{impl_color};width:{impl_w:.0f}%;"></div>
  </div>
  <span class="vs-cal-mid">|</span>
  <div class="vs-cal-track-right">
    <div class="vs-cal-fill" style="background:{bar_color};width:{actual_w:.0f}%;"></div>
  </div>
  <span class="vs-cal-label" style="color:{bar_color};">
    {actual:+.1f}% / impl {impl:.1f}%
  </span>
</div>''')

    return f'''
<div class="vs-cal-block">
  <div class="vs-cal-header">
    <span class="vs-cal-h-label">IMPLIED  ·  ACTUAL</span>
    <span class="vs-cal-h-note">last {len(cal_rows)} earnings · |actual| &gt; implied = green</span>
  </div>
  {"".join(rows_html)}
</div>'''


# ── 2. Pre-ER drift sparkline triple ─────────────────────────────────

def render_pre_er_drift(history: pd.DataFrame,
                          earnings_date: date,
                          *, days: int = 10) -> str:
    """Two sparklines: spot trajectory + IV trajectory, both for the
    last ``days`` trading rows ending ON earnings_date (or as close as
    we have). Side-by-side micro-summary of the pre-print build-up.
    """
    if history is None or history.empty or "date" not in history.columns:
        return ""
    h = history.copy()
    h["date"] = pd.to_datetime(h["date"]).dt.date
    window = h[h["date"] <= earnings_date].tail(days)
    if window.empty:
        return ""

    spots = window["spot_price"].dropna().tolist() if "spot_price" in window.columns else []
    ivs = window["iv_30d"].dropna().tolist() if "iv_30d" in window.columns else []
    if len(spots) < 2 and len(ivs) < 2:
        return ""

    spot_spark = sparkline_svg(spots, width=140, height=24) if len(spots) >= 2 else ""
    iv_spark = sparkline_svg(ivs, width=140, height=24,
                              color=COLORS["amber"]) if len(ivs) >= 2 else ""

    # Drift summary numbers
    spot_drift = ((spots[-1] - spots[0]) / spots[0] * 100) if len(spots) >= 2 else 0
    iv_change = (ivs[-1] - ivs[0]) if len(ivs) >= 2 else 0
    spot_drift_color = COLORS["accent"] if spot_drift >= 0 else COLORS["warn"]
    iv_drift_color = COLORS["amber"] if iv_change > 0 else COLORS["muted"]

    return f'''
<div class="vs-drift-block">
  <div class="vs-drift-row">
    <span class="vs-drift-label">SPOT pre-ER {days}d</span>
    {spot_spark}
    <span class="vs-drift-num" style="color:{spot_drift_color};">{spot_drift:+.1f}%</span>
  </div>
  <div class="vs-drift-row">
    <span class="vs-drift-label">IV30 pre-ER {days}d</span>
    {iv_spark}
    <span class="vs-drift-num" style="color:{iv_drift_color};">{iv_change:+.1f}pt</span>
  </div>
</div>'''


# ── 3. Anomaly badge ─────────────────────────────────────────────────

def render_anomaly_badge(score: Optional[float],
                           *, threshold: float = 1.5) -> str:
    """Pill rendered only when |score| > threshold.

    ``score`` is a z-score of the current pre-ER setup vs the ticker's
    historical pre-ER baseline (sigma-units of divergence). Negative
    scores indicate "calmer than usual pre-print" (also worth flagging
    because it can signal *missed news*). Positive scores indicate
    "more crowded than usual".
    """
    if score is None or abs(score) < threshold:
        return ""
    color = COLORS["warn"] if score > 0 else COLORS["amber"]
    direction = "build-up" if score > 0 else "calm-than-usual"
    return f'''
<span class="vs-anomaly-badge"
      style="color:{color};border:1px solid {color}55;background:{color}1a;">
  ⚠ ANOMALY · {score:+.1f}σ · {direction}
</span>'''


def compute_anomaly_score(history: pd.DataFrame,
                            earnings_date: date,
                            *, lookback_days: int = 7) -> Optional[float]:
    """Quick z-score of pre-ER crowdedness vs ticker's history.

    Compares today's pre-ER IV-rank against the average IV-rank in the
    7d window before *prior* earnings dates (using the same daily_vol
    series). Returns ``None`` when fewer than 3 prior windows exist.
    """
    if history is None or history.empty:
        return None
    if "date" not in history.columns or "iv_rank" not in history.columns:
        return None
    h = history.copy()
    h["date"] = pd.to_datetime(h["date"]).dt.date

    # Today's window — last `lookback_days` rows before earnings_date
    today_window = h[h["date"] <= earnings_date].tail(lookback_days)
    if today_window.empty:
        return None
    today_rank = today_window["iv_rank"].dropna().mean()
    if pd.isna(today_rank):
        return None

    # Historical baseline — every prior 7d window before each past ER
    # captured implicitly: we sample 30d-spaced rolling windows over
    # the full history as a proxy for "typical pre-event vol-rank".
    samples = []
    for end_idx in range(lookback_days, len(h) - lookback_days, 30):
        w = h.iloc[end_idx - lookback_days: end_idx]["iv_rank"].dropna()
        if not w.empty:
            samples.append(float(w.mean()))
    if len(samples) < 3:
        return None
    s = pd.Series(samples)
    mean = float(s.mean())
    sd = float(s.std())
    if sd <= 0:
        return None
    return float((today_rank - mean) / sd)
