"""
Help / Glossary page — single source of truth for VolScope terminology.

The page answers two questions a trader will repeatedly ask while using
the app:

  1. What does this metric *mean*?
  2. How do I read the signal it produces?

Organized by section so the user can scan: Vol metrics, Signals,
Strategy templates, Card colors, Keyboard shortcuts.

Why a single page (not tooltips everywhere): tooltips have a 1:1 cost
per metric and tend to drift. One canonical glossary anchored from the
sidebar keeps definitions consistent across pages.
"""
from __future__ import annotations

import streamlit as st

from volscope.data.database import VolScopeDB
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"


def _section(title: str, lead: str) -> None:
    render_html(
        st,
        f'<div style="margin-top:24px;margin-bottom:8px;">'
        f'<div style="font-family:{_MONO};font-size:11px;font-weight:700;'
        f'color:{COLORS["accent2"]};letter-spacing:1.2px;text-transform:uppercase;">'
        f'{title}</div>'
        f'<div style="color:{COLORS["muted"]};font-size:12px;margin-top:2px;">'
        f'{lead}</div></div>',
    )


def _term(name: str, definition: str, how_to_read: str | None = None) -> None:
    parts = [
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:6px;padding:12px 16px;margin-bottom:8px;">',
        f'<div style="font-family:{_MONO};font-size:12px;font-weight:700;'
        f'color:{COLORS["text"]};letter-spacing:0.4px;">{name}</div>',
        f'<div style="color:{COLORS["text"]};font-size:12px;line-height:1.55;'
        f'margin-top:6px;">{definition}</div>',
    ]
    if how_to_read:
        parts.append(
            f'<div style="color:{COLORS["muted"]};font-size:11px;line-height:1.5;'
            f'margin-top:6px;font-family:{_MONO};">→ {how_to_read}</div>'
        )
    parts.append('</div>')
    render_html(st, "".join(parts))


