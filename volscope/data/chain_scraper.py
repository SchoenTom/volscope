"""
Option-chain scraper — v0.3.0 paper engine data source.

Yahoo Finance via yfinance. Pulls the full chain (every strike, every
expiry) for a ticker and writes one row per (ticker, snapshot_ts,
expiry, strike, right) into `bot_chain_snapshots`.

Yahoo IV is approximate. The paper engine uses Yahoo `bid`/`ask` for
entry/exit; the IV column is stored for diagnostic comparison against
VolScope's own Newton-Raphson solver but is NOT used for pricing.

Run nightly via `scripts/scrape/scrape_chains.py` (added to `make scrape`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainRow:
    """One scraped row, ready for upsert into bot_chain_snapshots."""
    ticker: str
    snapshot_ts: datetime
    expiry: pd.Timestamp
    strike: float
    right: str                    # 'C' | 'P'
    bid: float | None
    ask: float | None
    mid: float | None
    last_price: float | None
    iv: float | None
    delta: float | None           # Yahoo doesn't return greeks; populated by our solver
    gamma: float | None
    theta: float | None
    vega: float | None
    volume: int | None
    open_interest: int | None
    underlying_px: float | None


def _mid(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2.0


def fetch_chain(ticker: str, *, max_expiries: int | None = None) -> list[ChainRow]:
    """
    Pull every available expiry for ``ticker``. Returns a flat list of
    ChainRow. Empty list on failure (logged; never raises).

    Heavy: ~5-20s per ticker over the network. Run nightly, not per-tick.
    """
    rows: list[ChainRow] = []
    snapshot_ts = datetime.now(tz=timezone.utc)
    try:
        tk = yf.Ticker(ticker)
        # Spot price for the row
        try:
            spot = float(tk.fast_info.last_price)
        except Exception:               # noqa: BLE001
            spot = None
        expiries = list(tk.options or [])
        if max_expiries is not None:
            expiries = expiries[:max_expiries]
        from volscope.data.yfinance_safe import safe_option_chain
        for exp_str in expiries:
            try:
                exp = pd.Timestamp(exp_str)
                # 12 s per-expiry budget; without it a single slow
                # expiry hangs the whole chain fetch and 50+ expiries
                # for SPY can stall daily_scrape for 10+ minutes.
                chain = safe_option_chain(tk, exp_str, timeout=12.0)
                if chain is None:
                    continue
                for df, right in ((chain.calls, "C"), (chain.puts, "P")):
                    if df is None or df.empty:
                        continue
                    for _, r in df.iterrows():
                        rows.append(ChainRow(
                            ticker=ticker,
                            snapshot_ts=snapshot_ts,
                            expiry=exp,
                            strike=float(r.get("strike", 0.0)),
                            right=right,
                            bid=_safe_float(r.get("bid")),
                            ask=_safe_float(r.get("ask")),
                            mid=_mid(_safe_float(r.get("bid")),
                                       _safe_float(r.get("ask"))),
                            last_price=_safe_float(r.get("lastPrice")),
                            iv=_safe_float(r.get("impliedVolatility")),
                            delta=None, gamma=None, theta=None, vega=None,
                            volume=_safe_int(r.get("volume")),
                            open_interest=_safe_int(r.get("openInterest")),
                            underlying_px=spot,
                        ))
            except Exception as exc:    # noqa: BLE001
                log.warning("chain fetch failed for %s exp=%s: %s",
                             ticker, exp_str, exc)
    except Exception as exc:            # noqa: BLE001
        log.warning("chain fetch failed for %s: %s", ticker, exc)
    return rows


def upsert_rows(db, rows: list[ChainRow]) -> int:
    """
    Write rows into `bot_chain_snapshots`. Idempotent on PK; the unique
    (ticker, snapshot_ts, expiry, strike, right) tuple ensures
    re-running the same scrape inserts no duplicates.

    Returns count of rows persisted.
    """
    if not rows:
        return 0
    df = pd.DataFrame([{
        "ticker": r.ticker, "snapshot_ts": r.snapshot_ts,
        "expiry": r.expiry.date() if hasattr(r.expiry, "date") else r.expiry,
        "strike": r.strike, "option_right": r.right,
        "bid": r.bid, "ask": r.ask, "mid": r.mid, "last_price": r.last_price,
        "iv": r.iv, "delta": r.delta, "gamma": r.gamma,
        "theta": r.theta, "vega": r.vega,
        "volume": r.volume, "open_interest": r.open_interest,
        "underlying_px": r.underlying_px,
    } for r in rows])
    db.con.execute("""
        INSERT INTO bot_chain_snapshots
        SELECT * FROM df
        ON CONFLICT (ticker, snapshot_ts, expiry, strike, option_right) DO NOTHING
    """)
    return len(rows)


def _safe_float(x) -> float | None:
    try:
        v = float(x)
        return v if pd.notna(v) else None
    except (TypeError, ValueError):
        return None


def _safe_int(x) -> int | None:
    try:
        if pd.isna(x):
            return None
        return int(x)
    except (TypeError, ValueError):
        return None
