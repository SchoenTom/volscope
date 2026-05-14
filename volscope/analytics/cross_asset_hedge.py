"""
Cross-Asset Hedge — relative-value scanner across vol indices.

A hedge-fund-grade workflow asks: *"VIX is at 14, but VSTOXX is at 21 and
VXFXI at 28 — which hedge is the best value?"* This module compares pairs
of vol indices, computes the current ratio vs its historical distribution,
and surfaces actionable cross-asset recommendations:

  - "VIX cheap vs VSTOXX (z=-2.1) → SPY puts better hedge value than EuroSTOXX"
  - "VXFXI rich vs VIX (z=+1.8) → take HSI hedge off; reuse capital on SPY"

The module is pure analytics — it consumes snapshot dicts and historical
Series produced by ``vol_index_fetcher`` and returns ranked edges.
No DB writes, no UI imports.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ── Output type ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CrossAssetEdge:
    """Relative-value edge between two vol indices.

    Attributes
    ----------
    cheap_asset    : Symbol that's currently cheap vs partner.
    rich_asset     : Symbol that's currently rich vs partner.
    ratio          : ``cheap_asset_level / rich_asset_level`` (current).
    ratio_z        : Z-score of current ratio vs 252-day history.
    severity       : Categorical: "extreme" | "elevated" | "normal".
    recommendation : Human-readable trade thesis (1 sentence).
    confidence     : 0..1 — function of n_obs and signal strength.
    """
    cheap_asset:    str
    rich_asset:     str
    ratio:          float
    ratio_z:        float
    severity:       str
    recommendation: str
    confidence:     float


@dataclass(frozen=True)
class CrossAssetSnapshot:
    """One vol-index snapshot input to the cross-asset analyser.

    Mirrors the dict structure already produced by
    ``vol_index_fetcher.vol_index_snapshot`` so callers can pass through
    without reshaping.
    """
    name:    str                             # e.g. "VIX", "VSTOXX"
    level:   Optional[float]
    history: Optional[pd.Series] = None      # closing prices, sorted ascending


# ── Configuration ────────────────────────────────────────────────────────

# Z-score thresholds for severity classification.
_Z_EXTREME  = 2.0
_Z_ELEVATED = 1.0

# Minimum historical observations required to compute a stable ratio z.
_MIN_OBS = 60


# ── Pair analysis ────────────────────────────────────────────────────────

def compute_pair_edge(
    a: CrossAssetSnapshot,
    b: CrossAssetSnapshot,
) -> Optional[CrossAssetEdge]:
    """Compute the relative-value edge for one pair.

    Returns None if either snapshot lacks data or the historical sample
    is too small. The cheap/rich orientation flips automatically based
    on the sign of the z-score.
    """
    if a.level is None or b.level is None or b.level <= 0:
        return None
    if a.history is None or b.history is None:
        return None
    # Align on common dates (inner join), drop NaN.
    df = pd.concat({a.name: a.history, b.name: b.history}, axis=1).dropna()
    if len(df) < _MIN_OBS:
        return None

    historical_ratio = df[a.name] / df[b.name]
    historical_ratio = historical_ratio.replace([np.inf, -np.inf], np.nan).dropna()
    if len(historical_ratio) < _MIN_OBS:
        return None

    current_ratio = a.level / b.level
    mean = float(historical_ratio.mean())
    std  = float(historical_ratio.std(ddof=1))
    if std <= 0 or not np.isfinite(std):
        return None
    z = (current_ratio - mean) / std

    if abs(z) >= _Z_EXTREME:
        severity = "extreme"
    elif abs(z) >= _Z_ELEVATED:
        severity = "elevated"
    else:
        severity = "normal"

    # Negative z → ratio LOW → a is cheap relative to its history → a is cheap, b is rich.
    if z < 0:
        cheap, rich = a.name, b.name
    else:
        cheap, rich = b.name, a.name

    recommendation = _build_recommendation(cheap, rich, z, severity)
    confidence = min(1.0, len(historical_ratio) / 252.0) * min(1.0, abs(z) / _Z_EXTREME)

    return CrossAssetEdge(
        cheap_asset=cheap,
        rich_asset=rich,
        ratio=round(current_ratio, 4),
        ratio_z=round(z, 2),
        severity=severity,
        recommendation=recommendation,
        confidence=round(confidence, 2),
    )


def _build_recommendation(cheap: str, rich: str, z: float, severity: str) -> str:
    """Compose a 1-sentence trade thesis."""
    base = f"{cheap} cheap vs {rich} (z={z:+.1f})"
    # Map well-known vol-index → underlying ETF for actionable wording.
    proxy = {
        "VIX":    "SPY",
        "VXN":    "QQQ",
        "RVX":    "IWM",
        "VXFXI":  "FXI",
        "VSTOXX": "EuroSTOXX",
        "V2X":    "EuroSTOXX",
        "VDAX":   "DAX",
        "VDAX-NEW": "DAX",
        "GVZ":    "GLD",
        "OVX":    "USO",
        "VXEEM":  "EEM",
    }
    cheap_proxy = proxy.get(cheap.upper(), cheap)
    rich_proxy  = proxy.get(rich.upper(), rich)

    if severity == "extreme":
        return f"{base} — {cheap_proxy} hedge clearly better value than {rich_proxy}; rotate"
    if severity == "elevated":
        return f"{base} — prefer {cheap_proxy} hedge over {rich_proxy} on relative value"
    return f"{base} — relative value within normal bounds"


# ── Universe scan ────────────────────────────────────────────────────────

def scan_cross_asset_edges(
    snapshots: list[CrossAssetSnapshot],
    min_severity: str = "normal",
) -> list[CrossAssetEdge]:
    """Compute all unique pair-edges across the snapshot list and rank.

    Parameters
    ----------
    snapshots    : List of CrossAssetSnapshot (≥ 2).
    min_severity : "normal" | "elevated" | "extreme" — filter cutoff.

    Returns
    -------
    list[CrossAssetEdge]
        Sorted descending by abs(ratio_z) — strongest signals first.
    """
    rank = {"normal": 0, "elevated": 1, "extreme": 2}
    cutoff = rank.get(min_severity, 0)

    edges: list[CrossAssetEdge] = []
    for i in range(len(snapshots)):
        for j in range(i + 1, len(snapshots)):
            edge = compute_pair_edge(snapshots[i], snapshots[j])
            if edge is None:
                continue
            if rank.get(edge.severity, 0) >= cutoff:
                edges.append(edge)

    edges.sort(key=lambda e: abs(e.ratio_z), reverse=True)
    return edges


# ── Display helper ───────────────────────────────────────────────────────

_BADGE_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


def cross_asset_card_html(edge: CrossAssetEdge) -> str:
    """Render one CrossAssetEdge as a compact card."""
    color = {
        "extreme":  "#00d4aa",
        "elevated": "#7db4ff",
        "normal":   "#8a8f9e",
    }.get(edge.severity, "#8a8f9e")
    sev_label = edge.severity.upper()
    return (
        f'<div style="font-family:{_BADGE_MONO};font-size:11px;'
        f'background:#15162088;border:1px solid #1e2038;border-left:3px solid {color};'
        f'border-radius:6px;padding:10px 12px;margin-bottom:6px;">'
        f'<div style="display:flex;justify-content:space-between;margin-bottom:4px;">'
        f'<span style="color:{color};font-weight:700;">{edge.cheap_asset} ↔ {edge.rich_asset}</span>'
        f'<span style="color:{color};font-size:9px;background:{color}22;padding:1px 6px;border-radius:3px;">'
        f'{sev_label}</span>'
        f'</div>'
        f'<div style="color:#e0e4ef;">{edge.recommendation}</div>'
        f'<div style="color:#8a8f9e;font-size:10px;margin-top:3px;">'
        f'ratio {edge.ratio:.3f} · z {edge.ratio_z:+.2f} · conf {edge.confidence:.0%}'
        f'</div>'
        f'</div>'
    )
