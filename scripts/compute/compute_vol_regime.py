#!/usr/bin/env python3
"""
Nightly job — compute 6-state Vol Regime for every ticker + persist.

Workflow
========
1. Pull ^VIX history once (the broad-market Crisis-trigger feed).
2. For every ticker with > 30 rows of daily_vol history:
   a. Build the 6-feature matrix via
      ``compute_vol_regime_features``.
   b. Fit a per-ticker GaussianHMM (5 learned states).
   c. ``predict_vol_regime`` → most-likely state + posteriors.
   d. ``apply_crisis_override`` → inject CRISIS state when VIX > 40
      or |IV-HV spread| > 15 vol points.
3. Upsert the most recent row's regime + 6 posteriors back into
   ``daily_vol`` via ``VolScopeDB.upsert_daily``.

Why per-ticker training (not one universe-wide model): vol regimes
are name-specific — TLT's "extreme rich IV" is a different beast
from NVDA's. A per-ticker HMM picks up the right state boundaries
even when broader-market conditions diverge.

Idempotent: re-running the job on the same day overwrites the most-
recent row's regime fields. Safe to run more than once per day.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

import pandas as pd

from volscope.analytics.vol_regime import classify_ticker
from volscope.data.database import VolScopeDB

log = logging.getLogger(__name__)


def _vix_history(db: VolScopeDB) -> pd.Series:
    """Fetch ^VIX daily levels as a date-indexed Series."""
    try:
        hist = db.get_ticker_history("^VIX")
    except Exception:                                          # noqa: BLE001
        return pd.Series(dtype=float)
    if hist is None or hist.empty or "spot_price" not in hist.columns:
        return pd.Series(dtype=float)
    df = hist.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    return pd.to_numeric(df["spot_price"], errors="coerce").dropna()


def compute_for_ticker(
    db: VolScopeDB,
    ticker: str,
    vix: pd.Series,
) -> Optional[dict]:
    """Compute the latest row's regime + posteriors for one ticker.

    Returns ``None`` (no upsert) if the ticker has too little history
    or the HMM fit failed — callers log + skip.
    """
    try:
        history = db.get_ticker_history(ticker)
    except Exception:                                          # noqa: BLE001
        return None
    if history is None or history.empty:
        return None

    regime_df = classify_ticker(ticker, history, vix_history=vix)
    if regime_df.empty:
        return None
    latest = regime_df.iloc[-1]
    out = {
        "vol_regime":   str(latest["regime"]),
        "p_vol_crushed": float(latest.get("p_vol_crushed", 0.0)),
        "p_vol_cheap":   float(latest.get("p_vol_cheap",   0.0)),
        "p_vol_fair":    float(latest.get("p_vol_fair",    0.0)),
        "p_vol_rich":    float(latest.get("p_vol_rich",    0.0)),
        "p_vol_extreme": float(latest.get("p_vol_extreme", 0.0)),
        "p_vol_crisis":  float(latest.get("p_vol_crisis",  0.0)),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute 6-state Vol Regime for every ticker.",
    )
    parser.add_argument("--limit", type=int, default=None,
                         help="Only process the first N tickers (smoke test).")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    db = VolScopeDB()
    try:
        vix = _vix_history(db)
        if vix.empty:
            log.warning(
                "No ^VIX history in daily_vol — Crisis-trigger via VIX "
                "is disabled. Add ^VIX to the universe and re-scrape.",
            )

        tickers = db.get_available_tickers() or []
        if args.limit:
            tickers = tickers[: args.limit]

        n_ok = 0
        n_skip = 0
        for ticker in tickers:
            try:
                row = compute_for_ticker(db, ticker, vix)
            except Exception as exc:                           # noqa: BLE001
                log.warning("regime compute failed for %s: %s", ticker, exc)
                n_skip += 1
                continue
            if row is None:
                n_skip += 1
                continue
            try:
                # Latest row's date — same path as ``classify_ticker``
                # returns; the DB upsert is keyed on (ticker, date).
                latest_date = db.con.execute(
                    "SELECT MAX(date) FROM daily_vol WHERE ticker = ?",
                    [ticker],
                ).fetchone()
                if not latest_date or latest_date[0] is None:
                    n_skip += 1
                    continue
                db.upsert_daily(ticker, latest_date[0], **row)
                n_ok += 1
            except Exception as exc:                           # noqa: BLE001
                log.warning("upsert failed for %s: %s", ticker, exc)
                n_skip += 1
        log.info("regime compute: %d ok, %d skipped", n_ok, n_skip)
        return 0
    finally:
        try:
            db.con.close()
        except Exception:                                      # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
