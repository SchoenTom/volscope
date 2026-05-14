"""
Earnings-meta scraper.

For every ticker that has a row in ``daily_vol`` (i.e. the active
universe), enriches the ``earnings`` table with:

  - **time_of_day**     bmo / amc / during / unknown
  - **eps_estimate**    consensus EPS from yfinance.calendar
  - **revenue_estimate** consensus revenue (when published)
  - **last_reaction_pct** actual 1-day move at the previous earnings
  - **last_implied_pct** reconstructed implied move at prior earnings,
                          computed as ``iv_30d[er - 1d] × sqrt(1/365)``

The scraper is idempotent — re-running upserts the latest data
without duplicating rows. It runs at ~1.5 s/ticker (rate-limited by
yfinance). ETA for 290 tickers: ~7 minutes.

Run:
    python -m scripts.scrape_earnings_meta              # all tickers
    python -m scripts.scrape_earnings_meta --tickers NVDA,AAPL,MSFT
    python -m scripts.scrape_earnings_meta --window 60  # next 60 days only
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

# Avoid the iCloud-cold project import path at module load — defer.
log = logging.getLogger(__name__)


# ── Time-of-day classification ───────────────────────────────────────

def _classify_time(epoch_or_dt) -> str:
    """Bucket a Yahoo earnings timestamp into bmo/amc/during/unknown.

    Yahoo returns either an epoch second (`earningsTimestamp`) or a
    pandas Timestamp depending on yfinance version. Both map to a
    US/Eastern hour via simple comparison.
    """
    if epoch_or_dt is None:
        return "unknown"
    try:
        if isinstance(epoch_or_dt, (int, float)) and epoch_or_dt > 0:
            ts = datetime.fromtimestamp(epoch_or_dt)
        elif isinstance(epoch_or_dt, datetime):
            ts = epoch_or_dt
        elif hasattr(epoch_or_dt, "to_pydatetime"):
            ts = epoch_or_dt.to_pydatetime()
        else:
            return "unknown"
    except Exception:
        return "unknown"
    h = ts.hour
    # Yahoo's timestamps land in US/Eastern semantically, regardless of tz
    if h < 9:
        return "bmo"
    if h >= 16:
        return "amc"
    if 9 <= h < 16:
        return "during"
    return "unknown"


# ── yfinance probes ──────────────────────────────────────────────────

def _fetch_calendar(ticker: str) -> dict[str, object]:
    """Return ``{date, time, eps, revenue, market_cap}`` for the next
    earnings; missing fields are ``None``.

    yfinance 0.2.x returns ``Ticker.calendar`` as a dict OR a
    pandas DataFrame depending on version. Handle both.
    """
    out: dict[str, object] = {
        "date": None, "time_str": "unknown", "epoch": None,
        "eps": None, "revenue": None, "market_cap": None,
    }
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
    except Exception as exc:
        log.debug("%s calendar fetch failed: %s", ticker, exc)
        return out

    # Newer yfinance: dict shape
    if isinstance(cal, dict):
        # 'Earnings Date' is either a list of pd.Timestamp OR a single one
        ed = cal.get("Earnings Date") or cal.get("earningsDate") or []
        if isinstance(ed, (list, tuple)) and ed:
            ed = ed[0]
        out["date"] = _coerce_date(ed)
        out["eps"] = _to_float(cal.get("Earnings Average")
                                  or cal.get("epsEstimate"))
        out["revenue"] = _to_float(cal.get("Revenue Average")
                                       or cal.get("revenueEstimate"))
    # Older yfinance: DataFrame shape
    elif hasattr(cal, "iloc") and not cal.empty:
        try:
            col = cal.iloc[:, 0]
            ed = col.get("Earnings Date")
            if isinstance(ed, (list, tuple)) and ed:
                ed = ed[0]
            out["date"] = _coerce_date(ed)
            out["eps"] = _to_float(col.get("Earnings Average"))
            out["revenue"] = _to_float(col.get("Revenue Average"))
        except Exception:
            pass

    # Market cap from .info — used for sorting bands by liquidity
    try:
        info = t.info
        out["market_cap"] = _to_float(info.get("marketCap"))
    except Exception:
        pass

    # earningsTimestampStart epoch (gives BMO/AMC fine-grain) — fallback path
    try:
        info = t.info if "info" in dir(t) else {}
        epoch = info.get("earningsTimestampStart") or info.get("earningsTimestamp")
        if epoch:
            out["epoch"] = int(epoch)
            out["time_str"] = _classify_time(int(epoch))
    except Exception:
        pass
    return out


def _historical_earnings_dates(ticker: str, n: int = 8) -> list[date]:
    """Return up to ``n`` past earnings dates from yfinance, newest first."""
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
    except Exception as exc:
        log.debug("%s earnings_dates failed: %s", ticker, exc)
        return []
    if ed is None or ed.empty:
        return []
    try:
        # Filter to historical only (past relative to today)
        today_ts = pd.Timestamp.today().tz_localize(None)
        idx = ed.index.tz_localize(None) if ed.index.tz is not None else ed.index
        mask = idx < today_ts
        past = ed[mask].index[: n]
        return [pd.to_datetime(d).date() for d in past]
    except Exception as exc:
        log.debug("%s earnings_dates parse: %s", ticker, exc)
        return []


# ── Computations from our own daily_vol ──────────────────────────────

def _compute_actual_1d_move(db, ticker: str, er_date: date) -> Optional[float]:
    """Actual 1-day move around an earnings date, in percent.

    We look for the close on ``er_date − 1`` (pre-print) and
    ``er_date + 1`` (post-print). For AMC events the close on
    ``er_date`` is pre-print and the next session's close is post-print.

    Conservative behaviour: pick the closest pre/post rows within ±3
    trading days of `er_date` if exact day doesn't exist.
    """
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
    spot_pre = float(pre["spot_price"].iloc[-1])
    spot_post = float(post["spot_price"].iloc[-1])
    if spot_pre <= 0:
        return None
    return (spot_post / spot_pre - 1.0) * 100.0


def _compute_implied_at(db, ticker: str, er_date: date) -> Optional[float]:
    """Reconstructed implied 1-day move at the time of a prior ER,
    using `iv_30d` from `er_date − 1 trading day` scaled to 1d."""
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
    iv = pre["iv_30d"].iloc[-1]
    if iv is None or pd.isna(iv) or iv <= 0:
        return None
    return float(iv) * math.sqrt(1.0 / 365.0)


# ── Helpers ──────────────────────────────────────────────────────────

def _coerce_date(v) -> Optional[date]:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, date) and not isinstance(v, pd.Timestamp):
        return v
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# ── Main ─────────────────────────────────────────────────────────────

def scrape_one(db, ticker: str, *, sleep_s: float = 1.5) -> dict:
    """Pull yfinance meta + compute last-quarter calibration. Upsert."""
    cal = _fetch_calendar(ticker)
    er_date = cal["date"]
    out = {"ticker": ticker, "status": "no-er"}

    last_reaction = last_implied = None
    historical = _historical_earnings_dates(ticker, n=1)
    if historical:
        prev_er = historical[0]
        last_reaction = _compute_actual_1d_move(db, ticker, prev_er)
        last_implied = _compute_implied_at(db, ticker, prev_er)

    if er_date is None:
        # Still upsert calibration history if we have it — useful for
        # the future-quarter tile
        return out

    db.con.execute(
        """
        INSERT INTO earnings
            (ticker, earnings_date, time_of_day, eps_estimate,
             revenue_estimate, last_reaction_pct, last_implied_pct,
             market_cap, meta_updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (ticker, earnings_date) DO UPDATE SET
            time_of_day = EXCLUDED.time_of_day,
            eps_estimate = EXCLUDED.eps_estimate,
            revenue_estimate = EXCLUDED.revenue_estimate,
            last_reaction_pct = EXCLUDED.last_reaction_pct,
            last_implied_pct = EXCLUDED.last_implied_pct,
            market_cap = EXCLUDED.market_cap,
            meta_updated_at = EXCLUDED.meta_updated_at
        """,
        [ticker, er_date, cal["time_str"], cal["eps"], cal["revenue"],
         last_reaction, last_implied, cal["market_cap"], datetime.utcnow()],
    )
    out["status"] = "ok"
    out["date"] = er_date.isoformat()
    out["time"] = cal["time_str"]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", default=None,
                        help="comma-separated list; default = all in daily_vol")
    parser.add_argument("--window", type=int, default=30,
                        help="only fetch earnings within N days (placeholder; yfinance returns nearest)")
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Lazy-import VolScopeDB so the CLI parses fast even when the
    # project is cold in iCloud.
    from volscope.data.database import VolScopeDB
    db = VolScopeDB()
    try:
        if args.tickers:
            tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        else:
            tickers = sorted(db.get_available_tickers() or [])
        if args.limit:
            tickers = tickers[: args.limit]

        n = len(tickers)
        log.info("Scraping earnings meta for %d ticker(s)...", n)
        ok = err = noerf = 0
        for i, tk in enumerate(tickers, 1):
            try:
                r = scrape_one(db, tk, sleep_s=args.sleep)
                if r["status"] == "ok":
                    ok += 1
                else:
                    noerf += 1
            except Exception as exc:
                err += 1
                log.warning("[%3d/%d] %s ERR %s", i, n, tk, exc)
            if i % 25 == 0 or i == n:
                log.info("[%3d/%d] ok=%d  no-er=%d  err=%d", i, n, ok, noerf, err)
            time.sleep(args.sleep)
        log.info("Done. ok=%d  no-er=%d  err=%d", ok, noerf, err)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
