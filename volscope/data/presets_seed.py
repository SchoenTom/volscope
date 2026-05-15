"""
Idempotent seeder for Tom's three starter presets.

Run with:

    python -m volscope.data.presets_seed

The script touches no other tables. JD's strike is auto-derived from
the most recent close ×1.10 rounded to the nearest whole dollar —
that's a typical OTM LEAPS pick and lets the preset adapt without
manual edits when the seed runs again later.
"""
from __future__ import annotations

import logging
import sys

from volscope.data.database import VolScopeDB
from volscope.data.presets import (
    ScalingTranche,
    StrategyPreset,
    upsert_preset,
)

log = logging.getLogger(__name__)


def _jd_strike(db) -> int:
    """Pick JD strike as round(latest_close * 1.10). Fallback 35 when no data."""
    try:
        hist = db.get_ticker_history("JD")
        if hist is not None and not hist.empty and "spot_price" in hist.columns:
            non_null = hist["spot_price"].dropna()
            if not non_null.empty:
                spot = float(non_null.iloc[-1])
                return int(round(spot * 1.10))
    except Exception as exc:
        log.debug("JD spot lookup failed: %s", exc)
    return 35


def build_presets(db) -> list[StrategyPreset]:
    """Construct the three Phase-6 starter presets."""
    return [
        StrategyPreset(
            id="pypl-long-call-80-jan2029",
            ticker="PYPL",
            strategy_name="Long Call",
            legs_spec={"strike": 80.0, "expiry": "2029-01-19", "dte": 730},
            thesis=(
                "IV Rank 2 / IV Percentile 1. Options at the absolute annual "
                "trough. Long-dated LEAPS call on a PYPL recovery setup."
            ),
            scaling_plan=[
                ScalingTranche("entry now",          0.33, "first tranche on signal"),
                ScalingTranche("PYPL < $60",         0.33, "second tranche on drawdown"),
                ScalingTranche("VIX > 25",           0.34, "macro stress add"),
            ],
            notes="2026-05-11 seed",
        ),
        StrategyPreset(
            id="ewz-long-call-50-jan2028",
            ticker="EWZ",
            strategy_name="Long Call",
            legs_spec={"strike": 50.0, "expiry": "2028-01-21", "dte": 540},
            thesis=(
                "IV Rank 3 — current IV 31.5 % vs. 1y mean 43.1 %. "
                "Brazil exposure with cheap vol premium."
            ),
            scaling_plan=[
                ScalingTranche("entry now",   0.50, "half size on signal"),
                ScalingTranche("EWZ < $25",   0.50, "double down on weakness"),
            ],
            notes="2026-05-11 seed",
        ),
        StrategyPreset(
            id="jd-long-call-otm-jan",
            ticker="JD",
            strategy_name="Long Call",
            legs_spec={"strike": _jd_strike(db), "expiry": "auto-leaps", "dte": 540},
            thesis=(
                "China-ADR vol setup. Strike and expiry resolved at seed-time "
                "from current spot (× 1.10 OTM, next January LEAPS ≥ 18 m)."
            ),
            scaling_plan=[
                ScalingTranche("entry now",         0.40, "starter"),
                ScalingTranche("-15 % drawdown",    0.30, "scale into weakness"),
                ScalingTranche("-25 % drawdown",    0.30, "max size"),
            ],
            notes="2026-05-11 seed",
        ),
    ]


def seed(db: VolScopeDB | None = None) -> int:
    """Insert any missing starter presets. Returns the count of new rows."""
    own = db is None
    db = db or VolScopeDB()
    try:
        before = len(db.con.execute(
            "SELECT id FROM strategy_presets",
        ).fetchdf())
        for preset in build_presets(db):
            upsert_preset(db, preset, overwrite=False)
        after = len(db.con.execute(
            "SELECT id FROM strategy_presets",
        ).fetchdf())
        added = after - before
        log.info("Seeded %d preset(s) — total now %d.", added, after)
        return added
    finally:
        if own:
            db.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    added = seed()
    print(f"presets seeded: +{added}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
