"""
Post-print auto-calibration — runs after each daily scrape.

For every earnings event where:
  - ``earnings_date < today`` (it's passed)
  - ``last_reaction_pct IS NULL`` (we haven't captured it yet)
  - We have spot-price rows in ``daily_vol`` both 1 day before and
    1 day after the earnings_date.

…we compute the actual 1d move and store it. This is the compounding
feature of the Earnings Hub: every print enriches the calibration
data for the *next* event of the same ticker.

We also (re-)compute and store ``last_implied_pct`` from the
``iv_30d`` on ``earnings_date - 1`` if it's missing.

Run:
    python -m scripts.post_earnings_capture                  # all tickers
    python -m scripts.post_earnings_capture --tickers NVDA   # one ticker
    python -m scripts.post_earnings_capture --recompute      # overwrite existing values
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from datetime import date, timedelta
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def _actual_move(db, ticker: str, er_date: date) -> Optional[float]:
    """Actual 1d %-move from `er_date - 1` close to `er_date + 1` close."""
    try:
        hist = db.get_ticker_history(ticker)
    except Exception:
        return None
    if hist is None or hist.empty or "spot_price" not in hist.columns:
        return None
    h = hist.copy()
    h["date"] = pd.to_datetime(h["date"]).dt.date

    pre = h[h["date"] < er_date].tail(1)
    post = h[h["date"] >= er_date].head(2)
    if pre.empty or post.shape[0] < 2:
        return None
    spot_pre = _f(pre["spot_price"].iloc[-1])
    spot_post = _f(post["spot_price"].iloc[-1])
    if spot_pre is None or spot_post is None or spot_pre <= 0:
        return None
    return (spot_post / spot_pre - 1.0) * 100.0


def _implied_at(db, ticker: str, er_date: date) -> Optional[float]:
    """Reconstructed 1d-implied move using `iv_30d` on `er_date - 1`."""
    try:
        hist = db.get_ticker_history(ticker)
    except Exception:
        return None
    if hist is None or hist.empty or "iv_30d" not in hist.columns:
        return None
    h = hist.copy()
    h["date"] = pd.to_datetime(h["date"]).dt.date
    pre = h[h["date"] < er_date].tail(1)
    if pre.empty:
        return None
    iv = _f(pre["iv_30d"].iloc[-1])
    if iv is None or iv <= 0:
        return None
    return iv * math.sqrt(1.0 / 365.0)


def capture_one(db, ticker: str, er_date: date, *, recompute: bool = False) -> dict:
    """Capture (or refresh) the actual + implied for one earnings event."""
    row = db.con.execute(
        "SELECT last_reaction_pct, last_implied_pct FROM earnings "
        "WHERE ticker = ? AND earnings_date = ?",
        [ticker, er_date],
    ).fetchone()
    if not row:
        return {"status": "no-event"}
    have_reaction, have_implied = row
    needs_reaction = recompute or have_reaction is None
    needs_implied = recompute or have_implied is None
    if not (needs_reaction or needs_implied):
        return {"status": "already-captured"}

    actual = _actual_move(db, ticker, er_date) if needs_reaction else have_reaction
    impl = _implied_at(db, ticker, er_date) if needs_implied else have_implied

    if actual is None and impl is None:
        return {"status": "no-data"}

    db.con.execute(
        """
        UPDATE earnings
        SET last_reaction_pct = COALESCE(?, last_reaction_pct),
            last_implied_pct  = COALESCE(?, last_implied_pct)
        WHERE ticker = ? AND earnings_date = ?
        """,
        [actual, impl, ticker, er_date],
    )
    return {
        "status": "captured",
        "actual": actual,
        "implied": impl,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", default=None,
                         help="comma-separated list; default = all")
    parser.add_argument("--recompute", action="store_true",
                         help="overwrite existing values even when populated")
    parser.add_argument("--lookback-days", type=int, default=120,
                         help="only consider earnings within last N days")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from volscope.data.database import VolScopeDB
    db = VolScopeDB()
    try:
        cutoff = date.today() - timedelta(days=args.lookback_days)
        if args.tickers:
            tickers = [t.strip().upper() for t in args.tickers.split(",")
                        if t.strip()]
            ticker_clause = "AND ticker IN ({})".format(
                ",".join(["?"] * len(tickers))
            )
            params = [cutoff, date.today()] + tickers
        else:
            ticker_clause = ""
            params = [cutoff, date.today()]

        events = db.con.execute(
            f"""
            SELECT ticker, earnings_date FROM earnings
            WHERE earnings_date BETWEEN ? AND ?
              {ticker_clause}
            ORDER BY earnings_date DESC
            """,
            params,
        ).fetchdf()
        log.info("Checking %d past earnings events ...", len(events))

        captured = 0
        skipped = 0
        for _, row in events.iterrows():
            t = str(row["ticker"])
            d = pd.to_datetime(row["earnings_date"]).date()
            r = capture_one(db, t, d, recompute=args.recompute)
            if r["status"] == "captured":
                captured += 1
                log.info("  ✓ %s %s  actual=%s  implied=%s",
                          t, d.isoformat(),
                          f"{r['actual']:+.2f}%" if r["actual"] is not None else "—",
                          f"{r['implied']:.2f}%" if r["implied"] is not None else "—")
            else:
                skipped += 1
        log.info("Done. captured=%d  skipped=%d", captured, skipped)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
