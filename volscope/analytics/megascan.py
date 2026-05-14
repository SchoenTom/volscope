"""
Mega-Scan analytics — universe-level rankings + KPIs + master export.

The single source of truth for the "Giga Screen" Mega-Scan page. All
rankings, KPI computations, and the 24-column master CSV are produced
here as pure functions — the UI layer is thin glue.

Six canonical rankings (one ``RankingSpec`` each):
  💎 CHEAPEST VOL    — lowest IV percentile, liquid only
  🔥 RICHEST PREMIUM  — highest IV percentile, liquid only
  ⚡ MOVERS UP        — biggest 1-day IV gain
  ⚡ MOVERS DOWN      — biggest 1-day IV loss
  🌐 CROWDED          — highest crowded-trade score
  🎯 HIGHEST EDGE     — highest composite Edge Score (long-vol)

Five hero KPIs:
  median IV percentile, top-cheap, top-rich, biggest mover, highest edge

Master CSV: 24 fixed columns documented inline; field-by-field-test-locked.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

import numpy as np
import pandas as pd


# ── Configuration ───────────────────────────────────────────────────────

# Liquidity threshold below which a row is excluded from "actionable"
# rankings (cheapest, richest, edge). Movers/Crowded keep them since
# illiquid spikes are themselves a signal.
_MIN_OI_LIQUID = 1000

# Max rows per ranking tile. Tiles render with overflow-y so the user
# can scroll through all 25 within the fixed-height card. 10 was too few
# (user feedback) — 25 lets the whole top-quartile show without paging.
_RANKING_N = 25


# ── Output types ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UniverseKPI:
    """One hero-strip tile."""
    label:    str
    value:    str
    sublabel: str
    color:    str
    target:   Optional[str] = None    # ticker for click-deep-link


@dataclass(frozen=True)
class RankingSpec:
    """One of the six canonical rankings on Mega-Scan.

    Held as a frozen dataclass so the spec table is read-only at module
    scope. Adding a 7th ranking requires an explicit code change here
    plus an updated test — by design, no runtime mutation.
    """
    title:        str          # display header, e.g. "💎 CHEAPEST VOL"
    accent_color: str
    sort_key:     str
    ascending:    bool
    filter_name:  str          # name of pre-filter (so tests can assert it)
    explain_col:  str          # which column carries the inline reason
    n:            int = _RANKING_N


# ── Pre-filters ────────────────────────────────────────────────────────

def _filter_liquid(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows with sufficient open interest."""
    if "total_open_interest" not in df.columns:
        return df
    oi = pd.to_numeric(df["total_open_interest"], errors="coerce").fillna(0)
    return df[oi >= _MIN_OI_LIQUID].copy()


