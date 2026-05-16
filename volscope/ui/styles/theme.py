"""
VolScope visual system.

Palette, typography, and reusable CSS classes. Every hex value traces to
PROMPT.md's visual specification — Bloomberg Terminal meets Apple design:
a dark cockpit at night where information glows instead of shouts.

Fonts:
    JetBrains Mono — numbers, data, KPI values (crisp, aligned)
    DM Sans        — labels, UI chrome, prose (clean, modern)
"""
from __future__ import annotations


def rgba(hex_color: str, alpha: float) -> str:
    """
    Convert a 6-char hex color to an rgba(r,g,b,a) string.

    Plotly accepts ``rgba()`` everywhere; the 8-char hex form
    (``#00d4aa55``) is rejected by some plot types (candlestick
    fillcolor, contour line color). Use this helper instead of string
    concatenation so we get a single, robust path.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"rgba() expects a 6-char hex color, got {hex_color!r}")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.3f})"

COLORS: dict[str, str] = {
    # Backgrounds
    "bg": "#0a0b0f",          # page — near-black, slightly blue
    "surface": "#12131a",     # sidebar, elevated panels
    "card": "#151620",        # cards, containers one level above surface
    "hover": "#181924",       # hover state
    "border": "#1e2038",      # barely-visible dividers
    # Text
    "text": "#e0e4ef",
    "muted": "#8a8f9e",
    "label": "#424666",       # tiny uppercase labels
    # Accents (semantic)
    "accent": "#00d4aa",      # primary — IV, cheap, go
    "accent2": "#5b8cff",     # secondary — HV, calm blue
    "warn": "#ff4466",        # danger — rich, alerts
    "amber": "#ff9f43",       # warning — IV Rank mid-high
    "gold": "#ffd700",        # highlight — earnings markers

    # Pro Chart role-keys (Phase 4) — explicit aliases so the chart
    # never hardcodes a hex. Project palette wins over the spec's
    # TradingView-marketing hex for cross-page consistency.
    "candle_up":   "#00d4aa",  # green up-candle (= accent)
    "candle_down": "#ff4466",  # red down-candle (= warn)
    "iv_overlay":  "#ff9f43",  # IV line (= amber)
    "spike":       "#787B86",  # crosshair / spike-line — new key

    # Redesign v3 (2026-05-12) — extra surface layers for stacked panels
    # (Risk-Navigator-style tables inside cards) and grid-cell backgrounds.
    "card_elevated": "#1a1b27",  # row hover inside cards
    "cell":          "#1d1e2b",  # individual grid cell (option chain etc.)

    # Legacy aliases kept for backwards compat with older code paths.
    "panel": "#12131a",
    "grid": "#1e2038",
}


# ── Redesign v3 — diverging & sequential scales for data-cells ──────
# These let any KPI cell encode MAGNITUDE not just direction. Use
# ``heat_color(v, vmin, vmax)`` (defined below) to translate a value
# into a hex string for a background fill.

# Diverging — symmetric around zero. Centered at HEAT[50].
HEAT: tuple[tuple[float, str], ...] = (
    (-1.00, "#b71c1c"),  # deepest red
    (-0.75, "#d32f2f"),
    (-0.50, "#e53935"),
    (-0.25, "#f06292"),
    ( 0.00, "#3a3d52"),  # neutral (matches `label`-grey for transparent feel)
    ( 0.25, "#66bb6a"),
    ( 0.50, "#43a047"),
    ( 0.75, "#2e7d32"),
    ( 1.00, "#1b5e20"),  # deepest green
)

# Sequential — for IV percentile, IV rank, density (0..1 inputs).
SEQ: tuple[tuple[float, str], ...] = (
    (0.0,  "#1a237e"),  # deep blue — cheap end
    (0.25, "#5b8cff"),
    (0.50, "#5bc8b0"),  # teal neutral
    (0.75, "#ff9f43"),
    (1.00, "#ff4466"),  # red — rich end
)


def _interpolate(scale: tuple[tuple[float, str], ...], x: float) -> str:
    """Pick a hex color from a (stop, hex)-tuple ladder via linear blend
    of the surrounding stops. ``x`` is clamped to the ladder's range."""
    x = max(scale[0][0], min(scale[-1][0], x))
    for (a_v, a_hex), (b_v, b_hex) in zip(scale, scale[1:]):
        if a_v <= x <= b_v:
            if b_v == a_v:
                return a_hex
            t = (x - a_v) / (b_v - a_v)
            ar, ag, ab = int(a_hex[1:3], 16), int(a_hex[3:5], 16), int(a_hex[5:7], 16)
            br, bg, bb = int(b_hex[1:3], 16), int(b_hex[3:5], 16), int(b_hex[5:7], 16)
            r = round(ar + t * (br - ar))
            g = round(ag + t * (bg - ag))
            b = round(ab + t * (bb - ab))
            return f"#{r:02x}{g:02x}{b:02x}"
    return scale[-1][1]


def heat_color(value: float, vmin: float, vmax: float) -> str:
    """Map ``value`` ∈ [vmin, vmax] to a diverging-heat hex.

    Useful for P&L cells, Greeks magnitude, IV-shifts in scenario
    matrices. Symmetric: zero maps to neutral grey, extremes map to
    HEAT[-1.0] / HEAT[1.0].
    """
    if vmax <= vmin:
        return _interpolate(HEAT, 0.0)
    # Normalise symmetric: take the larger magnitude of the bounds
    bound = max(abs(vmin), abs(vmax))
    if bound <= 1e-9:
        return _interpolate(HEAT, 0.0)
    return _interpolate(HEAT, value / bound)


def seq_color(value: float, vmin: float = 0.0, vmax: float = 100.0) -> str:
    """Map a 0..100 (or any range) value to the SEQ scale.

    Use for IV percentile / IV rank cells where 0 = cheap (blue),
    50 = neutral (teal), 100 = rich (red).
    """
    if vmax <= vmin:
        return _interpolate(SEQ, 0.5)
    return _interpolate(SEQ, (value - vmin) / (vmax - vmin))

# Translucent fills derived from the semantic palette.
FILL_RICH = "rgba(255, 68, 102, 0.12)"
FILL_CHEAP = "rgba(0, 212, 170, 0.12)"

# ── Design tokens (one source of truth for spacing / type / radius) ───
# Apple-Style pass 2026-05-10: type scale capped at five sizes, spacing on a
# generous Apple-marketing rhythm, motion curves shared across pages.

# Restrained type scale — five sizes, period. Anything outside this breaks
# the rhythm.
TYPE: dict[str, int] = {"micro": 11, "label": 13, "body": 15, "lead": 22, "hero": 34}

# Apple-marketing spacing rhythm. SPACE.section is the gap between
# top-level sections of the LEAPS pages.
SPACE: dict[str, int] = {
    "xs": 4, "sm": 8, "md": 16, "lg": 32, "xl": 56, "section": 80,
}

# Soft, modern radii.
RADIUS: dict[str, int] = {"sm": 4, "md": 8, "lg": 14}

# Two KPI grid variants — hero (3 col, big numbers) for the headline KPIs,
# detail (5 col, restrained) for Greeks and sub-stats.
KPI_HERO:   dict[str, int] = {"cols": 3, "min_w": 200}
KPI_DETAIL: dict[str, int] = {"cols": 5, "min_w": 132}

# Backwards-compat alias — older dossier code still references KPI.
KPI: dict[str, int] = {"min_w": KPI_DETAIL["min_w"], "row_cols": KPI_DETAIL["cols"], "gap": 10}

# Convergence dial geometry — single source for Lab Index + Dossier.
DIAL: dict[str, object] = {"size": 84, "stroke": 6, "track": COLORS["border"]}

# Motion — single source of curve and timing across all pages.
MOTION_FAST = "200ms cubic-bezier(0.4, 0.0, 0.2, 1)"
MOTION_BASE = "400ms cubic-bezier(0.4, 0.0, 0.2, 1)"
MOTION_SLOW = "600ms cubic-bezier(0.4, 0.0, 0.2, 1)"

