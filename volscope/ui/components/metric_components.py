"""
KPI cards and small UI helpers for the Scope page.

Design decisions (after audit round 2):
  - Freshness badge lives only in the sidebar. Showing it again in the KPI row
    was duplicate chrome and the two implementations had diverged.
  - The spread metric is colored: red if positive (options rich), green if
    negative (options cheap). Matches the palette semantic.
  - All render paths go through `render_html()` so the indentation-codeblock
    bug can never come back.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from volscope.analytics.signal import VolSignal
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS


def freshness_badge(last_update: Any) -> tuple[str, str]:
    """
    Return (label, hex color) describing how stale the latest data row is.
    Single source of truth for both the sidebar data-status block and any
    page-level freshness indicator.

    Accepts `date`, `datetime`, ISO date string, or None.
    """
    if last_update is None:
        return ("NO DATA", COLORS["warn"])
    try:
        if isinstance(last_update, datetime):
            d = last_update.date()
        elif isinstance(last_update, date):
            d = last_update
        else:
            d = datetime.fromisoformat(str(last_update)[:10]).date()
    except Exception:
        return ("UNKNOWN", COLORS["muted"])
    age = (date.today() - d).days
    if age <= 1:
        return (f"FRESH · {age}d", COLORS["accent"])
    if age <= 7:
        return (f"OK · {age}d", COLORS["amber"])
    return (f"STALE · {age}d", COLORS["warn"])


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _signed_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.1f}"
    except (TypeError, ValueError):
        return "—"


def _try_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _ibkr_cell(
    label: str, value: str, value_class: str = "", cell_class: str = "",
    *, tooltip: str = "",
) -> str:
    """Single dense KPI cell — used by render_kpi_row and other pages.

    ``tooltip`` (optional) renders as the cell's native HTML title=
    attribute. Tooltips come from
    ``volscope.ui.components.glossary.glossary(key)`` so all KPI
    explanations are sourced from one place (master plan §3 Stream A).
    """
    cls = f"volscope-ibkr-cell {cell_class}".strip()
    vcls = f"volscope-ibkr-value {value_class}".strip()
    title_attr = f' title="{tooltip}"' if tooltip else ""
    return (
        f'<div class="{cls}"{title_attr}>'
        f'<div class="volscope-ibkr-label">{label}</div>'
        f'<div class="{vcls}">{value}</div>'
        f'</div>'
    )


def render_kpi_row(row: dict) -> None:
    """
    IBKR-style dense KPI row — custom HTML so values never truncate.

    Color rules (single source of truth, mirrored across the app):
      IV       → accent (cyan)
      HV       → accent2 (blue)
      IV RANK  → accent if <30, warn if >70, amber otherwise
      IV PERC  → same band logic as RANK
      IV-HV    → accent if negative (cheap), warn if positive (rich)
    """
    iv = _try_float(row.get("iv_30d"))
    hv = _try_float(row.get("hv_20d"))
    rank = _try_float(row.get("iv_rank"))
    perc = _try_float(row.get("iv_percentile"))
    spot = _try_float(row.get("spot_price"))
    spread = iv - hv if (iv is not None and hv is not None) else None

    def _band(v: float | None) -> tuple[str, str]:
        """Return (value_class, cell_class) for a 0-100 band metric."""
        if v is None:
            return ("", "")
        if v < 30:
            return ("fg-cheap", "is-cheap")
        if v > 70:
            return ("fg-rich", "is-rich")
        return ("fg-warn", "is-warning")

    def _spread_classes(s: float | None) -> tuple[str, str]:
        if s is None:
            return ("", "")
        if s < 0:
            return ("fg-cheap", "is-cheap")
        return ("fg-rich", "is-rich")

    rank_v, rank_c = _band(rank)
    perc_v, perc_c = _band(perc)
    spread_v, spread_c = _spread_classes(spread)

    # Tooltip text from the centralised glossary — one source of
    # truth for every page that displays these KPIs.
    from volscope.ui.components.glossary import glossary
    cells = [
        _ibkr_cell("SPOT",     f"${spot:,.2f}" if spot is not None else "—",
                   tooltip="Current underlying price (most recent close)."),
        _ibkr_cell("IV 30D",   _pct(iv),  value_class="fg-cheap",
                   tooltip=glossary("iv_30d")),
        _ibkr_cell("HV 20D",   _pct(hv),  value_class="fg-mid",
                   tooltip=glossary("hv_20d")),
        _ibkr_cell("IV RANK",  _pct(rank), value_class=rank_v, cell_class=rank_c,
                   tooltip=glossary("iv_rank")),
        _ibkr_cell("IV PERC",  _pct(perc), value_class=perc_v, cell_class=perc_c,
                   tooltip=glossary("iv_percentile")),
        _ibkr_cell("IV − HV",  _signed_pct(spread), value_class=spread_v, cell_class=spread_c,
                   tooltip=glossary("iv_hv_spread")),
    ]
    html = '<div class="volscope-ibkr-row">' + "".join(cells) + "</div>"

    import streamlit as st
    render_html(st, html)


def render_iv_verdict_hero(history: Any, lookback_days: int = 252) -> None:
    """
    HERO-line below the ticker header — the most actionable single
    statement on the Scope page.

    Displays the 52-week IV verdict in oversize, trader-grade typography:

      CHEAP · bottom 14 % of 52w
        IV 22.3 %   ↘ from MAX 38.1 %   ↗ from MIN 18.7 %

    Pure HTML — no Plotly chart frame, no chrome.
    """
    import streamlit as st
    import math

    if history is None or getattr(history, "empty", True) or "iv_30d" not in history.columns:
        return
    window = history.tail(lookback_days).dropna(subset=["iv_30d"])
    if window.empty:
        return

    iv_min = float(window["iv_30d"].min())
    iv_max = float(window["iv_30d"].max())
    iv_now = float(window["iv_30d"].iloc[-1])
    if math.isclose(iv_max, iv_min):
        iv_max = iv_min + 1.0
    span = iv_max - iv_min
    pct = (iv_now - iv_min) / span * 100.0

    if pct < 25:
        verdict = "CHEAP"
        sub = f"bottom {pct:.0f} % of 52-week range"
        color = COLORS["accent"]
        bg = "rgba(0,212,170,0.07)"
    elif pct > 75:
        verdict = "RICH"
        sub = f"top {100 - pct:.0f} % of 52-week range"
        color = COLORS["warn"]
        bg = "rgba(255,68,102,0.07)"
    else:
        verdict = "NEUTRAL"
        sub = f"{pct:.0f} % through 52-week range"
        color = COLORS["amber"]
        bg = "rgba(255,159,67,0.07)"

    drop_from_max = (iv_max - iv_now) / iv_max * 100.0
    rise_from_min = (iv_now - iv_min) / iv_min * 100.0

    html = f'''
<div style="background:{bg};border-left:4px solid {color};border-radius:6px;
            padding:10px 14px;margin:6px 0 12px 0;
            display:flex;align-items:center;gap:14px;flex-wrap:wrap;
            font-family:'JetBrains Mono',monospace;
            animation:vs-fade-in 200ms ease-out both;">
  <div style="display:flex;flex-direction:column;line-height:1.1;">
    <span style="color:{color};font-weight:700;font-size:22px;letter-spacing:-0.3px;">
      {verdict}
    </span>
    <span style="color:{COLORS['muted']};font-size:11px;letter-spacing:0.6px;
                  text-transform:uppercase;margin-top:2px;">{sub}</span>
  </div>
  <div style="flex:1;border-left:1px solid {COLORS['border']};padding-left:14px;
              display:flex;gap:18px;flex-wrap:wrap;font-size:11px;color:{COLORS['muted']};">
    <span><span style="color:{COLORS['label']};">IV NOW</span>
          &nbsp;<strong style="color:{COLORS['text']};">{iv_now:.1f} %</strong></span>
    <span><span style="color:{COLORS['label']};">↘ from MAX</span>
          &nbsp;<strong style="color:{COLORS['text']};">{iv_max:.1f} %</strong>
          &nbsp;<span style="color:{COLORS['accent']};">(−{drop_from_max:.0f} %)</span></span>
    <span><span style="color:{COLORS['label']};">↗ from MIN</span>
          &nbsp;<strong style="color:{COLORS['text']};">{iv_min:.1f} %</strong>
          &nbsp;<span style="color:{COLORS['warn']};">(+{rise_from_min:.0f} %)</span></span>
  </div>
</div>'''
    render_html(st, html)


def render_iv_range_bar(history: Any, lookback_days: int = 252) -> None:
    """
    Compact 52-week IV range — IBKR-style horizontal bar with gradient
    fill, white indicator, MIN/MAX labels and CHEAP/RICH/NORMAL verdict.

    Far denser than the Plotly version (~50 px tall vs ~130 px) and
    composed of pure CSS so it renders instantly with no chart frame.
    """
    import streamlit as st
    import math

    if history is None or getattr(history, "empty", True) or "iv_30d" not in history.columns:
        return

    window = history.tail(lookback_days).dropna(subset=["iv_30d"])
    if window.empty:
        return

    iv_min = float(window["iv_30d"].min())
    iv_max = float(window["iv_30d"].max())
    iv_now = float(window["iv_30d"].iloc[-1])
    if math.isclose(iv_max, iv_min):
        iv_max = iv_min + 1.0

    span = iv_max - iv_min
    pct = (iv_now - iv_min) / span * 100.0

    if pct < 25:
        fill_class = "cheap"
        verdict = f"CHEAP · bottom {pct:.0f}% of 52w"
        verdict_color = COLORS["accent"]
    elif pct > 75:
        fill_class = "rich"
        verdict = f"RICH · top {100 - pct:.0f}% of 52w"
        verdict_color = COLORS["warn"]
    else:
        fill_class = "normal"
        verdict = f"NEUTRAL · {pct:.0f}% through 52w"
        verdict_color = COLORS["amber"]

    html = f'''
<div class="volscope-iv-range">
  <div class="volscope-iv-range-row">
    <span class="volscope-iv-range-label">52-WEEK IV RANGE</span>
    <span class="volscope-iv-range-verdict" style="color:{verdict_color};">{verdict}</span>
  </div>
  <div class="volscope-iv-range-track">
    <div class="volscope-iv-range-fill {fill_class}" style="width:{pct:.1f}%;"></div>
    <div class="volscope-iv-range-marker" style="left:calc({pct:.1f}% - 1.5px);"></div>
  </div>
  <div class="volscope-iv-range-foot">
    <span>MIN {iv_min:.1f}%</span>
    <span style="color:{COLORS['text']};font-weight:600;">{iv_now:.1f}%</span>
    <span>MAX {iv_max:.1f}%</span>
  </div>
</div>
'''
    render_html(st, html)


def render_ticker_header(
    symbol: str,
    name: str | None,
    spot: Any,
    sector: str | None,
    freshness_label: str,
    freshness_color: str,
    *,
    change: Any = None,
    change_pct: Any = None,
) -> None:
    """
    IBKR/TradingView-style ticker header — symbol + price + change on the
    left, sector + freshness dot on the right. Falls back gracefully when
    change data is unavailable (no day-over-day delta on first scrape).
    """
    import streamlit as st

    spot_f = _try_float(spot)
    chg_f = _try_float(change)
    pct_f = _try_float(change_pct)

    spot_str = f"${spot_f:,.2f}" if spot_f is not None else "—"
    if chg_f is not None and pct_f is not None:
        arrow = "▲" if chg_f >= 0 else "▼"
        sign = "+" if chg_f >= 0 else ""
        change_html = (
            f'<span class="volscope-th-change {"up" if chg_f >= 0 else "down"}">'
            f'{arrow} {sign}{chg_f:.2f} ({sign}{pct_f:.2f}%)</span>'
        )
    else:
        change_html = ""

    sector_html = (
        f'<div class="volscope-th-sector">{sector}</div>' if sector else ""
    )
    name_html = (
        f'<div class="volscope-th-name">{name}</div>' if name else ""
    )

    html = (
        '<div class="volscope-th">'
        '<div class="volscope-th-left">'
        '<div class="volscope-th-row">'
        f'<span class="volscope-th-symbol">◈ {symbol}</span>'
        f'<span class="volscope-th-price">{spot_str}</span>'
        f'{change_html}'
        '</div>'
        f'{name_html}'
        '</div>'
        '<div class="volscope-th-right">'
        f'{sector_html}'
        '<div class="volscope-th-fresh">'
        f'<span class="volscope-th-fresh-dot" style="background:{freshness_color};"></span>'
        f'{freshness_label}'
        '</div>'
        '</div>'
        '</div>'
    )
    render_html(st, html)


def render_percentile_pill(value: Any) -> str:
    """HTML string for a percentile pill — used inside other components."""
    v = _try_float(value)
    if v is None:
        return '<span class="volscope-pill volscope-pill-mid">—</span>'
    if v < 20:
        cls = "volscope-pill-low"
    elif v > 80:
        cls = "volscope-pill-high"
    else:
        cls = "volscope-pill-mid"
    return f'<span class="volscope-pill {cls}">IV Perc {v:.0f}</span>'


_SIGNAL_PALETTE: dict[str, tuple[str, str]] = {
    # category → (fg_color, bg_alpha_hex)
    "buy":       (COLORS["accent"], "26"),   # green, 15% opacity
    "lean_buy":  (COLORS["accent"], "14"),   # green, 8% opacity
    "neutral":   (COLORS["muted"],  "14"),   # gray
    "lean_rich": (COLORS["warn"],   "14"),   # red, 8% opacity
    "rich":      (COLORS["warn"],   "26"),   # red, 15% opacity
    "no_data":   (COLORS["label"],  "0a"),   # label gray, barely visible
}

_SIGNAL_ICONS: dict[str, str] = {
    "buy":       "●",
    "lean_buy":  "◉",
    "neutral":   "○",
    "lean_rich": "◉",
    "rich":      "●",
    "no_data":   "—",
}

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


def vol_signal_badge_html(signal: VolSignal) -> str:
    """
    Return an HTML string for a full-width signal badge to show on each
    Command Center card.

    The badge is the most prominent element on the card — large label,
    colored background, and a one-line reason below it.

    Parameters
    ----------
    signal : VolSignal
        Signal computed by volscope.analytics.signal.compute_signal().

    Returns
    -------
    str
        Self-contained ``<div>`` HTML string.
    """
    fg, alpha = _SIGNAL_PALETTE.get(signal.category, (COLORS["muted"], "14"))
    icon      = _SIGNAL_ICONS.get(signal.category, "○")
    bg        = f"{fg}{alpha}"

    strong_suffix = " ★★★" if signal.strong else ""

    return (
        f'<div style="background:{bg};border-left:3px solid {fg};'
        f'border-radius:4px;padding:6px 10px;margin-bottom:10px;">'
        f'<div style="font-family:{_MONO};font-size:13px;font-weight:700;'
        f'color:{fg};letter-spacing:0.04em;">'
        f'{icon} {signal.label}{strong_suffix}'
        f'</div>'
        f'<div style="font-family:{_MONO};font-size:10px;color:{COLORS["muted"]};'
        f'margin-top:2px;">{signal.reason}</div>'
        f'</div>'
    )


def render_warning_card(st, title: str, body: str) -> None:
    """Themed warning card — replaces st.warning (yellow default) on pages."""
    render_html(
        st,
        f"""
        <div style="background:{COLORS['card']};border:1px solid {COLORS['border']};border-left:4px solid {COLORS['amber']};border-radius:8px;padding:16px 20px;margin-top:12px;">
          <div style="color:{COLORS['amber']};font-weight:600;font-size:12px;letter-spacing:0.5px;margin-bottom:6px;font-family:'JetBrains Mono',monospace;">⚠ {title}</div>
          <div style="color:{COLORS['muted']};font-size:12px;line-height:1.5;">{body}</div>
        </div>
        """,
    )