def render_help_page(db: VolScopeDB, settings: dict) -> None:
    """Glossary + quick reference. Called from the page registry."""
    st.title("Help & Glossary")
    render_html(
        st,
        f'<div style="color:{COLORS["muted"]};font-size:12px;margin-top:-8px;'
        f'margin-bottom:16px;">VolScope answers four questions: '
        f'<b>buy or wait?</b> · <b>where is vol cheapest?</b> · '
        f'<b>what is the trade?</b> · <b>how big?</b></div>',
    )

    _section(
        "Volatility metrics",
        "How VolScope measures option richness vs cheapness.",
    )
    _term(
        "IV 30d",
        "Implied volatility from 30-day-ATM options. The market's "
        "forward expectation of price movement, annualized.",
        "Higher = options expensive; lower = options cheap (in absolute terms).",
    )
    _term(
        "HV 20d",
        "Realized (historical) volatility over the last 20 trading days, "
        "annualized.",
        "Compare to IV: IV >> HV means the market is paying for fear that "
        "hasn't shown up yet (rich premium); IV ≈ HV is fairly priced.",
    )
    _term(
        "IV − HV (Spread)",
        "The Volatility Risk Premium for this ticker. Positive spread = "
        "options expensive vs realized; negative = options cheap.",
        "Persistent positive spread is the structural edge of premium-selling. "
        "Watch for spread > +5pp on quality names.",
    )
    _term(
        "IV Rank",
        "Where current IV sits between its 1-year low and high (0–100). "
        "20 = near low, 80 = near high.",
        "Low IV Rank ⇒ debit spreads / long premium. High IV Rank ⇒ "
        "credit spreads / short premium.",
    )
    _term(
        "IV Percentile",
        "Percentage of the past year IV was BELOW today's value. "
        "(Different from IV Rank — accounts for distribution shape.)",
        "Above 80 = elevated; below 20 = compressed. Often the more honest "
        "of the two when IV history is skewed.",
    )

    _section(
        "Signals on Discover & Command Center",
        "Card colors and edge scores at a glance.",
    )
    _term(
        "Edge Score (0–100)",
        "Weighted composite of IV richness, term-structure, skew, and "
        "earnings proximity. Computed in analytics/edge.py.",
        "Above 70 = strong setup; 50–70 = lean; below 30 = avoid this side "
        "(consider the opposite trade).",
    )
    _term(
        "Card colors",
        f'<span style="color:{COLORS["accent"]};">Green border</span> = '
        f'cheap / buy bias. '
        f'<span style="color:{COLORS["warn"]};">Red border</span> = '
        f'rich / sell bias. '
        f'<span style="color:{COLORS["accent2"]};">Blue border</span> = '
        f'neutral / informational.',
        "Borders match the trade direction the metric suggests, not "
        "absolute price direction.",
    )
    _term(
        "Earnings badge (⚠ ER ≤30d)",
        "Earnings announcement within 30 days. IV will likely "
        "stay elevated until the print, then crush sharply.",
        "Avoid debit spreads heading into earnings — pay the IV premium, "
        "lose to crush. Credit spreads can work if the IV premium "
        "exceeds the historical move.",
    )

    _section(
        "Strategy templates",
        "How Pre-Trade builds the four core option structures.",
    )
    _term(
        "Long Put Spread",
        "Buy a put at one strike, sell a further OTM put. Defined-risk "
        "bearish bet that pays when the stock drops to/through the short strike.",
        "Best when IV is low (cheap to buy debit) AND you have a directional view.",
    )
    _term(
        "Short Iron Condor",
        "Sell an OTM call spread + an OTM put spread. Defined-risk "
        "premium-selling structure that profits if the stock stays in a range.",
        "Best when IV is high AND you expect mean-reversion / a quiet drift.",
    )
    _term(
        "Calendar Spread",
        "Sell a near-dated option, buy a same-strike longer-dated. "
        "Profits from short-dated theta decaying faster than long-dated.",
        "Best when the term structure is in steep contango (front IV >> back IV).",
    )

    _section(
        "Keyboard shortcuts",
        "Navigation and selection without the mouse.",
    )
    _term("g d", "Go to Discover.")
    _term("g c", "Go to Command Center.")
    _term("g s", "Go to Scope.")
    _term("g p", "Go to Portfolio.")
    _term("g t", "Go to Pre-Trade.")
    _term("/", "Focus the global ticker selector.")

    _section(
        "Where to dig deeper",
        "Source code locations for the curious or skeptical.",
    )
    _term(
        "Black-Scholes pricing",
        "<code>volscope/analytics/black_scholes.py</code> — pricing, all "
        "five Greeks, IV solver. Validated against published reference values.",
    )
    _term(
        "Edge scoring",
        "<code>volscope/analytics/edge.py</code> — composite score with "
        "weights for IV percentile, VRP, skew, term-structure.",
    )
    _term(
        "Signal categories",
        "<code>volscope/analytics/signal.py</code> — buy / lean_buy / "
        "neutral / lean_rich / rich classifier with thresholds.",
    )

    _section(
        "Estimators & pricing models",
        "What math is doing the work under the hood.",
    )
    _term(
        "Black-Scholes-Merton (BSM)",
        "Continuous-dividend, continuous-compounding Black-Scholes pricing "
        "for European options. Year fraction = days/365; risk-free rate "
        "from 3-month T-bill snapshot.",
        "Used everywhere a price → IV or IV → Greek conversion is needed. "
        "Newton-Raphson solver in <code>analytics/iv_solver.py</code> "
        "handles edge cases (deep OTM, zero theta).",
    )
    _term(
        "Yang-Zhang volatility (YZ)",
        "Open-high-low-close historical-volatility estimator from "
        "Yang & Zhang (2000). Combines overnight + intraday variance for "
        "lower sample noise than close-to-close.",
        "Default HV estimator in VolScope. Falls back to close-close only "
        "when OHLC missing. See <code>analytics/hv.py</code>.",
    )
    _term(
        "Volatility Regime (HMM)",
        "Six-state Hidden Markov Model fit on rolling IV / HV / skew "
        "features. States: CRUSHED, CHEAP, FAIR, RICH, EXTREME, BLOW-OFF.",
        "Regime transitions trigger Watchlist alarms if you tick the "
        "'≈ Vol Regime change' box on the Watchlist page. Model in "
        "<code>analytics/regime_hmm.py</code>; needs ≥ 252 days history.",
    )

    _section(
        "Bot & risk controls",
        "Live-trading guardrails (Phase 2.5+, paper-only this quarter).",
    )
    _term(
        "Kill switch",
        "Eight independent paths that halt the bot (operator manual, "
        "daily-loss limit, position-concentration cap, IBKR disconnect, "
        "data-staleness, audit-chain integrity break, risk-config drift, "
        "circuit-breaker).",
        "Implemented in <code>risk/kill_switch.py</code>; any path can "
        "fire from any process. See <code>docs/MASTERPLAN.md</code>.",
    )
    _term(
        "Audit chain",
        "Append-only, hash-chained log of every bot decision + execution. "
        "<code>bot_audit_chain</code> table — write-once-read-many. "
        "<code>make audit-verify</code> walks the chain end-to-end.",
        "Mutations are forbidden by code review + integration tests. "
        "Operator can replay any past decision without DB reconstruction.",
    )
    _term(
        "Paper engine",
        "Simulation lane that runs the full bot decision pipeline against "
        "real chains but writes only to <code>bot_trades</code>, never to "
        "IBKR. Required ≥ 100 closed paper trades before live opt-in.",
        "Code path: <code>execution/paper_engine.py</code> + "
        "<code>lifecycle/state_machine.py</code> (11-state).",
    )

    _section(
        "Operator tools",
        "Sidebar / page-level features the operator drives.",
    )
    _term(
        "Watchlist",
        "Custom-named ticker groupings with per-list alarm configuration. "
        "Tickers click through to Scope; alarms fire via Telegram + "
        "macOS desktop notifications.",
        "Page: <strong>Watchlist</strong> (in DECISIONS nav group). "
        "Persistence in <code>persistence/watchlists.py</code>.",
    )
    _term(
        "Quick-switch (JUMP TO TICKER)",
        "Sidebar search box — type any symbol + Enter to jump straight "
        "to Scope. Resolves regional suffixes (HK, XETRA, London, TWN).",
        "Implementation: <code>ui/components/ticker_quick_switch.py</code>.",
    )
