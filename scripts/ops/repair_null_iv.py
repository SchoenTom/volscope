"""Repair tickers whose latest daily_vol row has iv_30d=NULL.

Root cause: when daily_scrape's chain fetch fails or is sanity-rejected,
the row gets upserted with iv_30d=NULL — overwriting yesterday's clean
value. daily_scrape.py now has a fallback chain (prior-day -> hv-yz
proxy -> hv-cc proxy) but the in-DB damage from prior runs needs
explicit repair.

Strategy:
  1. Find all (ticker, latest_date) pairs where iv_30d IS NULL but
     hv_yz_20d or hv_20d is populated.
  2. For each, look back up to 30 trading days for the most recent
     non-null iv_30d.
  3. Write that value (or HV-YZ × 1.12 proxy if no history) into the
     NULL row, recompute iv_rank, iv_percentile, iv_hv_spread,
     iv_hv_spread_matched.

Idempotent — running it twice writes the same values the second time.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from volscope.analytics.vol_metrics import (  # noqa: E402
    iv_hv_spread, iv_percentile, iv_rank,
)
from volscope.config import DEFAULT_RANK_LOOKBACK  # noqa: E402
from volscope.data.database import VolScopeDB  # noqa: E402

log = logging.getLogger("volscope.repair_iv")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_VRP_MULT = 1.12


def _previous_iv(db: VolScopeDB, ticker: str) -> float | None:
    df = db.get_ticker_history(ticker)
    if df.empty or "iv_30d" not in df.columns:
        return None
    non_null = df["iv_30d"].dropna()
    return float(non_null.iloc[-1]) if not non_null.empty else None


def _iv_history(db: VolScopeDB, ticker: str) -> list[float]:
    df = db.get_ticker_history(ticker)
    if df.empty or "iv_30d" not in df.columns:
        return []
    return df["iv_30d"].dropna().tail(DEFAULT_RANK_LOOKBACK).tolist()


def main() -> int:
    db = VolScopeDB()

    null_rows = db.con.execute(
        """
        SELECT t.ticker, t.date, t.hv_20d, t.hv_yz_20d, t.hv_yz_30d
        FROM daily_vol t
        JOIN (
            SELECT ticker, MAX(date) AS max_date
            FROM daily_vol
            GROUP BY ticker
        ) mx ON t.ticker = mx.ticker AND t.date = mx.max_date
        WHERE t.iv_30d IS NULL
        """
    ).fetchall()

    log.info("Found %d tickers with NULL iv_30d on latest row", len(null_rows))
    repaired = 0
    for ticker, dt, hv_20, hv_yz_20, hv_yz_30 in null_rows:
        prev = _previous_iv(db, ticker)
        source = ""
        iv_val: float | None = None
        if prev is not None:
            iv_val = prev
            source = "prior-day"
        elif hv_yz_20 is not None:
            iv_val = float(hv_yz_20) * _VRP_MULT
            source = "hv-yz-proxy"
        elif hv_20 is not None:
            iv_val = float(hv_20) * _VRP_MULT
            source = "hv-cc-proxy"
        else:
            log.warning("Cannot repair %s — no IV history and no HV either", ticker)
            continue

        hist = _iv_history(db, ticker)
        if iv_val is not None and not (prev is not None and abs(iv_val - prev) < 1e-9):
            hist = (hist + [iv_val])[-DEFAULT_RANK_LOOKBACK:]

        rank = iv_rank(iv_val, hist) if len(hist) > 5 else None
        pct = iv_percentile(iv_val, hist) if len(hist) > 5 else None
        spread_info = iv_hv_spread(iv_val, float(hv_20)) if hv_20 is not None else {}
        spread = spread_info.get("spread")
        spread_matched = None
        if hv_yz_30 is not None:
            spread_matched = iv_val - float(hv_yz_30)

        # DuckDB rejects numpy scalars — cast to native Python types.
        def _py(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return v

        # upsert_daily roundtrips through INSERT and would re-bind any
        # existing numpy-typed columns (a separate DuckDB driver bug).
        # We don't need its merge logic here — only iv_30d-family
        # columns change, so direct UPDATE keeps everything else intact.
        db.con.execute(
            """
            UPDATE daily_vol
            SET iv_30d = ?,
                iv_rank = ?,
                iv_percentile = ?,
                iv_hv_spread = ?,
                iv_hv_spread_matched = ?
            WHERE ticker = ? AND date = ?
            """,
            [
                _py(iv_val), _py(rank), _py(pct),
                _py(spread), _py(spread_matched),
                ticker, dt,
            ],
        )
        repaired += 1
        log.info("Repaired %s @ %s: iv_30d=%.2f via %s", ticker, dt, iv_val, source)

    db.close()
    log.info("Repair complete: %d/%d rows fixed", repaired, len(null_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
