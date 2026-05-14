"""Capital flow proxy analytics — 5 smart-money signals from public options data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


def _rolling_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    """Rolling z-score vs trailing `window`-period mean/std. Returns NaN when std==0."""
    s = series.astype(float)
    mean = s.rolling(window, min_periods=3).mean()
    std = s.rolling(window, min_periods=3).std(ddof=1)
    return (s - mean) / std.replace(0.0, np.nan)


def _z_to_score(z: float) -> float:
    """Map signed z-score to 0-100 via smooth ±3σ clip (mirrors crowded_trades pattern)."""
    if np.isnan(z):
        return 50.0
    clipped = max(-3.0, min(3.0, float(z)))
    return (clipped + 3.0) / 6.0 * 100.0


@dataclass(frozen=True)
class FlowDivergence:
    sector: str
    date: object
    flow_score: float
    flow_change_5d: float
    price_change_5d: Optional[float]
    signal: str  # "ACCUMULATION" | "DISTRIBUTION" | "NEUTRAL"


_COMPONENT_COLS = ["oi_change_z", "vol_oi_ratio_z", "pcr_shift_z", "iv_hv_div_z", "cluster_z"]
_OUT_COLS = ["sector", "date"] + _COMPONENT_COLS


def compute_flow_components(
    sector_hist: pd.DataFrame,
    ticker_hist_map: Optional[dict[str, pd.DataFrame]] = None,
    window: int = 20,
) -> pd.DataFrame:
    """
    Compute 5 capital flow proxy components per (sector, date).

    All components expressed as rolling z-scores so they are dimensionless and
    comparable across sectors with different absolute vol levels.

    Components:
        oi_change_z    — rate of OI growth (d/dt of total_oi), z-scored rolling
        vol_oi_ratio_z — Volume/OI ratio, negated (low ratio = patient institutional flow)
        pcr_shift_z    — PCR z-score vs rolling mean (put buying = directional flow)
        iv_hv_div_z    — IV-HV divergence z-score (IV rising while HV flat = front-running)
        cluster_z      — count of tickers with abnormal volume, z-scored (cluster = coordinated)

    Requires sector_hist columns: sector, date, + some subset of
    total_oi, total_vol, mean_pcr, median_iv, median_hv.
    ticker_hist_map: {ticker: df} from db.get_recent_for_tickers() for cluster component.
    """
    if sector_hist is None or sector_hist.empty:
        return pd.DataFrame(columns=_OUT_COLS)
    if not {"sector", "date"}.issubset(sector_hist.columns):
        return pd.DataFrame(columns=_OUT_COLS)

    # Build volume-clustering lookup: {(sector, date): [ticker_vol_z_scores]}
    cluster_lookup: dict[tuple, list[float]] = {}
    for ticker, tdf in (ticker_hist_map or {}).items():
        if tdf is None or tdf.empty:
            continue
        if "sector" not in tdf.columns or "date" not in tdf.columns:
            continue
        tdf = tdf.copy().sort_values("date").reset_index(drop=True)
        if "total_call_volume" in tdf.columns and "total_put_volume" in tdf.columns:
            vol_ser = (
                tdf["total_call_volume"].fillna(0) + tdf["total_put_volume"].fillna(0)
            ).astype(float)
        elif "total_open_interest" in tdf.columns:
            vol_ser = tdf["total_open_interest"].astype(float)
        else:
            continue
        vol_z = _rolling_zscore(vol_ser, window)
        for i, row in tdf.iterrows():
            sec = row.get("sector")
            if sec is None or (isinstance(sec, float) and np.isnan(sec)):
                continue
            z_val = vol_z.iloc[i]
            if pd.isna(z_val):
                continue
            key = (str(sec), row["date"])
            cluster_lookup.setdefault(key, []).append(float(z_val))

    out_frames: list[pd.DataFrame] = []
    for sector, group in sector_hist.groupby("sector", sort=False):
        g = group.sort_values("date").copy().reset_index(drop=True)
        sector_str = str(sector)

        # 1. OI change rate
        if "total_oi" in g.columns:
            oi_change = g["total_oi"].astype(float).diff(1)
            g["oi_change_z"] = _rolling_zscore(oi_change, window)
        else:
            g["oi_change_z"] = np.nan

        # 2. Vol/OI ratio (negated: lower ratio → more institutional)
        if "total_vol" in g.columns and "total_oi" in g.columns:
            oi = g["total_oi"].astype(float).replace(0.0, np.nan)
            ratio = g["total_vol"].astype(float) / oi
            g["vol_oi_ratio_z"] = -_rolling_zscore(ratio, window)
        else:
            g["vol_oi_ratio_z"] = np.nan

        # 3. PCR shift
        if "mean_pcr" in g.columns:
            g["pcr_shift_z"] = _rolling_zscore(g["mean_pcr"].astype(float), window)
        else:
            g["pcr_shift_z"] = np.nan

        # 4. IV-HV divergence
        if "median_iv" in g.columns and "median_hv" in g.columns:
            div = g["median_iv"].astype(float) - g["median_hv"].astype(float)
            g["iv_hv_div_z"] = _rolling_zscore(div, window)
        else:
            g["iv_hv_div_z"] = np.nan

        # 5. Volume clustering
        cluster_counts = []
        for _, row in g.iterrows():
            key = (sector_str, row["date"])
            zs = cluster_lookup.get(key, [])
            cluster_counts.append(float(sum(1 for z in zs if z > 2.0)) if zs else np.nan)

        cluster_series = pd.Series(cluster_counts, index=g.index)
        non_null = cluster_series.dropna()
        if len(non_null) >= 3:
            g["cluster_z"] = _rolling_zscore(cluster_series, window)
        else:
            g["cluster_z"] = np.nan

        out_frames.append(g[_OUT_COLS])

    if not out_frames:
        return pd.DataFrame(columns=_OUT_COLS)
    return pd.concat(out_frames, ignore_index=True).sort_values(["sector", "date"]).reset_index(drop=True)


def compute_flow_score(components: pd.DataFrame) -> pd.DataFrame:
    """
    Compute composite flow score (0-100) per (sector, date).

    50 = neutral (all components at their rolling mean).
    > 50 = above-average institutional flow activity.
    < 50 = below-average / retail-dominated.

    Available z-score columns are averaged after mapping each through _z_to_score.
    Missing components are skipped (not forced to 50) so partial data still works.
    """
    if components is None or components.empty:
        return pd.DataFrame(columns=["sector", "date", "flow_score"])

    present_z_cols = [c for c in _COMPONENT_COLS if c in components.columns]
    if not present_z_cols:
        return pd.DataFrame(columns=["sector", "date", "flow_score"])

    def _row_score(row: pd.Series) -> float:
        vals = [_z_to_score(v) for v in row[present_z_cols] if not np.isnan(v)]
        return float(np.mean(vals)) if vals else 50.0

    out = components[["sector", "date"]].copy()
    out["flow_score"] = components.apply(_row_score, axis=1)
    return out.sort_values(["sector", "date"]).reset_index(drop=True)


def detect_flow_divergence(
    flow_df: pd.DataFrame,
    sector_hist: Optional[pd.DataFrame] = None,
    flow_window: int = 5,
    min_flow_rise: float = 5.0,
    max_price_change: float = 1.0,
) -> list[FlowDivergence]:
    """
    Detect accumulation/distribution signals: flow moving but price not.

    ACCUMULATION: flow_score rose >= min_flow_rise pts in `flow_window` periods,
                  but sector median_iv price proxy changed <= max_price_change %.
    DISTRIBUTION: flow_score fell >= min_flow_rise pts, price change also small.

    `flow_df`: sector, date, flow_score.
    `sector_hist`: optional sector_daily with median_iv as a price-direction proxy.
    """
    if flow_df is None or flow_df.empty:
        return []

    results: list[FlowDivergence] = []

    for sector, grp in flow_df.groupby("sector", sort=False):
        g = grp.sort_values("date").reset_index(drop=True)
        if len(g) < flow_window + 1:
            continue

        latest = g.iloc[-1]
        earlier = g.iloc[-(flow_window + 1)]
        flow_now = float(latest["flow_score"])
        flow_prev = float(earlier["flow_score"])
        flow_change = flow_now - flow_prev

        if abs(flow_change) < min_flow_rise:
            continue

        # Price proxy from sector_hist median_iv
        price_change: Optional[float] = None
        if sector_hist is not None and not sector_hist.empty and "median_iv" in sector_hist.columns:
            sh = sector_hist[sector_hist["sector"] == sector].sort_values("date").reset_index(drop=True)
            if len(sh) >= flow_window + 1:
                iv_now = sh["median_iv"].iloc[-1]
                iv_prev = sh["median_iv"].iloc[-(flow_window + 1)]
                if pd.notna(iv_now) and pd.notna(iv_prev) and float(iv_prev) != 0.0:
                    price_change = (float(iv_now) - float(iv_prev)) / float(iv_prev) * 100.0

        price_quiet = price_change is None or abs(price_change) <= max_price_change
        if flow_change >= min_flow_rise and price_quiet:
            signal = "ACCUMULATION"
        elif flow_change <= -min_flow_rise and price_quiet:
            signal = "DISTRIBUTION"
        else:
            continue

        results.append(FlowDivergence(
            sector=str(sector),
            date=latest["date"],
            flow_score=round(flow_now, 1),
            flow_change_5d=round(flow_change, 1),
            price_change_5d=round(price_change, 2) if price_change is not None else None,
            signal=signal,
        ))

    return sorted(results, key=lambda d: abs(d.flow_change_5d), reverse=True)
