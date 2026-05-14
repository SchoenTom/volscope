"""IV-HV spread time-series utilities."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_iv_hv_timeseries(iv_series: pd.Series, hv_series: pd.Series) -> pd.DataFrame:
    """Return DataFrame with columns: iv, hv, spread, ratio, z_score (90-day rolling)."""
    df = pd.DataFrame({"iv": iv_series, "hv": hv_series}).dropna()
    if df.empty:
        return pd.DataFrame(columns=["iv", "hv", "spread", "ratio", "z_score"])
    df["spread"] = df["iv"] - df["hv"]
    df["ratio"] = np.where(df["hv"] > 0, df["iv"] / df["hv"], np.nan)
    roll = df["spread"].rolling(window=90, min_periods=20)
    mean = roll.mean()
    std = roll.std(ddof=1)
    df["z_score"] = (df["spread"] - mean) / std.replace(0, np.nan)
    return df


def detect_spread_extremes(
    spread_series: pd.Series, threshold_z: float = 2.0
) -> pd.DataFrame:
    """Return dates where |z-score of spread| > threshold."""
    s = spread_series.dropna()
    if s.empty:
        return pd.DataFrame(columns=["spread", "z_score", "direction"])
    mean = s.expanding(min_periods=30).mean()
    std = s.expanding(min_periods=30).std(ddof=1)
    z = (s - mean) / std.replace(0, np.nan)
    extreme_mask = z.abs() > threshold_z
    extremes = pd.DataFrame(
        {
            "spread": s[extreme_mask],
            "z_score": z[extreme_mask],
        }
    )
    extremes["direction"] = np.where(extremes["z_score"] > 0, "RICH", "CHEAP")
    return extremes
