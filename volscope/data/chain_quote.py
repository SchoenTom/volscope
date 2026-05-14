"""
Chain-quote lookup — v0.3.0 paper engine.

`get_quote(ticker, strike, expiry, right, as_of=None)` returns a Quote
from bot_chain_snapshots. Used by:

- `paper_engine.py` at trade entry (latest snapshot per ticker)
- `daily_mtm.py` for marking open trades (next snapshot after open)
- `paper_backtest.py` for historical replay

Strike + expiry rarely match the engine's target exactly — we always
fall back to the **closest available** strike + expiry within tolerance.
This mirrors what a real broker does ("fill at the nearest tradable
strike") and is essential for paper-engine realism.

Slippage layer wraps the raw mid quote with a haircut derived from
`config/risk.yaml::slippage_model`. The same model is used for entry
AND exit so a round-trip's net cost is symmetric.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Right = Literal["C", "P"]


@dataclass(frozen=True)
class Quote:
    """A single point-in-time quote, post-resolution to actual chain rows."""
    ticker: str
    snapshot_ts: datetime
    expiry: date
    strike: float                  # the *actual* strike found in the chain
    right: Right
    bid: float | None
    ask: float | None
    mid: float | None
    iv: float | None
    underlying_px: float | None

    @property
    def spread(self) -> float:
        if self.bid is None or self.ask is None:
            return 0.0
        return max(0.0, self.ask - self.bid)

    @property
    def spread_pct(self) -> float:
        if not self.mid or self.mid <= 0:
            return 1.0   # treat unknown as max haircut
        return self.spread / self.mid


@dataclass(frozen=True)
class SlippageModel:
    """Parameters from config/risk.yaml::slippage_model."""
    base_haircut_tight_index: float = 0.30
    base_haircut_medium: float = 0.50
    base_haircut_wide: float = 0.70
    extra_short_dte_le1: float = 0.10
    extra_long_dte_gt60: float = 0.05

    def haircut_pct(self, q: Quote, *, dte: int, is_index: bool) -> float:
        """Per-leg slippage as a fraction of half-spread."""
        spread = q.spread
        # Pick base haircut on liquidity tier
        if is_index and spread <= 0.10:
            base = self.base_haircut_tight_index
        elif spread <= 0.25:
            base = self.base_haircut_medium
        else:
            base = self.base_haircut_wide
        if dte <= 1:
            base += self.extra_short_dte_le1
        elif dte > 60:
            base += self.extra_long_dte_gt60
        return base


def apply_slippage(q: Quote, *, side: Literal["buy", "sell"],
                    model: SlippageModel, dte: int,
                    is_index: bool = False) -> float:
    """
    Return the fillable price for ``side`` given ``model``.

    Buy ⇒ pay mid + haircut × (spread/2). Sell ⇒ receive mid - haircut × (spread/2).

    Falls back to ``mid`` if spread is 0. Returns 0.0 if quote is unusable
    (no mid).
    """
    if q.mid is None:
        return 0.0
    haircut_pct = model.haircut_pct(q, dte=dte, is_index=is_index)
    half_spread = q.spread / 2.0
    haircut = haircut_pct * half_spread
    if side == "buy":
        return q.mid + haircut
    return q.mid - haircut


def get_quote(db, *, ticker: str, strike: float, expiry: date,
              right: Right, as_of: datetime | None = None,
              strike_tol_pct: float = 0.05,
              expiry_tol_days: int = 7) -> Quote | None:
    """
    Look up a chain quote.

    - ``as_of=None`` → latest snapshot.
    - Falls back to the closest (strike, expiry) within tolerances. Returns
      ``None`` if no row within tolerance.
    """
    where_ts = "snapshot_ts = (SELECT MAX(snapshot_ts) FROM bot_chain_snapshots WHERE ticker = ?)"
    params: list = [ticker]
    if as_of is not None:
        where_ts = "snapshot_ts = (SELECT MAX(snapshot_ts) FROM bot_chain_snapshots WHERE ticker = ? AND snapshot_ts <= ?)"
        params = [ticker, as_of]

    # Pull the slice for this ticker @ snapshot, then pick closest in-Python.
    sql = f"""
        SELECT ticker, snapshot_ts, expiry, strike, option_right,
               bid, ask, mid, iv, underlying_px
        FROM bot_chain_snapshots
        WHERE ticker = ? AND option_right = ? AND {where_ts}
    """
    qparams: list = [ticker, right] + params
    rows = db.con.execute(sql, qparams).fetchall()
    if not rows:
        return None

    # Filter to tolerance band
    strike_min = strike * (1 - strike_tol_pct)
    strike_max = strike * (1 + strike_tol_pct)
    candidates = []
    for r in rows:
        r_strike = float(r[3])
        r_expiry = r[2] if hasattr(r[2], "year") else date.fromisoformat(str(r[2]))
        days_off = abs((r_expiry - expiry).days)
        if days_off > expiry_tol_days:
            continue
        if not (strike_min <= r_strike <= strike_max):
            continue
        # Score by combined distance — smaller is better
        score = abs(r_strike - strike) / strike + 0.5 * days_off / 30.0
        candidates.append((score, r, r_expiry))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    _, best, best_expiry = candidates[0]

    return Quote(
        ticker=best[0], snapshot_ts=best[1],
        expiry=best_expiry, strike=float(best[3]),
        right=best[4],
        bid=float(best[5]) if best[5] is not None else None,
        ask=float(best[6]) if best[6] is not None else None,
        mid=float(best[7]) if best[7] is not None else None,
        iv=float(best[8]) if best[8] is not None else None,
        underlying_px=float(best[9]) if best[9] is not None else None,
    )
