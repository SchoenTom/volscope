"""Data sanity checks on the daily_vol table."""
from __future__ import annotations

import pandas as pd


def validate_iv(iv: float | None) -> bool:
    """IV must be a percentage in [1, 500] (annualized)."""
    if iv is None:
        return False
    try:
        v = float(iv)
    except (TypeError, ValueError):
        return False
    if pd.isna(v):
        return False
    return 1.0 <= v <= 500.0


def validate_daily_row(row: dict) -> list[str]:
    """Return list of human-readable problem strings, empty if row is clean."""
    problems: list[str] = []
    iv = row.get("iv_30d")
    if iv is not None and not validate_iv(iv):
        problems.append(f"iv_30d out of range: {iv}")
    hv = row.get("hv_20d")
    if hv is not None and (pd.isna(hv) or hv < 0 or hv > 500):
        problems.append(f"hv_20d out of range: {hv}")
    spot = row.get("spot_price")
    if spot is not None and (pd.isna(spot) or spot <= 0):
        problems.append(f"spot_price non-positive: {spot}")
    return problems


def find_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows duplicated on (ticker, date)."""
    if df.empty or "ticker" not in df.columns or "date" not in df.columns:
        return df.iloc[0:0]
    return df[df.duplicated(subset=["ticker", "date"], keep=False)]


def find_missing_dates(df: pd.DataFrame, expected_dates: list) -> list:
    """Given a df for a single ticker, return expected dates with no row."""
    if df.empty:
        return list(expected_dates)
    have = set(pd.to_datetime(df["date"]).dt.date)
    return [d for d in expected_dates if d not in have]
