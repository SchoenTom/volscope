"""
LEAPS Lab — convergence-of-signals scanner with concrete LEAPS suggestions.

Surfaces tickers where vol is mispriced, the name is neglected vs. its
benchmark, and the chart shows a base-pattern reversal — the three-signal
convergence the PYPL $80 / Jan-2029 thesis describes.

For every actionable name (composite score ≥ ``CONVERGENCE_THRESHOLD``),
the page also computes a concrete deep-OTM LEAPS suggestion: strike,
expiry, premium estimate, breakeven, Greeks, and a payoff ladder.

Pure presentation layer — all numbers come from
``volscope.analytics.leaps_convergence``.
"""
from __future__ import annotations

from html import escape
from typing import Optional

import pandas as pd
import streamlit as st

from volscope.analytics.leaps_convergence import (
    CONVERGENCE_THRESHOLD,
    LeapsSuggestion,
    rank_universe,
    suggest_leaps,
)
from volscope.ui.components.html_utils import (
    convergence_dial_html,
    empty_state_html,
    render_html,
    score_bar_group_html,
    section_rule_html,
)
from volscope.ui.styles.theme import COLORS


_BENCHMARK_TICKER = "SPY"
_DEFAULT_LOOKBACK_DAYS = 280       # > 252 so 12-month return is always defined


def _render_watchlist_strip(db) -> None:
    """Compact strip showing pinned tickers with a one-click Open Dossier.

    No-op when the watchlist is empty — keeps the Lab uncluttered for new
    users, surfaces the tracked names for returning users.
    """
    try:
        from volscope.analytics.leaps_watchlist import load_watchlist
        items = load_watchlist(db)
    except Exception:
        items = []
    if not items:
        return
    render_html(
        st,
        f'<div style="margin-top:4px;margin-bottom:18px;color:{COLORS["muted"]};'
        f'font-size:10px;letter-spacing:0.6px;font-family:JetBrains Mono,monospace;">'
        f'★ WATCHLIST · {len(items)} pinned</div>',
    )
    cols = st.columns(min(6, len(items)))
    for idx, entry in enumerate(items[:6]):
        with cols[idx]:
            if st.button(
                f"◈ {entry.ticker}",
                key=f"wl_open_{entry.ticker}",
                use_container_width=True,
                help=f"Pinned {entry.pinned_at.isoformat()} · open dossier",
            ):
                st.session_state["dossier_ticker"] = entry.ticker
                st.session_state["active_page"] = "Dossier"
                st.rerun()


def _section(title: str, sub: str = "") -> None:
    sub_html = (
        f'<div style="color:{COLORS["muted"]};font-size:11px;'
        f'font-family:JetBrains Mono,monospace;margin-top:2px;">{escape(sub)}</div>'
        if sub else ""
    )
    render_html(
        st,
        f'<div style="margin-top:18px;margin-bottom:6px;">'
        f'<div style="color:{COLORS["text"]};font-weight:600;font-size:14px;'
        f'letter-spacing:0.6px;font-family:DM Sans,sans-serif;">{escape(title)}</div>'
        f'{sub_html}'
        f'</div>',
    )


def _component_pill(label: str, value: Optional[float]) -> str:
    """Render a single sub-score as a coloured pill."""
    if value is None:
        bg = COLORS["border"]
        fg = COLORS["muted"]
        text = f"{label} —"
    else:
        if value >= 70:
            bg, fg = COLORS["accent"] + "22", COLORS["accent"]
        elif value >= 40:
            bg, fg = COLORS["accent2"] + "22", COLORS["accent2"]
        else:
            bg, fg = COLORS["border"], COLORS["muted"]
        text = f"{label} {value:.0f}"
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;'
        f'border-radius:3px;font-size:10px;font-weight:600;'
        f'font-family:JetBrains Mono,monospace;letter-spacing:0.4px;'
        f'margin-right:4px;">{text}</span>'
    )