# "Quiet chip" outline — replaces shouting amber-bg EST chips. The chip
# becomes a 1-px outline only; values keep their visual weight.
CHIP_QUIET_BG = "transparent"
CHIP_QUIET_BORDER = COLORS["amber"] + "55"

# Plotly categorical palette — used wherever a chart needs N distinct
# sector / category colors. Derived from the semantic accents extended
# with secondary brand-compatible hues. Centralised here so charts
# don't drift; pages import ``CHART_PALETTE`` instead of inlining.
CHART_PALETTE: tuple[str, ...] = (
    "#00d4aa",   # accent
    "#5b8cff",   # accent2
    "#ff9f43",   # amber
    "#ff4466",   # warn
    "#ffd700",   # gold
    "#a890ff",   # violet
    "#7db4ff",   # sky
    "#43d4ff",   # cyan
    "#ff79b0",   # rose
    "#8be9b3",   # mint
)

# Diverging cheap → rich heatmap scale, used by the Sector Rotation
# heatmap and any other view that maps a 0–1 percentile to color.
# Anchored to the semantic palette: 0 = accent (cheap), 0.5 = muted
# (neutral), 1 = warn (rich). Intermediate stops are interpolated
# brand-compatible blends, not arbitrary hues.
HEATMAP_SCALE: tuple[tuple[float, str], ...] = (
    (0.0, "#00d4aa"),   # cheap
    (0.2, "#5bc8b0"),
    (0.4, "#8a8f9e"),   # neutral
    (0.6, "#ff9f43"),
    (0.8, "#ff6688"),
    (1.0, "#ff4466"),   # rich
)

# Google Fonts import — JetBrains Mono for data, DM Sans for UI,
# Material Symbols for Streamlit's icons (chevrons, expanders, help).
# Without Material Symbols loaded, Streamlit renders icon names as
# literal text ("keyboard_arrow_down") which collides with adjacent
# labels — observed bug 2026-05-03 and reported again 2026-05-11
# ("keyboard ghost text in LEAPS Lab").
#
# Two separate icon URLs because the combined `?family=A|B` form
# silently falls back to the first family on some networks. Plus an
# explicit CSS rule below that styles any element with the
# material-symbols-outlined / material-icons class so the literal text
# is invisible until the font lands.
_FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=JetBrains+Mono:wght@400;500;600;700&"
    "family=DM+Sans:wght@400;500;600;700&display=swap');"
    # display=block hides the fallback text completely while the font
    # is loading (vs swap which flashes the literal ligature like
    # "keyboard_double_arrow_left"). For icon fonts, block is the
    # correct choice — operator reported the swap-flash as
    # "keyboard_load_" ghost text in the sidebar header on 2026-05-15.
    "@import url('https://fonts.googleapis.com/icon?family=Material+Icons&display=block');"
    "@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,400,0,0&display=block');"
)

