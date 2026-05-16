"""
Scanner page — full-width sortable table of every tracked ticker.

Columns, left to right:
    TICKER · NAME · SECTOR · IV · 1D D · RANK · PERC · SPREAD · PC RATIO · CROWD · HV20

The page uses the full content width. No explicit column widths on
ProgressColumn / NumberColumn: Streamlit auto-distributes space across the
visible set, which means adding or hiding a column re-balances automatically.

Interaction: click any row to jump to Scope for that ticker via the modern
`on_select="rerun"` single-row API.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from volscope.analytics.crowded_trades import compute_crowded_score
from volscope.analytics.opportunity import _looks_like_data_artifact
from volscope.ui.components.metric_components import render_warning_card


def _company_map(db, tickers: list[str]) -> dict[str, str]:
    """v0.9.2: bulk single-SELECT instead of N per-ticker queries.

    Scanner renders the universe (~842 tickers); the prior loop did
    one DuckDB ``get_company_name`` per row → ~842 sequential
    queries per Scanner render. Replaced with one indexed SELECT
    that returns all (ticker, company_name) pairs in a single
    round-trip.
    """
    if not tickers:
        return {}
    try:
        ph = ",".join(["?"] * len(tickers))
        rows = db.con.execute(
            f"""
            SELECT ticker, company_name
            FROM daily_vol
            WHERE ticker IN ({ph})
              AND company_name IS NOT NULL
            GROUP BY ticker, company_name
            """,
            list(tickers),
        ).fetchall()
        return {str(t): str(n) for t, n in rows if n}
    except Exception:                                          # noqa: BLE001
        # Fall back to per-ticker if the bulk query fails (e.g.
        # company_name column missing on a fresh DB).
        out: dict[str, str] = {}
        for t in tickers:
            try:
                name = db.get_company_name(t)
            except Exception:                                  # noqa: BLE001
                name = None
            if name:
                out[t] = name
        return out


def _augment_with_derived_columns(
    df: pd.DataFrame, bulk_history: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """Attach 1-day/30-day IV change, percentile trend, and crowded score to each row.

    All columns use bulk_history so we make ONE DB round-trip per scan,
    not N. The crowded score is computed using the last 60 rows of each
    ticker's history (same lookback as the Discover panel).
    """
    out = df.copy()

    def _one_day_change(ticker: str) -> float | None:
        hist = bulk_history.get(ticker)
        if hist is None or hist.shape[0] < 2 or "iv_30d" not in hist.columns:
            return None
        a = hist["iv_30d"].iloc[-1]
        b = hist["iv_30d"].iloc[-2]
        if pd.isna(a) or pd.isna(b):
            return None
        # Suppress data-source-change artifacts — if the 1-day jump looks
        # like a seed-to-scrape rotation rather than a real market move,
        # the Scanner should report None, not the fake number.
        if _looks_like_data_artifact(float(b), float(a)):
            return None
        return float(a) - float(b)

    def _thirty_day_change(ticker: str) -> float | None:
        """30-day change in iv_30d. Positive = IV trending up (watch out)."""
        hist = bulk_history.get(ticker)
        if hist is None or "iv_30d" not in hist.columns:
            return None
        h = hist.dropna(subset=["iv_30d"])
        if len(h) < 2:
            return None
        now = h["iv_30d"].iloc[-1]
        # Find the reading closest to 30 rows back (calendar ~30 trading days)
        lookback = min(30, len(h) - 1)
        then = h["iv_30d"].iloc[-(lookback + 1)]
        if pd.isna(now) or pd.isna(then):
            return None
        return float(now) - float(then)

    def _perc_trend(ticker: str) -> float | None:
        """30-day change in iv_percentile. Negative = falling = opportunity signal."""
        hist = bulk_history.get(ticker)
        if hist is None or "iv_percentile" not in hist.columns:
            return None
        h = hist.dropna(subset=["iv_percentile"])
        if len(h) < 2:
            return None
        now = h["iv_percentile"].iloc[-1]
        lookback = min(30, len(h) - 1)
        then = h["iv_percentile"].iloc[-(lookback + 1)]
        if pd.isna(now) or pd.isna(then):
            return None
        return float(now) - float(then)

    def _crowded(row: pd.Series) -> float | None:
        ticker = row.get("ticker")
        if ticker is None:
            return None
        hist = bulk_history.get(ticker, pd.DataFrame())
        # Need at least 20 rows for the crowded score's z-score components
        # to be meaningful. Sparse data produces a noisy 50-ish result that
        # clutters the scanner — better to show blank.
        if hist is None or hist.shape[0] < 20:
            return None
        try:
            return float(compute_crowded_score(row, hist))
        except Exception:
            return None

    if "ticker" in out.columns:
        out["iv_change_1d"]  = out["ticker"].apply(_one_day_change)
        out["iv_change_30d"] = out["ticker"].apply(_thirty_day_change)
        out["perc_trend"]    = out["ticker"].apply(_perc_trend)
    else:
        out["iv_change_1d"]  = None
        out["iv_change_30d"] = None
        out["perc_trend"]    = None
    out["crowded_score"] = out.apply(_crowded, axis=1) if "ticker" in out.columns else None
    return out


def render_scan_page(db, settings: dict | None = None) -> None:
    # v0.9.7 — 4-phase orientation strip (master plan §2)
    from volscope.ui.components.phase_header import render_phase_header
    render_phase_header(st, page_name='Scanner')
    import streamlit as st

    st.markdown("## ◈ Scanner")
    st.caption(
        "Every tracked ticker. Sorted by IV Percentile. Click any row to jump to Scope."
    )

    latest = db.get_all_latest()
    if latest.empty:
        render_warning_card(
            st,
            title="No data yet",
            body=(
                "Use the <strong>Add ticker</strong> box in the sidebar to "
                "load your first name, or run <code>make seed</code>."
            ),
        )
        return

    # Fetch historical context once so we can enrich with derived columns.
    if "ticker" in latest.columns:
        all_tickers = latest["ticker"].dropna().tolist()
    else:
        all_tickers = []
    bulk_history: dict[str, pd.DataFrame] = {}
    if all_tickers:
        with st.spinner("Computing derived metrics..."):
            bulk_history = db.get_recent_for_tickers(all_tickers, lookback_days=60)

    # Filter state persists across reruns so the user's "Sector=Tech"
    # survives navigating to Scope and back.
    fs = st.session_state.setdefault("scan_filters_v1", {
        "iv_perc_range":    (0, 100),
        "selected_sectors": None,   # None = default-to-all on first render
        "direction":        "All",
        "min_crowded":      0,
        "only_falling_iv":  False,
    })

    # ── Preset filter buttons — common queries with one click ────────
    preset_cols = st.columns([1, 1, 1, 1, 4])
    if preset_cols[0].button("💎 Cheap", help="iv_perc ≤ 25, spread < 0",
                              width='stretch'):
        st.session_state["scan_filters_v1"] = {
            "iv_perc_range": (0, 25),
            "selected_sectors": None,
            "direction": "Cheap (IV < HV)",
            "min_crowded": 0,
            "only_falling_iv": False,
        }
        st.rerun()
    if preset_cols[1].button("🔥 Rich", help="iv_perc ≥ 75, spread > 0",
                              width='stretch'):
        st.session_state["scan_filters_v1"] = {
            "iv_perc_range": (75, 100),
            "selected_sectors": None,
            "direction": "Rich (IV > HV)",
            "min_crowded": 0,
            "only_falling_iv": False,
        }
        st.rerun()
    if preset_cols[2].button("🌐 Crowded", help="crowded_score ≥ 70",
                              width='stretch'):
        st.session_state["scan_filters_v1"] = {
            "iv_perc_range": (0, 100),
            "selected_sectors": None,
            "direction": "All",
            "min_crowded": 70,
            "only_falling_iv": False,
        }
        st.rerun()
    if preset_cols[3].button("🪓 Crushed", help="iv falling + cheap spread",
                              width='stretch'):
        st.session_state["scan_filters_v1"] = {
            "iv_perc_range": (0, 50),
            "selected_sectors": None,
            "direction": "Cheap (IV < HV)",
            "min_crowded": 0,
            "only_falling_iv": True,
        }
        st.rerun()
    fs = st.session_state["scan_filters_v1"]

    with st.expander("Filters (advanced)", expanded=False):
        iv_perc_range = st.slider(
            "IV Percentile window",
            min_value=0,
            max_value=100,
            value=fs["iv_perc_range"],
            help="Only show tickers whose IV percentile lies in this range.",
        )
        sectors = (
            sorted(latest["sector"].dropna().unique().tolist())
            if "sector" in latest.columns
            else []
        )
        default_sectors = (
            fs["selected_sectors"] if fs["selected_sectors"] is not None else sectors
        )
        # Drop any persisted sector that no longer exists in the universe
        default_sectors = [s for s in default_sectors if s in sectors] or sectors
        selected_sectors = st.multiselect(
            "Sector", sectors, default=default_sectors, help="Filter by sector membership."
        )
        direction_options = ["All", "Rich (IV > HV)", "Cheap (IV < HV)"]
        direction = st.radio(
            "Spread direction",
            direction_options,
            index=direction_options.index(fs["direction"]),
            horizontal=True,
            help="Rich = options look expensive. Cheap = options look underpriced.",
        )
        min_crowded = st.slider(
            "Min crowded score",
            min_value=0,
            max_value=100,
            value=int(fs["min_crowded"]),
            help="Only show tickers with a crowded score at or above this value.",
        )
        only_falling_iv = st.checkbox(
            "Show only tickers where IV is falling (30d trend)",
            value=bool(fs["only_falling_iv"]),
            help="Potential long-vol setups: IV trending down, could reverse up.",
        )

    # Persist the user's choices so they survive page navigation.
    st.session_state["scan_filters_v1"] = {
        "iv_perc_range":    iv_perc_range,
        "selected_sectors": selected_sectors,
        "direction":        direction,
        "min_crowded":      min_crowded,
        "only_falling_iv":  only_falling_iv,
    }

    df = latest.copy()
    df = _augment_with_derived_columns(df, bulk_history)

    if "iv_percentile" in df.columns:
        df = df[
            df["iv_percentile"].between(
                iv_perc_range[0], iv_perc_range[1], inclusive="both"
            )
            | df["iv_percentile"].isna()
        ]
    if selected_sectors and "sector" in df.columns:
        df = df[df["sector"].isin(selected_sectors) | df["sector"].isna()]
    if "iv_30d" in df.columns and "hv_20d" in df.columns:
        spread_filter = df["iv_30d"] - df["hv_20d"]
        if direction.startswith("Rich"):
            df = df[spread_filter > 0]
        elif direction.startswith("Cheap"):
            df = df[spread_filter < 0]
    if min_crowded > 0 and "crowded_score" in df.columns:
        df = df[df["crowded_score"].fillna(0) >= min_crowded]
    if only_falling_iv and "iv_change_30d" in df.columns:
        df = df[df["iv_change_30d"].fillna(0) < 0]

    # Company-name fill (fast path from daily_vol column, slow path from DB).
    if "company_name" in df.columns:
        df["NAME"] = df["company_name"].fillna("")
    else:
        df["NAME"] = ""
    missing_name = (
        df[df["NAME"] == ""]["ticker"].tolist() if "ticker" in df.columns else []
    )
    if missing_name:
        filled = _company_map(db, missing_name)
        if filled:
            df["NAME"] = df.apply(
                lambda r: filled.get(r.get("ticker"), r.get("NAME", "")), axis=1
            )

    # Full scanner column order, left to right.
    display_cols = [
        ("ticker", "TICKER"),
        ("NAME", "NAME"),
        ("sector", "SECTOR"),
        ("iv_30d", "IV"),
        ("iv_change_1d", "1D D"),
        ("iv_change_30d", "30D D"),
        ("iv_rank", "RANK"),
        ("iv_percentile", "PERC"),
        ("iv_quality_score", "QUALITY"),  # v0.6.1 — IV Robustness Subsystem
        ("perc_trend", "PERC TREND"),
        ("hv_20d", "HV20"),
        ("put_call_ratio", "PC"),
        ("crowded_score", "CROWD"),
    ]
    present = [(src, lbl) for src, lbl in display_cols if src in df.columns]
    if not present:
        render_warning_card(
            st, title="No columns to display", body="Your filters returned nothing."
        )
        return

    rename_map = {src: lbl for src, lbl in present}
    table = df[[src for src, _ in present]].rename(columns=rename_map).copy()
    if "IV" in table.columns and "HV20" in table.columns:
        table["SPREAD"] = (
            table["IV"].astype(float) - table["HV20"].astype(float)
        )
        # Reorder so SPREAD sits next to HV20 like the PDF shows.
        cols = list(table.columns)
        if "SPREAD" in cols:
            cols.remove("SPREAD")
            hv_idx = cols.index("HV20")
            cols.insert(hv_idx + 1, "SPREAD")
            table = table[cols]
    if "PERC" in table.columns:
        table = table.sort_values("PERC", ascending=False, na_position="last")
    table = table.reset_index(drop=True)

    # Sort indicator visible above the table — many users were unsure
    # which column drove the order. Click headers to re-sort.
    st.caption(f"Sorted by **PERC** (descending) · {len(table)} tickers · click any column header to re-sort")

    # Column configs — no explicit widths. Streamlit distributes space across
    # the visible columns, which means adding/removing one auto-rebalances.
    column_config: dict = {}
    if "TICKER" in table.columns:
        column_config["TICKER"] = st.column_config.TextColumn("TICKER", width="small")
    if "NAME" in table.columns:
        column_config["NAME"] = st.column_config.TextColumn("NAME", width="medium")
    if "SECTOR" in table.columns:
        column_config["SECTOR"] = st.column_config.TextColumn("SECTOR", width="small")
    if "IV" in table.columns:
        column_config["IV"] = st.column_config.NumberColumn(
            "IV",
            format="%.1f%%",
            help="Current implied volatility (ATM, 30-day).",
        )
    if "1D D" in table.columns:
        column_config["1D D"] = st.column_config.NumberColumn(
            "1D Δ",
            format="%+.1f",
            help="1-day IV change in absolute points.",
        )
    if "30D D" in table.columns:
        column_config["30D D"] = st.column_config.NumberColumn(
            "30D Δ",
            format="%+.1f",
            help="30-day change in IV 30d. Positive = IV trending up (rising risk premium). Negative = IV falling (potential long-vol opportunity).",
        )
    if "PERC TREND" in table.columns:
        column_config["PERC TREND"] = st.column_config.NumberColumn(
            "Pct Trend",
            format="%+.0f",
            help="30-day change in IV Percentile. Negative = percentile falling (cheaper than a month ago). Positive = rising (getting richer).",
        )
    if "RANK" in table.columns:
        column_config["RANK"] = st.column_config.ProgressColumn(
            "RANK",
            help="IV Rank: where current IV sits in its 52-week min-max range (0-100).",
            format="%.0f",
            min_value=0,
            max_value=100,
        )
    if "PERC" in table.columns:
        column_config["PERC"] = st.column_config.ProgressColumn(
            "PERC",
            help="IV Percentile: fraction of past-year IV readings BELOW current (0-100).",
            format="%.0f",
            min_value=0,
            max_value=100,
        )
    if "QUALITY" in table.columns:
        column_config["QUALITY"] = st.column_config.ProgressColumn(
            "QUALITY",
            help=(
                "IV data quality score (0-100). Composite of contamination "
                "(IVR/IVP divergence), structural-break recency, and data "
                "sufficiency. ≥70 trade · 40-69 caution · <40 block."
            ),
            format="%.0f",
            min_value=0,
            max_value=100,
        )
    if "HV20" in table.columns:
        column_config["HV20"] = st.column_config.NumberColumn(
            "HV 20d",
            format="%.1f%%",
            help="20-day close-to-close historical volatility.",
        )
    if "SPREAD" in table.columns:
        column_config["SPREAD"] = st.column_config.NumberColumn(
            "SPREAD",
            format="%+.1f",
            help="IV − HV. Positive: options look rich. Negative: options look cheap.",
        )
    if "PC" in table.columns:
        column_config["PC"] = st.column_config.NumberColumn(
            "PC",
            format="%.2f",
            help="Put/Call volume ratio. >1 = more put volume, <1 = more call volume.",
        )
    if "CROWD" in table.columns:
        column_config["CROWD"] = st.column_config.ProgressColumn(
            "CROWD",
            help=(
                "Crowded score 0-100: composite of PCR z, OI z, volume z, "
                "IV-HV spread z. 50 = neutral, 80+ = extreme consensus / "
                "high reversal risk."
            ),
            format="%.0f",
            min_value=0,
            max_value=100,
        )

    selection = st.dataframe(
        table,
        width='stretch',
        hide_index=True,
        column_config=column_config,
        on_select="rerun",
        selection_mode="single-row",
        key="scan_table",
        height=640,
    )

    # CSV export — lets traders snapshot the current filtered view for
    # external analysis or sharing. Mirrors the visible table exactly.
    csv_bytes = table.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Export CSV",
        data=csv_bytes,
        file_name=f"volscope_scan_{date.today().isoformat()}.csv",
        mime="text/csv",
        key="scan_csv_export",
        help="Download the currently-filtered Scanner view as CSV.",
    )

    # Row-click navigation.
    rows = getattr(selection, "selection", None)
    selected_row_idx: list[int] = []
    if rows is not None:
        try:
            selected_row_idx = list(getattr(rows, "rows", []) or [])
        except Exception:
            selected_row_idx = []
    if selected_row_idx and "TICKER" in table.columns:
        picked_ticker = str(table.iloc[selected_row_idx[0]]["TICKER"])
        # v0.9.8 Phase C — route through NavIntent so SSOT history,
        # URL sync, and toast feedback all fire.
        try:
            from volscope.ui.components.navigation import NavIntent, nav_to
            nav_to(NavIntent(
                page="Scope", ticker=picked_ticker, source="Scanner",
            ))
        except Exception:                                          # noqa: BLE001
            # Fallback to legacy direct mutation if nav layer breaks
            st.session_state["selected_ticker"] = picked_ticker
            st.session_state["active_page"] = "Scope"
        st.rerun()

    # Explanation strip at the bottom — users need to know what the columns
    # mean without hovering on each header.
    with st.expander("How to read this table", expanded=False):
        st.markdown(
            """