def _render_payoff_table(suggestion: LeapsSuggestion) -> None:
    rows = []
    for spot, intrinsic, ret_pct in suggestion.payoff:
        ret_color = (
            COLORS["accent"] if ret_pct > 0
            else COLORS["warn"] if ret_pct < 0
            else COLORS["muted"]
        )
        rows.append(
            f'<tr>'
            f'<td style="padding:3px 10px;color:{COLORS["text"]};'
            f'font-family:JetBrains Mono,monospace;font-size:11px;'
            f'font-variant-numeric:tabular-nums;">${spot:.2f}</td>'
            f'<td style="padding:3px 10px;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:11px;'
            f'font-variant-numeric:tabular-nums;">${intrinsic:.2f}</td>'
            f'<td style="padding:3px 10px;color:{ret_color};text-align:right;'
            f'font-family:JetBrains Mono,monospace;font-size:11px;'
            f'font-variant-numeric:tabular-nums;font-weight:600;">'
            f'{ret_pct:+.1f}%</td>'
            f'</tr>'
        )
    render_html(
        st,
        f'<div style="margin:10px 0 6px 0;color:{COLORS["muted"]};'
        f'font-size:10px;font-family:JetBrains Mono,monospace;'
        f'letter-spacing:0.6px;">PAYOFF AT EXPIRY</div>'
        f'<table style="border-collapse:collapse;width:100%;">'
        f'<thead><tr>'
        f'<th style="padding:4px 10px;text-align:left;color:{COLORS["muted"]};'
        f'font-size:10px;font-family:JetBrains Mono,monospace;letter-spacing:0.6px;'
        f'border-bottom:1px solid {COLORS["border"]};">SPOT</th>'
        f'<th style="padding:4px 10px;text-align:left;color:{COLORS["muted"]};'
        f'font-size:10px;font-family:JetBrains Mono,monospace;letter-spacing:0.6px;'
        f'border-bottom:1px solid {COLORS["border"]};">INTRINSIC</th>'
        f'<th style="padding:4px 10px;text-align:right;color:{COLORS["muted"]};'
        f'font-size:10px;font-family:JetBrains Mono,monospace;letter-spacing:0.6px;'
        f'border-bottom:1px solid {COLORS["border"]};">RETURN</th>'
        f'</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>',
    )