def _filter_with_iv(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows with non-null iv_30d."""
    if "iv_30d" not in df.columns:
        return df
    return df[pd.to_numeric(df["iv_30d"], errors="coerce").notna()].copy()


_FILTERS: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    "liquid":  _filter_liquid,
    "with_iv": _filter_with_iv,
}


# ── Canonical rankings ─────────────────────────────────────────────────

RANKINGS: tuple[RankingSpec, ...] = (
    RankingSpec("💎 CHEAPEST VOL",   "#00d4aa", "iv_percentile", True,  "liquid",  "context", _RANKING_N),
    RankingSpec("🔥 RICHEST PREMIUM", "#ff4466", "iv_percentile", False, "liquid",  "context", _RANKING_N),
    RankingSpec("⚡ MOVERS UP",       "#ff9f43", "iv_change_1d",  False, "with_iv", "delta_str", _RANKING_N),
    RankingSpec("⚡ MOVERS DOWN",     "#7db4ff", "iv_change_1d",  True,  "with_iv", "delta_str", _RANKING_N),
    RankingSpec("🌐 CROWDED",         "#ffd700", "crowded_score", False, "with_iv", "crowded_str", _RANKING_N),
    RankingSpec("🎯 HIGHEST EDGE",    "#00d4aa", "edge_score",    False, "liquid",  "edge_str", _RANKING_N),
)


def apply_ranking(df: pd.DataFrame, spec: RankingSpec) -> pd.DataFrame:
    """Filter + sort according to a RankingSpec; return the top N rows.

    Pure function — does not mutate the input. Returns a fresh copy.
    """
    if df is None or df.empty:
        return df.iloc[0:0].copy() if df is not None else pd.DataFrame()
    if spec.sort_key not in df.columns:
        return df.iloc[0:0].copy()
    filt = _FILTERS.get(spec.filter_name)
    work = filt(df) if filt else df.copy()
    if work.empty or spec.sort_key not in work.columns:
        return work.iloc[0:0].copy()
    work = work.dropna(subset=[spec.sort_key])
    if work.empty:
        return work
    return work.sort_values(spec.sort_key, ascending=spec.ascending).head(spec.n).copy()


# ── Hero KPIs ──────────────────────────────────────────────────────────

def universe_kpis(df: pd.DataFrame) -> list[UniverseKPI]:
    """Five hero-strip tiles. Each tile is independently safe — missing
    fields produce a "—" value rather than raising.
    """
    out: list[UniverseKPI] = []

    # 1. Median IV percentile across the universe
    if "iv_percentile" in df.columns and not df.empty:
        med = float(pd.to_numeric(df["iv_percentile"], errors="coerce").median())
        n = int(df["iv_percentile"].notna().sum()) if "iv_percentile" in df.columns else 0
        out.append(UniverseKPI(
            label="MEDIAN PCT", value=f"{med:.0f}",
            sublabel=f"of {n} tickers", color="#7db4ff",
        ))
    else:
        out.append(UniverseKPI(label="MEDIAN PCT", value="—", sublabel="no data", color="#8a8f9e"))

    # 2. Top cheap (lowest percentile, liquid)
    cheap = apply_ranking(df, RANKINGS[0])
    if not cheap.empty:
        row = cheap.iloc[0]
        out.append(UniverseKPI(
            label="TOP CHEAP", value=str(row["ticker"]),
            sublabel=f"perc {float(row['iv_percentile']):.0f}",
            color="#00d4aa", target=str(row["ticker"]),
        ))
    else:
        out.append(UniverseKPI(label="TOP CHEAP", value="—", sublabel="no liquid", color="#8a8f9e"))

    # 3. Top rich
    rich = apply_ranking(df, RANKINGS[1])
    if not rich.empty:
        row = rich.iloc[0]
        out.append(UniverseKPI(
            label="TOP RICH", value=str(row["ticker"]),
            sublabel=f"perc {float(row['iv_percentile']):.0f}",
            color="#ff4466", target=str(row["ticker"]),
        ))
    else:
        out.append(UniverseKPI(label="TOP RICH", value="—", sublabel="no liquid", color="#8a8f9e"))

    # 4. Biggest mover (absolute 1d Δ-IV)
    if "iv_change_1d" in df.columns and not df.empty:
        d = df.copy()
        d["abs_change"] = pd.to_numeric(d["iv_change_1d"], errors="coerce").abs()
        d = d.dropna(subset=["abs_change"])
        if not d.empty:
            top = d.sort_values("abs_change", ascending=False).iloc[0]
            chg = float(top["iv_change_1d"])
            out.append(UniverseKPI(
                label="BIG MOVER", value=str(top["ticker"]),
                sublabel=f"Δ-IV {chg:+.1f}pt",
                color="#ff9f43", target=str(top["ticker"]),
            ))
        else:
            out.append(UniverseKPI(label="BIG MOVER", value="—", sublabel="no Δ data", color="#8a8f9e"))
    else:
        out.append(UniverseKPI(label="BIG MOVER", value="—", sublabel="no Δ data", color="#8a8f9e"))

    # 5. Highest edge (composite)
    edge = apply_ranking(df, RANKINGS[5])
    if not edge.empty:
        row = edge.iloc[0]
        score = pd.to_numeric(row.get("edge_score"), errors="coerce")
        out.append(UniverseKPI(
            label="HIGHEST EDGE", value=str(row["ticker"]),
            sublabel=f"score {float(score):.0f}" if pd.notna(score) else "—",
            color="#00d4aa", target=str(row["ticker"]),
        ))
    else:
        out.append(UniverseKPI(label="HIGHEST EDGE", value="—", sublabel="no edge data", color="#8a8f9e"))

    return out


# ── Master CSV — 24 columns, exact ────────────────────────────────────

# Locked column list. Adding a column requires explicit edit + matching
# test update. The order is the export contract.
MASTER_CSV_COLUMNS: tuple[str, ...] = (
    "ticker", "sector", "company",
    "iv_30d", "iv_60d", "iv_90d", "iv_180d", "iv_skew_25d",
    "hv_20d", "hv_60d",
    "iv_rank", "iv_percentile",
    "iv_change_1d", "iv_change_30d", "perc_trend_30d",
    "put_call_ratio", "total_open_interest",
    "total_call_volume", "total_put_volume",
    "crowded_score", "flow_score",
    "edge_score", "edge_components_json",
    "quality_overall",
)


def build_master_csv(df: pd.DataFrame) -> str:
    """Render the universe DataFrame as the 24-column master CSV.

    Missing columns are filled with empty values — the schema is fixed
    even when the source data is partial. Column order is locked.

    Returns
    -------
    str
        CSV text content (UTF-8, comma-separated, header included).
    """
    out = pd.DataFrame()
    for col in MASTER_CSV_COLUMNS:
        if col in df.columns:
            out[col] = df[col]
        else:
            out[col] = pd.NA
    buf = io.StringIO()
    out.to_csv(buf, index=False)
    return buf.getvalue()


# ── Page-data prep — single entry point used by both UI and perf test ──

@dataclass(frozen=True)
class PageData:
    """All data needed to render the Mega-Scan page in one pass.

    Computed once per render so no in-page recomputation. The perf SLA
    test runs ``build_full_page_data`` against a 300-ticker fixture and
    asserts < 1500ms p95.
    """
    kpis:       list[UniverseKPI]
    rankings:   list[tuple[RankingSpec, pd.DataFrame]]
    scatter_df: pd.DataFrame
    csv_text:   str


def _build_scatter_df(df: pd.DataFrame, max_dots: int = 500) -> pd.DataFrame:
    """Universe scatter: x=iv_percentile, y=iv30-hv20, color=sector, size=OI.

    Caps at ``max_dots`` — when over, downsamples by stratified sector
    sample so every sector remains visible.
    """
    needed = {"iv_percentile", "iv_30d", "hv_20d"}
    if df.empty or not needed.issubset(df.columns):
        return pd.DataFrame(columns=["ticker", "sector", "x", "y", "size", "company"])
    work = df.copy()
    work["x"]    = pd.to_numeric(work["iv_percentile"], errors="coerce")
    work["y"]    = pd.to_numeric(work["iv_30d"], errors="coerce") - pd.to_numeric(work["hv_20d"], errors="coerce")
    work["size"] = pd.to_numeric(work.get("total_open_interest", 0), errors="coerce").fillna(0).clip(lower=0)
    work = work.dropna(subset=["x", "y"])
    keep_cols = ["ticker", "sector", "x", "y", "size"]
    if "company_name" in work.columns:
        work["company"] = work["company_name"].fillna("")
        keep_cols.append("company")
    else:
        work["company"] = ""
        keep_cols.append("company")
    work = work[keep_cols]
    if len(work) <= max_dots:
        return work
    # Stratified per-sector downsample
    if "sector" in work.columns:
        per_sector = max(1, max_dots // max(1, work["sector"].nunique()))
        return work.groupby("sector", group_keys=False).head(per_sector).reset_index(drop=True)
    return work.head(max_dots).reset_index(drop=True)


def build_full_page_data(df: pd.DataFrame) -> PageData:
    """Compose all Mega-Scan render data. Pure, deterministic, cached-friendly.

    Used by:
      - the UI render path
      - the perf SLA test (no streamlit dependency)
    """
    kpis = universe_kpis(df)
    rankings = [(spec, apply_ranking(df, spec)) for spec in RANKINGS]
    scatter = _build_scatter_df(df)
    csv_text = build_master_csv(df)
    return PageData(
        kpis=kpis,
        rankings=rankings,
        scatter_df=scatter,
        csv_text=csv_text,
    )