| Column | What it means |
|---|---|
| **IV** | Current implied volatility from the 30-day ATM options (self-computed, not Yahoo's column). |
| **1D Δ** | One-day change in IV in absolute percentage points. |
| **30D Δ** | 30-day change in IV 30d. Positive = IV trending up (option sellers winning). Negative = IV falling — could be a long-vol setup if near a floor. |
| **Pct Trend** | 30-day change in IV Percentile. Negative = percentile has been falling (getting cheaper vs history). |
| **RANK** | IV Rank: where IV sits in its 52-week min-max range. 0 = at the floor, 100 = at the ceiling. |
| **PERC** | IV Percentile: what fraction of past-year IV days had a LOWER IV than today. 0 = today is the lowest, 100 = today is the highest. |
| **HV 20d** | 20-day close-to-close realized volatility. |
| **SPREAD** | IV − HV. Positive = options rich vs realized, negative = options cheap. |
| **PC** | Put/Call volume ratio. >1 indicates put-heavy flow. |
| **CROWD** | 0-100 composite of positioning indicators. See the Discover page's Crowded Trades panel for the full breakdown. |

**Rank vs Percentile — what's the difference?**
- **Rank** is normalized to the *range*: if the 52-week range was 10%-50%, then IV=30 is rank 50.
- **Percentile** is normalized to the *distribution*: if 80% of trading days in the past year had IV below 30, percentile is 80.

Two tickers can have the same Rank but very different Percentiles, and vice versa.
A huge range with IV sitting near the middle → medium Rank, but if most days clustered at
the low end, the Percentile is HIGH — meaning today is unusual vs typical history.
            """
        )

    # v0.9.7 — cross-page weave footer (master plan §4)
    from volscope.ui.components.next_step import render_next_step_footer
    render_next_step_footer(st, page='Scanner')
