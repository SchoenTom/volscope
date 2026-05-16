"""
Research — statistical-significance gauntlet for VolScope signals.

Why this page exists
====================
VolScope is built around signals that *look* like alpha — IV mean-
reversion, IV-HV spread cheap/rich, term-structure inversion, etc.
Every retail vol tool surfaces these. Almost none subject them to
real out-of-sample statistical testing. This page does.

The user picks a signal definition (Cheap-IV-Mean-Reversion, Rich-IV-
Premium-Selling, IV-HV-Spread Reversion), a universe, and a holding
period; the engine generates a return series and runs the four-test
gauntlet from Bailey & López de Prado (2014):

  1. t-test of the strategy Sharpe (H₀: SR ≤ 0)
  2. Moving-block bootstrap (Künsch 1989) of Sharpe + 95 % CI
  3. Permutation test of strategy-vs-benchmark alpha (SPY default)
  4. Deflated Sharpe Ratio (correction for data-mining bias)

A signal that clears all four at p < 0.01 is well-supported. None
of the four alone is sufficient — together they are the academic
gold standard for retail-vol-trader-grade evidence.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from volscope.data.database import VolScopeDB
from volscope.research import GauntletResult, run_gauntlet
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"
_SANS = "DM Sans, Inter, system-ui, sans-serif"


# ── Signal definitions ─────────────────────────────────────────────

# Each signal is a pure function of a single-ticker history DataFrame
# returning a daily "in-strategy" boolean mask. The strategy then
# earns the next-day return when the mask is True, else zero. This
# is the simplest mean-reversion harness; more sophisticated signals
# (rolling-window weights, leveraged exposure) can be added later
# without changing the gauntlet plumbing.

_SIGNALS = {
    "Cheap IV Mean-Reversion": {
        "description": (
            "Long underlying when ``iv_percentile < 20``. Tests whether "
            "tickers with extreme-cheap implied vol revert to higher prices."
        ),
        "mask_fn":     "_mask_cheap_iv",
    },
    "Rich IV Premium-Selling": {
        "description": (
            "Short underlying when ``iv_percentile > 80``. Tests whether "
            "extreme-rich IV regimes preceded mean-reversion."
        ),
        "mask_fn":     "_mask_rich_iv",
    },
    "IV-HV Spread Reversion": {
        "description": (
            "Long underlying when ``iv_30d - hv_yz_30d > 5`` (rich premium "
            "selling proxy); tests whether the spread compresses on average."
        ),
        "mask_fn":     "_mask_iv_hv_rich",
    },
    "Term-Structure Inversion": {
        "description": (
            "Long underlying when ``iv_30d > iv_60d`` (inverted curve)."
            " Tests if curve normalisation typically follows."
        ),
        "mask_fn":     "_mask_term_inverted",
    },
}


def _mask_cheap_iv(hist: pd.DataFrame) -> pd.Series:
    return (hist["iv_percentile"] < 20).fillna(False)


def _mask_rich_iv(hist: pd.DataFrame) -> pd.Series:
    return (hist["iv_percentile"] > 80).fillna(False)


def _mask_iv_hv_rich(hist: pd.DataFrame) -> pd.Series:
    iv = pd.to_numeric(hist.get("iv_30d"), errors="coerce")
    hv = pd.to_numeric(
        hist.get("hv_yz_30d", hist.get("hv_20d")), errors="coerce",
    )
    return (iv - hv > 5.0).fillna(False)


def _mask_term_inverted(hist: pd.DataFrame) -> pd.Series:
    iv30 = pd.to_numeric(hist.get("iv_30d"), errors="coerce")
    iv60 = pd.to_numeric(hist.get("iv_60d"), errors="coerce")
    return (iv30 > iv60).fillna(False)


_MASK_REGISTRY = {
    "_mask_cheap_iv":      _mask_cheap_iv,
    "_mask_rich_iv":       _mask_rich_iv,
    "_mask_iv_hv_rich":    _mask_iv_hv_rich,
    "_mask_term_inverted": _mask_term_inverted,
}


def _signal_returns(
    hist: pd.DataFrame,
    mask: pd.Series,
    *,
    holding_days: int,
    short: bool = False,
) -> pd.Series:
    """Strategy return series.

    On every date where ``mask`` is True, the strategy earns the
    forward ``holding_days``-day return on ``spot_price`` (divided
    by ``holding_days`` so the resulting daily-equivalent return is
    comparable across different holding windows).

    ``short=True`` flips the sign — used for the "Rich IV Premium
    Selling" definition where the thesis is that rich IV precedes
    *downward* price moves.
    """
    if "spot_price" not in hist.columns or hist.empty:
        return pd.Series(dtype=float)
    spot = pd.to_numeric(hist["spot_price"], errors="coerce")
    fwd_ret = spot.shift(-holding_days) / spot - 1.0
    fwd_daily = fwd_ret / max(1, holding_days)
    out = pd.Series(0.0, index=hist.index)
    out.loc[mask & fwd_daily.notna()] = fwd_daily.loc[mask & fwd_daily.notna()]
    if short:
        out = -out
    return out


def _gather_strategy_returns(
    db: VolScopeDB,
    tickers: list[str],
    signal_name: str,
    holding_days: int,
) -> pd.Series:
    """Pool the strategy returns across ``tickers`` into one daily series.

    Each ticker's signal contributes when its mask fires; cross-
    ticker the daily returns are averaged so the pooled series is
    "average return of all tickers in-signal that day".
    """
    sig = _SIGNALS[signal_name]
    mask_fn = _MASK_REGISTRY[sig["mask_fn"]]
    short_side = signal_name == "Rich IV Premium-Selling"

    per_ticker: list[pd.Series] = []
    for t in tickers:
        try:
            hist = db.get_ticker_history(t)
        except Exception:                                       # noqa: BLE001
            continue
        if hist is None or hist.empty or "date" not in hist.columns:
            continue
        hist = hist.copy()
        hist["date"] = pd.to_datetime(hist["date"])
        hist = hist.sort_values("date").set_index("date")
        m = mask_fn(hist)
        if not m.any():
            continue
        ret = _signal_returns(hist, m, holding_days=holding_days, short=short_side)
        if not ret.empty:
            per_ticker.append(ret.rename(t))
    if not per_ticker:
        return pd.Series(dtype=float)
    panel = pd.concat(per_ticker, axis=1).sort_index()
    # Average across tickers — zero contribution when a ticker is
    # not in-signal that day. Use ``mean(skipna=True)`` so days with
    # no tickers in-signal at all return NaN (and are filtered out).
    pooled = panel.where(panel != 0.0).mean(axis=1, skipna=True)
    # Convert NaN (no signal that day) to zero return so the series
    # is dense for downstream statistical tests.
    return pooled.fillna(0.0)


def _benchmark_returns(db: VolScopeDB, ticker: str = "SPY") -> pd.Series:
    """Daily SPY (or other benchmark) returns — anchored to the same
    date index as the strategy returns where possible."""
    try:
        hist = db.get_ticker_history(ticker)
    except Exception:
        return pd.Series(dtype=float)
    if hist is None or hist.empty or "spot_price" not in hist.columns:
        return pd.Series(dtype=float)
    h = hist.copy()
    h["date"] = pd.to_datetime(h["date"])
    h = h.sort_values("date").set_index("date")
    spot = pd.to_numeric(h["spot_price"], errors="coerce")
    return spot.pct_change().dropna().rename(ticker)


# ── Result rendering helpers ───────────────────────────────────────

def _pval_chip(p: float) -> str:
    """Colour-coded p-value pill — operators read these at a glance."""
    if p <= 0.01:
        color, label = COLORS["accent"], "p ≤ 0.01"
    elif p <= 0.05:
        color, label = COLORS["amber"], "p ≤ 0.05"
    elif p <= 0.10:
        color, label = COLORS["accent2"], "p ≤ 0.10"
    else:
        color, label = COLORS["warn"], "n.s."
    return (
        f'<span style="background:{color}1a;color:{color};'
        f'border:1px solid {color}55;padding:2px 8px;border-radius:4px;'
        f'font-family:{_MONO};font-size:10px;font-weight:600;">'
        f'{p:.4f} · {label}</span>'
    )


def _render_results(result: GauntletResult) -> None:
    # Headline strip — 4 chips, one per test.
    t_chip   = _pval_chip(result.t_test.p_value)
    boot_chip = _pval_chip(result.bootstrap.p_value)
    perm_chip = (
        _pval_chip(result.permutation.p_value)
        if result.permutation is not None
        else f'<span style="color:{COLORS["muted"]};font-size:10px;">no benchmark</span>'
    )
    dsr_chip = _pval_chip(result.deflated.p_value)

    sr_obs   = result.t_test.sharpe_annual
    sr_color = COLORS["accent"] if sr_obs >= 0 else COLORS["warn"]
    sr_sign  = "+" if sr_obs >= 0 else ""

    render_html(
        st,
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-left:3px solid {sr_color};border-radius:8px;'
        f'padding:14px 18px;margin:12px 0;">'
        f'<div style="display:flex;align-items:baseline;gap:18px;'
        f'flex-wrap:wrap;font-family:{_SANS};">'
        f'<div>'
        f'<div style="color:{COLORS["muted"]};font-size:10px;text-transform:uppercase;'
        f'letter-spacing:0.04em;">Annualised Sharpe (test set)</div>'
        f'<div style="font-family:{_MONO};font-size:28px;font-weight:700;'
        f'color:{sr_color};line-height:1.0;'
        f'font-variant-numeric:tabular-nums;">{sr_sign}{sr_obs:.2f}</div>'
        f'</div>'
        f'<div style="margin-left:auto;color:{COLORS["muted"]};font-size:11px;'
        f'text-align:right;">'
        f'train {result.n_train}d · test {result.n_test}d · '
        f'split {result.split_date.date()}'
        f'</div>'
        f'</div>'
        f'</div>',
    )

    # 4-test table.
    render_html(
        st,
        f'<table style="width:100%;border-collapse:collapse;'
        f'font-family:{_MONO};font-size:12px;margin-bottom:14px;">'
        f'<thead>'
        f'<tr style="background:{COLORS["surface"]};">'
        f'<th style="text-align:left;padding:8px 12px;color:{COLORS["muted"]};'
        f'border-bottom:1px solid {COLORS["border"]};">Test</th>'
        f'<th style="text-align:left;padding:8px 12px;color:{COLORS["muted"]};'
        f'border-bottom:1px solid {COLORS["border"]};">p-value</th>'
        f'<th style="text-align:left;padding:8px 12px;color:{COLORS["muted"]};'
        f'border-bottom:1px solid {COLORS["border"]};">Detail</th>'
        f'</tr>'
        f'</thead>'
        f'<tbody>'
        f'<tr><td style="padding:8px 12px;color:{COLORS["text"]};">'
        f't-test of Sharpe</td>'
        f'<td style="padding:8px 12px;">{t_chip}</td>'
        f'<td style="padding:8px 12px;color:{COLORS["muted"]};">'
        f't = {result.t_test.t_stat:+.2f}, n = {result.t_test.n_obs}</td></tr>'
        f'<tr><td style="padding:8px 12px;color:{COLORS["text"]};">'
        f'Block bootstrap (Künsch)</td>'
        f'<td style="padding:8px 12px;">{boot_chip}</td>'
        f'<td style="padding:8px 12px;color:{COLORS["muted"]};">'
        f'95% CI [{result.bootstrap.sharpe_ci_low:+.2f}, '
        f'{result.bootstrap.sharpe_ci_high:+.2f}] · '
        f'{result.bootstrap.n_resamples:,} resamples · '
        f'block {result.bootstrap.block_length}d</td></tr>'
        f'<tr><td style="padding:8px 12px;color:{COLORS["text"]};">'
        f'Permutation vs benchmark</td>'
        f'<td style="padding:8px 12px;">{perm_chip}</td>'
        f'<td style="padding:8px 12px;color:{COLORS["muted"]};">'
        + (
            f'α = {result.permutation.alpha_observed:+.5f} · '
            f'{result.permutation.n_permutations:,} perms'
            if result.permutation is not None
            else 'skipped — no benchmark data'
        )
        + f'</td></tr>'
        f'<tr><td style="padding:8px 12px;color:{COLORS["text"]};">'
        f'Deflated Sharpe Ratio</td>'
        f'<td style="padding:8px 12px;">{dsr_chip}</td>'
        f'<td style="padding:8px 12px;color:{COLORS["muted"]};">'
        f'SR={result.deflated.sharpe_observed:+.2f}, '
        f'E[max under H₀]={result.deflated.sharpe_expected_max:+.2f}, '
        f'γ̂₃={result.deflated.skew:+.2f}, γ̂₄={result.deflated.kurt:+.2f}'
        f'</td></tr>'
        f'</tbody></table>',
    )

    # Equity curve — strategy vs benchmark on the test window.
    if result.test_equity is None or result.test_equity.empty:
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=result.test_equity.index, y=result.test_equity.values,
        mode="lines",
        line=dict(color=sr_color, width=2),
        name="Strategy",
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.3f}<extra></extra>",
    ))
    if result.bench_equity is not None and not result.bench_equity.empty:
        fig.add_trace(go.Scatter(
            x=result.bench_equity.index, y=result.bench_equity.values,
            mode="lines",
            line=dict(color=COLORS["muted"], width=1.5, dash="dot"),
            name="Benchmark",
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.3f}<extra></extra>",
        ))
    fig.add_hline(y=1.0, line=dict(color=COLORS["border"], width=1, dash="dash"))
    fig.update_layout(
        title=dict(
            text="EQUITY CURVE — TEST WINDOW",
            font=dict(family=_SANS, color=COLORS["muted"], size=11),
            x=0.0, xanchor="left", y=0.97,
        ),
        paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["bg"],
        font=dict(family=_MONO, color=COLORS["text"], size=10),
        height=320,
        margin=dict(l=12, r=24, t=36, b=28),
        hovermode="x unified",
        xaxis=dict(gridcolor=COLORS["border"]),
        yaxis=dict(gridcolor=COLORS["border"], side="right"),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1.0,
            font=dict(family=_MONO, size=10, color=COLORS["text"]),
        ),
    )
    st.plotly_chart(fig, width='stretch',
                     config={"displayModeBar": False})


# ── Public entry point ─────────────────────────────────────────────

def render_research_page(db: VolScopeDB, settings: dict) -> None:
    # v0.9.7 — 4-phase orientation strip (master plan §2)
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name='Research', ticker=st.session_state.get('selected_ticker'))
    """Render the statistical-significance gauntlet page."""
    render_html(
        st,
        f'<div style="margin-bottom:14px;font-family:{_MONO};">'
        f'<span style="font-size:22px;font-weight:700;color:{COLORS["text"]};">'
        f'<span style="color:{COLORS["accent2"]};">σ</span> Research</span>'
        f'<div style="color:{COLORS["muted"]};font-size:12px;margin-top:3px;">'
        f'Four-test statistical gauntlet (Bailey-López de Prado 2014). '
        f'Pick a signal, a universe, a holding period — verdict in 10-30 seconds.'
        f'</div>'
        f'</div>',
    )

    # ── Controls strip ─────────────────────────────────────────────
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        signal_name = st.selectbox(
            "Signal",
            list(_SIGNALS.keys()),
            index=0,
            help="Each signal is a pure function of daily_vol history.",
        )
    with c2:
        try:
            available = sorted(db.get_available_tickers() or [])
        except Exception:
            available = []
        default_pick = [t for t in ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
                         if t in available][:5]
        universe = st.multiselect(
            "Universe",
            available,
            default=default_pick,
            help="Strategy returns are pooled across these tickers.",
        )
    with c3:
        holding_days = st.number_input(
            "Holding (days)", min_value=1, max_value=60, value=5, step=1,
            help="Forward-return window. Returns are normalised to "
                  "daily-equivalent so different holdings are comparable.",
        )

    # Description of the chosen signal.
    sig = _SIGNALS[signal_name]
    render_html(
        st,
        f'<div style="background:{COLORS["surface"]};border-left:3px solid '
        f'{COLORS["accent2"]};padding:10px 14px;border-radius:5px;margin:6px 0;'
        f'font-family:{_SANS};font-size:12px;color:{COLORS["text"]};">'
        f'<strong>{signal_name}</strong> — {sig["description"]}'
        f'</div>',
    )

    # Advanced controls.
    with st.expander("Advanced — gauntlet parameters", expanded=False):
        ac1, ac2, ac3, ac4 = st.columns(4)
        with ac1:
            train_frac = st.slider(
                "Train fraction", min_value=0.4, max_value=0.8,
                value=0.6, step=0.05,
                help="Chronological split — first X% trains, rest is "
                      "held out for the gauntlet.",
            )
        with ac2:
            n_boot = st.number_input(
                "Bootstrap resamples", min_value=500, max_value=20000,
                value=5000, step=500,
                help="Higher = tighter CI but slower.",
            )
        with ac3:
            n_perm = st.number_input(
                "Permutations", min_value=500, max_value=20000,
                value=5000, step=500,
            )
        with ac4:
            n_trials = st.number_input(
                "Trials for DSR", min_value=1, max_value=10000,
                value=10, step=1,
                help="Number of candidate signals you considered "
                      "before picking this one. Drives the Deflated-"
                      "Sharpe data-mining correction.",
            )

    if not universe:
        st.info("Select at least one ticker to run the gauntlet.")
        return

    if st.button("▶ Run gauntlet", type="primary", width='content'):
        with st.spinner(
            f"Gathering strategy returns for {len(universe)} tickers…",
        ):
            strat_ret = _gather_strategy_returns(
                db, universe, signal_name, int(holding_days),
            )
        if strat_ret.empty:
            st.warning(
                "No strategy returns generated — none of the selected "
                "tickers triggered the signal mask. Try a different "
                "signal or expand the universe."
            )
            return
        with st.spinner("Running 4-test gauntlet (~10 s)…"):
            bench_ret = _benchmark_returns(db, "SPY")
            result = run_gauntlet(
                strat_ret,
                benchmark_returns=bench_ret if not bench_ret.empty else None,
                train_frac=float(train_frac),
                n_bootstrap=int(n_boot),
                n_permutations=int(n_perm),
                n_trials_in_search=int(n_trials),
            )
        _render_results(result)

    # v0.9.7 — cross-page weave footer (master plan §4)
    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(st, page='Research', ticker=st.session_state.get('selected_ticker'))