def _render_convergence_card(row: pd.Series, suggestion: Optional[LeapsSuggestion]) -> None:
    """Redesigned card (2026-05-10).

    Anatomy: dial (hero) right-anchored · ticker + sector pill left ·
    score-bar trio inline · single-line stats row · suggestion strip with
    leading ▸ and a quiet inline `est` marker. Border-left agrees with the
    dial colour — same stoplight, two surfaces.
    """
    ticker = str(row["ticker"])
    score = float(row["score"])
    score_color = (
        COLORS["accent"] if score >= CONVERGENCE_THRESHOLD
        else COLORS["accent2"] if score >= 50
        else COLORS["muted"]
    )

    bars = score_bar_group_html([
        ("MIS", row.get("mispricing")),
        ("NEG", row.get("neglect")),
        ("REV", row.get("reversal")),
    ])

    iv = row.get("iv_30d")
    hv = row.get("hv_20d")
    rank = row.get("iv_rank")
    perc = row.get("iv_percentile")
    spot = row.get("spot_price")
    sector = row.get("sector") or ""

    iv_hv = (iv / hv) if (iv and hv and hv > 0) else None
    spot_str = f"${float(spot):,.2f}" if spot else "—"
    iv_hv_str = f"{iv_hv:.2f}" if iv_hv else "—"
    rank_str = f"{float(rank):.0f}" if rank is not None and not pd.isna(rank) else "—"
    perc_str = f"{float(perc):.0f}" if perc is not None and not pd.isna(perc) else "—"

    sector_html = (
        f'<span class="volscope-pill volscope-pill-sector" '
        f'style="margin-left:8px;font-size:10px;padding:1px 8px;">'
        f'{escape(str(sector))}</span>' if sector else ""
    )

    actionable_badge = ""
    if score >= CONVERGENCE_THRESHOLD:
        actionable_badge = (
            f'<span style="color:{COLORS["accent"]};font-family:JetBrains Mono,monospace;'
            f'font-size:10px;font-weight:700;letter-spacing:0.8px;margin-left:10px;">'
            f'· CONVERGENCE</span>'
        )

    suggestion_html = ""
    if suggestion is not None:
        suggestion_html = (
            f'<div style="margin-top:10px;font-family:JetBrains Mono,monospace;'
            f'font-size:11px;color:{COLORS["text"]};font-variant-numeric:tabular-nums;'
            f'line-height:1.6;">'
            f'<span style="color:{COLORS["accent2"]};">▸</span> '
            f'<strong>${suggestion.strike:.0f}C</strong> · '
            f'{suggestion.expiry.isoformat()} ({suggestion.days_to_exp}d) · '
            f'prem <strong>${suggestion.est_premium:.2f}</strong> · '
            f'BE <strong>${suggestion.breakeven:.2f}</strong>'
            f'<span class="volscope-est-quiet">est</span>'
            f'</div>'
            f'<div style="margin-top:4px;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:10px;'
            f'font-variant-numeric:tabular-nums;">'
            f'Δ {suggestion.delta:+.2f} · '
            f'Γ {suggestion.gamma:.4f} · '
            f'Θ/d {suggestion.theta_per_day:+.4f} · '
            f'ν/% {suggestion.vega_per_pct:+.3f}'
            f'</div>'
        )

    body = (
        f'<div class="volscope-card" style="border-left:4px solid {score_color};'
        f'padding:16px 18px;margin-bottom:12px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;'
        f'gap:18px;">'
        # ── Left column: ticker, sector, bars, stats ──
        f'<div style="flex:1;min-width:0;">'
        f'<div style="display:flex;align-items:center;flex-wrap:wrap;">'
        f'<span class="volscope-card-ticker" style="font-size:18px;">◈ {escape(ticker)}</span>'
        f'{sector_html}{actionable_badge}'
        f'</div>'
        f'{bars}'
        f'<div style="color:{COLORS["muted"]};font-size:11px;'
        f'font-family:JetBrains Mono,monospace;line-height:1.6;'
        f'font-variant-numeric:tabular-nums;">'
        f'Spot {spot_str} · IV/HV {iv_hv_str} · '
        f'IV-Rank {rank_str} · IV-Pct {perc_str}'
        f'</div>'
        f'{suggestion_html}'
        f'</div>'
        # ── Right column: convergence dial ──
        f'<div style="flex:0 0 auto;">'
        f'{convergence_dial_html(score, score_color)}'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    render_html(st, body)


def render_leaps_page(db, settings: Optional[dict] = None) -> None:
    """Top-level entry — wired into ``volscope.ui.app._PAGE_REGISTRY``."""
    render_html(
        st,
        f'<div style="font-family:DM Sans,sans-serif;color:{COLORS["text"]};'
        f'font-size:22px;font-weight:600;letter-spacing:0.4px;margin-bottom:4px;">'
        f'◈ LEAPS Lab</div>'
        f'<div style="font-family:JetBrains Mono,monospace;color:{COLORS["muted"]};'
        f'font-size:11px;line-height:1.7;margin-bottom:18px;">'
        f'Convergence-of-signals scanner. Surfaces tickers where vol is '
        f'mispriced (IV vs HV vs own history), the name is neglected vs. SPY, '
        f'and the chart base is reversing — the three-signal pattern behind '
        f'the PYPL $80 / Jan-2029 thesis. Each actionable row produces a '
        f'concrete deep-OTM LEAPS suggestion with Greeks and payoff ladder.'
        f'</div>',
    )
    from volscope.ui.components.data_freshness_bar import render_data_freshness_bar
    render_data_freshness_bar(db, compact=True)

    _render_watchlist_strip(db)

    with st.spinner("Scanning universe for convergence …"):
        try:
            latest = db.get_all_latest()
        except Exception as exc:
            st.error(f"Could not load latest snapshot: {exc}")
            return
        if latest is None or latest.empty:
            render_html(st, empty_state_html(
                headline="The DB is empty — let's seed it",
                body=(
                    "VolScope has no daily snapshot yet. Run `make seed-starter` "
                    "for an 8-ticker quickstart, or `make scrape` to fetch a full "
                    "universe. Both finish under a minute on a fresh checkout."
                ),
            ))
            return

        tickers = latest["ticker"].dropna().astype(str).tolist()
        try:
            histories = db.get_recent_for_tickers(tickers, lookback_days=_DEFAULT_LOOKBACK_DAYS)
        except Exception as exc:
            st.error(f"Could not load histories: {exc}")
            return

        try:
            benchmark_history = db.get_ticker_history(_BENCHMARK_TICKER)
        except Exception:
            benchmark_history = pd.DataFrame()

        ranked = rank_universe(latest, histories, benchmark_history, n=20)

    if ranked.empty:
        st.info("No tickers had enough history for convergence scoring.")
        return

    actionable = ranked[ranked["score"] >= CONVERGENCE_THRESHOLD]
    watchlist  = ranked[ranked["score"] < CONVERGENCE_THRESHOLD]

    _section(
        f"Actionable convergence ({len(actionable)})",
        f"composite ≥ {CONVERGENCE_THRESHOLD:.0f} — vol mispricing × neglect × reversal aligned",
    )
    if actionable.empty:
        render_html(st, empty_state_html(
            headline="No actionable convergence today",
            body=(
                "None of the 280+ tracked names currently clear the gate. "
                "Three independent signals aligning is rare on purpose — patience "
                "is the trade. Set a daily alert to know the moment one fires, "
                "or pin candidates from the watchlist below."
            ),
        ))
    else:
        for _, row in actionable.iterrows():
            spot = row.get("spot_price")
            iv30 = row.get("iv_30d")
            suggestion: Optional[LeapsSuggestion] = None
            if spot is not None and iv30 is not None and not pd.isna(spot) and not pd.isna(iv30):
                suggestion = suggest_leaps(
                    ticker=str(row["ticker"]),
                    spot=float(spot),
                    iv=float(iv30) / 100.0,
                )
            _render_convergence_card(row, suggestion)

            if suggestion is not None:
                ticker_str = str(row["ticker"])
                col_open, col_payoff = st.columns([1, 4])
                with col_open:
                    if st.button(
                        "Open dossier →",
                        key=f"open_dossier_{ticker_str}",
                        use_container_width=True,
                        help="Drill into the full single-ticker analysis: "
                             "sizing, risk, scenarios, execution checklist.",
                    ):
                        st.session_state["dossier_ticker"] = ticker_str
                        st.session_state["active_page"] = "Dossier"
                        st.rerun()
                with col_payoff:
                    with st.expander(f"Payoff ladder · {ticker_str}", expanded=False):
                        _render_payoff_table(suggestion)
                        st.caption(suggestion.rationale)

    _section(
        f"Watchlist ({len(watchlist)})",
        "below the convergence gate — track for further IV compression or reversal trigger",
    )
    if watchlist.empty:
        st.caption("Watchlist empty.")
    else:
        for _, row in watchlist.iterrows():
            _render_convergence_card(row, suggestion=None)

    with st.expander("How is the convergence score computed?", expanded=False):
        st.markdown(
            f"""
**Composite (0–100):** weighted average of three independent signals.
A name passes the actionable gate at **≥ {CONVERGENCE_THRESHOLD:.0f}**.

| Component | Weight | What it measures |
|-----------|-------:|------------------|
| **Mispricing** | 50 % | `IV/HV` ratio + IV Rank + IV Percentile — options cheap vs realised vol *and* near their own annual floor. |
| **Neglect**    | 30 % | Trailing-12-month return of the name minus SPY's. Deep underperformance = market has stopped paying attention = vol stays cheap longer than it should. |
| **Reversal**   | 20 % | Drawdown from 52-week high + short-term realised vol cooling vs longer term. The "Wave-II base" pattern. |

**Why these three together?** Each on its own is a weak signal:
mispriced vol can stay cheap for months in a name no one trades; a
neglected stock can keep falling; a base pattern without cheap vol means
the LEAPS premium eats the convexity. The combination is what made the
PYPL $80 deck non-trivial — and that combination is rare enough (1–2× per
year per name) to justify a deep-OTM convexity bet sized at 5–10 % of book.

**LEAPS suggestion**: a deep-OTM call (default strike +75 % over spot,
~24 months to expiry) priced via Black-Scholes at the current ATM IV.
Premium, breakeven, Greeks, and a payoff ladder anchored on Wave-III
fibonacci milestones are shown so the trade is concrete, not directional
hand-waving.
            """
        )
