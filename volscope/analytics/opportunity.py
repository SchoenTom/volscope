"""Opportunity scanners: cheapest vol, richest premium, daily outliers."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_sort(df: pd.DataFrame, col: str, ascending: bool) -> pd.DataFrame:
    if df.empty or col not in df.columns:
        return df
    return df.dropna(subset=[col]).sort_values(col, ascending=ascending)


def _cheap_context(row: pd.Series) -> str:
    """Build the short trader-facing rationale for a 'cheap' recommendation.

    Critically, we now flag tickers whose IV is genuinely at its annual
    floor: a 'percentile=5%' read is not the same as 'great entry' if the
    annual range is [10%, 12%] — there's no upside left. Owners explicitly
    flagged low-vol-area recs as the weakest signal in VolScope.
    """
    iv = row.get("iv_30d")
    perc = row.get("iv_percentile")
    if iv is None or perc is None or pd.isna(iv) or pd.isna(perc):
        return ""
    iv_f = float(iv)
    perc_f = float(perc)

    # Optional floor / ceiling info if the row has 52w extremes
    floor_warning = ""
    iv_low = row.get("iv_low52") if hasattr(row, "get") else None
    iv_high = row.get("iv_high52") if hasattr(row, "get") else None
    try:
        if iv_low is not None and iv_high is not None and not (pd.isna(iv_low) or pd.isna(iv_high)):
            lo = float(iv_low)
            hi = float(iv_high)
            iv_range = hi - lo
            if iv_range > 0:
                floor_distance = (iv_f - lo) / iv_range
                # Within 10% of the annual range from the floor → mostly no upside.
                if floor_distance < 0.10:
                    floor_warning = " · at annual floor — limited upside"
                elif floor_distance < 0.25:
                    floor_warning = " · near floor"
    except (TypeError, ValueError):
        pass

    remainder = max(0.0, min(100.0, 100.0 - perc_f))
    if remainder >= 90:
        return f"IV at {iv_f:.1f}% — cheaper than {remainder:.0f}% of past year · historical floor{floor_warning}"
    if remainder >= 70:
        return f"IV at {iv_f:.1f}% — cheaper than {remainder:.0f}% of past year{floor_warning}"
    return f"IV at {iv_f:.1f}% — quiet tape{floor_warning}"


def _rich_context(row: pd.Series) -> str:
    iv = row.get("iv_30d")
    perc = row.get("iv_percentile")
    if iv is None or perc is None or pd.isna(iv) or pd.isna(perc):
        return ""
    if perc >= 95:
        return f"IV at {iv:.1f}% — richer than {perc:.0f}% of past year · extreme premium"
    if perc >= 80:
        return f"IV at {iv:.1f}% — richer than {perc:.0f}% of past year"
    return f"IV at {iv:.1f}% — elevated"


def _compute_dual_score(row: pd.Series, want: str) -> float:
    """
    Dual-signal score combining IV percentile (vs own history) with IV-HV
    spread (vs realized vol). For 'cheap' we want LOW percentile AND NEGATIVE
    spread — the two signals pointing the same way. For 'rich' the opposite.

    Owner-flagged improvement (2026-05-01): a ticker can have a low
    percentile but already sit at its absolute 52w floor — there's no
    reversion-upside left. We use iv_rank (a 0-100 normalisation against
    the 52w min-max range) as a floor-distance proxy: rank < 10 means
    IV is in the bottom decile of its annual range. We penalise such
    tickers in the 'cheap' direction so the recommender stops surfacing
    'cheap percentile but at floor' false positives.

    Returns a float where *lower is better* for the chosen direction. Rows
    missing either signal get a large sentinel so they sort last.
    """
    perc = row.get("iv_percentile")
    iv = row.get("iv_30d")
    hv = row.get("hv_20d")
    if perc is None or iv is None or hv is None or any(
        pd.isna(x) for x in (perc, iv, hv)
    ):
        return 1e9
    spread = float(iv) - float(hv)
    perc = float(perc)

    if want == "cheap":
        # Penalise positive spread (options still look rich vs realized).
        spread_penalty = max(0.0, spread) * 5.0
        # Floor penalty — only applied to 'cheap' direction. Tickers near
        # their annual floor have no upside to a vega trade. Magnitude
        # tuned so that a rank-5 ticker pays a +20pt penalty (enough to
        # demote it below all percentile<25 candidates with rank>10).
        rank_obj = row.get("iv_rank")
        floor_penalty = 0.0
        if rank_obj is not None and not pd.isna(rank_obj):
            rank = float(rank_obj)
            if rank < 10.0:
                floor_penalty = (10.0 - rank) * 2.0       # up to +20
            elif rank < 25.0:
                floor_penalty = (25.0 - rank) * 0.5       # up to +7.5
        return perc + spread_penalty + floor_penalty

    # want == "rich": invert percentile (higher=better becomes lower=better)
    # and penalize NEGATIVE spread (options cheap vs realized).
    spread_penalty = max(0.0, -spread) * 5.0
    return (100.0 - perc) + spread_penalty


def find_cheapest_vol(latest_data: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """
    Top N tickers that are cheap by BOTH signals: low IV percentile and
    non-positive IV-HV spread. Cards that are only percentile-cheap but still
    have IV>HV rank below.
    """
    if latest_data.empty:
        return latest_data
    scored = latest_data.copy()
    scored["_dual_score"] = scored.apply(
        lambda r: _compute_dual_score(r, "cheap"), axis=1
    )
    out = scored.sort_values("_dual_score", ascending=True).head(n).copy()
    out = out.drop(columns=["_dual_score"])
    if "iv_percentile" in out.columns and "iv_30d" in out.columns:
        out["context"] = out.apply(_cheap_context, axis=1)
    return out


def find_richest_premium(latest_data: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """
    Top N tickers rich by BOTH signals: high IV percentile and positive
    IV-HV spread.
    """
    if latest_data.empty:
        return latest_data
    scored = latest_data.copy()
    scored["_dual_score"] = scored.apply(
        lambda r: _compute_dual_score(r, "rich"), axis=1
    )
    out = scored.sort_values("_dual_score", ascending=True).head(n).copy()
    out = out.drop(columns=["_dual_score"])
    if "iv_percentile" in out.columns and "iv_30d" in out.columns:
        out["context"] = out.apply(_rich_context, axis=1)
    return out


#: Day-over-day IV changes greater than this are flagged as data-source
#: artifacts. Single-day IV moves above 30 absolute points are almost always
#: the result of a seed-proxy row sitting next to a real-scrape row in the
#: same time series, not a real market move. Real market events (gap, earnings
#: announcement, flash crash) rarely push broad IV by more than 20 points in
#: a single session.
_DAILY_MOVE_ARTIFACT_THRESHOLD_ABS = 30.0
_DAILY_MOVE_ARTIFACT_THRESHOLD_REL = 1.5  # 150% relative change


def _looks_like_data_artifact(prev: float | None, curr: float | None) -> bool:
    """True if the prev→curr IV change looks like a data-source change,
    not a real market move."""
    if prev is None or curr is None or pd.isna(prev) or pd.isna(curr):
        return False
    if prev <= 0:
        return False
    abs_change = abs(curr - prev)
    rel_change = abs_change / prev
    return (
        abs_change > _DAILY_MOVE_ARTIFACT_THRESHOLD_ABS
        and rel_change > _DAILY_MOVE_ARTIFACT_THRESHOLD_REL
    )


def find_daily_outliers(
    latest_data: pd.DataFrame,
    prev_data: pd.DataFrame,
    n: int = 5,
    history: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """
    Top N tickers with the largest 1-day IV change, normalized by each ticker's
    own typical daily IV change (so a 5pt move on TSLA doesn't outrank a 5pt
    move on KO). If `history` is provided, normalization uses the std of that
    ticker's diff series; otherwise falls back to relative change.

    Rows whose prev→curr change looks like a data-source artifact (e.g. an
    old seed-proxy row next to a fresh scrape) are dropped entirely, not
    ranked. Surfacing a 58-point "mover" that's actually a data rotation is
    worse than showing nothing.
    """
    if latest_data.empty or prev_data.empty:
        return pd.DataFrame()
    if "ticker" not in latest_data.columns or "ticker" not in prev_data.columns:
        return pd.DataFrame()
    merged = latest_data.merge(
        prev_data[["ticker", "iv_30d"]].rename(columns={"iv_30d": "iv_30d_prev"}),
        on="ticker",
        how="inner",
    )
    merged["iv_change"] = merged["iv_30d"] - merged["iv_30d_prev"]

    # Drop rows that look like data artifacts BEFORE scoring.
    artifact_mask = merged.apply(
        lambda r: _looks_like_data_artifact(
            r.get("iv_30d_prev"), r.get("iv_30d")
        ),
        axis=1,
    )
    merged = merged[~artifact_mask].copy()

    def _score(row: pd.Series) -> float:
        change = row["iv_change"]
        if pd.isna(change):
            return float("nan")
        if history is not None:
            series = history.get(row["ticker"])
            if series is not None and len(series) > 5:
                diffs = pd.Series(series).diff().dropna()
                std = float(diffs.std(ddof=1)) if len(diffs) > 1 else 0.0
                if std > 0:
                    return float(abs(change) / std)
        prev = row["iv_30d_prev"]
        if prev and prev > 0:
            return float(abs(change) / prev)
        return float(abs(change))

    merged["iv_change_score"] = merged.apply(_score, axis=1)
    return (
        merged.dropna(subset=["iv_change_score"])
        .sort_values("iv_change_score", ascending=False)
        .head(n)
    )
