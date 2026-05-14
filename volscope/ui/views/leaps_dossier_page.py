"""
LEAPS Dossier — single-ticker auto-deck.

Reorders the analyst-style anomaly→stock→instrument flow into the
trader-style **Header → Sizing → Risk → Instrument → (collapsed) Anomaly /
Stock / Scenarios / Execution**. The trader's first question is "is this
my size and what is my downside" — that is what the dossier answers
above the fold; the *why* is one click away in expanders.

Every BSM-derived premium is rendered with a persistent ``EST · BSM``
chip until ``options_snapshots`` is wired with live bid/ask. The chip is
defensive: a model price next to a confident JetBrains-Mono digit is the
single most likely way for the page to mislead a trader.
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape
from typing import Optional

import pandas as pd
import streamlit as st

from volscope.analytics.leaps_convergence import (
    CONVERGENCE_THRESHOLD,
    ConvergenceResult,
    LeapsSuggestion,
    auto_thesis,
    compute_convergence,
    suggest_leaps,
)
from volscope.analytics.leaps_pdf import filename_for, render_dossier_pdf
from volscope.analytics.leaps_pretrade import run_pretrade_checks
from volscope.analytics.leaps_watchlist import (
    is_pinned,
    pin_to_watchlist,
    unpin_from_watchlist,
)
from volscope.analytics.leaps_scenarios import (
    build_risk_table,
    build_scenario_matrix,
    build_theta_runway,
    build_vega_gain_table,
)
from volscope.analytics.leaps_sizing import (
    SIZING_RULES,
    FixedDollarRule,
    FractionOfBookRule,
    lift_to_next_contract_cost,
    size_position,
)
from volscope.ui.components.html_utils import (
    convergence_dial_html,
    empty_state_html,
    est_underline_html,
    kpi_grid_html,
    kpi_value_with_est_html,
    render_html,
    score_bar_group_html,
    section_rule_html,
)
from volscope.ui.styles.theme import COLORS, TYPE


_BENCHMARK_TICKER = "SPY"


# ── Small HTML helpers ───────────────────────────────────────────────────

def _est_chip() -> str:
    """The persistent 'this number is a model estimate' marker."""
    return (
        f'<span style="background:{COLORS["amber"]}22;color:{COLORS["amber"]};'
        f'padding:1px 6px;border-radius:3px;font-size:9px;font-weight:600;'
        f'margin-left:6px;letter-spacing:0.4px;font-family:JetBrains Mono,monospace;'
        f'" title="Black-Scholes model price; live bid/ask not yet ingested.">'
        f'EST · BSM</span>'
    )


def _section_header(title: str, subtitle: str = "") -> None:
    """Thin wrapper around the shared section-rule helper.

    Kept as a function (not inlined) so existing call sites need no
    change. The helper itself now produces the new "── LABEL · subtitle"
    rule from the redesign brief.
    """
    render_html(st, section_rule_html(title.upper(), subtitle))


def _kpi_card(label: str, value: str, color: str = None, est: bool = False) -> str:
    color = color or COLORS["text"]
    est_html = _est_chip() if est else ""
    return (
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-radius:6px;padding:12px 14px;min-width:120px;">'
        f'<div style="color:{COLORS["muted"]};font-size:9px;letter-spacing:0.6px;'
        f'font-family:JetBrains Mono,monospace;text-transform:uppercase;">{escape(label)}</div>'
        f'<div style="color:{color};font-size:18px;font-weight:600;'
        f'font-family:JetBrains Mono,monospace;font-variant-numeric:tabular-nums;'
        f'margin-top:2px;">{value}{est_html}</div>'
        f'</div>'
    )


def _signal_pill(label: str, value: Optional[float]) -> str:
    if value is None:
        bg, fg = COLORS["border"], COLORS["muted"]
        text = f"{label} —"
    else:
        if value >= 70:
            bg, fg = COLORS["accent"] + "33", COLORS["accent"]
        elif value >= 40:
            bg, fg = COLORS["accent2"] + "33", COLORS["accent2"]
        else:
            bg, fg = COLORS["border"], COLORS["muted"]
        text = f"{label} {value:.0f}"
    return (
        f'<span style="background:{bg};color:{fg};padding:3px 10px;'
        f'border-radius:4px;font-size:11px;font-weight:600;'
        f'font-family:JetBrains Mono,monospace;letter-spacing:0.4px;'
        f'margin-right:6px;">{text}</span>'
    )


# ── Data loading helpers ────────────────────────────────────────────────

def _resolve_ticker(db, ticker: str) -> Optional[pd.Series]:
    df = db.get_all_latest()
    if df is None or df.empty:
        return None
    sub = df[df["ticker"] == ticker]
    if sub.empty:
        return None
    return sub.iloc[0]


def _resolve_history(db, ticker: str, lookback: int = 280) -> pd.DataFrame:
    try:
        h = db.get_recent_for_tickers([ticker], lookback_days=lookback)
        return h.get(ticker, pd.DataFrame())
    except Exception:
        return pd.DataFrame()


def _resolve_benchmark_history(db) -> pd.DataFrame:
    try:
        return db.get_ticker_history(_BENCHMARK_TICKER)
    except Exception:
        return pd.DataFrame()


def _resolve_next_earnings(db, ticker: str) -> Optional[date]:
    try:
        df = db.get_upcoming_earnings(ticker, date.today())
    except Exception:
        return None
    if df is None or df.empty:
        return None
    try:
        return pd.Timestamp(df["earnings_date"].iloc[0]).date()
    except Exception:
        return None


# ── Header section ──────────────────────────────────────────────────────

def _render_header(
    ticker: str,
    row: pd.Series,
    result: ConvergenceResult,
    suggestion: Optional[LeapsSuggestion],
    thesis: str,
) -> None:
    score = result.score
    score_color = (
        COLORS["accent"] if score >= CONVERGENCE_THRESHOLD
        else COLORS["accent2"] if score >= 50 else COLORS["muted"]
    )
    sector = row.get("sector") or ""
    company = row.get("company_name") or ""

    sector_html = (
        f'<span style="background:{COLORS["border"]};color:{COLORS["muted"]};'
        f'padding:2px 8px;border-radius:3px;font-size:10px;font-weight:600;'
        f'margin-left:10px;letter-spacing:0.4px;font-family:JetBrains Mono,monospace;">'
        f'{escape(str(sector))}</span>' if sector else ""
    )
    company_html = (
        f'<span style="color:{COLORS["muted"]};font-size:13px;margin-left:10px;'
        f'font-family:DM Sans,sans-serif;">{escape(str(company))}</span>'
        if company and not pd.isna(company) else ""
    )
    render_html(
        st,
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:14px;gap:18px;">'
        f'<div style="flex:1;min-width:0;">'
        f'<span style="font-family:DM Sans,sans-serif;font-size:26px;font-weight:600;'
        f'color:{COLORS["text"]};letter-spacing:0.4px;">◈ {escape(ticker)}</span>'
        f'{sector_html}{company_html}'
        f'</div>'
        f'<div style="flex:0 0 auto;">'
        f'{convergence_dial_html(score, score_color)}'
        f'</div>'
        f'</div>',
    )

    bars = score_bar_group_html([
        ("MIS", result.mispricing),
        ("NEG", result.neglect),
        ("REV", result.reversal),
    ])
    pills = bars   # legacy variable name kept; the rendered HTML is the bar group
    coverage_chip = ""
    if result.coverage < 3:
        coverage_chip = (
            f'<span style="background:{COLORS["amber"]}22;color:{COLORS["amber"]};'
            f'padding:2px 8px;border-radius:3px;font-size:10px;font-weight:600;'
            f'margin-left:8px;letter-spacing:0.4px;font-family:JetBrains Mono,monospace;'
            f'" title="Score based on fewer than 3 components.">'
            f'{result.coverage}/3 SIGNALS</span>'
        )
    render_html(st, f'<div style="margin-bottom:14px;">{pills}{coverage_chip}</div>')

    render_html(
        st,
        f'<div style="background:{COLORS["card"]};border-left:4px solid {score_color};'
        f'padding:12px 16px;border-radius:4px;margin-bottom:8px;">'
        f'<div style="color:{COLORS["muted"]};font-size:9px;letter-spacing:0.6px;'
        f'font-family:JetBrains Mono,monospace;margin-bottom:4px;">THESIS</div>'
        f'<div style="color:{COLORS["text"]};font-size:14px;font-family:DM Sans,sans-serif;'
        f'line-height:1.55;">{escape(thesis)}</div>'
        f'</div>',
    )

    if suggestion is None:
        st.error("Cannot price a LEAPS for this ticker — missing spot or IV.")


# ── Sizing section ──────────────────────────────────────────────────────

def _render_sizing_section(
    ticker: str,
    suggestion: LeapsSuggestion,
    book_value: float,
) -> tuple[float, int]:
    """Render the sizing widget. Returns (budget, contracts) for downstream sections."""
    _section_header(
        "Sizing",
        "is this my size — capital deployed, max loss, personalised payoff",
    )

    rule_choices = [r.name for r in SIZING_RULES] + ["Custom $"]
    state_key = f"leaps_sizing_rule_{ticker}"
    if state_key not in st.session_state:
        st.session_state[state_key] = "Fixed $1,000"

    col_rule, col_budget = st.columns([2, 3])
    with col_rule:
        rule_name = st.selectbox(
            "Sizing rule",
            options=rule_choices,
            index=rule_choices.index(st.session_state[state_key])
                if st.session_state[state_key] in rule_choices else 0,
            key=f"leaps_sizing_select_{ticker}",
            help="Pick a fixed dollar size, a fraction of book, or set a custom budget.",
        )
        st.session_state[state_key] = rule_name

    if rule_name == "Custom $":
        with col_budget:
            budget = float(st.slider(
                "Custom budget ($)",
                min_value=100, max_value=20_000,
                value=1_000, step=100,
                key=f"leaps_budget_slider_{ticker}",
            ))
    else:
        rule = next(r for r in SIZING_RULES if r.name == rule_name)
        if isinstance(rule, FractionOfBookRule):
            with col_budget:
                book_value = float(st.number_input(
                    "Book value ($)",
                    min_value=0, value=int(book_value), step=1_000,
                    key=f"leaps_book_input_{ticker}",
                ))
            budget = rule.budget_from_book(book_value)
        else:
            assert isinstance(rule, FixedDollarRule)
            budget = rule.budget_from_book(0.0)
            with col_budget:
                # st.metric truncates at ~9 chars on narrow columns ($1,200,000
                # becomes "$1,200,…"). The custom KPI HTML uses tabular-nums
                # JetBrains Mono with no max-width and matches the dossier
                # palette anyway, so we use that everywhere.
                render_html(st, kpi_grid_html(
                    [("BUDGET", f"${budget:,.0f}", None)], variant="compact"
                ))

    plan = size_position(suggestion, budget=budget)

    # Hero KPIs: the three numbers a trader needs first.
    render_html(st, kpi_grid_html([
        ("CONTRACTS",  f"{plan.contracts}",                                          None),
        ("DEPLOYED",   kpi_value_with_est_html(f"${plan.capital_deployed:,.0f}"),    None),
        ("MAX LOSS",   kpi_value_with_est_html(f"${plan.max_loss:,.0f}"),            COLORS["warn"]),
    ], variant="hero"))
    # Detail KPIs below for context.
    render_html(st, kpi_grid_html([
        ("BUDGET",     f"${plan.budget:,.0f}",                                       None),
        ("RESIDUAL",   f"${plan.capital_residual:,.0f}",                             COLORS["muted"]),
        ("BREAKEVEN",  kpi_value_with_est_html(f"${plan.breakeven_spot:,.2f}"),      None),
        ("PREMIUM",    kpi_value_with_est_html(f"${suggestion.est_premium:.2f}"),    COLORS["accent"]),
        ("STRIKE",     f"${suggestion.strike:.0f}",                                  None),
    ], variant="detail"))

    if plan.is_undersized:
        st.warning(plan.rationale)
    elif plan.capital_residual > 0:
        extra = lift_to_next_contract_cost(plan, suggestion)
        st.caption(
            f"Residual ${plan.capital_residual:,.2f}. "
            f"+${extra:,.2f} buys one more contract."
        )

    if plan.payoff:
        rows = []
        for cell in plan.payoff:
            color = (
                COLORS["accent"] if cell.profit_dollars > 0
                else COLORS["warn"] if cell.profit_dollars < 0
                else COLORS["muted"]
            )
            rows.append(
                f'<tr>'
                f'<td style="padding:4px 12px;color:{COLORS["text"]};'
                f'font-family:JetBrains Mono,monospace;font-size:11px;'
                f'font-variant-numeric:tabular-nums;">${cell.spot_at_expiry:,.2f}</td>'
                f'<td style="padding:4px 12px;text-align:right;color:{color};'
                f'font-family:JetBrains Mono,monospace;font-size:11px;font-weight:600;'
                f'font-variant-numeric:tabular-nums;">${cell.profit_dollars:+,.0f}</td>'
                f'<td style="padding:4px 12px;text-align:right;color:{color};'
                f'font-family:JetBrains Mono,monospace;font-size:11px;'
                f'font-variant-numeric:tabular-nums;">{cell.return_pct:+.0f}%</td>'
                f'</tr>'
            )
        render_html(
            st,
            f'<div style="margin-top:14px;color:{COLORS["muted"]};font-size:10px;'
            f'letter-spacing:0.6px;font-family:JetBrains Mono,monospace;">'
            f'PERSONALISED PAYOFF AT EXPIRY · {plan.contracts} contract'
            f'{"s" if plan.contracts != 1 else ""}</div>'
            f'<table style="border-collapse:collapse;width:100%;margin-top:4px;">'
            f'<thead><tr>'
            f'<th style="padding:6px 12px;text-align:left;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
            f'border-bottom:1px solid {COLORS["border"]};">SPOT</th>'
            f'<th style="padding:6px 12px;text-align:right;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
            f'border-bottom:1px solid {COLORS["border"]};">P&amp;L $</th>'
            f'<th style="padding:6px 12px;text-align:right;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
            f'border-bottom:1px solid {COLORS["border"]};">RETURN</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>',
        )

    return budget, plan.contracts


# ── Risk section ────────────────────────────────────────────────────────

def _render_risk_section(suggestion: LeapsSuggestion, capital_deployed: float) -> None:
    _section_header(
        "Risk · invalidation · scaling",
        "where does the thesis break, and what is the plan if it does",
    )
    rt = build_risk_table(suggestion, capital_deployed=capital_deployed)
    render_html(st, kpi_grid_html([
        ("MAX LOSS",     kpi_value_with_est_html(f"${rt.max_loss_dollars:,.0f}"),    COLORS["warn"]),
        ("INVALIDATION", f"${rt.invalidation_spot:,.2f}",                            COLORS["amber"]),
        ("KNOCK-OUT",    "None",                                                      COLORS["accent"]),
    ], variant="hero"))
    render_html(st, kpi_grid_html([
        ("INSTRUMENT",   "Long call",                                                 None),
        ("MARGIN CALL",  "None",                                                      COLORS["accent"]),
        ("FORCED EXIT",  "None",                                                      COLORS["accent"]),
        ("DTE LEFT",     f"{suggestion.days_to_exp}d",                                None),
        ("DRAWDOWN/INV", f"-{(1.0 - rt.invalidation_spot/suggestion.spot)*100:.0f}%", COLORS["muted"]),
    ], variant="detail"))

    rows = []
    for rung in rt.scaling_in_levels:
        rows.append(
            f'<tr>'
            f'<td style="padding:6px 12px;color:{COLORS["text"]};'
            f'font-family:JetBrains Mono,monospace;font-size:11px;'
            f'font-variant-numeric:tabular-nums;">${rung.spot_trigger:,.2f}</td>'
            f'<td style="padding:6px 12px;color:{COLORS["text"]};'
            f'font-family:JetBrains Mono,monospace;font-size:11px;'
            f'font-variant-numeric:tabular-nums;">+{rung.add_fraction*100:.0f}% of original</td>'
            f'<td style="padding:6px 12px;color:{COLORS["muted"]};'
            f'font-family:DM Sans,sans-serif;font-size:11px;">{escape(rung.rationale)}</td>'
            f'</tr>'
        )
    render_html(
        st,
        f'<div style="margin-top:14px;color:{COLORS["muted"]};font-size:10px;'
        f'letter-spacing:0.6px;font-family:JetBrains Mono,monospace;">SCALING-IN PLAN</div>'
        f'<table style="border-collapse:collapse;width:100%;margin-top:4px;">'
        f'<thead><tr>'
        f'<th style="padding:6px 12px;text-align:left;color:{COLORS["muted"]};'
        f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
        f'border-bottom:1px solid {COLORS["border"]};">SPOT TRIGGER</th>'
        f'<th style="padding:6px 12px;text-align:left;color:{COLORS["muted"]};'
        f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
        f'border-bottom:1px solid {COLORS["border"]};">ADD</th>'
        f'<th style="padding:6px 12px;text-align:left;color:{COLORS["muted"]};'
        f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
        f'border-bottom:1px solid {COLORS["border"]};">RATIONALE</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table>',
    )


# ── Instrument section ──────────────────────────────────────────────────

def _render_instrument_section(suggestion: LeapsSuggestion) -> None:
    _section_header(
        "Instrument",
        "what you are actually buying — strike, expiry, Greeks, intrinsic ladder",
    )
    render_html(st, kpi_grid_html([
        ("STRIKE",    f"${suggestion.strike:.0f}",                                   None),
        ("EXPIRY",    suggestion.expiry.isoformat(),                                 None),
        ("PREMIUM",   kpi_value_with_est_html(f"${suggestion.est_premium:.2f}"),     COLORS["accent"]),
    ], variant="hero"))
    render_html(st, kpi_grid_html([
        ("Δ DELTA",   kpi_value_with_est_html(f"{suggestion.delta:+.2f}"),           None),
        ("Γ GAMMA",   kpi_value_with_est_html(f"{suggestion.gamma:.4f}"),            None),
        ("Θ /DAY",    kpi_value_with_est_html(f"{suggestion.theta_per_day:+.4f}"),   COLORS["warn"]),
        ("ν / 1%",    kpi_value_with_est_html(f"{suggestion.vega_per_pct:+.3f}"),    COLORS["accent"]),
        ("DTE",       f"{suggestion.days_to_exp}",                                    None),
    ], variant="detail"))
    st.caption(suggestion.rationale)


# ── Anomaly + Stock combined (collapsed by default) ─────────────────────

def _render_anomaly_section(row: pd.Series, history: pd.DataFrame, benchmark: pd.DataFrame) -> None:
    iv = row.get("iv_30d")
    hv = row.get("hv_20d")
    rank = row.get("iv_rank")
    perc = row.get("iv_percentile")
    iv_hv = (iv / hv) if (iv and hv and hv > 0) else None

    summary = (
        f"IV/HV {iv_hv:.2f} · IV-Rank {rank:.0f} · "
        f"IV-Percentile {perc:.0f}"
        if iv_hv and rank is not None and perc is not None
        else "summary unavailable"
    )

    def _trailing(series_df: pd.DataFrame, lookback: int) -> Optional[float]:
        if series_df is None or series_df.empty or "spot_price" not in series_df.columns:
            return None
        s = series_df["spot_price"].dropna()
        if len(s) < 60:
            return None
        first = float(s.iloc[max(0, len(s) - lookback)])
        last = float(s.iloc[-1])
        return last / first - 1.0 if first > 0 else None

    t_ret = _trailing(history, 252)
    b_ret = _trailing(benchmark, 252)

    rs_summary = (
        f"TTM ticker {t_ret*100:+.0f}% vs SPY {b_ret*100:+.0f}%"
        if t_ret is not None and b_ret is not None
        else "trailing-12m comparison unavailable"
    )

    last_high = None
    drawdown_pct = None
    if not history.empty and "spot_price" in history.columns:
        s = history["spot_price"].dropna()
        if len(s) >= 60:
            last_high = float(s.tail(252).max())
            drawdown_pct = (last_high - float(s.iloc[-1])) / last_high * 100.0
    drawdown_summary = (
        f"-{drawdown_pct:.0f}% from 52w high · base {'forming' if drawdown_pct and drawdown_pct > 30 else 'shallow'}"
        if drawdown_pct is not None else "drawdown unavailable"
    )

    with st.expander(f"Why this works · {summary} · {rs_summary} · {drawdown_summary}",
                     expanded=False):
        st.markdown(
            f"""
