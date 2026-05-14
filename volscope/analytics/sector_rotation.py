"""Sector rotation analytics — regime classification, momentum, transition matrix."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SectorRegime:
    sector: str
    regime: str           # HOT / NEUTRAL / COLD
    regime_z: float
    trend: str            # HEATING / COOLING / STABLE
    momentum_5d: Optional[float]
    momentum_21d: Optional[float]
    current_perc: Optional[float]


def compute_sector_aggregates(daily_vol_df: pd.DataFrame) -> pd.DataFrame:
    """
    Group daily_vol rows by (sector, date) and return sector-level aggregates.

    Returns columns: sector, date, median_iv, median_perc, median_hv, mean_pcr,
    total_oi, total_vol, n_tickers.
    """
    _empty = pd.DataFrame(
        columns=["sector", "date", "median_iv", "median_perc", "median_hv",
                 "mean_pcr", "total_oi", "total_vol", "n_tickers"]
    )
    if daily_vol_df is None or daily_vol_df.empty:
        return _empty

    df = daily_vol_df.copy()
    if "sector" not in df.columns:
        df["sector"] = "Unknown"
    df["sector"] = df["sector"].fillna("Unknown")
    if "date" not in df.columns:
        return _empty

    def _agg(g: pd.DataFrame) -> pd.Series:
        call_vol = g["total_call_volume"].fillna(0).sum() if "total_call_volume" in g.columns else 0
        put_vol = g["total_put_volume"].fillna(0).sum() if "total_put_volume" in g.columns else 0
        return pd.Series({
            "median_iv": g["iv_30d"].median() if "iv_30d" in g.columns else np.nan,
            "median_perc": g["iv_percentile"].median() if "iv_percentile" in g.columns else np.nan,
            "median_hv": g["hv_20d"].median() if "hv_20d" in g.columns else np.nan,
            "mean_pcr": g["put_call_ratio"].mean() if "put_call_ratio" in g.columns else np.nan,
            "total_oi": int(g["total_open_interest"].fillna(0).sum()) if "total_open_interest" in g.columns else 0,
            "total_vol": int(call_vol + put_vol),
            "n_tickers": g["ticker"].nunique() if "ticker" in g.columns else len(g),
        })

    try:
        agg = df.groupby(["sector", "date"]).apply(_agg, include_groups=False).reset_index()
    except TypeError:
        agg = df.groupby(["sector", "date"]).apply(_agg).reset_index()

    return agg.sort_values(["sector", "date"]).reset_index(drop=True)


def compute_sector_momentum(
    agg: pd.DataFrame,
    windows: Optional[list[int]] = None,
) -> pd.DataFrame:
    """
    Add rolling momentum columns perc_delta_Nd for each window in `windows`.
    Computed per sector as the difference in median_perc over the window period.
    """
    if windows is None:
        windows = [5, 10, 21]
    if agg is None or agg.empty:
        return agg

    out_frames = []
    for _, group in agg.groupby("sector", sort=False):
        g = group.sort_values("date").copy()
        for w in windows:
            g[f"perc_delta_{w}d"] = g["median_perc"].diff(w)
        out_frames.append(g)

    if not out_frames:
        return agg
    return pd.concat(out_frames, ignore_index=True).sort_values(["sector", "date"])


def classify_sector_regime(
    agg: pd.DataFrame,
    lookback: int = 252,
) -> list[SectorRegime]:
    """
    Classify each sector's current regime as HOT / NEUTRAL / COLD.

    z-score > 1.0 → HOT, < -1.0 → COLD, else NEUTRAL.
    Trend uses the 5d perc_delta: > 2pt → HEATING, < -2pt → COOLING.
    Returns list sorted by regime_z descending (hottest first).
    """
    if agg is None or agg.empty:
        return []

    agg_mom = compute_sector_momentum(agg, windows=[5, 21])
    regimes: list[SectorRegime] = []

    for sector, group in agg_mom.groupby("sector"):
        g = group.sort_values("date")
        if g.empty:
            continue
        current_row = g.iloc[-1]
        current_perc = (
            float(current_row["median_perc"])
            if "median_perc" in current_row.index and pd.notna(current_row["median_perc"])
            else None
        )

        hist = g["median_perc"].dropna().tail(lookback)
        if len(hist) < 5 or current_perc is None:
            regime_z = 0.0
        else:
            mean = float(hist.mean())
            std = float(hist.std(ddof=1)) if len(hist) > 1 else 0.0
            regime_z = float((current_perc - mean) / std) if std > 0 else 0.0

        if regime_z > 1.0:
            regime = "HOT"
        elif regime_z < -1.0:
            regime = "COLD"
        else:
            regime = "NEUTRAL"

        def _get_mom(col: str) -> Optional[float]:
            if col in current_row.index and pd.notna(current_row[col]):
                return float(current_row[col])
            return None

        mom5 = _get_mom("perc_delta_5d")
        mom21 = _get_mom("perc_delta_21d")

        if mom5 is None:
            trend = "STABLE"
        elif mom5 > 2.0:
            trend = "HEATING"
        elif mom5 < -2.0:
            trend = "COOLING"
        else:
            trend = "STABLE"

        regimes.append(SectorRegime(
            sector=str(sector),
            regime=regime,
            regime_z=round(regime_z, 2),
            trend=trend,
            momentum_5d=round(mom5, 2) if mom5 is not None else None,
            momentum_21d=round(mom21, 2) if mom21 is not None else None,
            current_perc=round(current_perc, 1) if current_perc is not None else None,
        ))

    return sorted(regimes, key=lambda r: r.regime_z, reverse=True)


def compute_rotation_matrix(
    agg: pd.DataFrame,
    lag: int = 21,
) -> pd.DataFrame:
    """
    Compute Markov-like transition probability matrix between sector regimes.

    For each pair (leader, follower), estimates P(follower enters HOT within
    `lag` trading days after leader enters HOT). Returns a DataFrame where
    matrix.loc[leader, follower] is that probability.
    """
    if agg is None or agg.empty:
        return pd.DataFrame()

    regime_z: dict[str, pd.Series] = {}
    for sector, group in agg.groupby("sector"):
        g = group.sort_values("date").set_index("date")
        series = g["median_perc"].dropna()
        if len(series) < 10:
            continue
        mean = float(series.mean())
        std = float(series.std(ddof=1)) if len(series) > 1 else 1.0
        if std == 0:
            std = 1.0
        regime_z[str(sector)] = (series - mean) / std

    sector_list = sorted(regime_z.keys())
    if len(sector_list) < 2:
        return pd.DataFrame()

    all_dates = sorted(set().union(*[set(s.index) for s in regime_z.values()]))
    matrix: dict[str, dict[str, float]] = {s: {} for s in sector_list}

    for leader in sector_list:
        z_l = regime_z[leader].reindex(all_dates)
        hot_entries: list = []
        prev: Optional[float] = None
        for d in all_dates:
            cur = z_l.get(d)
            if cur is None or (isinstance(cur, float) and np.isnan(float(cur))):
                prev = None
                continue
            cur_f = float(cur)
            if prev is not None and prev <= 1.0 and cur_f > 1.0:
                hot_entries.append(d)
            prev = cur_f

        for follower in sector_list:
            if follower == leader:
                continue
            if not hot_entries:
                matrix[leader][follower] = 0.0
                continue
            z_f = regime_z[follower].reindex(all_dates)
            follow_count = 0
            for entry_date in hot_entries:
                idx = all_dates.index(entry_date)
                window = all_dates[idx + 1: idx + 1 + lag]
                prev_f_val = z_l.get(entry_date)
                prev_f = float(prev_f_val) if prev_f_val is not None and not np.isnan(float(prev_f_val)) else 0.0
                for wd in window:
                    v = z_f.get(wd)
                    if v is None or (isinstance(v, float) and np.isnan(float(v))):
                        continue
                    v_f = float(v)
                    if prev_f <= 1.0 and v_f > 1.0:
                        follow_count += 1
                        break
                    prev_f = v_f
            matrix[leader][follower] = follow_count / len(hot_entries)

    return pd.DataFrame(matrix).T.fillna(0.0)


def get_current_rotation_snapshot(
    regimes: list[SectorRegime],
    matrix: pd.DataFrame,
    top_n: int = 3,
) -> list[dict]:
    """
    Identify currently active (HOT or HEATING) sectors and predict successors.

    Returns dicts: {leader, leader_regime, follower, probability, lead_days_estimate}.
    """
    if not regimes or matrix is None or matrix.empty:
        return []

    leaders = [r for r in regimes if r.regime == "HOT" or r.trend == "HEATING"]
    if not leaders:
        leaders = sorted(regimes, key=lambda r: r.momentum_5d or 0.0, reverse=True)[:2]

    predictions: list[dict] = []
    for leader_r in leaders:
        leader = leader_r.sector
        if leader not in matrix.index:
            continue
        row = matrix.loc[leader].drop(leader, errors="ignore")
        if row.empty:
            continue
        for follower, prob in row.sort_values(ascending=False).head(top_n).items():
            if float(prob) < 0.1:
                continue
            predictions.append({
                "leader": leader,
                "leader_regime": leader_r.regime,
                "follower": str(follower),
                "probability": round(float(prob), 2),
                "lead_days_estimate": 21,
            })

    return sorted(predictions, key=lambda p: p["probability"], reverse=True)
