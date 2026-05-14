"""
IV quality warning banner — v0.6.1.

Renders above the Scope-page KPIs when the IV-robustness subsystem
flagged the ticker as CAUTION or BLOCK. Pulls the persisted columns
from ``daily_vol`` (filled by ``scripts/compute/compute_iv_quality.py``).

When ``iv_recommendation = 'TRADE'`` the banner is silent. When
``CAUTION``: amber, soft warning. When ``BLOCK``: red, do-not-trade.
"""
from __future__ import annotations

import json
from typing import Any

from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS, rgba


def _format_warnings(warnings: list[str] | str | None) -> list[str]:
    """Accept JSON list, Python list, or None — normalise to ``list[str]``."""
    if warnings is None or warnings == "":
        return []
    if isinstance(warnings, list):
        return [str(w) for w in warnings]
    if isinstance(warnings, str):
        try:
            data = json.loads(warnings)
            if isinstance(data, list):
                return [str(w) for w in data]
        except json.JSONDecodeError:
            return [warnings]
    return []


def render_iv_quality_banner(st, latest: dict[str, Any]) -> None:
    """Render the warning banner if quality < TRADE; silent otherwise."""
    recommendation = latest.get("iv_recommendation")
    if recommendation is None or recommendation == "TRADE":
        return

    quality_score = latest.get("iv_quality_score") or 0
    warnings = _format_warnings(latest.get("iv_warnings"))
    robust_ivr = latest.get("robust_iv_rank")
    divergence = latest.get("ivr_ivp_divergence")

    if recommendation == "BLOCK":
        bg = rgba(COLORS.get("warn", "#ff4466"), 0.15)
        fg = COLORS.get("warn", "#ff4466")
        icon = "⛔"
        verdict_text = "BLOCK"
    elif recommendation == "CAUTION":
        bg = rgba(COLORS.get("amber", "#ff9f43"), 0.15)
        fg = COLORS.get("amber", "#ff9f43")
        icon = "⚠"
        verdict_text = "CAUTION"
    else:
        return

    extras: list[str] = []
    if robust_ivr is not None:
        extras.append(f"Robust IVR: {float(robust_ivr):.1f}")
    if divergence is not None:
        extras.append(f"IVR-IVP divergence: {float(divergence):.1f} pt")
    extras_line = " · ".join(extras) if extras else ""

    warnings_html = "".join(
        f"<div style='margin-top:4px;'>• {w}</div>" for w in warnings
    )

    html = f"""
<div style="background:{bg};
            border-left:3px solid {fg};
            padding:12px 16px;
            margin:8px 0 16px 0;
            border-radius:4px;
            font-family:'DM Sans', sans-serif;">
  <div style="color:{fg};font-weight:600;font-size:13px;letter-spacing:0.04em;">
    {icon} {verdict_text} — IV data quality score: {int(quality_score)}/100
  </div>
  {f'<div style="color:{COLORS["muted"]};font-size:11px;margin-top:4px;font-family:JetBrains Mono, monospace;">{extras_line}</div>' if extras_line else ''}
  <div style="color:{COLORS['text']};font-size:11px;line-height:1.5;margin-top:6px;">
    {warnings_html}
  </div>
</div>
"""
    render_html(st, html)
