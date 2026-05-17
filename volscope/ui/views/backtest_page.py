"""
Strategy Backtest page — surfaces simulation results to the trader.

Reads ``data/backtest/strategy_stats.jsonl`` via the calibration module
and presents:
  - Universe-level strategy ranking by Sharpe
  - Per-ticker top performers (filterable)
  - Per-strategy detail with hit-rate distribution

When the simulation hasn't been run, the page shows a one-click CTA to
trigger ``make simulate``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from volscope.analytics.strategy_calibration import (
    load_latest_stats,
    universe_ranking,
)
from volscope.data.database import VolScopeDB
from volscope.ui.components.html_utils import render_html
from volscope.ui.styles.theme import COLORS

_MONO = "JetBrains Mono, SF Mono, Menlo, monospace"
_REPORT_PATH = Path(__file__).resolve().parents[3] / "data" / "backtest" / "strategy_report.md"


def render_backtest_page(db: VolScopeDB, settings: dict) -> None:
    # v0.9.7 — 4-phase orientation strip (master plan §2)
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name='Backtest', ticker=st.session_state.get('selected_ticker'))
    """Render the Strategy Backtest results page."""
    render_html(
        st,
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid {COLORS["border"]};">'
        f'<div style="font-family:{_MONO};font-size:20px;font-weight:700;color:{COLORS["text"]};">'
        f'<span style="color:{COLORS["accent"]};">▣</span> STRATEGY BACKTEST'
        f'</div>'
        f'<div style="font-family:{_MONO};font-size:11px;color:{COLORS["muted"]};">'
        f'walk-forward · first-order vega P&amp;L'
        f'</div>'
        f'</div>',
    )

    stats = load_latest_stats()
    if not stats:
        _render_empty_state(st)
        return

    universe_stats = universe_ranking()
    per_ticker = [
        s for (strat, t), s in stats.items() if t is not None
    ]

    # ── Universe-level KPI strip ─────────────────────────────────────
    st.markdown("### Universe-level performance")
    if universe_stats:
        _render_universe_strip(st, universe_stats)
    else:
        st.info("No universe-level stats yet — re-run `make simulate`.")

    # ── Filter controls ──────────────────────────────────────────────
    st.markdown("### Per-ticker performance")
    cols = st.columns([2, 1, 1, 1])
    strategies = sorted({s.strategy for s in per_ticker})
    chosen_strats = cols[0].multiselect(
        "Strategy filter",
        strategies,
        default=strategies,
        help="Show only these strategies in the per-ticker table.",
    )
    min_n = cols[1].number_input(
        "Min trades",
        min_value=0, max_value=500,
        value=20,
        help="Filter out (strategy, ticker) pairs with too few simulated trades.",
    )
    min_sharpe = cols[2].number_input(
        "Min Sharpe",
        min_value=-5.0, max_value=20.0,
        value=0.5, step=0.1,
        help="Annualised Sharpe ratio threshold.",
    )
    sort_by = cols[3].selectbox(
        "Sort by",
        ["sharpe", "expected_pnl", "hit_rate", "n_trades"],
        index=0,
    )

    # ── Per-ticker table ─────────────────────────────────────────────
    rows = [
        {
            "ticker":        s.ticker,
            "strategy":      s.strategy,
            "n_trades":      s.n_trades,
            "hit_rate":      s.hit_rate,
            "avg_win_pct":   s.avg_win_pct,
            "avg_loss_pct":  s.avg_loss_pct,
            "payoff_ratio":  s.payoff_ratio,
            "expected_pnl":  s.expected_pnl,
            "sharpe":        s.sharpe,
            "max_drawdown":  s.max_drawdown,
            "confidence":    s.confidence,
        }
        for s in per_ticker
        if s.strategy in chosen_strats
        and s.n_trades >= min_n
        and s.sharpe >= min_sharpe
    ]
    if not rows:
        st.info("No (strategy, ticker) pairs match the filter — relax the thresholds.")
        return

    df = pd.DataFrame(rows).sort_values(sort_by, ascending=False).reset_index(drop=True)

    column_config = {
        "ticker":       st.column_config.TextColumn("Ticker", width="small"),
        "strategy":     st.column_config.TextColumn("Strategy", width="medium"),
        "n_trades":     st.column_config.NumberColumn("n", format="%d", width="small"),
        "hit_rate":     st.column_config.ProgressColumn(
            "Hit", format="%.0f%%", min_value=0.0, max_value=1.0,
            help="Fraction of simulated trades with positive P&L."
        ),
        "avg_win_pct":  st.column_config.NumberColumn("avg_win", format="%+.3f"),
        "avg_loss_pct": st.column_config.NumberColumn("avg_loss", format="%.3f"),
        "payoff_ratio": st.column_config.NumberColumn("payoff", format="%.2fx"),
        "expected_pnl": st.column_config.NumberColumn("E[pnl]", format="%+.4f"),
        "sharpe":       st.column_config.NumberColumn(
            "Sharpe", format="%+.2f",
            help="Annualised at 12 trades/year.",
        ),
        "max_drawdown": st.column_config.NumberColumn("max_dd", format="%.3f"),
        "confidence":   st.column_config.ProgressColumn(
            "Conf", format="%.0f%%", min_value=0.0, max_value=1.0
        ),
    }

    st.dataframe(
        df, width='stretch', hide_index=True,
        column_config=column_config, height=520,
    )

    # CSV export of the filtered view
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Export filtered table as CSV",
        data=csv_bytes,
        file_name="volscope_backtest.csv",
        mime="text/csv",
        key="backtest_csv_export",
    )

    # ── Methodology ─────────────────────────────────────────────────
    if _REPORT_PATH.exists():
        with st.expander("Methodology + full Markdown report", expanded=False):
            st.markdown(_REPORT_PATH.read_text())

    # v0.9.7 — cross-page weave footer (master plan §4)
    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(st, page='Backtest', ticker=st.session_state.get('selected_ticker'))


# ── Internals ────────────────────────────────────────────────────────────

def _render_empty_state(st_module) -> None:
    """CTA when no simulation has run yet."""
    render_html(
        st_module,
        f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
        f'border-left:4px solid {COLORS["accent"]};padding:18px 22px;'
        f'border-radius:8px;font-family:{_MONO};">'
        f'<div style="color:{COLORS["accent"]};font-weight:700;font-size:14px;margin-bottom:8px;">'
        f'No backtest data yet'
        f'</div>'
        f'<div style="color:{COLORS["text"]};font-size:12px;line-height:1.6;">'
        f'Run the strategy simulation to populate this page. The simulation '
        f'walks every ticker in the DB, simulates each Strategy Recommender '
        f'template across available history, and writes calibrated hit-rates '
        f'and Sharpe ratios to data/backtest/strategy_stats.jsonl.'
        f'</div>'
        f'<div style="color:{COLORS["muted"]};font-size:11px;margin-top:8px;">'
        f'Synchronous: takes ~10–60 seconds depending on universe size.'
        f'</div>'
        f'</div>',
    )
    # Inputs to configure the run (Operator feedback 2026-05-17:
    # "Backtest hat 0 Inputs"). Surfacing the CLI flags as widgets so
    # the operator can scope the simulation without dropping to a
    # terminal.
    c1, c2 = st_module.columns([3, 1])
    with c1:
        ticker_filter = st_module.text_input(
            "Ticker filter (optional)",
            placeholder="leave empty for full universe — or e.g. SPY,QQQ,AAPL",
            key="backtest_ticker_filter",
            help="Comma-separated subset. Empty = simulate every ticker in the DB.",
        )
    with c2:
        dry_run = st_module.checkbox(
            "Dry run",
            value=False,
            key="backtest_dry_run",
            help="Read-only dry run — no JSONL output. Useful to verify config.",
        )

    if st_module.button(
        "▶ Run simulation now",
        key="backtest_run_btn",
        type="primary",
        help="Runs scripts/backtest/run_strategy_simulation.py with live progress streaming.",
    ):
        import subprocess
        # Stream stdout to a live text panel so the user sees per-ticker
        # progress instead of staring at a spinner for 30s.
        status = st_module.empty()
        cmd = ["python", "scripts/backtest/run_strategy_simulation.py"]
        clean_tickers = (ticker_filter or "").strip()
        if clean_tickers:
            cmd += ["--tickers", clean_tickers]
        if dry_run:
            cmd.append("--dry-run")
        try:
            # cwd from this module's location — was hardcoded to the
            # old iCloud Desktop path which silently broke after the
            # 2026-05-15 migration to ~/dev/VolScope.
            from pathlib import Path as _P
            _root = _P(__file__).resolve().parents[3]
            proc = subprocess.Popen(
                cmd,
                cwd=str(_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            tail_lines: list[str] = []
            for line in proc.stdout or []:
                line = line.rstrip()
                if not line:
                    continue
                tail_lines.append(line)
                tail_lines = tail_lines[-6:]
                status.code("\n".join(tail_lines), language="text")
            proc.wait(timeout=600)
            if proc.returncode == 0:
                status.success("Simulation complete — reload the page to see results.")
                st_module.rerun()
            else:
                status.error(f"Simulation exited code={proc.returncode}")
        except Exception as exc:
            status.error(f"Could not run simulation: {exc}")


def _render_universe_strip(st_module, universe_stats: list) -> None:
    """5 KPI tiles for the top universe strategies."""
    n = min(5, len(universe_stats))
    cols = st_module.columns(n)
    for i, s in enumerate(universe_stats[:n]):
        sharpe_color = (
            COLORS["accent"]  if s.sharpe >= 1.0 else
            COLORS["accent2"] if s.sharpe >= 0.5 else
            COLORS["warn"]
        )
        render_html(
            cols[i],
            f'<div style="background:{COLORS["card"]};border:1px solid {COLORS["border"]};'
            f'border-radius:6px;padding:12px 14px;height:100%;">'
            f'<div style="color:{COLORS["label"]};font-size:9px;text-transform:uppercase;'
            f'letter-spacing:1px;font-family:{_MONO};">{s.strategy}</div>'
            f'<div style="font-family:{_MONO};font-size:18px;font-weight:700;'
            f'color:{sharpe_color};margin-top:4px;">'
            f'sharpe {s.sharpe:+.2f}'
            f'</div>'
            f'<div style="color:{COLORS["muted"]};font-family:{_MONO};font-size:10px;margin-top:4px;">'
            f'hit {s.hit_rate:.0%} · payoff {s.payoff_ratio:.2f}x · n={s.n_trades:,}'
            f'</div>'
            f'</div>',
        )
