"""
Aggregate daily_vol into sector_daily and classify regimes.

Run with: python scripts/sector_aggregate.py
Or via:   make sectors
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # v0.2.0 reorg: repo root is 3 levels up
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from volscope.data.database import VolScopeDB
from volscope.analytics.sector_rotation import (
    compute_sector_aggregates,
    classify_sector_regime,
)


def run(db: VolScopeDB) -> int:
    """Compute sector aggregates from daily_vol and upsert into sector_daily. Returns rows written."""
    print("Loading daily_vol sector data...")
    df = db.get_all_vol_history_for_sectors()
    if df.empty:
        print("No sector data in daily_vol. Run seed/scrape first.")
        return 0

    # Need ticker column for n_tickers count; fetch it
    full_df = db.con.execute(
        "SELECT date, sector, ticker, iv_30d, iv_percentile, hv_20d, "
        "put_call_ratio, total_call_volume, total_put_volume, total_open_interest "
        "FROM daily_vol WHERE sector IS NOT NULL ORDER BY date, sector"
    ).fetchdf()

    print(f"  {len(full_df)} daily_vol rows across {full_df['sector'].nunique()} sectors.")
    agg = compute_sector_aggregates(full_df)
    if agg.empty:
        print("Aggregation produced no rows.")
        return 0

    regimes = classify_sector_regime(agg)
    regime_map = {r.sector: (r.regime, r.regime_z) for r in regimes}

    rows_written = 0
    for _, row in agg.iterrows():
        sector = str(row["sector"])
        regime, regime_z = regime_map.get(sector, ("NEUTRAL", 0.0))
        db.upsert_sector_daily(
            sector=sector,
            date=row["date"],
            median_iv=row.get("median_iv"),
            median_perc=row.get("median_perc"),
            median_hv=row.get("median_hv"),
            mean_pcr=row.get("mean_pcr"),
            total_oi=int(row.get("total_oi") or 0),
            total_vol=int(row.get("total_vol") or 0),
            n_tickers=int(row.get("n_tickers") or 0),
            regime=regime,
            regime_z=regime_z,
        )
        rows_written += 1

    print(f"  Upserted {rows_written} sector_daily rows.")
    return rows_written


if __name__ == "__main__":
    with VolScopeDB() as db:
        written = run(db)
    sys.exit(0 if written >= 0 else 1)