**Mispricing — vol cheap vs reality, near annual floor.**
Implied vol prints {iv:.1f} % while realised 20d vol prints {hv:.1f} %.
Options are pricing {(1 - (iv/hv if iv and hv and hv>0 else 1)) * 100:.0f} % less
movement than the stock has actually delivered. IV-Rank
{f"{rank:.0f}" if rank is not None else "?"} means current IV sits in the
bottom {f"{rank:.0f}" if rank is not None else "?"} % of its 52-week range.

**Three independent reasons this anomaly persists.**
1. *Post-earnings IV crush* — IV mechanically collapses after each
   binary print, regardless of the stock direction. The window is
   typically 2–4 weeks.
2. *Neglect premium* — when the broader market ignores a name, no one
   bids up its options. Demand drives premium; absence of demand
   leaves it cheap. Attention returns; premium re-rates.
3. *Mean-reversion bias* — option markets price realised vol to revert.
   Names in regime change (new CEO, restructuring) often do not
   normalise. The market is systematically slow to recognise this.

**Stock setup — {rs_summary} · {drawdown_summary}.**
The relative-strength gap is the cleanest read on neglect: a name down
double-digits while SPY is up double-digits is, by definition, off most
investors' screens. Combined with a deep drawdown from the 52-week high,
the chart base is the asymmetric-risk part of the trade — the downside
is already in the price.
            """
        )


# ── Scenarios (collapsed) ───────────────────────────────────────────────

def _render_scenarios_section(suggestion: LeapsSuggestion) -> None:
    matrix = build_scenario_matrix(suggestion)
    vega   = build_vega_gain_table(suggestion)
    runway = build_theta_runway(suggestion)

    headline = (
        f"vega +1 σ → +${vega.rows[len(vega.rows)//2].pnl_per_contract:,.0f}/contract · "
        f"theta cliff at "
        f"{(runway.cliff_starts_at_month or '—')}m"
    )

    with st.expander(f"Scenarios · {headline}", expanded=False):
        # Spot × time matrix
        cols_html = []
        for j, months in enumerate(matrix.months_grid):
            cols_html.append(
                f'<th style="padding:4px 10px;text-align:right;color:{COLORS["muted"]};'
                f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
                f'border-bottom:1px solid {COLORS["border"]};">{months}m</th>'
            )
        rows_html = []
        for i, spot in enumerate(matrix.spot_grid):
            cells = "".join(
                f'<td style="padding:4px 10px;text-align:right;'
                f'color:{COLORS["accent"] if matrix.cells[i][j].pnl_per_contract > 0 else COLORS["warn"] if matrix.cells[i][j].pnl_per_contract < 0 else COLORS["muted"]};'
                f'font-family:JetBrains Mono,monospace;font-size:11px;'
                f'font-variant-numeric:tabular-nums;">'
                f'${matrix.cells[i][j].pnl_per_contract:+,.0f}</td>'
                for j in range(len(matrix.months_grid))
            )
            rows_html.append(
                f'<tr>'
                f'<td style="padding:4px 10px;color:{COLORS["text"]};'
                f'font-family:JetBrains Mono,monospace;font-size:11px;'
                f'font-variant-numeric:tabular-nums;">${spot:,.2f}</td>'
                f'{cells}</tr>'
            )
        render_html(
            st,
            f'<div style="margin-bottom:6px;color:{COLORS["muted"]};font-size:10px;'
            f'letter-spacing:0.6px;font-family:JetBrains Mono,monospace;">'
            f'P&amp;L PER CONTRACT — SPOT PATH × TIME (σ held constant at {matrix.iv_assumed*100:.0f}%)</div>'
            f'<table style="border-collapse:collapse;width:100%;">'
            f'<thead><tr>'
            f'<th style="padding:4px 10px;text-align:left;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
            f'border-bottom:1px solid {COLORS["border"]};">SPOT</th>'
            f'{"".join(cols_html)}'
            f'</tr></thead><tbody>{"".join(rows_html)}</tbody></table>',
        )

        # Vega gain table
        vega_rows = "".join(
            f'<tr>'
            f'<td style="padding:4px 10px;color:{COLORS["text"]};'
            f'font-family:JetBrains Mono,monospace;font-size:11px;'
            f'font-variant-numeric:tabular-nums;">{r.target_iv*100:.0f}%</td>'
            f'<td style="padding:4px 10px;text-align:right;color:{COLORS["text"]};'
            f'font-family:JetBrains Mono,monospace;font-size:11px;'
            f'font-variant-numeric:tabular-nums;">${r.new_premium:.2f}</td>'
            f'<td style="padding:4px 10px;text-align:right;'
            f'color:{COLORS["accent"] if r.pnl_per_contract > 0 else COLORS["warn"]};'
            f'font-family:JetBrains Mono,monospace;font-size:11px;font-weight:600;'
            f'font-variant-numeric:tabular-nums;">${r.pnl_per_contract:+,.0f}</td>'
            f'<td style="padding:4px 10px;text-align:right;'
            f'color:{COLORS["accent"] if r.pnl_pct_of_premium > 0 else COLORS["warn"]};'
            f'font-family:JetBrains Mono,monospace;font-size:11px;'
            f'font-variant-numeric:tabular-nums;">{r.pnl_pct_of_premium:+.0f}%</td>'
            f'</tr>'
            for r in vega.rows
        )
        render_html(
            st,
            f'<div style="margin-top:18px;margin-bottom:6px;color:{COLORS["muted"]};'
            f'font-size:10px;letter-spacing:0.6px;font-family:JetBrains Mono,monospace;">'
            f'VEGA GAIN — IF IV REVERTS TODAY, SPOT UNCHANGED (current IV {vega.current_iv*100:.0f}%)</div>'
            f'<table style="border-collapse:collapse;width:100%;">'
            f'<thead><tr>'
            f'<th style="padding:4px 10px;text-align:left;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
            f'border-bottom:1px solid {COLORS["border"]};">TARGET IV</th>'
            f'<th style="padding:4px 10px;text-align:right;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
            f'border-bottom:1px solid {COLORS["border"]};">NEW PREMIUM</th>'
            f'<th style="padding:4px 10px;text-align:right;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
            f'border-bottom:1px solid {COLORS["border"]};">P&amp;L /CONTRACT</th>'
            f'<th style="padding:4px 10px;text-align:right;color:{COLORS["muted"]};'
            f'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:0.6px;'
            f'border-bottom:1px solid {COLORS["border"]};">% OF PREMIUM</th>'
            f'</tr></thead><tbody>{vega_rows}</tbody></table>',
        )

        if runway.cliff_starts_at_month is not None:
            st.caption(
                f"Theta cliff begins around month {runway.cliff_starts_at_month}. "
                f"Roll or close before this point to avoid the steep-decay zone."
            )


# ── Pre-trade execution checklist (collapsed) ───────────────────────────

def _level_to_color(level: str) -> str:
    return {
        "GREEN": COLORS["accent"],
        "AMBER": COLORS["amber"],
        "RED":   COLORS["warn"],
        "INFO":  COLORS["accent2"],
    }.get(level, COLORS["muted"])


def _render_execution_section(
    suggestion: LeapsSuggestion,
    underlying_row: pd.Series,
    history: pd.DataFrame,
    next_earnings_date: Optional[date],
    contracts: int,
) -> None:
    checklist = run_pretrade_checks(
        suggestion=suggestion,
        underlying_row=underlying_row,
        history=history,
        chain_row=None,
        next_earnings_date=next_earnings_date,
        contracts=max(1, contracts),
    )
    headline = (
        f"{checklist.green_count()}/{len(checklist.rows)} green · "
        f"{'BLOCKED' if checklist.blocked else 'open'}"
    )
    with st.expander(f"Execution · {headline}", expanded=False):
        for row in checklist.rows:
            color = _level_to_color(row.level)
            detail_html = (
                f'<div style="color:{COLORS["muted"]};font-size:10px;'
                f'font-family:JetBrains Mono,monospace;margin-top:2px;">{escape(row.detail)}</div>'
                if row.detail else ""
            )
            render_html(
                st,
                f'<div style="display:flex;align-items:flex-start;gap:14px;'
                f'padding:8px 10px;border-left:3px solid {color};'
                f'background:{COLORS["card"]};margin-bottom:6px;">'
                f'<div style="color:{color};font-weight:600;font-family:JetBrains Mono,monospace;'
                f'font-size:11px;letter-spacing:0.6px;width:80px;">{row.level}</div>'
                f'<div style="flex:1;">'
                f'<div style="color:{COLORS["text"]};font-family:DM Sans,sans-serif;'
                f'font-size:13px;font-weight:600;">{escape(row.label)}</div>'
                f'<div style="color:{COLORS["muted"]};font-size:11px;'
                f'font-family:JetBrains Mono,monospace;margin-top:2px;">{escape(row.one_liner)}</div>'
                f'{detail_html}'
                f'</div></div>',
            )

        st.markdown("**Order templates (paste into broker)**")
        for broker, text in checklist.order_templates.items():
            st.code(text, language=None)


# ── Top-level entry ─────────────────────────────────────────────────────

def render_leaps_dossier_page(db, settings: Optional[dict] = None) -> None:
    """Top-level entry — wired into ``volscope.ui.app._PAGE_REGISTRY``."""
    settings = settings or {}
    fallback_ticker = (
        st.session_state.get("dossier_ticker")
        or st.session_state.get("selected_ticker")
        or "PYPL"
    )

    # Picker — also accepts free-text input.
    available = []
    try:
        latest = db.get_all_latest()
        if latest is not None and not latest.empty:
            available = sorted(latest["ticker"].dropna().astype(str).unique().tolist())
    except Exception:
        available = []

    cols = st.columns([3, 2])
    with cols[0]:
        if available:
            default_idx = available.index(fallback_ticker) if fallback_ticker in available else 0
            ticker = st.selectbox(
                "Ticker",
                options=available, index=default_idx,
                key="dossier_ticker_select",
            )
        else:
            ticker = st.text_input("Ticker", value=fallback_ticker, key="dossier_ticker_input")
    with cols[1]:
        book_value = st.number_input(
            "Book value ($) for fraction-of-book sizing",
            min_value=0, value=int(st.session_state.get("dossier_book", 25_000)),
            step=5_000, key="dossier_book",
        )

    st.session_state["dossier_ticker"] = ticker
    if not ticker:
        st.warning("Pick a ticker.")
        return

    row = _resolve_ticker(db, ticker)
    if row is None:
        st.error(f"No data for {ticker}. Add it via the sidebar resolver first.")
        return

    history = _resolve_history(db, ticker)
    bench_history = _resolve_benchmark_history(db)
    next_er = _resolve_next_earnings(db, ticker)

    result = compute_convergence(row, history, bench_history)
    suggestion = None
    spot = row.get("spot_price")
    iv30 = row.get("iv_30d")
    if (
        spot is not None and iv30 is not None
        and not pd.isna(spot) and not pd.isna(iv30)
        and float(spot) > 0 and float(iv30) > 0
    ):
        suggestion = suggest_leaps(
            ticker=ticker,
            spot=float(spot),
            iv=float(iv30) / 100.0,
        )
    thesis = auto_thesis(result, row, history, bench_history)

    _render_header(ticker, row, result, suggestion, thesis)
    if suggestion is None:
        return

    # ── Quick actions row (watchlist + alert) ──────────────────────────
    pinned = False
    try:
        pinned = is_pinned(db, ticker)
    except Exception:
        pinned = False
    qa_cols = st.columns([1, 1, 4])
    with qa_cols[0]:
        if pinned:
            if st.button("★ Unpin", key=f"unpin_{ticker}",
                         help="Remove from LEAPS watchlist."):
                try:
                    unpin_from_watchlist(db, ticker)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not unpin: {exc}")
        else:
            if st.button("☆ Pin to watchlist", key=f"pin_{ticker}",
                         help="Persistently pin this ticker for later review."):
                try:
                    pin_to_watchlist(db, ticker)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not pin: {exc}")
    with qa_cols[1]:
        if st.button("🔔 Add convergence alert", key=f"alert_{ticker}",
                     help="Fire an alert when the convergence score crosses the gate."):
            try:
                db.add_alert_rule(
                    ticker=ticker,
                    metric="convergence_score",
                    operator=">=",
                    threshold=float(CONVERGENCE_THRESHOLD),
                    label=f"{ticker} convergence ≥ {CONVERGENCE_THRESHOLD:.0f}",
                )
                st.success(f"Alert armed for {ticker}.")
            except Exception as exc:
                st.error(f"Could not arm alert: {exc}")

    budget, contracts = _render_sizing_section(ticker, suggestion, book_value)
    capital_deployed = round(contracts * suggestion.est_premium * 100, 2)
    _render_risk_section(suggestion, capital_deployed=capital_deployed)
    _render_instrument_section(suggestion)
    _render_anomaly_section(row, history, bench_history)
    _render_scenarios_section(suggestion)
    _render_execution_section(suggestion, row, history, next_er, contracts)

    _section_header(
        "Export",
        "printable PDF dossier — structurally identical to the PYPL deck",
    )
    if st.button("Generate PDF dossier",
                 key=f"pdf_btn_{ticker}",
                 help="Renders the full dossier (header, sizing, risk, "
                      "instrument, anomaly read, scenarios, checklist, "
                      "glossary) into a single PDF you can print or share."):
        try:
            from volscope.analytics.leaps_sizing import size_position as _sz
            sizing_plan = _sz(suggestion, budget=budget)
            pdf_bytes = render_dossier_pdf(
                ticker=ticker,
                snapshot_date=date.today(),
                convergence=result,
                thesis=thesis,
                suggestion=suggestion,
                sizing_plan=sizing_plan,
                risk_table=build_risk_table(suggestion, capital_deployed),
                scenario_matrix=build_scenario_matrix(suggestion),
                vega_table=build_vega_gain_table(suggestion),
                theta_runway=build_theta_runway(suggestion),
                pretrade=run_pretrade_checks(
                    suggestion=suggestion,
                    underlying_row=row,
                    history=history,
                    chain_row=None,
                    next_earnings_date=next_er,
                    contracts=max(1, contracts),
                ),
                underlying_row=row,
            )
        except Exception as exc:
            st.error(f"PDF render failed: {exc}")
        else:
            st.session_state[f"pdf_bytes_{ticker}"] = pdf_bytes
            st.session_state[f"pdf_filename_{ticker}"] = filename_for(suggestion)
            st.success("PDF generated. Click below to download.")

    pdf_buf = st.session_state.get(f"pdf_bytes_{ticker}")
    pdf_name = st.session_state.get(f"pdf_filename_{ticker}")
    if pdf_buf and pdf_name:
        st.download_button(
            label=f"Download {pdf_name}",
            data=pdf_buf,
            file_name=pdf_name,
            mime="application/pdf",
            key=f"pdf_dl_{ticker}",
            use_container_width=True,
        )
