"""
Inline SVG sparkline — 50×14 px by default.

A *single-purpose* component: hand it a sequence of numbers, get back
a tiny inline SVG that renders directly inside any HTML block. No
Plotly, no Streamlit chart frame, no rerender cost — the SVG goes
straight into the DOM.

Used by:
    - Scanner row 30-day IV trace
    - Status bar 5-day IV mini-chart
    - Discover metric-wall cards

Design choices
--------------
* Auto-fits via ``preserveAspectRatio="none"`` — the parent decides width.
* Single line, no axes, no labels — context is in the surrounding card.
* Color either explicit or auto: green if last >= first, red otherwise.
* Filled area below the line at 8 % opacity — gives the line some weight
  without dominating the row.

The whole module is pure-Python with no third-party deps.
"""
from __future__ import annotations

from typing import Iterable, Optional


def sparkline_svg(
    values: Iterable[float],
    *,
    width: int = 50,
    height: int = 14,
    color: Optional[str] = None,
    fill: bool = True,
) -> str:
    """Render a values-sequence as an inline SVG sparkline.

    Parameters
    ----------
    values
        Numeric sequence. Length must be ≥ 2; otherwise returns a
        single-line spacer of the requested size.
    width / height
        Pixel size in the host page. Aspect is fluid via the SVG's
        ``viewBox`` so the line scales cleanly inside CSS layouts.
    color
        Hex color to use. Auto-picks green/red based on direction
        when None.
    fill
        Whether to drop an 8 %-alpha fill below the line.

    Returns
    -------
    str — a single ``<svg>...</svg>`` snippet, safe to drop inside any
    ``unsafe_allow_html=True`` markdown block.
    """
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return f'<svg width="{width}" height="{height}"></svg>'

    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        vmax = vmin + 1.0

    n = len(vals)
    pad = 1.0   # 1-px breathing room top & bottom
    span = (height - 2 * pad)

    pts = []
    for i, v in enumerate(vals):
        x = i * (width - 1) / (n - 1)
        # Map vmax → top (y small), vmin → bottom (y large)
        y = pad + span * (1 - (v - vmin) / (vmax - vmin))
        pts.append(f"{x:.1f},{y:.2f}")

    is_up = vals[-1] >= vals[0]
    auto_color = "#00d4aa" if is_up else "#ff4466"
    stroke = color or auto_color
    fill_rgb = "0,212,170" if is_up and color is None else \
               "255,68,102" if (not is_up) and color is None else \
               _hex_to_rgb_str(stroke)

    polyline = (
        f'<polyline fill="none" stroke="{stroke}" stroke-width="1.2" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'points="{" ".join(pts)}" />'
    )
    fill_svg = ""
    if fill:
        # Close the polygon to the baseline so we get a filled area
        first_x = pts[0].split(",")[0]
        last_x = pts[-1].split(",")[0]
        bottom_y = f"{height - pad:.2f}"
        fill_pts = " ".join(pts) + f" {last_x},{bottom_y} {first_x},{bottom_y}"
        fill_svg = (
            f'<polygon fill="rgba({fill_rgb},0.08)" stroke="none" '
            f'points="{fill_pts}" />'
        )

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" style="display:inline-block;vertical-align:middle;">'
        f'{fill_svg}{polyline}'
        f'</svg>'
    )


def _hex_to_rgb_str(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "120,125,150"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r},{g},{b}"