CUSTOM_CSS = f"""
<style>
    {_FONT_IMPORT}

    /* Hide Streamlit's default chrome — but KEEP the sidebar
       collapse/expand controls. Earlier we hid `stToolbar` and
       `stHeader` outright, which killed the chevron the user clicks to
       reopen the sidebar after collapsing it. New approach:
         • hide only the specific noise (deploy button, hamburger,
           footer, status widget, auto-generated multipage nav)
         • leave stHeader / stToolbar in the DOM but transparent so
           the sidebar collapse control remains clickable. */
    [data-testid="stDeployButton"],
    [data-testid="stMainMenu"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    [data-testid="stSidebarNav"],
    [data-testid="stSidebarNavItems"],
    [data-testid="stSidebarNavSeparator"],
    footer,
    #MainMenu {{
        display: none !important;
        visibility: hidden !important;
    }}
    /* Header strip: kept slim but NOT collapsed to 0. Previous
       `height:0; overflow:hidden` clipped Streamlit's floating
       "open sidebar" chevron when the sidebar was collapsed —
       meaning operators could close the sidebar but had no way to
       reopen it. Now: low height, transparent bg, overflow visible
       so the chevron can spill into the page if it lives there. */
    header[data-testid="stHeader"] {{
        background: transparent !important;
        min-height: 32px !important;
        height: auto !important;
        overflow: visible !important;
    }}
    header[data-testid="stHeader"] [data-testid="stToolbar"] {{
        background: transparent !important;
    }}
    /* Floating "open sidebar" button (visible when sidebar is
       collapsed). v0.9.4 — moved from top-left to a more discreet
       position on the LEFT edge, vertically centered. Operator
       feedback: the top-left spot conflicted with the ghost
       "keyboard_double_arrow_right" text from the Material Symbols
       font when the CDN was slow. We now render a clean glyph via
       ::before regardless of font load state, and the element sits
       out of the headline-stats area. */
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"] {{
        position: fixed !important;
        top: 50% !important;
        left: 0 !important;
        transform: translateY(-50%) !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        visibility: visible !important;
        opacity: 0.85 !important;
        z-index: 9999 !important;
        background: {COLORS['surface']} !important;
        border: 1px solid {COLORS['border']} !important;
        border-left: none !important;
        border-radius: 0 6px 6px 0 !important;
        padding: 10px 6px !important;
        width: 24px !important;
        height: 36px !important;
        box-shadow: 2px 0 8px rgba(0, 0, 0, 0.35) !important;
        pointer-events: auto !important;
        cursor: pointer !important;
        /* Kill ALL inner text — the Material-Symbols ligature, any
           <span> the platform inserts, etc. We replace it with a
           single CSS chevron via ::after on the container. */
        font-size: 0 !important;
        color: transparent !important;
    }}
    [data-testid="collapsedControl"] *,
    [data-testid="stSidebarCollapsedControl"] * {{
        font-size: 0 !important;
        color: transparent !important;
        line-height: 0 !important;
    }}
    [data-testid="collapsedControl"]::after,
    [data-testid="stSidebarCollapsedControl"]::after {{
        content: "›";
        font-family: 'DM Sans', sans-serif !important;
        font-size: 18px !important;
        color: {COLORS['accent']} !important;
        line-height: 1 !important;
        font-weight: 700 !important;
    }}
    [data-testid="collapsedControl"]:hover,
    [data-testid="stSidebarCollapsedControl"]:hover {{
        border-color: {COLORS['accent']} !important;
        opacity: 1 !important;
    }}
    /* In case the SVG ever does render, keep it clean — but the
       text-nuke above takes precedence for the broken-CDN case. */
    [data-testid="collapsedControl"] svg,
    [data-testid="stSidebarCollapsedControl"] svg {{
        display: none !important;
    }}
    /* Sidebar collapse chevron (the one inside the open sidebar).
       Same text-nuke + ::after replacement strategy as the floating
       open-button so a slow Material-Symbols CDN never leaks the raw
       "keyboard_double_arrow_left" ligature text. */
    [data-testid="stSidebarCollapseArrow"],
    [data-testid="stSidebarCollapseButton"],
    button[kind="header"] {{
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        visibility: visible !important;
        opacity: 1 !important;
        position: relative !important;
        font-size: 0 !important;
        color: transparent !important;
    }}
    [data-testid="stSidebarCollapseArrow"] *,
    [data-testid="stSidebarCollapseButton"] *,
    button[kind="header"] * {{
        font-size: 0 !important;
        color: transparent !important;
        line-height: 0 !important;
    }}
    [data-testid="stSidebarCollapseArrow"]::after,
    [data-testid="stSidebarCollapseButton"]::after,
    button[kind="header"]::after {{
        content: "‹";
        font-family: 'DM Sans', sans-serif !important;
        font-size: 18px !important;
        color: {COLORS['accent']} !important;
        line-height: 1 !important;
        font-weight: 700 !important;
    }}
    /* If the SVG renders, prefer it over the ::after fallback by
       hiding the fallback when an svg child exists. */
    [data-testid="stSidebarCollapseArrow"]:has(svg)::after,
    [data-testid="stSidebarCollapseButton"]:has(svg)::after,
    button[kind="header"]:has(svg)::after {{
        content: none !important;
    }}
    [data-testid="stSidebarCollapseArrow"] svg,
    [data-testid="stSidebarCollapseButton"] svg,
    button[kind="header"] svg {{
        color: {COLORS['accent']} !important;
        fill: {COLORS['accent']} !important;
        width: 18px !important;
        height: 18px !important;
        opacity: 1 !important;
    }}
    [data-testid="stSidebarCollapseArrow"]:hover,
    [data-testid="stSidebarCollapseButton"]:hover,
    button[kind="header"]:hover {{
        background: rgba(0, 212, 170, 0.12) !important;
    }}

    /* v0.9.8 — belt-and-suspenders. Streamlit 1.57 occasionally
       introduces a new sidebar-header test-id we haven't pinned
       (operator saw a "keyboard_load_" ghost on 2026-05-15 — that's
       "keyboard_double_arrow_left" truncated). This rule covers any
       descendant span of the sidebar-header / sidebar-user-content
       wrappers that still contains literal ligature text. Once the
       Material Symbols font lands (display=block) the rule becomes a
       no-op. Sidebar body content is unaffected because the wrapper
       containers only hold chrome buttons. */
    [data-testid="stSidebarHeader"] button,
    [data-testid="stSidebarHeader"] span,
    [data-testid="stSidebarUserContent"] > header button,
    [data-testid="stSidebarUserContent"] > header span {{
        font-size: 0 !important;
        color: transparent !important;
        line-height: 0 !important;
    }}
    [data-testid="stSidebarHeader"] button::after {{
        content: "‹" !important;
        font-family: 'DM Sans', sans-serif !important;
        font-size: 18px !important;
        color: {COLORS['accent']} !important;
        line-height: 1 !important;
        font-weight: 700 !important;
    }}
    [data-testid="stSidebarHeader"] button:has(svg)::after {{
        content: none !important;
    }}
    [data-testid="stSidebarHeader"] svg {{
        width: 18px !important;
        height: 18px !important;
        color: {COLORS['accent']} !important;
        fill: {COLORS['accent']} !important;
    }}

    /* ── IBKR-Density Layout ────────────────────────────────────────────
       Trading-app density: Streamlit's defaults waste 30-40 % of vertical
       real-estate. Compress to laptop-friendly proportions.                  */
    .block-container {{
        padding-top: 0.6rem !important;
        padding-bottom: 0.4rem !important;
        padding-left: 1.1rem !important;
        padding-right: 1.1rem !important;
        max-width: 100% !important;
    }}

    /* Compress vertical rhythm — Streamlit pads ~16-24 px between
       elements which feels luxurious on a marketing page and wasteful
       on a cockpit. Cap to ~4 px (small but non-zero so adjacent text
       blocks never visually collide). */
    .element-container {{
        margin-bottom: 4px !important;
    }}
    div[data-testid="column"] > div {{
        padding: 0 6px !important;
    }}
    /* Inside expanders Streamlit drops in extra padding around every
       element. We claw it back, but keep the header detached from its
       body so the chevron + label never overlap. */
    [data-testid="stExpander"] [data-testid="stVerticalBlock"] {{
        gap: 6px !important;
    }}
    [data-testid="stExpander"] details > div {{
        padding-top: 6px !important;
    }}
    /* ── NUCLEAR EXPANDER CHEVRON FIX (2026-05-11) ──────────────────
       Streamlit's expander chevron is rendered as a Material-Symbols
       ligature span containing the literal text "keyboard_arrow_down".
       When the icon font is slow / blocked, the literal ASCII leaks
       into the UI ("Bulk load universe keyboard ▾").

       Strategy: hide ALL non-content children of <summary>, then inject
       our own ASCII chevron via ::after. Robust against any font load
       failure. The visible label is the <p> inside summary. */
    [data-testid="stExpander"] summary {{
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
        min-height: 32px !important;
        list-style: none !important;
        cursor: pointer !important;
        position: relative !important;
        padding-right: 22px !important;
    }}
    [data-testid="stExpander"] summary::-webkit-details-marker {{
        display: none !important;
    }}
    /* Hide every direct child of summary EXCEPT the label container
       (Streamlit wraps the label in a div with stMarkdownContainer). */
    [data-testid="stExpander"] summary > svg,
    [data-testid="stExpander"] summary > span:not(.streamlit-expanderHeader),
    [data-testid="stExpander"] summary > [class*="material"],
    [data-testid="stExpander"] summary > .material-symbols-outlined,
    [data-testid="stExpander"] summary > .material-icons {{
        display: none !important;
    }}
    [data-testid="stExpander"] summary p {{
        margin: 0 !important;
        line-height: 1.2 !important;
    }}
    /* Inject our own chevron — pure ASCII, no font dependency. */
    [data-testid="stExpander"] summary::after {{
        content: '▾';
        position: absolute;
        right: 6px;
        top: 50%;
        transform: translateY(-50%);
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: {COLORS['muted']};
        line-height: 1;
        transition: transform 150ms ease;
    }}
    [data-testid="stExpander"] details[open] summary::after {{
        transform: translateY(-50%) rotate(180deg);
        color: {COLORS['accent']};
    }}
    /* Plotly charts come with a default margin we already tightened in
       chart_builders, but Streamlit's wrapper still adds 8 px above and
       below — claw most of it back. */
    .js-plotly-plot {{
        margin-top: -2px !important;
        margin-bottom: -2px !important;
    }}

    /* Sidebar — narrow & dense when expanded; collapses to 0 when the
       user hits the chevron. The earlier hard `max-width: 232px !important`
       blocked the collapse animation entirely (sidebar visibly closed
       but the layout still reserved 232 px). New scope: the width
       constraint applies ONLY to the expanded state. */
    [data-testid="stSidebar"][aria-expanded="true"] {{
        width: 232px !important;
        min-width: 232px !important;
        max-width: 232px !important;
    }}
    [data-testid="stSidebar"][aria-expanded="false"] {{
        /* Let Streamlit's native collapse take over — no width override. */
        min-width: 0 !important;
        max-width: 0 !important;
        width: 0 !important;
        overflow: hidden !important;
    }}
    [data-testid="stSidebar"] > div:first-child {{
        padding-top: 0.4rem !important;
    }}

    /* ── Tabs — IBKR-style underline, no chrome ───────────────────────── */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 0 !important;
        background: transparent !important;
        border-bottom: 1px solid {COLORS['border']} !important;
    }}
    .stTabs [data-baseweb="tab"] {{
        height: 34px !important;
        padding: 0 16px !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        letter-spacing: 1px !important;
        text-transform: uppercase !important;
        color: {COLORS['label']} !important;
        border-bottom: 2px solid transparent !important;
        background: transparent !important;
        font-family: 'DM Sans', sans-serif !important;
    }}
    .stTabs [aria-selected="true"] {{
        color: {COLORS['accent']} !important;
        border-bottom: 2px solid {COLORS['accent']} !important;
        background: transparent !important;
    }}

    /* Expander — compact header, no big chrome. NOTE: the actual flex
       layout for the summary lives above (in the density block) so the
       chevron + label can never overlap. This block only sets typography. */
    .streamlit-expanderHeader,
    [data-testid="stExpander"] summary {{
        font-size: 12px !important;
        font-weight: 600 !important;
        letter-spacing: 0.4px !important;
        color: {COLORS['text']} !important;
        background: transparent !important;
    }}
    /* Expander BODY background — slightly inset from page so the
       contained content (tables, charts) reads as a panel. */
    [data-testid="stExpander"] {{
        background: rgba(255,255,255,0.012) !important;
        border: 1px solid {COLORS['border']} !important;
        border-radius: 6px !important;
        padding: 4px 6px !important;
        margin-bottom: 8px !important;
    }}

    /* Compact buttons — TWS-style 32px height */
    .stButton > button {{
        min-height: 32px !important;
        height: auto !important;
        padding: 4px 12px !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        letter-spacing: 0.4px !important;
    }}

    /* Slider compaction */
    [data-testid="stSlider"] {{
        padding-top: 0 !important;
    }}

    /* Hide Plotly's mode bar (zoom/pan/reset toolbar) globally — it
       clutters every chart and traders interact with charts via gestures
       and the range-selector buttons we already render inline. */
    .modebar-container,
    .js-plotly-plot .plotly .modebar {{
        display: none !important;
    }}

    /* Material Symbols / Icons — force the icon font + ligatures so
       Streamlit's chevron/expander icons never render as literal text
       ("keyboard_arrow_down") if the font CDN is slow. This rule is
       defensive: even if the @import below fails, the icon glyph stays
       hidden rather than leaking ASCII into the UI. */
    .material-symbols-outlined,
    .material-icons,
    [class^="material-symbols"],
    [class*="material-icons"] {{
        font-family: 'Material Symbols Outlined', 'Material Icons' !important;
        font-weight: normal !important;
        font-style: normal !important;
        line-height: 1 !important;
        letter-spacing: normal !important;
        text-transform: none !important;
        display: inline-block;
        white-space: nowrap;
        word-wrap: normal;
        direction: ltr;
        font-feature-settings: 'liga';
        -webkit-font-feature-settings: 'liga';
        -webkit-font-smoothing: antialiased;
    }}
    /* Last-line defence: if the font CDN is slow or blocked, the span
       still contains the literal ligature text ("keyboard_arrow_down").
       Setting font-size:inherit doesn't help — we have to fully blank
       the glyph. ``font-size: 0`` collapses the text to zero width while
       a 1em-tall replacement chevron via ``::before`` preserves layout.
       Once the icon font loads, browsers re-render the original ligature
       glyph and this rule becomes a no-op. */
    .material-symbols-outlined,
    .material-icons {{
        font-size: 0 !important;
        color: transparent !important;
        line-height: 1 !important;
    }}
    .material-symbols-outlined::before,
    .material-icons::before {{
        content: "▾";
        font-size: 12px;
        color: {COLORS['muted']};
        font-family: 'DM Sans', sans-serif;
    }}

    /* v0.9.8 Phase E — pointer cursor on every Streamlit-rendered
       button-like element so the operator's mouse always tells them
       what's pressable. !important wins over Streamlit's defaults. */
    .stButton button,
    .stDownloadButton button,
    .stFormSubmitButton button,
    button[kind="primary"],
    button[kind="secondary"],
    [role="button"],
    [role="link"],
    .volscope-clickable-row {{
        cursor: pointer !important;
    }}

    /* Subtle hover state for custom HTML data rows that opt into
       .volscope-clickable-row. Used by Portfolio / Scanner / Alerts
       / Signals / Bot row renderers (Phase C wiring). */
    .volscope-clickable-row:hover {{
        background: rgba(0, 212, 170, 0.06) !important;
        transition: background 0.15s ease;
    }}

    /* Thin scrollbars (TradingView feel) */
    ::-webkit-scrollbar {{
        width: 6px;
        height: 6px;
    }}
    ::-webkit-scrollbar-track {{
        background: transparent;
    }}
    ::-webkit-scrollbar-thumb {{
        background: {COLORS['border']};
        border-radius: 3px;
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background: {COLORS['muted']};
    }}

    /* Base — everything flows through the cockpit palette */
    .stApp {{
        background-color: {COLORS['bg']};
        color: {COLORS['text']};
        font-family: 'DM Sans', -apple-system, sans-serif;
    }}
    .stApp, .stApp * {{
        font-family: 'DM Sans', -apple-system, sans-serif;
    }}
    code, pre, kbd,
    [data-testid="stMetricValue"],
    [data-testid="stMetricDelta"],
    .volscope-mono,
    .volscope-kpi-value {{
        font-family: 'JetBrains Mono', 'SF Mono', Menlo, monospace !important;
        font-variant-numeric: tabular-nums;
    }}

    /* Sidebar — one shade lighter than the page */
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div,
    [data-testid="stSidebarContent"] {{
        background-color: {COLORS['surface']};
        border-right: 1px solid {COLORS['border']};
    }}

    /* Main content headings — smaller, more subtle than Streamlit default */
    h1, h2, h3, h4 {{
        color: {COLORS['text']};
        letter-spacing: 0.02em;
        font-weight: 600;
    }}
    h2 {{
        font-size: 18px !important;
        color: {COLORS['text']};
        margin-top: 0 !important;
        margin-bottom: 2px !important;
        padding-bottom: 0 !important;
        padding-top: 0 !important;
        border-bottom: none !important;
        line-height: 1.2 !important;
    }}
    h3 {{
        font-size: 11px !important;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        color: {COLORS['text']} !important;
        font-weight: 600 !important;
        margin-top: 12px !important;
        margin-bottom: 6px !important;
        padding-bottom: 4px !important;
        border-bottom: 1px solid {COLORS['border']};
    }}
    /* Streamlit's caption is bigger than necessary */
    [data-testid="stCaptionContainer"] {{
        margin-bottom: 4px !important;
    }}
    [data-testid="stCaptionContainer"] p {{
        font-size: 10px !important;
        color: {COLORS['muted']} !important;
        margin: 0 !important;
    }}

    /* Section divider header — replaces h3 where emoji are used.
       No text-transform so emoji render cleanly. */
    .volscope-section-header {{
        font-family: 'DM Sans', -apple-system, sans-serif;
        font-size: 12px;
        font-weight: 700;
        color: {COLORS['text']};
        letter-spacing: 0.8px;
        text-transform: uppercase;
        padding-bottom: 8px;
        margin-top: 22px;
        margin-bottom: 12px;
        border-bottom: 1px solid {COLORS['border']};
        display: flex;
        align-items: center;
        gap: 7px;
    }}
    .volscope-section-header .volscope-section-icon {{
        font-size: 14px;
        letter-spacing: 0;
        text-transform: none;
        display: inline-block;
    }}

    /* Tiny uppercase labels — the Bloomberg feel */
    .volscope-label {{
        color: {COLORS['label']};
        font-size: 9px;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        font-weight: 600;
        margin-bottom: 4px;
    }}

    /* KPI / metric cards — colored accent bar on top edge, subtle lift */
    [data-testid="stMetric"] {{
        background-color: {COLORS['card']};
        border: 1px solid {COLORS['border']};
        padding: 16px 18px 14px 18px;
        border-radius: 8px;
        position: relative;
        overflow: hidden;
        transition: border-color 150ms ease, transform 150ms ease;
    }}
    [data-testid="stMetric"]::before {{
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(90deg, {COLORS['accent']} 0%, transparent 100%);
        opacity: 0.4;
    }}
    [data-testid="stMetric"]:hover {{
        border-color: {COLORS['accent']}66;
        transform: translateY(-1px);
    }}
    [data-testid="stMetric"]:hover::before {{
        opacity: 0.8;
    }}
    [data-testid="stMetricLabel"] {{
        color: {COLORS['label']} !important;
        font-size: 10px !important;
        text-transform: uppercase;
        letter-spacing: 1.4px;
        font-weight: 600;
    }}
    [data-testid="stMetricValue"] {{
        color: {COLORS['text']} !important;
        font-size: 18px !important;
        font-weight: 600 !important;
        letter-spacing: -0.4px !important;
    }}
    [data-testid="stMetricDelta"] {{
        font-size: 11px !important;
    }}

    /* Pills — percentile tags, regime markers, sector labels */
    .volscope-pill {{
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        font-family: 'JetBrains Mono', monospace;
    }}
    .volscope-pill-low    {{ background: {FILL_CHEAP}; color: {COLORS['accent']}; border: 1px solid {COLORS['accent']}33; }}
    .volscope-pill-mid    {{ background: {COLORS['hover']}; color: {COLORS['muted']}; border: 1px solid {COLORS['border']}; }}
    .volscope-pill-high   {{ background: {FILL_RICH}; color: {COLORS['warn']}; border: 1px solid {COLORS['warn']}33; }}
    .volscope-pill-amber  {{ background: rgba(255,159,67,0.12); color: {COLORS['amber']}; border: 1px solid {COLORS['amber']}33; }}
    .volscope-pill-sector {{ background: {COLORS['hover']}; color: {COLORS['accent2']}; border: 1px solid {COLORS['accent2']}33; }}

    /* ── LEAPS-Lab redesign primitives (2026-05-10, Apple-Style pass) ──
       Single source of truth for the convergence dial, section rules,
       KPI grid, score bars, motion, and the quiet `est · BSM` marker.
       Pages reference these classes; nothing should re-invent the styling.

       Motion philosophy: 5 transition-only animations, 0 JS. Each fires
       once per page render. Apple's Cockpit-aesthetic — minimal motion,
       generous spacing, tabular-numerals everywhere. */

    @keyframes vs-fade-in {{
        from {{ opacity: 0; transform: translateY(4px); }}
        to   {{ opacity: 1; transform: none; }}
    }}
    @keyframes vs-bar-grow {{
        from {{ width: 0; }}
        to   {{ width: var(--bar-pct, 0%); }}
    }}
    @keyframes vs-dial-arc {{
        from {{ --dial-pct-anim: 0; }}
        to   {{ --dial-pct-anim: var(--dial-pct, 0); }}
    }}

    /* Convergence dial — pure CSS conic-gradient ring with the score
       in the centre. */
    .volscope-dial {{
        --dial-pct: 0;
        --dial-color: {COLORS['accent']};
        width: {DIAL['size']}px;
        height: {DIAL['size']}px;
        border-radius: 50%;
        background:
            conic-gradient(
                var(--dial-color) calc(var(--dial-pct) * 1%),
                {DIAL['track']} calc(var(--dial-pct) * 1%)
            );
        display: flex;
        align-items: center;
        justify-content: center;
        position: relative;
        flex: 0 0 auto;
    }}
    .volscope-dial {{
        animation: vs-fade-in {MOTION_BASE} both;
    }}
    .volscope-dial::before {{
        content: "";
        position: absolute;
        inset: {DIAL['stroke']}px;
        background: {COLORS['card']};
        border-radius: 50%;
    }}
    .volscope-dial-value {{
        position: relative;
        font-family: 'JetBrains Mono', monospace;
        font-variant-numeric: tabular-nums;
        font-size: {TYPE['hero']}px;
        font-weight: 700;
        line-height: 1;
        color: var(--dial-color);
    }}
    .volscope-dial-caption {{
        font-family: 'JetBrains Mono', monospace;
        font-size: {TYPE['micro']}px;
        letter-spacing: 0.6px;
        color: {COLORS['muted']};
        text-transform: uppercase;
        margin-top: 2px;
        text-align: center;
    }}

    /* Section rule — IBKR-density override: the previous Apple-marketing
       80 px gap was wasted space on a trading cockpit. Reduce to a
       trader-grade rhythm so each page packs more signal per scroll. */
    .volscope-section-rule {{
        display: flex;
        align-items: baseline;
        gap: {SPACE['md']}px;
        margin: 18px 0 8px 0;
        padding-bottom: 4px;
        border-bottom: 1px solid {COLORS['border']};
        animation: vs-fade-in {MOTION_FAST} both;
    }}
    .volscope-section-rule:first-of-type {{
        margin-top: 8px;
    }}
    .volscope-section-rule-label {{
        font-family: 'JetBrains Mono', monospace;
        font-size: {TYPE['label']}px;
        letter-spacing: 1.6px;
        color: {COLORS['text']};
        font-weight: 600;
        text-transform: uppercase;
    }}
    .volscope-section-rule-sub {{
        font-family: 'JetBrains Mono', monospace;
        font-size: {TYPE['label']}px;
        color: {COLORS['muted']};
        font-weight: 400;
    }}

    /* KPI grid — Apple-style flat surfaces, no border by default,
       border only on hover. Two variants:
         volscope-kpi-grid-detail   — 5 cols × 18px, restrained, sub-stats
         volscope-kpi-grid-hero     — 3 cols × 34px, hero numbers, headline KPIs
       Both fall back to 3 cols at narrow widths so cells never wrap.    */
    .volscope-kpi-grid,
    .volscope-kpi-grid-detail {{
        display: grid;
        grid-template-columns: repeat({KPI_DETAIL['cols']}, minmax({KPI_DETAIL['min_w']}px, 1fr));
        gap: 4px;
        margin: 6px 0 8px 0;
    }}
    .volscope-kpi-grid-hero {{
        display: grid;
        grid-template-columns: repeat({KPI_HERO['cols']}, minmax({KPI_HERO['min_w']}px, 1fr));
        gap: 8px;
        margin: 6px 0 10px 0;
    }}
    @media (max-width: 900px) {{
        .volscope-kpi-grid,
        .volscope-kpi-grid-detail {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }}
        .volscope-kpi-grid-hero {{ grid-template-columns: repeat(2, minmax(160px, 1fr)); }}
    }}
    .volscope-kpi-cell {{
        background: {COLORS['surface']};
        border: 1px solid transparent;
        border-radius: {RADIUS['md']}px;
        padding: 8px 12px;
        transition: transform {MOTION_FAST}, border-color {MOTION_FAST}, background {MOTION_FAST};
        animation: vs-fade-in {MOTION_BASE} both;
    }}
    .volscope-kpi-cell:hover {{
        background: {COLORS['hover']};
        border-color: {COLORS['border']};
        transform: translateY(-2px);
    }}
    .volscope-kpi-grid-hero .volscope-kpi-cell {{
        padding: 14px 18px;
    }}
    .volscope-kpi-label {{
        font-family: 'JetBrains Mono', monospace;
        font-size: {TYPE['micro']}px;
        letter-spacing: 1.0px;
        color: {COLORS['muted']};
        text-transform: uppercase;
        margin-bottom: 6px;
    }}
    .volscope-kpi-value {{
        font-family: 'JetBrains Mono', monospace;
        font-variant-numeric: tabular-nums;
        font-size: {TYPE['lead']}px;
        font-weight: 600;
        line-height: 1.1;
        color: {COLORS['text']};
    }}
    .volscope-kpi-grid-hero .volscope-kpi-value {{
        font-size: {TYPE['hero']}px;
        font-weight: 700;
    }}
    /* Inline EST sup-marker on a single value. Replaces full-section
       underline where the EST scope is one number, not a whole row. */
    .volscope-est-sup {{
        font-family: 'JetBrains Mono', monospace;
        font-size: {TYPE['micro']}px;
        font-weight: 500;
        color: {COLORS['muted']};
        margin-left: 4px;
        vertical-align: super;
        letter-spacing: 0.4px;
    }}

    /* Score bars — quieter than coloured pills, group as one unit. */
    .volscope-bar-group {{
        display: flex;
        gap: {SPACE['md']}px;
        flex-wrap: wrap;
        margin: {SPACE['sm']}px 0;
    }}
    .volscope-bar {{
        display: flex;
        align-items: center;
        gap: {SPACE['sm']}px;
        font-family: 'JetBrains Mono', monospace;
        font-size: {TYPE['label']}px;
    }}
    .volscope-bar-key {{
        color: {COLORS['muted']};
        letter-spacing: 0.6px;
        min-width: 36px;
    }}
    .volscope-bar-value {{
        color: {COLORS['text']};
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        min-width: 24px;
        text-align: right;
    }}
    .volscope-bar-track {{
        width: 80px;
        height: 4px;
        border-radius: 2px;
        background: {COLORS['border']};
        overflow: hidden;
    }}
    .volscope-bar-fill {{
        height: 100%;
        border-radius: 2px;
        background: {COLORS['muted']};
        animation: vs-bar-grow {MOTION_BASE} ease-out 100ms both;
    }}
    .volscope-bar-fill-strong {{ background: {COLORS['accent']}; }}
    .volscope-bar-fill-mid    {{ background: {COLORS['accent2']}; }}
    .volscope-bar-fill-weak   {{ background: {COLORS['muted']}; }}

    /* Quiet `est · BSM` underline — replaces every per-card amber chip
       with one dotted underline placed under whole sections. */
    .volscope-est-underline {{
        font-family: 'JetBrains Mono', monospace;
        font-size: {TYPE['micro']}px;
        letter-spacing: 1.0px;
        color: {COLORS['muted']};
        text-transform: lowercase;
        text-align: right;
        padding-top: 2px;
        border-top: 1px dotted {CHIP_QUIET_BORDER};
        margin-top: {SPACE['sm']}px;
    }}

    /* Quiet inline est marker — when the underline is too heavy. */
    .volscope-est-quiet {{
        background: {CHIP_QUIET_BG};
        border: 1px solid {CHIP_QUIET_BORDER};
        color: {COLORS['muted']};
        padding: 1px 6px;
        border-radius: {RADIUS['sm']}px;
        font-family: 'JetBrains Mono', monospace;
        font-size: {TYPE['micro']}px;
        letter-spacing: 0.6px;
        margin-left: {SPACE['sm']}px;
    }}

    /* Apple-style empty state — declarative + actionable, replaces the
       trockene "No data — run make scrape" Streamlit defaults. */
    .volscope-empty-state {{
        background: {COLORS['surface']};
        border-radius: {RADIUS['lg']}px;
        padding: {SPACE['xl']}px {SPACE['xl']}px;
        margin: {SPACE['lg']}px 0;
        text-align: center;
        animation: vs-fade-in {MOTION_BASE} both;
    }}
    .volscope-empty-headline {{
        font-family: 'DM Sans', sans-serif;
        font-size: {TYPE['lead']}px;
        font-weight: 600;
        color: {COLORS['text']};
        margin-bottom: {SPACE['sm']}px;
    }}
    .volscope-empty-body {{
        font-family: 'JetBrains Mono', monospace;
        font-size: {TYPE['body']}px;
        color: {COLORS['muted']};
        line-height: 1.6;
        max-width: 540px;
        margin: 0 auto;
    }}

    /* Generic .volscope-card — already defined below. Apple-pass adds
       a fade-in entrance and surface-style hover (no border kept). */
    .volscope-card {{
        animation: vs-fade-in {MOTION_FAST} both;
    }}

    /* Opportunity cards — Discover page (tightened 2026-05-10 UI overhaul) */
    .volscope-card {{
        background: {COLORS['card']};
        border: 1px solid {COLORS['border']};
        border-left: 3px solid {COLORS['border']};
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 6px;
        transition: background {MOTION_FAST}, transform {MOTION_FAST}, border-color {MOTION_FAST};
    }}
    .volscope-card:hover {{
        background: {COLORS['hover']};
        transform: translateX(3px);
    }}
    .volscope-card-cheap  {{ border-left: 3px solid {COLORS['accent']}; }}
    .volscope-card-cheap:hover {{ box-shadow: -4px 0 20px {COLORS['accent']}22; }}
    .volscope-card-rich   {{ border-left: 3px solid {COLORS['warn']}; }}
    .volscope-card-rich:hover  {{ box-shadow: -4px 0 20px {COLORS['warn']}22; }}
    .volscope-card-neutral {{ border-left: 3px solid {COLORS['accent2']}; }}

    .volscope-card-ticker {{
        font-size: 18px;
        font-weight: 700;
        letter-spacing: 0.05em;
        font-family: 'JetBrains Mono', monospace;
        color: {COLORS['text']};
    }}
    .volscope-card-name {{
        color: {COLORS['muted']};
        font-size: 11px;
        margin-left: 6px;
    }}
    .volscope-card-context {{
        color: {COLORS['muted']};
        font-size: 12px;
        margin-top: 6px;
        line-height: 1.4;
    }}
    .volscope-card-stats {{
        margin-top: 8px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        color: {COLORS['text']};
    }}

    /* Freshness badge */
    .volscope-freshness {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.8px;
        font-family: 'JetBrains Mono', monospace;
        margin-bottom: 12px;
    }}

    /* Scope hero — ticker + name + sector */
    .volscope-scope-header {{
        display: flex;
        align-items: baseline;
        gap: 14px;
        margin-bottom: 20px;
        padding-bottom: 12px;
        border-bottom: 1px solid {COLORS['border']};
    }}
    .volscope-scope-ticker {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 26px;
        font-weight: 700;
        color: {COLORS['accent']};
        letter-spacing: 0.04em;
    }}
    .volscope-scope-name {{
        color: {COLORS['muted']};
        font-size: 14px;
        font-weight: 400;
    }}

    /* Data editor + tables — subtle, not white */
    [data-testid="stDataFrame"] {{
        background: {COLORS['card']};
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
    }}

    /* Buttons */
    .stButton > button {{
        background: {COLORS['card']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        font-weight: 600;
        letter-spacing: 0.03em;
        transition: all 120ms ease;
    }}
    .stButton > button:hover {{
        background: {COLORS['hover']};
        border-color: {COLORS['accent']};
        color: {COLORS['accent']};
    }}

    /* Input elements — force DM Sans so Streamlit's browser default doesn't
       override our custom font.  Without this, text inputs fall back to the
       system-ui stack which renders visibly different from the rest of the UI. */
    input, textarea, select,
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stSelectbox"] div[data-baseweb="select"] *,
    [data-testid="stNumberInput"] input,
    [data-baseweb="input"] input,
    [data-baseweb="select"] * {{
        font-family: 'DM Sans', -apple-system, sans-serif !important;
        font-size: 13px !important;
        background-color: {COLORS['surface']} !important;
        border-color: {COLORS['border']} !important;
        color: {COLORS['text']} !important;
    }}
    [data-baseweb="select"] {{
        background-color: {COLORS['surface']} !important;
    }}
    /* Selectbox dropdown menu */
    [data-baseweb="popover"] li,
    [data-baseweb="menu"] li {{
        font-family: 'DM Sans', -apple-system, sans-serif !important;
        background-color: {COLORS['surface']} !important;
        color: {COLORS['text']} !important;
    }}
    [data-baseweb="popover"] li:hover,
    [data-baseweb="menu"] li:hover {{
        background-color: {COLORS['hover']} !important;
    }}

    /* Earnings warning inline badge */
    .volscope-earnings-badge {{
        display: inline-block;
        background: rgba(255,215,0,0.13);
        color: {COLORS['gold']};
        padding: 2px 7px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 600;
        margin-left: 6px;
        letter-spacing: 0.4px;
        font-family: 'JetBrains Mono', monospace;
    }}

    /* ── IBKR-Style components (2026-05-10 UI overhaul) ────────────────
       Dense, professional cockpit primitives. Prefer these classes over
       inline styles wherever possible — the day we redesign, one file
       changes, not fifty. */

    /* Custom KPI row — replaces st.metric where truncation is a risk and
       where dense IBKR proportions are wanted. */
    .volscope-ibkr-row {{
        display: flex;
        gap: 4px;
        margin-bottom: 14px;
        flex-wrap: wrap;
    }}
    .volscope-ibkr-cell {{
        flex: 1 1 96px;
        min-width: 96px;
        text-align: center;
        padding: 9px 10px 8px 10px;
        background: rgba(255,255,255,0.018);
        border: 1px solid rgba(255,255,255,0.04);
        border-radius: 6px;
        transition: border-color {MOTION_FAST}, background {MOTION_FAST};
        overflow: hidden;
    }}
    .volscope-ibkr-cell:hover {{
        border-color: {COLORS['border']};
        background: rgba(255,255,255,0.035);
    }}
    .volscope-ibkr-cell.is-cheap   {{ background: rgba(0,212,170,0.06); }}
    .volscope-ibkr-cell.is-rich    {{ background: rgba(255,68,102,0.06); }}
    .volscope-ibkr-cell.is-warning {{ background: rgba(255,159,67,0.06); }}
    .volscope-ibkr-label {{
        font-family: 'DM Sans', -apple-system, sans-serif;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 1.4px;
        text-transform: uppercase;
        color: {COLORS['label']};
        margin-bottom: 4px;
        line-height: 1;
    }}
    .volscope-ibkr-value {{
        font-family: 'JetBrains Mono', 'SF Mono', monospace;
        font-variant-numeric: tabular-nums;
        font-size: 16px;
        font-weight: 600;
        letter-spacing: -0.4px;
        white-space: nowrap;
        line-height: 1.1;
        color: {COLORS['text']};
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    /* Narrow viewports — scale numerals down so 5-6 cells per row still fit. */
    @media (max-width: 1280px) {{
        .volscope-ibkr-value {{ font-size: 14px; }}
        .volscope-ibkr-label {{ font-size: 8px; letter-spacing: 1.2px; }}
    }}
    @media (max-width: 960px) {{
        .volscope-ibkr-cell {{ min-width: 80px; padding: 7px 8px 6px 8px; }}
        .volscope-ibkr-value {{ font-size: 13px; }}
    }}
    .volscope-ibkr-value.fg-cheap {{ color: {COLORS['accent']}; }}
    .volscope-ibkr-value.fg-rich  {{ color: {COLORS['warn']}; }}
    .volscope-ibkr-value.fg-warn  {{ color: {COLORS['amber']}; }}
    .volscope-ibkr-value.fg-mid   {{ color: {COLORS['accent2']}; }}

    /* Ticker header — symbol + price + change + sector + freshness in
       IBKR's split-row layout (left: identity + price, right: meta). */
    .volscope-th {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 12px;
        padding-bottom: 12px;
        border-bottom: 1px solid {COLORS['border']};
        animation: vs-fade-in {MOTION_FAST} both;
    }}
    .volscope-th-left {{ display: flex; flex-direction: column; gap: 2px; }}
    .volscope-th-row {{
        display: flex;
        align-items: baseline;
        gap: 10px;
        flex-wrap: wrap;
    }}
    .volscope-th-symbol {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 22px;
        font-weight: 700;
        letter-spacing: -0.3px;
        color: {COLORS['text']};
    }}
    .volscope-th-price {{
        font-family: 'JetBrains Mono', monospace;
        font-variant-numeric: tabular-nums;
        font-size: 18px;
        font-weight: 600;
        color: {COLORS['text']};
    }}
    .volscope-th-change {{
        font-family: 'JetBrains Mono', monospace;
        font-variant-numeric: tabular-nums;
        font-size: 13px;
        font-weight: 500;
    }}
    .volscope-th-change.up   {{ color: {COLORS['accent']}; }}
    .volscope-th-change.down {{ color: {COLORS['warn']}; }}
    .volscope-th-name {{
        font-family: 'DM Sans', sans-serif;
        font-size: 12px;
        color: {COLORS['muted']};
    }}
    .volscope-th-right {{
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 4px;
    }}
    .volscope-th-sector {{
        font-family: 'DM Sans', sans-serif;
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 1px;
        text-transform: uppercase;
        color: {COLORS['label']};
    }}
    .volscope-th-fresh {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        color: {COLORS['label']};
        display: flex;
        align-items: center;
        gap: 5px;
    }}
    .volscope-th-fresh-dot {{
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: {COLORS['accent']};
        display: inline-block;
    }}

    /* 52-week IV range — compact horizontal bar with gradient + indicator */
    .volscope-iv-range {{
        margin: 6px 0 14px 0;
    }}
    .volscope-iv-range-row {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 5px;
    }}
    .volscope-iv-range-label {{
        font-family: 'DM Sans', sans-serif;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 1.4px;
        text-transform: uppercase;
        color: {COLORS['label']};
    }}
    .volscope-iv-range-verdict {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 1px;
    }}
    .volscope-iv-range-track {{
        position: relative;
        height: 6px;
        background: {COLORS['border']};
        border-radius: 3px;
    }}
    .volscope-iv-range-fill {{
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        border-radius: 3px;
        opacity: 0.7;
    }}
    .volscope-iv-range-fill.cheap   {{ background: linear-gradient(90deg, {COLORS['accent']}, {COLORS['accent2']}); }}
    .volscope-iv-range-fill.normal  {{ background: linear-gradient(90deg, {COLORS['accent2']}, {COLORS['amber']}); }}
    .volscope-iv-range-fill.rich    {{ background: linear-gradient(90deg, {COLORS['amber']}, {COLORS['warn']}); }}
    .volscope-iv-range-marker {{
        position: absolute;
        top: -4px;
        width: 3px;
        height: 14px;
        background: {COLORS['text']};
        border-radius: 1.5px;
        box-shadow: 0 0 8px rgba(255,255,255,0.35);
    }}
    .volscope-iv-range-foot {{
        display: flex;
        justify-content: space-between;
        margin-top: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 9px;
        color: {COLORS['label']};
        font-variant-numeric: tabular-nums;
    }}

    /* Opportunity card — Discover page row layout with 3 px left accent */
    .volscope-opp {{
        background: rgba(255,255,255,0.018);
        border: 1px solid rgba(255,255,255,0.04);
        border-left: 3px solid {COLORS['border']};
        border-radius: 6px;
        padding: 10px 12px;
        margin-bottom: 6px;
        cursor: pointer;
        transition: background {MOTION_FAST}, transform {MOTION_FAST}, border-color {MOTION_FAST};
    }}
    .volscope-opp.cheap   {{ border-left-color: {COLORS['accent']}; }}
    .volscope-opp.rich    {{ border-left-color: {COLORS['warn']}; }}
    .volscope-opp.neutral {{ border-left-color: {COLORS['accent2']}; }}
    .volscope-opp:hover {{
        background: rgba(255,255,255,0.035);
        transform: translateX(3px);
    }}
    .volscope-opp-head {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 4px;
    }}
    .volscope-opp-id {{ display: flex; align-items: center; gap: 6px; }}
    .volscope-opp-tk {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 13px;
        font-weight: 700;
        color: {COLORS['text']};
    }}
    .volscope-opp-nm {{
        font-family: 'DM Sans', sans-serif;
        font-size: 10px;
        color: {COLORS['label']};
    }}
    .volscope-opp-pill {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        font-weight: 600;
        padding: 1px 6px;
        border-radius: 3px;
    }}
    .volscope-opp-pill.cheap {{ background: rgba(0,212,170,0.10); color: {COLORS['accent']}; }}
    .volscope-opp-pill.rich  {{ background: rgba(255,68,102,0.10); color: {COLORS['warn']}; }}
    .volscope-opp-tag {{
        font-family: 'DM Sans', sans-serif;
        font-size: 8px;
        font-weight: 700;
        letter-spacing: 1.4px;
        text-transform: uppercase;
        margin-bottom: 2px;
    }}
    .volscope-opp-tag.cheap {{ color: {COLORS['accent']}; }}
    .volscope-opp-tag.rich  {{ color: {COLORS['warn']}; }}
    .volscope-opp-ctx {{
        font-family: 'DM Sans', sans-serif;
        font-size: 10px;
        color: {COLORS['muted']};
        line-height: 1.4;
    }}

    /* Sidebar snapshot widget — bottom-fixed dense KPI strip */
    .volscope-snap {{
        background: rgba(13,14,20,0.9);
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
        padding: 9px 11px;
        margin-top: 8px;
    }}
    .volscope-snap-head {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 1.6px;
        text-transform: uppercase;
        color: {COLORS['label']};
        margin-bottom: 6px;
    }}
    .volscope-snap-row {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        padding: 2px 0;
    }}
    .volscope-snap-row .k {{ color: {COLORS['label']}; }}
    .volscope-snap-row .v {{
        font-weight: 600;
        color: {COLORS['text']};
        font-variant-numeric: tabular-nums;
    }}

    /* ── Earnings Hub v2 — drawer diagnostics (2026-05-14) ─────────
       Calibration bar, drift sparklines, anomaly badge. */
    .vs-cal-block {{
        margin: 8px 0;
        padding: 8px 10px;
        background: rgba(255,255,255,0.018);
        border-radius: 6px;
        font-family: 'JetBrains Mono', monospace;
    }}
    .vs-cal-header {{
        display: flex; justify-content: space-between;
        font-size: 9px; letter-spacing: 1.3px; text-transform: uppercase;
        color: {COLORS['label']};
        margin-bottom: 6px;
    }}
    .vs-cal-h-note {{ color: {COLORS['muted']}; font-style: italic; }}
    .vs-cal-row {{
        display: flex; align-items: center; gap: 6px;
        padding: 3px 0;
        font-size: 10px;
    }}
    .vs-cal-date {{
        flex: 0 0 80px; color: {COLORS['label']};
    }}
    .vs-cal-track-left, .vs-cal-track-right {{
        flex: 0 0 120px;
        height: 8px;
        background: {COLORS['border']};
        border-radius: 2px;
        position: relative;
    }}
    .vs-cal-track-left .vs-cal-fill {{
        position: absolute; right: 0; top: 0; bottom: 0;
        border-radius: 2px;
    }}
    .vs-cal-track-right .vs-cal-fill {{
        position: absolute; left: 0; top: 0; bottom: 0;
        border-radius: 2px;
    }}
    .vs-cal-mid {{
        color: {COLORS['label']};
        font-weight: 700;
    }}
    .vs-cal-label {{
        flex: 1; font-size: 10px; font-weight: 600;
        text-align: right;
    }}

    .vs-drift-block {{
        margin: 8px 0;
        padding: 8px 10px;
        background: rgba(255,255,255,0.012);
        border-radius: 6px;
        font-family: 'JetBrains Mono', monospace;
    }}
    .vs-drift-row {{
        display: flex; align-items: center; gap: 10px;
        padding: 3px 0; font-size: 10px;
    }}
    .vs-drift-label {{
        flex: 0 0 140px;
        font-size: 9px; letter-spacing: 1.3px; text-transform: uppercase;
        color: {COLORS['label']};
    }}
    .vs-drift-num {{
        margin-left: auto;
        font-weight: 600;
    }}

    .vs-anomaly-badge {{
        display: inline-block;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.8px;
        padding: 2px 8px;
        border-radius: 4px;
        white-space: nowrap;
    }}

    /* ── Earnings Hub tile (v1, 2026-05-13) ────────────────────────
       Dense 4-line ticker card for the weekly earnings grid. */
    .vs-er-tile {{
        background: rgba(255,255,255,0.012);
        border: 1px solid {COLORS['border']};
        border-radius: 5px;
        padding: 6px 9px;
        margin-bottom: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-variant-numeric: tabular-nums;
        transition: background {MOTION_FAST}, transform {MOTION_FAST};
    }}
    .vs-er-tile:hover {{
        background: rgba(255,255,255,0.028);
        transform: translateX(2px);
    }}
    .vs-er-row1 {{
        display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap;
        margin-bottom: 3px;
    }}
    .vs-er-ticker {{
        font-size: 12px; font-weight: 700; color: {COLORS['text']};
        letter-spacing: -0.2px;
    }}
    .vs-er-spot {{
        font-size: 10px; color: {COLORS['muted']};
        margin-left: auto;
    }}
    .vs-er-row2 {{
        display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
        font-size: 10px; margin-bottom: 2px;
    }}
    .vs-er-move {{
        font-size: 13px; font-weight: 700; color: {COLORS['accent']};
        min-width: 56px;
    }}
    .vs-er-arrows {{
        display: inline-flex; gap: 6px; font-size: 10px;
        color: {COLORS['muted']};
    }}
    .vs-er-skew {{
        font-size: 10px;
        margin-left: auto;
    }}
    .vs-er-row3 {{
        display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
        font-size: 10px; margin-bottom: 2px;
        color: {COLORS['muted']};
    }}
    .vs-er-row4 {{
        display: flex; align-items: baseline;
        font-size: 10px;
        padding-top: 2px;
        border-top: 1px dashed {COLORS['border']};
        gap: 6px;
    }}
    .vs-er-rec-label {{
        color: {COLORS['text']};
        font-weight: 600;
    }}

    /* ── v3 Data-Freshness Bar (2026-05-13) ─────────────────────────
       Always-visible "how stale is the data I'm looking at" strip.
       Sits directly under each page's title. */
    .vs-fresh-pill {{
        display: inline-block;
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1px;
        padding: 4px 10px;
        border-radius: 4px;
        white-space: nowrap;
    }}
    .vs-fresh-strip {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 6px 0 10px 0;
        font-family: 'JetBrains Mono', monospace;
    }}
    .vs-fresh-meta {{
        font-size: 10px;
        color: {COLORS['muted']};
    }}
    .vs-fresh-meta-full {{
        display: flex;
        align-items: baseline;
        gap: 6px;
        flex-wrap: wrap;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        padding-top: 6px;
        line-height: 1.6;
    }}
    .vs-fresh-meta-k {{
        color: {COLORS['label']};
        text-transform: uppercase;
        letter-spacing: 1.1px;
        font-size: 9px;
    }}
    .vs-fresh-meta-v {{
        color: {COLORS['text']};
        font-weight: 600;
        font-variant-numeric: tabular-nums;
    }}
    .vs-fresh-sep {{ color: {COLORS['label']}; }}
    .vs-fresh-hint {{
        color: {COLORS['muted']};
        font-style: italic;
        font-size: 10px;
    }}

    /* ── v3 Status Bar (2026-05-12) ─────────────────────────────────
       One-row ticker summary, Bloomberg-style. Always visible above
       a ticker page so the trader sees the headline numbers without
       scrolling. */
    .vs-status-bar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 6px 12px;
        background: linear-gradient(180deg,
            rgba(255,255,255,0.025) 0%, rgba(255,255,255,0.008) 100%);
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        margin-bottom: 8px;
        font-family: 'JetBrains Mono', monospace;
        font-variant-numeric: tabular-nums;
        flex-wrap: wrap;
        min-height: 34px;
        animation: vs-fade-in {MOTION_FAST} both;
    }}
    .vs-status-left, .vs-status-mid, .vs-status-right {{
        display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    }}
    .vs-status-symbol {{
        font-size: 14px; font-weight: 700; color: {COLORS['text']};
        letter-spacing: -0.3px;
    }}
    .vs-status-company {{
        font-family: 'DM Sans', sans-serif;
        font-size: 11px; color: {COLORS['muted']};
    }}
    .vs-status-sector {{
        font-family: 'DM Sans', sans-serif;
        font-size: 9px; letter-spacing: 1.4px; text-transform: uppercase;
        color: {COLORS['label']};
    }}
    .vs-status-spot {{ font-size: 14px; font-weight: 600; color: {COLORS['text']}; }}
    .vs-status-chg {{ font-size: 12px; font-weight: 500; }}
    .vs-status-cell {{
        display: inline-flex; align-items: baseline; gap: 4px;
    }}
    .vs-status-label {{
        font-family: 'DM Sans', sans-serif;
        font-size: 8px; letter-spacing: 1.3px; text-transform: uppercase;
        color: {COLORS['label']};
    }}
    .vs-status-val {{ font-size: 12px; font-weight: 600; }}
    .vs-status-pill {{
        font-size: 10px; font-weight: 600;
        padding: 1px 6px; border-radius: 3px;
        border: 1px solid; letter-spacing: 0.5px;
    }}
    .vs-status-spark {{ display: inline-flex; align-items: center; }}
    @media (max-width: 1100px) {{
        .vs-status-mid {{ gap: 8px; }}
        .vs-status-label {{ font-size: 7px; }}
        .vs-status-val {{ font-size: 11px; }}
    }}

    /* ── Mobile responsive layout (< 800px) ───────────────────────── */
    @media (max-width: 800px) {{
        /* Streamlit-injected wrapper — shrink padding so charts breathe */
        .block-container {{
            padding-left: 0.6rem !important;
            padding-right: 0.6rem !important;
            padding-top: 0.6rem !important;
        }}
        /* Reduce h3 size on phones so headers don't dominate the screen */
        h3 {{
            font-size: 0.95rem !important;
        }}
        /* Compact cards — tighter vertical rhythm on small screens */
        .volscope-card {{
            padding: 10px 12px !important;
        }}
        /* Hide secondary muted-text rows by default to reduce clutter */
        [data-testid="stHorizontalBlock"] > div {{
            min-width: 0 !important;
        }}
        /* Charts default-height shrunk for mobile */
        .js-plotly-plot {{
            min-height: 220px !important;
        }}
    }}
</style>
"""


def inject_theme() -> None:
    """Mount the VolScope theme into the current Streamlit page."""
    import streamlit as st

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
